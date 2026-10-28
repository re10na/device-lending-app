"""利用者の申請の状態遷移（user_requests.py）。

    申請中(pending) ─確認→ 確認済み(confirmed) ─対応→ 対応済み(done)
        │                  │
        ├─却下/取り消し──────┴─却下/取り消し→ 却下(rejected) / 取り消し(cancelled)
        └←──────── 申請中に戻す（確認済み・対応済み・却下から）
"""
import pymysql
import pytest

from device_lending import devices, issues, loans, user_requests
from device_lending.codes import format_device_code
from device_lending.errors import DeviceActionError, RecordNotFound

from .factories import (
    PC, PC_OTHER, RETIRED, SMARTPHONE, SUZUKI, TANAKA, UNKNOWN_EMPLOYEE, UNKNOWN_MODEL,
    add_device, fetch_one, get_request, latest_request, lend,
)


def submit_loan(cursor, shain_code=TANAKA, model_id=PC, reason='在宅勤務で使うため'):
    user_requests.submit_loan_request(cursor, shain_code, model_id, reason)
    return latest_request(cursor)['id']


def submit_issue(cursor, device_id, shain_code=TANAKA, detail='キーボードが反応しない'):
    user_requests.submit_issue_request(cursor, shain_code, device_id, detail)
    return latest_request(cursor)['id']


def borrowed_device(cursor, shain_code=TANAKA):
    device_id = add_device(cursor)
    lend(cursor, device_id, shain_code)
    return device_id


def status(cursor, request_id):
    return get_request(cursor, request_id)['status']


# --- 借りたい申請 ---

def test_submit_loan_request(cursor):
    label = user_requests.submit_loan_request(cursor, TANAKA, PC, ' 在宅用 ')
    request = latest_request(cursor)
    assert label == 'Dell Latitude 5440'
    assert request['request_type'] == 'loan'
    assert request['status'] == 'pending'
    assert request['device_model_id'] == PC
    assert request['device_id'] is None
    assert request['detail'] == '在宅用'
    assert request['closed_at'] is None


def test_loan_request_reason_is_optional(cursor):
    request_id = submit_loan(cursor, reason='  ')
    assert get_request(cursor, request_id)['detail'] is None


def test_loan_request_reason_max_length(cursor):
    with pytest.raises(DeviceActionError, match='1000文字以内'):
        submit_loan(cursor, reason='あ' * 1001)


@pytest.mark.parametrize('shain_code', [RETIRED, UNKNOWN_EMPLOYEE, ''])
def test_loan_request_needs_active_employee(cursor, shain_code):
    with pytest.raises(DeviceActionError, match='社員を選択してください'):
        submit_loan(cursor, shain_code=shain_code)


def test_loan_request_needs_known_model(cursor):
    with pytest.raises(DeviceActionError, match='機種を選択してください'):
        submit_loan(cursor, model_id=UNKNOWN_MODEL)


def test_same_loan_request_twice_is_rejected(cursor):
    submit_loan(cursor)
    with pytest.raises(DeviceActionError, match='この機種はすでに申請しています'):
        submit_loan(cursor)


def test_same_model_by_other_employee_or_other_model_is_allowed(cursor):
    submit_loan(cursor)
    submit_loan(cursor, shain_code=SUZUKI)
    submit_loan(cursor, model_id=PC_OTHER)


def test_loan_request_can_be_resubmitted_after_it_is_closed(cursor):
    first = submit_loan(cursor)
    user_requests.cancel_request(cursor, first, TANAKA)
    second = submit_loan(cursor)
    assert second != first


# --- 不具合の申請 ---

def test_submit_issue_request(cursor):
    device_id = borrowed_device(cursor)
    request = get_request(cursor, submit_issue(cursor, device_id))
    assert request['request_type'] == 'issue'
    assert request['status'] == 'pending'
    assert request['device_id'] == device_id
    assert request['device_model_id'] is None
    assert request['detail'] == 'キーボードが反応しない'


def test_issue_request_needs_detail(cursor):
    device_id = borrowed_device(cursor)
    with pytest.raises(DeviceActionError, match='不具合の内容を入力してください'):
        submit_issue(cursor, device_id, detail='   ')


def test_issue_request_only_for_own_current_loan(cursor):
    not_borrowed = add_device(cursor)
    others = borrowed_device(cursor, SUZUKI)
    returned = borrowed_device(cursor)
    loans.return_loan(cursor, devices.find_open_loan(cursor, returned)['id'])
    for device_id in (not_borrowed, others, returned):
        with pytest.raises(DeviceActionError, match='今借りている機器だけ'):
            submit_issue(cursor, device_id)


def test_issue_request_for_missing_device(cursor):
    with pytest.raises(RecordNotFound):
        submit_issue(cursor, 999999)


def test_same_issue_request_twice_is_rejected(cursor):
    device_id = borrowed_device(cursor)
    submit_issue(cursor, device_id)
    with pytest.raises(DeviceActionError, match='この機器の不具合はすでに申請しています'):
        submit_issue(cursor, device_id)


# --- DB の UNIQUE（Migration 011）---

def test_db_rejects_second_open_request_even_without_app_check(cursor):
    """アプリの事前確認をすり抜けた（同時に送られた）申請も DB が止める。"""
    submit_loan(cursor)
    with pytest.raises(pymysql.err.IntegrityError, match='uq_user_requests_one_open'):
        cursor.execute(
            "INSERT INTO user_requests (request_type, shain_code, device_model_id) "
            "VALUES ('loan', %s, %s)",
            (TANAKA, PC),
        )


def test_unique_violation_is_shown_as_message(cursor):
    submit_loan(cursor)
    with pytest.raises(DeviceActionError, match='二重'):
        user_requests._execute_unique_open(
            cursor,
            "INSERT INTO user_requests (request_type, shain_code, device_model_id) "
            "VALUES ('loan', %s, %s)",
            (TANAKA, PC),
            '二重です',
        )


# --- 利用者による取り消し ---

@pytest.mark.parametrize('confirm_first', [False, True])
def test_cancel_open_request(cursor, confirm_first):
    request_id = submit_loan(cursor)
    if confirm_first:
        user_requests.confirm_request(cursor, request_id)
    user_requests.cancel_request(cursor, request_id, TANAKA)
    request = get_request(cursor, request_id)
    assert request['status'] == 'cancelled'
    assert request['closed_at'] is not None


def test_cannot_cancel_someone_elses_request(cursor):
    request_id = submit_loan(cursor)
    with pytest.raises(RecordNotFound):
        user_requests.cancel_request(cursor, request_id, SUZUKI)
    assert status(cursor, request_id) == 'pending'


def test_cannot_cancel_closed_request(cursor):
    request_id = submit_loan(cursor)
    user_requests.reject_request(cursor, request_id)
    with pytest.raises(DeviceActionError, match='申請中・確認済みの申請だけ'):
        user_requests.cancel_request(cursor, request_id, TANAKA)


def test_cancel_missing_request(cursor):
    with pytest.raises(RecordNotFound):
        user_requests.cancel_request(cursor, 999999, TANAKA)


# --- 確認済みにする ---

def test_confirm_request(cursor):
    request_id = submit_loan(cursor)
    user_requests.confirm_request(cursor, request_id)
    request = get_request(cursor, request_id)
    assert request['status'] == 'confirmed'
    assert request['confirmed_at'] is not None
    assert request['closed_at'] is None


def test_confirm_twice_is_rejected(cursor):
    request_id = submit_loan(cursor)
    user_requests.confirm_request(cursor, request_id)
    with pytest.raises(DeviceActionError, match='申請中ではありません'):
        user_requests.confirm_request(cursor, request_id)


def test_confirm_missing_request(cursor):
    with pytest.raises(RecordNotFound):
        user_requests.confirm_request(cursor, 999999)


# --- 借りたい申請を対応済みにする（貸し出す）---

def confirmed_loan_request(cursor, **kwargs):
    request_id = submit_loan(cursor, **kwargs)
    user_requests.confirm_request(cursor, request_id)
    return request_id


def test_approve_loan_request_lends_the_device(cursor):
    device_id = add_device(cursor)
    request_id = confirmed_loan_request(cursor)

    name = user_requests.approve_loan_request(cursor, request_id, device_id)

    assert name == '田中太郎'
    request = get_request(cursor, request_id)
    loan = devices.find_open_loan(cursor, device_id)
    assert request['status'] == 'done'
    assert request['closed_at'] is not None
    assert request['loan_id'] == loan['id']
    assert loan['shain_code'] == TANAKA


def test_approve_loan_request_needs_confirmation_first(cursor):
    device_id = add_device(cursor)
    request_id = submit_loan(cursor)
    with pytest.raises(DeviceActionError, match='確認済みではありません'):
        user_requests.approve_loan_request(cursor, request_id, device_id)
    assert devices.find_open_loan(cursor, device_id) is None


def test_approve_loan_request_rejects_other_model(cursor):
    other_model_device = add_device(cursor, PC_OTHER)
    request_id = confirmed_loan_request(cursor)
    with pytest.raises(DeviceActionError, match='申請された機種と違う機器'):
        user_requests.approve_loan_request(cursor, request_id, other_model_device)
    assert status(cursor, request_id) == 'confirmed'


def test_approve_loan_request_follows_loan_rules(cursor):
    """貸出のルール（ここでは貸出不可の故障）に引っかかれば、申請は確認済みのまま。"""
    device_id = add_device(cursor)
    issues.report_issue(cursor, device_id, '画面割れ', blocks_loan=True)
    request_id = confirmed_loan_request(cursor)
    with pytest.raises(DeviceActionError, match='貸出不可の故障'):
        user_requests.approve_loan_request(cursor, request_id, device_id)
    assert status(cursor, request_id) == 'confirmed'


def test_approve_loan_on_issue_request_is_not_found(cursor):
    device_id = borrowed_device(cursor)
    request_id = submit_issue(cursor, device_id)
    user_requests.confirm_request(cursor, request_id)
    with pytest.raises(RecordNotFound):
        user_requests.approve_loan_request(cursor, request_id, add_device(cursor))


# --- 不具合の申請を対応済みにする（故障として記録）---

@pytest.mark.parametrize('blocks_loan', [True, False])
def test_approve_issue_request_records_issue(cursor, blocks_loan):
    device_id = borrowed_device(cursor)
    request_id = submit_issue(cursor, device_id)
    user_requests.confirm_request(cursor, request_id)

    user_requests.approve_issue_request(cursor, request_id, blocks_loan)

    request = get_request(cursor, request_id)
    issue = fetch_one(cursor, 'SELECT * FROM device_issues WHERE id = %s', (request['issue_id'],))
    assert request['status'] == 'done'
    assert issue['device_id'] == device_id
    assert issue['detail'] == 'キーボードが反応しない'
    assert bool(issue['blocks_loan']) is blocks_loan


def test_approve_issue_request_needs_confirmation_first(cursor):
    request_id = submit_issue(cursor, borrowed_device(cursor))
    with pytest.raises(DeviceActionError, match='確認済みではありません'):
        user_requests.approve_issue_request(cursor, request_id, True)


# --- 却下 ---

@pytest.mark.parametrize('confirm_first', [False, True])
def test_reject_open_request(cursor, confirm_first):
    request_id = submit_loan(cursor)
    if confirm_first:
        user_requests.confirm_request(cursor, request_id)
    user_requests.reject_request(cursor, request_id)
    request = get_request(cursor, request_id)
    assert request['status'] == 'rejected'
    assert request['closed_at'] is not None


@pytest.mark.parametrize('close', ['reject', 'cancel'])
def test_cannot_reject_closed_request(cursor, close):
    request_id = submit_loan(cursor)
    if close == 'reject':
        user_requests.reject_request(cursor, request_id)
    else:
        user_requests.cancel_request(cursor, request_id, TANAKA)
    with pytest.raises(DeviceActionError, match='すでに処理されています'):
        user_requests.reject_request(cursor, request_id)


# --- 申請中に戻す ---

def test_reopen_confirmed_request(cursor):
    request_id = confirmed_loan_request(cursor)
    message = user_requests.reopen_request(cursor, request_id)
    request = get_request(cursor, request_id)
    assert message == '申請を申請中に戻しました。'
    assert request['status'] == 'pending'
    assert request['confirmed_at'] is None


def test_reopen_rejected_request(cursor):
    request_id = submit_loan(cursor)
    user_requests.reject_request(cursor, request_id)
    user_requests.reopen_request(cursor, request_id)
    request = get_request(cursor, request_id)
    assert request['status'] == 'pending'
    assert request['closed_at'] is None


def test_reopen_done_loan_request_cancels_the_loan(cursor):
    device_id = add_device(cursor)
    request_id = confirmed_loan_request(cursor)
    user_requests.approve_loan_request(cursor, request_id, device_id)
    loan_id = get_request(cursor, request_id)['loan_id']

    message = user_requests.reopen_request(cursor, request_id)

    assert message == '貸出記録を取り消し、申請を申請中に戻しました。'
    request = get_request(cursor, request_id)
    assert (request['status'], request['loan_id'], request['closed_at']) == ('pending', None, None)
    loan = fetch_one(cursor, 'SELECT cancelled_at FROM loans WHERE id = %s', (loan_id,))
    assert loan['cancelled_at'] is not None
    # 取り消した貸出は貸出中に数えないので、すぐ別の人に貸せる
    assert devices.find_open_loan(cursor, device_id) is None
    lend(cursor, device_id, SUZUKI)


def test_reopen_done_issue_request_cancels_the_issue(cursor):
    device_id = borrowed_device(cursor)
    request_id = submit_issue(cursor, device_id)
    user_requests.confirm_request(cursor, request_id)
    user_requests.approve_issue_request(cursor, request_id, True)
    issue_id = get_request(cursor, request_id)['issue_id']

    message = user_requests.reopen_request(cursor, request_id)

    assert message == '故障・不具合の記録を取り消し、申請を申請中に戻しました。'
    issue = fetch_one(cursor, 'SELECT cancelled_at FROM device_issues WHERE id = %s', (issue_id,))
    assert issue['cancelled_at'] is not None
    assert devices.fetch_device(cursor, device_id)['flags'] == []


def test_cannot_reopen_done_loan_after_it_was_returned(cursor):
    device_id = add_device(cursor)
    request_id = confirmed_loan_request(cursor)
    user_requests.approve_loan_request(cursor, request_id, device_id)
    loans.return_loan(cursor, get_request(cursor, request_id)['loan_id'])
    with pytest.raises(DeviceActionError, match='返却・修正された記録があるため'):
        user_requests.reopen_request(cursor, request_id)
    assert status(cursor, request_id) == 'done'


def test_cannot_reopen_done_request_without_linked_record(cursor):
    """取り消し機能（Migration 005）より前に対応済みにした申請は戻せない。"""
    request_id = submit_loan(cursor)
    cursor.execute(
        "UPDATE user_requests SET status = 'done', closed_at = NOW() WHERE id = %s", (request_id,)
    )
    with pytest.raises(DeviceActionError, match='取り消し機能を入れる前'):
        user_requests.reopen_request(cursor, request_id)


@pytest.mark.parametrize('close', [None, 'cancel'])
def test_cannot_reopen_pending_or_cancelled(cursor, close):
    request_id = submit_loan(cursor)
    if close:
        user_requests.cancel_request(cursor, request_id, TANAKA)
    with pytest.raises(DeviceActionError, match='確認済み・対応済み・却下の申請だけ'):
        user_requests.reopen_request(cursor, request_id)


def test_cannot_reopen_when_same_request_was_submitted_again(cursor):
    rejected = submit_loan(cursor)
    user_requests.reject_request(cursor, rejected)
    submit_loan(cursor)  # 却下されたので申請し直した
    with pytest.raises(DeviceActionError, match='同じ社員の同じ申請がすでにある'):
        user_requests.reopen_request(cursor, rejected)
    assert status(cursor, rejected) == 'rejected'


def test_reopen_missing_request(cursor):
    with pytest.raises(RecordNotFound):
        user_requests.reopen_request(cursor, 999999)


def test_full_round_trip(cursor):
    """申請 → 確認 → 貸出 → 申請中に戻す → もう一度確認 → 別の機器で貸出。"""
    first_device, second_device = add_device(cursor), add_device(cursor)
    request_id = confirmed_loan_request(cursor)
    user_requests.approve_loan_request(cursor, request_id, first_device)
    user_requests.reopen_request(cursor, request_id)
    user_requests.confirm_request(cursor, request_id)
    user_requests.approve_loan_request(cursor, request_id, second_device)

    assert status(cursor, request_id) == 'done'
    assert devices.find_open_loan(cursor, first_device) is None
    assert devices.find_open_loan(cursor, second_device)['shain_code'] == TANAKA


# --- 一覧の取得 ---

def test_fetch_requests_for_employee(cursor):
    device_id = borrowed_device(cursor)
    issue_id = submit_issue(cursor, device_id)
    loan_id = submit_loan(cursor)
    submit_loan(cursor, shain_code=SUZUKI)

    rows = user_requests.fetch_requests(cursor, TANAKA)

    assert {row['id'] for row in rows} == {issue_id, loan_id}
    by_id = {row['id']: row for row in rows}
    assert by_id[loan_id]['model_label'] == 'Dell Latitude 5440'
    assert by_id[loan_id]['identifier_summary'] is None
    # シリアル番号は一覧のまとめに出さないので、照合情報が無い機器と同じく管理番号で示す
    assert by_id[issue_id]['identifier_summary'] == format_device_code(device_id)


def test_admin_lists_and_pending_count(cursor):
    pending = submit_loan(cursor)
    confirmed = confirmed_loan_request(cursor, shain_code=SUZUKI)
    rejected = submit_loan(cursor, model_id=PC_OTHER)
    user_requests.reject_request(cursor, rejected)

    assert [r['id'] for r in user_requests.fetch_pending_requests(cursor)] == [pending]
    assert [r['id'] for r in user_requests.fetch_confirmed_requests(cursor)] == [confirmed]
    processed = user_requests.fetch_processed_requests(cursor, 10)
    assert [r['id'] for r in processed] == [rejected]
    assert processed[0]['employee_name'] == '田中太郎'
    assert user_requests.count_pending_requests(cursor) == 1


def test_processed_requests_paging(cursor):
    """処理済みは新しい順。limit / offset でページを分け、件数は別に数える。"""
    request_ids = []
    for model_id in (PC, PC_OTHER, SMARTPHONE):
        request_id = submit_loan(cursor, model_id=model_id)
        user_requests.reject_request(cursor, request_id)
        request_ids.append(request_id)
    # 同じ秒に閉じても、id の大きい方を新しいものとして並べる
    newest_first = request_ids[::-1]

    assert [r['id'] for r in user_requests.fetch_processed_requests(cursor, 2)] == newest_first[:2]
    assert [r['id'] for r in user_requests.fetch_processed_requests(cursor, 2, offset=2)] == newest_first[2:]
    assert user_requests.fetch_processed_requests(cursor, 2, offset=3) == ()
    assert user_requests.count_processed_requests(cursor) == 3
