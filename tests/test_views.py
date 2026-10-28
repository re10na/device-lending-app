"""画面（Flask のルート）を通したテスト。テンプレートの表示と、POST → リダイレクト → flash の流れ。

client で送った操作はアプリの transaction で commit されるので、確認は新しい接続で読む。
"""
import pytest
from flask import template_rendered

from device_lending import devices as devices_module, issues, losses, user_requests
from device_lending.db import transaction

from .conftest import log_in_as_admin, log_in_as_user
from .factories import PC, SUZUKI, TANAKA, add_device, latest_request, lend

CSRF = {'csrf_token': 'test'}


def seed(operation):
    """commit されるトランザクションでデータを作る（client から見えるように）。"""
    with transaction() as cursor:
        return operation(cursor)


def read(operation):
    with transaction() as cursor:
        return operation(cursor)


def flashed(client):
    with client.session_transaction() as session:
        return session.get('_flashes', [])


@pytest.fixture
def sample(client):
    """いろいろな状態の機器をそろえる（画面がどの分岐でも落ちないことを見る）。"""
    def build(cursor):
        loaned = add_device(cursor, hostname='LT-TANAKA')
        lend(cursor, loaned)
        broken = add_device(cursor)
        issues.report_issue(cursor, broken, '起動しない', True)
        lost = add_device(cursor)
        losses.report_loss(cursor, lost, '電車で紛失')
        installed = add_device(cursor)
        devices_module.install_device(cursor, installed, '会議室A')
        add_device(cursor)
        user_requests.submit_loan_request(cursor, SUZUKI, PC, '')
        return {'loaned': loaned, 'broken': broken, 'lost': lost, 'installed': installed}
    return seed(build)


@pytest.mark.parametrize('path', [
    '/admin',
    '/admin?q=dell',
    '/admin?q=見つからない',
    '/admin/events',
    '/admin/requests',
    '/admin/requests/processed',
    '/admin/requests/processed?page=5',
    '/admin/sims',
    '/admin/sims/events',
    '/devices',
    '/devices?placement=loaned&flag=issue&q=LT',
    '/devices?flag=any',
])
def test_pages_render(client, sample, path):
    response = client.get(path)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]


@pytest.mark.parametrize('path', ['/user', '/user?history=all&device_type=PC'])
def test_user_pages_render(client, sample, path):
    log_in_as_user(client, TANAKA)
    response = client.get(path)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]


def test_device_detail_pages_render(client, sample):
    for device_id in sample.values():
        assert client.get(f'/devices/{device_id}').status_code == 200


def test_missing_device_is_404(client):
    assert client.get('/devices/999999').status_code == 404


@pytest.mark.parametrize('path', [
    '/devices?placement=unknown',
    '/devices?flag=unknown',
    '/admin?q=' + 'a' * 101,
    '/admin/search?q=' + 'a' * 101,
    '/admin/events?page=0',
    '/admin/requests/processed?page=0',
])
def test_bad_query_is_400(client, path):
    assert client.get(path).status_code == 400


def test_bad_user_query_is_400(client):
    log_in_as_user(client, TANAKA)
    assert client.get('/user?device_type=Unknown').status_code == 400


def test_dashboard_counts(app, client, sample):
    """ダッシュボードの集計カードに渡す数（テンプレートに渡した値を横取りして確かめる）。"""
    rendered = []

    def record(sender, template, context, **extra):
        rendered.append(context)

    with template_rendered.connected_to(record, app):
        client.get('/admin')
    counts = rendered[0]['counts']
    assert counts == {
        'total': 5, 'loaned': 1, 'installed': 1, 'stored': 3,
        'broken': 1, 'minor': 0, 'review': 0, 'lost': 1, 'issue': 1,
    }
    assert rendered[0]['pending_request_count'] == 1  # サイドバーの未処理の申請


def test_csv_export(client, sample):
    response = client.get('/devices/export.csv?placement=loaned')
    assert response.status_code == 200
    assert response.mimetype == 'text/csv'
    body = response.get_data(as_text=True)
    assert 'LT-TANAKA' in body
    assert '会議室A' not in body  # 絞り込みが効いている


def test_post_without_csrf_token_is_rejected(client):
    device_id = seed(add_device)
    response = client.post(f'/devices/{device_id}/install', data={'location': '受付'})
    assert response.status_code == 400
    assert read(lambda c: devices_module.fetch_device(c, device_id))['placement'] == 'stored'


def test_rule_violation_is_flashed_as_error(client):
    device_id = seed(add_device)
    response = client.post(f'/devices/{device_id}/loans', data={**CSRF, 'shain_code': '1003'})
    assert response.status_code == 302
    assert flashed(client) == [('error', '選択した社員が見つからないか、退職済みです。')]


def test_post_to_missing_record_is_404(client):
    assert client.post('/loans/999999/return', data=CSRF).status_code == 404


def test_redirects_back_to_next_only_within_site(client):
    device_id = seed(add_device)
    response = client.post(
        f'/devices/{device_id}/install', data={**CSRF, 'location': '受付', 'next': '/devices'}
    )
    assert response.headers['Location'] == '/devices'
    response = client.post(
        f'/devices/{device_id}/uninstall', data={**CSRF, 'next': 'https://evil.example.com/'}
    )
    assert response.headers['Location'] == f'/devices/{device_id}'


def test_loan_request_flow_through_screens(client):
    """利用者が申請 → 管理者が確認 → 貸し出して対応済み → 利用者画面に出る。"""
    device_id = seed(add_device)

    log_in_as_user(client, TANAKA)
    client.post('/user/requests/loan', data={**CSRF, 'device_model_id': PC})
    assert flashed(client)[-1][0] == 'success'
    request_id = read(latest_request)['id']
    assert read(latest_request)['shain_code'] == TANAKA
    assert read(user_requests.count_pending_requests) == 1

    log_in_as_admin(client)
    client.post(f'/admin/requests/{request_id}/confirm', data=CSRF)
    client.post(f'/admin/requests/{request_id}/approve-loan', data={**CSRF, 'device_id': device_id})
    assert flashed(client)[-1] == ('success', '機器を田中太郎さんに貸し出し、申請を対応済みにしました。')

    log_in_as_user(client, TANAKA)
    html = client.get('/user').get_data(as_text=True)
    assert 'Dell Latitude 5440' in html
    assert read(lambda c: devices_module.find_open_loan(c, device_id))['shain_code'] == TANAKA


def test_user_cannot_cancel_someone_elses_request(client):
    seed(lambda c: user_requests.submit_loan_request(c, TANAKA, PC, ''))
    request_id = read(latest_request)['id']
    # 鈴木さんとしてログインして、田中さんの申請を取り消そうとする（フォームの社員番号は無視される）
    log_in_as_user(client, SUZUKI)
    response = client.post(
        f'/user/requests/{request_id}/cancel', data={**CSRF, 'shain_code': TANAKA}
    )
    assert response.status_code == 404
    assert read(latest_request)['status'] == 'pending'


def test_user_reports_loss_through_screen(client):
    device_id = seed(add_device)
    seed(lambda c: lend(c, device_id))
    log_in_as_user(client, TANAKA)
    client.post('/user/losses', data={**CSRF, 'device_id': device_id})
    assert flashed(client)[-1][0] == 'success'
    assert read(lambda c: devices_module.fetch_device(c, device_id))['flags'] == ['lost']


def rendered_context(app, client, path):
    rendered = []

    def record(sender, template, context, **extra):
        rendered.append(context)

    with template_rendered.connected_to(record, app):
        assert client.get(path).status_code == 200
    return rendered[0]


def reject_many(count):
    def build(cursor):
        for _ in range(count):
            user_requests.submit_loan_request(cursor, TANAKA, PC, '')
            user_requests.reject_request(cursor, latest_request(cursor)['id'])
    seed(build)


def test_requests_page_shows_latest_processed_and_link_to_all(app, client):
    reject_many(12)
    context = rendered_context(app, client, '/admin/requests')
    assert len(context['processed']) == 10
    assert context['processed_total'] == 12
    assert 'すべて見る（12 件）' in client.get('/admin/requests').get_data(as_text=True)


def test_requests_page_hides_link_when_all_are_shown(client):
    reject_many(3)
    assert 'すべて見る' not in client.get('/admin/requests').get_data(as_text=True)


def test_processed_page_is_split_into_pages(app, client, monkeypatch):
    monkeypatch.setattr(user_requests, 'PROCESSED_PAGE_SIZE', 5)
    reject_many(12)

    first = rendered_context(app, client, '/admin/requests/processed')
    last = rendered_context(app, client, '/admin/requests/processed?page=3')

    assert (len(first['processed']), first['has_next'], first['first_number']) == (5, True, 1)
    assert (len(last['processed']), last['has_next'], last['first_number']) == (2, False, 11)
    newest = read(latest_request)['id']
    assert first['processed'][0]['id'] == newest
