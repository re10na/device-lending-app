"""一覧ページの共通の作り（数のタイル・絞り込みの札・種類の印）。"""
import pytest

from device_lending import events, issues, sims, user_requests
from device_lending.db import transaction

from .factories import PC, RETIRED, SMARTPHONE, SUZUKI, TANAKA, add_device, lend


def seed(operation):
    with transaction() as cursor:
        return operation(cursor)


def test_member_tiles_and_chips_show_counts(client):
    def build(cursor):
        cursor.execute(
            "INSERT INTO loans (device_id, shain_code, loaned_on) VALUES (%s, %s, '2019-04-01')",
            (add_device(cursor), RETIRED),
        )
    seed(build)
    body = client.get('/members').get_data(as_text=True)
    # conftest の社員は 3 人（うち 1 人退職済み）
    assert 'data-select="status-filter" data-value="active"' in body
    assert '在籍</span>\n          <strong>2<small>人</small>' in body
    assert '退職済み</span>\n          <strong>1<small>人</small>' in body
    assert 'data-value="review"' in body and '要確認<span class="chip-count">1</span>' in body


def sim_table(body):
    start = body.index('<tbody>')
    return body[start:body.index('</tbody>', start)]


def test_sim_state_tiles_filter(client):
    def build(cursor):
        used = sims.register_sim(cursor, {'iccid': '8981100000000000011', 'phone_number': '', 'extension': ''})
        sims.register_sim(cursor, {'iccid': '8981100000000000012', 'phone_number': '', 'extension': ''})
        sims.attach_sim(cursor, used, add_device(cursor, SMARTPHONE))
    seed(build)
    body = client.get('/admin/sims').get_data(as_text=True)
    assert '使用中</span>\n          <strong>1<small>枚</small>' in body
    assert '未使用</span>\n          <strong>1<small>枚</small>' in body
    # SIM の表の中だけを見る（下の「SIM の最新の変更」にも番号が出るため）
    used = sim_table(client.get('/admin/sims?state=used').get_data(as_text=True))
    assert '8981100000000000011' in used and '8981100000000000012' not in used
    free = sim_table(client.get('/admin/sims?state=free').get_data(as_text=True))
    assert '8981100000000000012' in free and '8981100000000000011' not in free
    assert client.get('/admin/sims?state=x').status_code == 400


@pytest.mark.parametrize('event_type, kind', [
    ('loaned', 'loan'), ('returned', 'loan'), ('loan_cancelled', 'loan'),
    ('issue_reported', 'issue'), ('lost_found', 'lost'), ('sim_attached', 'sim'),
    ('registered', 'device'), ('disposed', 'device'), ('status_changed', 'device'),
])
def test_event_kind(event_type, kind):
    assert events.event_kind(event_type) == kind


def test_event_list_shows_kind_tags(client):
    def build(cursor):
        device = add_device(cursor)
        lend(cursor, device, TANAKA)
        issues.report_issue(cursor, device, '起動しない', False)
    seed(build)
    body = client.get('/admin/events').get_data(as_text=True)
    for kind, label in (('loan', '貸出'), ('issue', '故障'), ('device', '機器')):
        assert f'class="event-{kind}"' in body
        assert f'<span class="event-kind">{label}</span>' in body


def test_request_tiles_link_to_sections(client):
    seed(lambda cursor: user_requests.submit_loan_request(cursor, SUZUKI, PC, ''))
    body = client.get('/admin/requests').get_data(as_text=True)
    for key in ('pending', 'confirmed', 'processed'):
        assert f'href="#{key}"' in body and f'id="{key}"' in body
    assert '申請中</span>\n          <strong>1<small>件</small>' in body
    assert 'request-type">借りたい' in body
