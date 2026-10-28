"""ダッシュボードの円グラフの種別の内訳、もうすぐ退職する人の貸出、対応待ちの申請。"""
from datetime import date, timedelta

from flask import template_rendered

from device_lending import losses, members, user_requests
from device_lending.db import transaction
from device_lending.devices import type_breakdown

from .factories import PC, RETIRED, SUZUKI, TANAKA, add_device, lend
from .test_device_state import derived


def test_type_breakdown_by_placement_in_fixed_type_order():
    rows = [
        derived(id=1, loan_id=11, holder_code='1001', device_type='SmartPhone'),
        derived(id=2, loan_id=12, holder_code='1002'),                  # PC
        derived(id=3, loan_id=13, holder_code='1003'),                  # PC
        derived(id=4, loan_id=14, holder_code='1001', device_type='Tablet'),  # 順番にない種別
        derived(id=5),                                                  # 保管中の PC
        derived(id=6, disposed_on=date(2025, 1, 1)),                    # 廃棄済みは数えない
    ]
    assert type_breakdown(rows) == {
        'loaned': [
            {'device_type': 'PC', 'short_name': 'PC', 'count': 2, 'slot': 1},
            {'device_type': 'SmartPhone', 'short_name': 'スマホ', 'count': 1, 'slot': 2},
            {'device_type': 'Tablet', 'short_name': 'Tablet', 'count': 1, 'slot': 0},
        ],
        'stored': [{'device_type': 'PC', 'short_name': 'PC', 'count': 1, 'slot': 1}],
    }


def test_type_breakdown_empty():
    assert type_breakdown([]) == {}


def set_retirement(cursor, shain_code, days_from_today):
    cursor.execute(
        'UPDATE master_test.m_shain SET taishoku_date = %s WHERE shain_code = %s',
        (date.today() + timedelta(days=days_from_today), shain_code),
    )


def test_upcoming_retirements_only_with_loans_within_range(cursor):
    lend(cursor, add_device(cursor), TANAKA)
    lend(cursor, add_device(cursor), SUZUKI)
    set_retirement(cursor, TANAKA, 10)
    set_retirement(cursor, SUZUKI, 40)       # 範囲外
    rows = members.fetch_upcoming_retirements(cursor, 30)
    assert [(r['shain_code'], r['days_left'], r['loan_count']) for r in rows] == [(TANAKA, 10, 1)]


def test_upcoming_retirements_excludes_retired_and_no_loans(cursor):
    set_retirement(cursor, TANAKA, 5)        # 借りていない
    lend(cursor, add_device(cursor), SUZUKI)
    set_retirement(cursor, SUZUKI, 0)        # 今日退職 → もう「要確認」の側
    assert not members.fetch_upcoming_retirements(cursor, 30)


def test_dashboard_widgets_context(app, client):
    with transaction() as cursor:
        user_requests.submit_loan_request(cursor, SUZUKI, PC, '')
        cursor.execute(
            'UPDATE user_requests SET requested_at = NOW() - INTERVAL 4 DAY ORDER BY id DESC LIMIT 1'
        )
        user_requests.submit_loan_request(cursor, TANAKA, PC, '')
    rendered = []

    def record(sender, template, context, **extra):
        rendered.append(context)

    with template_rendered.connected_to(record, app):
        response = client.get('/admin')
    assert response.status_code == 200
    context = rendered[0]
    assert context['pending_count'] == 2
    assert context['oldest_wait_days'] == 4
    assert [r['shain_code'] for r in context['waiting_requests']] == [SUZUKI, TANAKA]
    assert context['confirmed_count'] == 0
    # 「対応が必要なこと」のカードは一旦画面に出していないので、渡している値だけを確かめる



def test_chart_links_to_filtered_device_list(client):
    """円グラフの区分・扇形・種別の内訳から、状態（と種別）で絞り込んだ機器一覧へ移動できる。"""
    with transaction() as cursor:
        lend(cursor, add_device(cursor), TANAKA)
        add_device(cursor)
    body = client.get('/admin').get_data(as_text=True)
    assert 'href="/devices?placement=loaned"' in body
    assert 'href="/devices?placement=loaned&amp;type=PC"' in body
    assert 'href="/devices?placement=stored&amp;type=PC"' in body


def test_dashboard_shows_search_chart_and_side_column(client):
    """ダッシュボードは左に検索、真ん中に円グラフと四隅のタイル、右に要確認・紛失中と最新の変更。"""
    with transaction() as cursor:
        cursor.execute(
            "INSERT INTO loans (device_id, shain_code, loaned_on) VALUES (%s, %s, '2019-04-01')",
            (add_device(cursor), RETIRED),
        )
        lost = add_device(cursor)
        lend(cursor, lost, TANAKA)
        losses.report_loss(cursor, lost, '電車で紛失')
    body = client.get('/admin').get_data(as_text=True)
    assert 'class="dash-search' in body and 'id="quick-search-input"' in body
    assert 'class="donut-stage"' in body and 'corner-nav' in body
    # 要確認・紛失中はアイコンと台数だけ。1 台以上あれば赤にする
    assert body.count('alert-tile is-alert') == 2
    assert 'href="/devices?flag=review"' in body and 'href="/devices?flag=lost"' in body
    assert '要確認</span><strong>1<small>' in body and '紛失中</span><strong>1<small>' in body
    assert 'events-panel' in body and 'href="/admin/events"' in body
    for hidden in ('page-heading', 'page-footer', 'events-drawer'):
        assert hidden not in body, hidden
    # 他のページのフッターはそのまま
    assert 'page-footer' in client.get('/devices').get_data(as_text=True)


def test_alert_tiles_are_quiet_when_nothing_to_check(client):
    body = client.get('/admin').get_data(as_text=True)
    assert 'alert-tile is-alert' not in body
    assert '要確認</span><strong>0<small>' in body and '紛失中</span><strong>0<small>' in body

def test_corner_tiles_link_to_admin_pages(client):
    """ダッシュボードはサイドバーを出さず、円グラフの四隅のタイルから各ページへ移動する。"""
    body = client.get('/admin').get_data(as_text=True)
    assert 'class="sidebar"' not in body
    assert 'class="breadcrumb-home" href="/"' in body   # 画面選択へは上の帯から戻る
    for href in ('/devices', '/admin/sims', '/members', '/admin/requests'):
        assert f'href="{href}"' in body
    assert '在籍 2 人' in body   # conftest の社員 3 人のうち 1 人は退職済み


def test_sidebar_is_on_every_page_except_dashboard(client):
    for path in ('/devices', '/members', '/admin/sims', '/admin/requests', '/admin/events'):
        assert 'class="sidebar"' in client.get(path).get_data(as_text=True), path


def test_event_history_has_no_back_to_dashboard_button(client):
    """すべての変更履歴には「ダッシュボードへ戻る」を出さない（SIM の変更履歴の「SIM 一覧へ戻る」は残す）。"""
    assert 'ダッシュボードへ戻る' not in client.get('/admin/events').get_data(as_text=True)
    assert 'SIM 一覧へ戻る' in client.get('/admin/sims/events').get_data(as_text=True)


def test_device_list_flag_choices(client):
    """機器一覧の「注意」の選択肢: 「故障・不具合（両方）」は出さず、「すべて（注意あり）」を「指定なし」の次に出す。"""
    body = client.get('/devices').get_data(as_text=True)
    assert '故障・不具合（両方）' not in body
    # 選択肢（select）の中だけを見る（上の注意の札にも同じ値がある）
    select = body[body.index('<select id="flag-filter"'):]
    select = select[:select.index('</select>')]
    assert select.index('>指定なし<') < select.index('value="any"') < select.index('value="broken"')
    # 注意の札にも「注意あり」がある
    assert 'data-select="flag-filter" data-value="any"' in body
    # リンクからの ?flag=issue は今までどおり使える
    assert client.get('/devices?flag=issue').status_code == 200
