"""人物一覧・人物詳細（members.py と /members の画面）。"""
import pytest

from device_lending import issues, loans, losses, members, user_requests
from device_lending.db import transaction

from .factories import RETIRED, SUZUKI, TANAKA, add_device, fetch_one, lend


def member(cursor, shain_code):
    return next(m for m in members.fetch_members(cursor) if m['shain_code'] == shain_code)


def issue_loan_id(cursor, issue_id):
    return fetch_one(cursor, 'SELECT loan_id FROM device_issues WHERE id = %s', (issue_id,))['loan_id']


# --- 故障を報告したときの貸出 ---

def test_issue_records_current_loan(cursor):
    device_id = add_device(cursor)
    loan_id = lend(cursor, device_id)
    issue_id = issues.report_issue(cursor, device_id, '起動しない', True)
    assert issue_loan_id(cursor, issue_id) == loan_id


def test_issue_without_loan_records_no_loan(cursor):
    device_id = add_device(cursor)
    issue_id = issues.report_issue(cursor, device_id, '起動しない', True)
    assert issue_loan_id(cursor, issue_id) is None


def test_same_day_handover_links_only_current_holder(cursor):
    """返却した日に次の人が借りて、同じ日に故障が報告されても、今借りている人だけに結びつく。"""
    device_id = add_device(cursor)
    first_loan = lend(cursor, device_id, TANAKA)
    loans.return_loan(cursor, first_loan)
    lend(cursor, device_id, SUZUKI)
    issues.report_issue(cursor, device_id, '画面が割れている', False)
    assert member(cursor, SUZUKI)['ever_issue']
    assert not member(cursor, TANAKA)['ever_issue']


def test_issue_before_return_stays_with_previous_holder(cursor):
    device_id = add_device(cursor)
    first_loan = lend(cursor, device_id, TANAKA)
    issues.report_issue(cursor, device_id, '画面が割れている', False)
    loans.return_loan(cursor, first_loan)
    lend(cursor, device_id, SUZUKI)
    assert member(cursor, TANAKA)['ever_issue']
    assert not member(cursor, SUZUKI)['ever_issue']


def test_approved_request_links_requester_even_after_handover(cursor):
    """申請から対応までの間に返却・貸し替えがあっても、申請した人の貸出に結びつく。"""
    device_id = add_device(cursor)
    tanaka_loan = lend(cursor, device_id, TANAKA)
    user_requests.submit_issue_request(cursor, TANAKA, device_id, 'キーが反応しない')
    request_id = fetch_one(cursor, 'SELECT id FROM user_requests ORDER BY id DESC LIMIT 1')['id']
    user_requests.confirm_request(cursor, request_id)
    loans.return_loan(cursor, tanaka_loan)
    lend(cursor, device_id, SUZUKI)
    user_requests.approve_issue_request(cursor, request_id, blocks_loan=False)
    issue_id = fetch_one(cursor, 'SELECT issue_id FROM user_requests WHERE id = %s', (request_id,))['issue_id']
    assert issue_loan_id(cursor, issue_id) == tanaka_loan
    assert member(cursor, TANAKA)['ever_issue']
    assert not member(cursor, SUZUKI)['ever_issue']


def test_cancelled_loan_does_not_link_issue(cursor):
    device_id = add_device(cursor)
    loan_id = lend(cursor, device_id, TANAKA)
    issue_id = issues.report_issue(cursor, device_id, '起動しない', False)
    issues.cancel_issue(cursor, issue_id)
    issues.report_issue(cursor, device_id, '起動しない', False)
    loans.return_loan(cursor, loan_id)
    assert member(cursor, TANAKA)['ever_issue']
    cursor.execute('UPDATE loans SET cancelled_at = CURRENT_TIMESTAMP WHERE id = %s', (loan_id,))
    assert not member(cursor, TANAKA)['ever_issue']


# --- 一覧の注意マークと絞り込み ---

def test_marks_and_filters(cursor):
    held = add_device(cursor)
    cursor.execute(
        "INSERT INTO loans (device_id, shain_code, loaned_on) VALUES (%s, %s, '2019-04-01')",
        (held, RETIRED),
    )
    lost = add_device(cursor)
    lend(cursor, lost, TANAKA)
    losses.report_loss(cursor, lost, '電車で紛失')

    rows = members.fetch_members(cursor)
    by_code = {m['shain_code']: m for m in rows}
    assert by_code[RETIRED]['marks'] == ['review']
    assert by_code[TANAKA]['marks'] == ['lost']
    assert by_code[TANAKA]['ever_lost'] and not by_code[SUZUKI]['ever_lost']

    def codes(**filters):
        return [m['shain_code'] for m in members.filter_members(rows, **filters)]

    assert codes(status='retired') == [RETIRED]
    assert codes(loan_state='without') == [SUZUKI]
    assert codes(flag='review') == [RETIRED]
    assert codes(flag='ever_lost') == [TANAKA]
    assert codes(keyword='鈴木') == [SUZUKI]


# --- 画面 ---

@pytest.fixture
def sample(client):
    with transaction() as cursor:
        device_id = add_device(cursor, hostname='LT-TANAKA')
        lend(cursor, device_id, TANAKA)
        issues.report_issue(cursor, device_id, '起動しない', False)


@pytest.mark.parametrize('path', [
    '/members',
    '/members?status=active&loans=with&flag=ever_issue&q=田中',
    f'/members/{TANAKA}',
    f'/members/{SUZUKI}',
])
def test_member_pages_render(client, sample, path):
    response = client.get(path)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]


def test_member_detail_shows_linked_issue(client, sample):
    body = client.get(f'/members/{TANAKA}').get_data(as_text=True)
    assert '起動しない' in body and '貸出中に発生' in body
    assert '起動しない' not in client.get(f'/members/{SUZUKI}').get_data(as_text=True)


def test_unknown_member_is_404(client):
    assert client.get('/members/9999').status_code == 404


@pytest.mark.parametrize('query', ['status=x', 'loans=x', 'flag=x', 'q=' + 'x' * 101])
def test_bad_member_query_is_400(client, query):
    assert client.get(f'/members?{query}').status_code == 400


def test_member_csv_export(client, sample):
    response = client.get('/members/export.csv?flag=ever_issue')
    assert response.status_code == 200
    assert response.mimetype == 'text/csv'
    body = response.get_data(as_text=True)
    assert TANAKA in body and SUZUKI not in body
