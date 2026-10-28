"""故障・不具合（issues.py）と紛失（losses.py）。"""
from datetime import date, timedelta

import pymysql
import pytest

from device_lending import devices, issues, loans, losses
from device_lending.errors import DeviceActionError, RecordNotFound

from .factories import RETIRED, SUZUKI, TANAKA, add_device, event_types, fetch_one, lend

TODAY = date.today()


def get_issue(cursor, issue_id):
    return fetch_one(cursor, 'SELECT * FROM device_issues WHERE id = %s', (issue_id,))


def get_loss(cursor, loss_id):
    return fetch_one(cursor, 'SELECT * FROM device_losses WHERE id = %s', (loss_id,))


# --- 故障・不具合 ---

def test_report_issue(cursor):
    device_id = add_device(cursor)
    issue_id = issues.report_issue(cursor, device_id, ' 起動しない ', blocks_loan=True)
    issue = get_issue(cursor, issue_id)
    assert (issue['detail'], issue['reported_on'], issue['blocks_loan']) == ('起動しない', TODAY, 1)
    assert event_types(cursor, device_id)[-1] == 'issue_reported'
    assert devices.fetch_device(cursor, device_id)['flags'] == ['broken']


def test_report_issue_needs_detail(cursor):
    with pytest.raises(DeviceActionError, match='内容を入力してください'):
        issues.report_issue(cursor, add_device(cursor), '  ', True)


def test_cannot_report_issue_on_disposed(cursor):
    device_id = add_device(cursor)
    devices.dispose_device(cursor, device_id, '')
    with pytest.raises(DeviceActionError, match='廃棄済み'):
        issues.report_issue(cursor, device_id, '起動しない', True)


def test_resolve_issue(cursor):
    device_id = add_device(cursor)
    issue_id = issues.report_issue(cursor, device_id, '起動しない', True)
    issues.resolve_issue(cursor, issue_id, '  ')
    issue = get_issue(cursor, issue_id)
    assert issue['resolved_on'] == TODAY
    assert issue['resolution'] is None  # 対処内容は任意。空は NULL
    assert devices.fetch_device(cursor, device_id)['flags'] == []
    with pytest.raises(DeviceActionError, match='すでに解決済み'):
        issues.resolve_issue(cursor, issue_id, '')


def test_cancel_issue(cursor):
    device_id = add_device(cursor)
    issue_id = issues.report_issue(cursor, device_id, '起動しない', True)
    issues.cancel_issue(cursor, issue_id)
    assert not issues.fetch_issues(cursor, device_id)
    assert devices.fetch_device(cursor, device_id)['flags'] == []
    with pytest.raises(RecordNotFound):
        issues.resolve_issue(cursor, issue_id, '')


def test_cannot_cancel_resolved_issue(cursor):
    issue_id = issues.report_issue(cursor, add_device(cursor), '起動しない', True)
    issues.resolve_issue(cursor, issue_id, '')
    with pytest.raises(DeviceActionError, match='取り消せません'):
        issues.cancel_issue(cursor, issue_id)


def test_edit_issue(cursor):
    issue_id = issues.report_issue(cursor, add_device(cursor), '起動しない', True)
    yesterday = TODAY - timedelta(days=1)
    issues.edit_issue(cursor, issue_id, '起動が遅い', False, yesterday, None, '')
    issue = get_issue(cursor, issue_id)
    assert (issue['detail'], issue['blocks_loan'], issue['reported_on']) == ('起動が遅い', 0, yesterday)
    with pytest.raises(DeviceActionError, match='変更がありません'):
        issues.edit_issue(cursor, issue_id, '起動が遅い', False, yesterday, None, '')


@pytest.mark.parametrize('reported_on, resolved_on, message', [
    (None, None, '発生日を入力してください'),
    (TODAY + timedelta(days=1), None, '未来の日付'),
    (TODAY, TODAY - timedelta(days=1), '解決日は発生日以降'),
])
def test_edit_issue_date_rules(cursor, reported_on, resolved_on, message):
    issue_id = issues.report_issue(cursor, add_device(cursor), '起動しない', True)
    with pytest.raises(DeviceActionError, match=message):
        issues.edit_issue(cursor, issue_id, '起動しない', True, reported_on, resolved_on, '')


# --- 紛失（管理者）---

def test_admin_reports_loss_of_stored_device(cursor):
    device_id = add_device(cursor)
    loss_id = losses.report_loss(cursor, device_id, '')
    loss = get_loss(cursor, loss_id)
    assert (loss['reported_by'], loss['loan_id'], loss['detail']) == ('admin', None, None)
    device = devices.fetch_device(cursor, device_id)
    assert (device['placement'], device['flags']) == ('stored', ['lost'])


def test_admin_reports_loss_of_loaned_device_keeps_loan(cursor):
    device_id = add_device(cursor)
    loan_id = lend(cursor, device_id)
    loss = get_loss(cursor, losses.report_loss(cursor, device_id, '電車で紛失'))
    assert (loss['loan_id'], loss['shain_code']) == (loan_id, TANAKA)
    assert devices.fetch_device(cursor, device_id)['placement'] == 'loaned'


def test_cannot_report_loss_twice(cursor):
    device_id = add_device(cursor)
    losses.report_loss(cursor, device_id, '')
    with pytest.raises(DeviceActionError, match='すでに紛失中'):
        losses.report_loss(cursor, device_id, '')


def test_db_allows_only_one_open_loss_per_device(cursor):
    device_id = add_device(cursor)
    losses.report_loss(cursor, device_id, '')
    with pytest.raises(pymysql.err.IntegrityError, match='uq_device_losses_one_open_per_device'):
        cursor.execute(
            "INSERT INTO device_losses (device_id, reported_by, reported_on) VALUES (%s, 'admin', CURDATE())",
            (device_id,),
        )


def test_cannot_report_loss_of_disposed(cursor):
    device_id = add_device(cursor)
    devices.dispose_device(cursor, device_id, '')
    with pytest.raises(DeviceActionError, match='廃棄済み'):
        losses.report_loss(cursor, device_id, '')


# --- 紛失（利用者の報告）---

def test_user_reports_loss_of_own_loan(cursor):
    device_id = add_device(cursor)
    loan_id = lend(cursor, device_id)
    loss = get_loss(cursor, losses.report_loss_by_user(cursor, TANAKA, device_id, '駅で紛失'))
    assert (loss['reported_by'], loss['loan_id'], loss['detail']) == ('user', loan_id, '駅で紛失')
    assert devices.fetch_device(cursor, device_id)['flags'] == ['lost']


def test_user_cannot_report_loss_of_others_device(cursor):
    device_id = add_device(cursor)
    lend(cursor, device_id, SUZUKI)
    with pytest.raises(DeviceActionError, match='今借りている機器だけ'):
        losses.report_loss_by_user(cursor, TANAKA, device_id, '')


def test_retired_user_cannot_report_loss(cursor):
    device_id = add_device(cursor)
    loan_id = lend(cursor, device_id)
    loans.edit_loan(cursor, loan_id, RETIRED, TODAY, None)
    with pytest.raises(DeviceActionError, match='社員を選択してください'):
        losses.report_loss_by_user(cursor, RETIRED, device_id, '')


# --- 紛失の解除 ---

def test_resolve_loss_keeps_loan(cursor):
    device_id = add_device(cursor)
    lend(cursor, device_id)
    loss_id = losses.report_loss(cursor, device_id, '')
    losses.resolve_loss(cursor, loss_id, '机の下にあった')

    loss = get_loss(cursor, loss_id)
    assert (loss['found_on'], loss['resolution']) == (TODAY, '机の下にあった')
    device = devices.fetch_device(cursor, device_id)
    assert (device['placement'], device['flags']) == ('loaned', [])
    assert event_types(cursor, device_id)[-2:] == ['lost_reported', 'lost_found']
    with pytest.raises(DeviceActionError, match='すでに解除'):
        losses.resolve_loss(cursor, loss_id, '')


def test_device_can_be_lost_again_after_found(cursor):
    device_id = add_device(cursor)
    losses.resolve_loss(cursor, losses.report_loss(cursor, device_id, ''), '')
    losses.report_loss(cursor, device_id, '')
    assert len(losses.fetch_losses(cursor, device_id)) == 2


def test_resolve_missing_loss(cursor):
    with pytest.raises(RecordNotFound):
        losses.resolve_loss(cursor, 999999, '')
