"""貸出・返却・取り消し・貸出記録の修正（loans.py）。"""
from datetime import date, timedelta

import pytest

from device_lending import devices, issues, loans, losses
from device_lending.errors import DeviceActionError, RecordNotFound

from .factories import (
    RETIRED, SUZUKI, TANAKA, UNKNOWN_EMPLOYEE, add_device, event_types, fetch_one, lend,
)

TODAY = date.today()


def get_loan(cursor, loan_id):
    return fetch_one(cursor, 'SELECT * FROM loans WHERE id = %s', (loan_id,))


# --- 貸出 ---

def test_loan_device(cursor):
    device_id = add_device(cursor)
    assert loans.loan_device(cursor, device_id, TANAKA) == '田中太郎'
    loan = devices.find_open_loan(cursor, device_id)
    assert loan['shain_code'] == TANAKA
    assert get_loan(cursor, loan['id'])['loaned_on'] == TODAY
    assert event_types(cursor, device_id) == ['registered', 'loaned']
    assert devices.fetch_device(cursor, device_id)['placement'] == 'loaned'


def test_cannot_lend_twice(cursor):
    device_id = add_device(cursor)
    lend(cursor, device_id)
    with pytest.raises(DeviceActionError, match='すでに貸出中'):
        loans.loan_device(cursor, device_id, SUZUKI)


@pytest.mark.parametrize('shain_code', [RETIRED, UNKNOWN_EMPLOYEE, ''])
def test_cannot_lend_to_retired_or_unknown(cursor, shain_code):
    device_id = add_device(cursor)
    with pytest.raises(DeviceActionError, match='見つからないか、退職済み'):
        loans.loan_device(cursor, device_id, shain_code)


def test_cannot_lend_disposed(cursor):
    device_id = add_device(cursor)
    devices.dispose_device(cursor, device_id, '老朽化')
    with pytest.raises(DeviceActionError, match='廃棄済み'):
        loans.loan_device(cursor, device_id, TANAKA)


def test_cannot_lend_installed(cursor):
    device_id = add_device(cursor)
    devices.install_device(cursor, device_id, '会議室A')
    with pytest.raises(DeviceActionError, match='設置中'):
        loans.loan_device(cursor, device_id, TANAKA)


def test_cannot_lend_lost(cursor):
    device_id = add_device(cursor)
    losses.report_loss(cursor, device_id, '')
    with pytest.raises(DeviceActionError, match='紛失中'):
        loans.loan_device(cursor, device_id, TANAKA)


def test_blocking_issue_prevents_loan_but_minor_issue_does_not(cursor):
    broken = add_device(cursor)
    issues.report_issue(cursor, broken, '起動しない', blocks_loan=True)
    with pytest.raises(DeviceActionError, match='貸出不可の故障'):
        loans.loan_device(cursor, broken, TANAKA)

    minor = add_device(cursor)
    issues.report_issue(cursor, minor, 'キーが 1 つ固い', blocks_loan=False)
    loans.loan_device(cursor, minor, TANAKA)


def test_resolved_issue_no_longer_prevents_loan(cursor):
    device_id = add_device(cursor)
    issue_id = issues.report_issue(cursor, device_id, '起動しない', blocks_loan=True)
    issues.resolve_issue(cursor, issue_id, '修理済み')
    loans.loan_device(cursor, device_id, TANAKA)


def test_loan_missing_device(cursor):
    with pytest.raises(RecordNotFound):
        loans.loan_device(cursor, 999999, TANAKA)


# --- 返却 ---

def test_return_loan(cursor):
    device_id = add_device(cursor)
    loan_id = lend(cursor, device_id)
    loans.return_loan(cursor, loan_id)
    assert get_loan(cursor, loan_id)['returned_on'] == TODAY
    assert devices.find_open_loan(cursor, device_id) is None
    assert event_types(cursor, device_id)[-1] == 'returned'
    # 返却したら別の人に貸せる
    lend(cursor, device_id, SUZUKI)


def test_cannot_return_twice(cursor):
    loan_id = lend(cursor, add_device(cursor))
    loans.return_loan(cursor, loan_id)
    with pytest.raises(DeviceActionError, match='すでに返却済み'):
        loans.return_loan(cursor, loan_id)


def test_cannot_return_while_lost(cursor):
    device_id = add_device(cursor)
    loan_id = lend(cursor, device_id)
    losses.report_loss(cursor, device_id, '')
    with pytest.raises(DeviceActionError, match='紛失中の機器は返却できません'):
        loans.return_loan(cursor, loan_id)


def test_return_missing_loan(cursor):
    with pytest.raises(RecordNotFound):
        loans.return_loan(cursor, 999999)


# --- 取り消し ---

def test_cancel_loan(cursor):
    device_id = add_device(cursor)
    loan_id = lend(cursor, device_id)
    loans.cancel_loan(cursor, loan_id)
    assert get_loan(cursor, loan_id)['cancelled_at'] is not None
    assert devices.find_open_loan(cursor, device_id) is None
    assert not loans.fetch_loans(cursor, device_id)  # 取り消した貸出は履歴にも出さない
    assert event_types(cursor, device_id)[-1] == 'loan_cancelled'


def test_cancelled_loan_is_treated_as_missing(cursor):
    loan_id = lend(cursor, add_device(cursor))
    loans.cancel_loan(cursor, loan_id)
    with pytest.raises(RecordNotFound):
        loans.return_loan(cursor, loan_id)
    with pytest.raises(RecordNotFound):
        loans.cancel_loan(cursor, loan_id)


def test_cannot_cancel_after_return_or_edit(cursor):
    returned = lend(cursor, add_device(cursor))
    loans.return_loan(cursor, returned)
    with pytest.raises(DeviceActionError, match='取り消せません'):
        loans.cancel_loan(cursor, returned)

    edited = lend(cursor, add_device(cursor))
    loans.edit_loan(cursor, edited, SUZUKI, TODAY, None)
    with pytest.raises(DeviceActionError, match='取り消せません'):
        loans.cancel_loan(cursor, edited)


# --- 貸出記録の修正 ---

def test_edit_loan_records_changes(cursor):
    device_id = add_device(cursor)
    loan_id = lend(cursor, device_id)
    yesterday = TODAY - timedelta(days=1)
    loans.edit_loan(cursor, loan_id, SUZUKI, yesterday, TODAY)

    loan = get_loan(cursor, loan_id)
    assert (loan['shain_code'], loan['loaned_on'], loan['returned_on']) == (SUZUKI, yesterday, TODAY)
    event = fetch_one(
        cursor, "SELECT changes FROM device_events WHERE event_type = 'loan_edited' AND loan_id = %s",
        (loan_id,),
    )
    assert '"shain_code": ["1001", "1002"]' in event['changes']


def test_edit_loan_allows_retired_employee(cursor):
    """過去の記録の修正なので、退職者にも直せる。"""
    loan_id = lend(cursor, add_device(cursor))
    loans.edit_loan(cursor, loan_id, RETIRED, TODAY, None)
    assert get_loan(cursor, loan_id)['shain_code'] == RETIRED


def test_edit_loan_rejects_unknown_employee(cursor):
    loan_id = lend(cursor, add_device(cursor))
    with pytest.raises(DeviceActionError, match='社員マスタに見つかりません'):
        loans.edit_loan(cursor, loan_id, UNKNOWN_EMPLOYEE, TODAY, None)


def test_edit_loan_without_changes(cursor):
    loan_id = lend(cursor, add_device(cursor))
    with pytest.raises(DeviceActionError, match='変更がありません'):
        loans.edit_loan(cursor, loan_id, TANAKA, TODAY, None)


@pytest.mark.parametrize('loaned_on, returned_on, message', [
    (None, None, '貸出日を入力してください'),
    (TODAY + timedelta(days=1), None, '未来の日付'),
    (TODAY, TODAY + timedelta(days=1), '未来の日付'),
    (TODAY, TODAY - timedelta(days=1), '返却日は貸出日以降'),
])
def test_edit_loan_date_rules(cursor, loaned_on, returned_on, message):
    loan_id = lend(cursor, add_device(cursor))
    with pytest.raises(DeviceActionError, match=message):
        loans.edit_loan(cursor, loan_id, TANAKA, loaned_on, returned_on)


def test_edit_loan_rejects_overlapping_period(cursor):
    device_id = add_device(cursor)
    first = lend(cursor, device_id)
    loans.edit_loan(cursor, first, TANAKA, TODAY - timedelta(days=10), TODAY - timedelta(days=5))
    second = lend(cursor, device_id, SUZUKI)
    with pytest.raises(DeviceActionError, match='期間が重なっています'):
        loans.edit_loan(cursor, second, SUZUKI, TODAY - timedelta(days=7), None)
    # 返却した当日からの貸出は重なりにしない
    loans.edit_loan(cursor, second, SUZUKI, TODAY - timedelta(days=5), None)


def test_edit_loan_cannot_reopen_when_another_loan_is_open(cursor):
    device_id = add_device(cursor)
    first = lend(cursor, device_id)
    loans.return_loan(cursor, first)
    lend(cursor, device_id, SUZUKI)
    with pytest.raises(DeviceActionError, match='他の貸出がすでに貸出中'):
        loans.edit_loan(cursor, first, TANAKA, TODAY, None)


def test_edit_loan_cannot_reopen_on_installed_device(cursor):
    device_id = add_device(cursor)
    loan_id = lend(cursor, device_id)
    loans.return_loan(cursor, loan_id)
    devices.install_device(cursor, device_id, '受付')
    with pytest.raises(DeviceActionError, match='設置中の機器を貸出中に戻す'):
        loans.edit_loan(cursor, loan_id, TANAKA, TODAY, None)


def test_fetch_loans_newest_first_with_employee_state(cursor):
    device_id = add_device(cursor)
    old = lend(cursor, device_id)
    # 退職者には貸し出せないので、過去の記録として退職者に直す
    loans.edit_loan(cursor, old, RETIRED, TODAY - timedelta(days=3), TODAY - timedelta(days=1))
    current = lend(cursor, device_id, TANAKA)

    rows = loans.fetch_loans(cursor, device_id)

    assert [row['id'] for row in rows] == [current, old]
    assert rows[0]['employee_name'] == '田中太郎'
    assert rows[1]['employee_retired'] == 1
