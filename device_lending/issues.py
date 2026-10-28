"""故障・不具合の報告・解決・修正（request には触れない）。"""
from datetime import date

from .config import ISSUE_TEXT_MAX_LENGTH
from .devices import find_open_loan, lock_device
from .errors import DeviceActionError, RecordNotFound
from .events import build_changes, record_event

# report_issue の loan_id を省略したとき: 報告した時点の貸出を記録する
CURRENT_LOAN = object()


def fetch_issues(cursor, device_id):
    """機器の故障・不具合履歴（新しい順）。"""
    cursor.execute(
        '''
        SELECT id, reported_on, detail, blocks_loan, resolved_on, resolution
        FROM device_issues
        WHERE device_id = %s AND cancelled_at IS NULL
        ORDER BY reported_on DESC, id DESC
        ''',
        (device_id,),
    )
    return cursor.fetchall()


def _clean_text(text, label, required=False):
    text = (text or '').strip()
    if required and not text:
        raise DeviceActionError(f'{label}を入力してください。')
    if len(text) > ISSUE_TEXT_MAX_LENGTH:
        raise DeviceActionError(f'{label}は{ISSUE_TEXT_MAX_LENGTH}文字以内で入力してください。')
    return text


def report_issue(cursor, device_id, detail, blocks_loan, loan_id=CURRENT_LOAN):
    """故障・不具合を登録する。loan_id はそのとき機器を借りていた貸出（人物一覧で人に結びつける）。"""
    detail = _clean_text(detail, '内容', required=True)
    device = lock_device(cursor, device_id)
    if device['disposed_on']:
        raise DeviceActionError('廃棄済みの機器には登録できません。')
    if loan_id is CURRENT_LOAN:
        open_loan = find_open_loan(cursor, device_id)
        loan_id = open_loan['id'] if open_loan else None
    cursor.execute(
        '''
        INSERT INTO device_issues (device_id, loan_id, reported_on, detail, blocks_loan)
        VALUES (%s, %s, %s, %s, %s)
        ''',
        (device_id, loan_id, date.today(), detail, blocks_loan),
    )
    issue_id = cursor.lastrowid
    record_event(cursor, device_id, 'issue_reported', issue_id=issue_id)
    return issue_id


def _lock_issue(cursor, issue_id):
    """機器 → 故障の順にロックして故障の行を返す。取り消した記録は無いものとする。"""
    cursor.execute('SELECT device_id FROM device_issues WHERE id = %s', (issue_id,))
    found = cursor.fetchone()
    if found is None:
        raise RecordNotFound('故障・不具合の記録が見つかりません。')
    lock_device(cursor, found['device_id'])
    cursor.execute('SELECT * FROM device_issues WHERE id = %s FOR UPDATE', (issue_id,))
    issue = cursor.fetchone()
    if issue['cancelled_at'] is not None:
        raise RecordNotFound('故障・不具合の記録が見つかりません。')
    return issue


def resolve_issue(cursor, issue_id, resolution):
    resolution = _clean_text(resolution, '対処内容')
    issue = _lock_issue(cursor, issue_id)
    if issue['resolved_on'] is not None:
        raise DeviceActionError('この故障・不具合はすでに解決済みです。')
    cursor.execute(
        'UPDATE device_issues SET resolved_on = %s, resolution = %s WHERE id = %s',
        (date.today(), resolution or None, issue_id),
    )
    record_event(cursor, issue['device_id'], 'issue_resolved', issue_id=issue_id)


def cancel_issue(cursor, issue_id):
    """誤って登録した故障・不具合を取り消す（行は残す）。登録後に解決・修正していれば取り消せない。"""
    issue = _lock_issue(cursor, issue_id)
    cursor.execute(
        '''
        SELECT 1 FROM device_events
        WHERE issue_id = %s AND event_type <> 'issue_reported'
        LIMIT 1
        ''',
        (issue_id,),
    )
    if issue['resolved_on'] is not None or cursor.fetchone():
        raise DeviceActionError(
            '登録した後に解決・修正された記録があるため取り消せません。機器の画面から修正してください。'
        )
    cursor.execute(
        'UPDATE device_issues SET cancelled_at = CURRENT_TIMESTAMP WHERE id = %s', (issue_id,)
    )
    record_event(cursor, issue['device_id'], 'issue_cancelled', issue_id=issue_id)


def edit_issue(cursor, issue_id, detail, blocks_loan, reported_on, resolved_on, resolution):
    detail = _clean_text(detail, '内容', required=True)
    resolution = _clean_text(resolution, '対処内容') or None
    if reported_on is None:
        raise DeviceActionError('発生日を入力してください。')
    today = date.today()
    if reported_on > today or (resolved_on is not None and resolved_on > today):
        raise DeviceActionError('未来の日付は入力できません。')
    if resolved_on is not None and resolved_on < reported_on:
        raise DeviceActionError('解決日は発生日以降にしてください。')

    issue = _lock_issue(cursor, issue_id)
    issue['blocks_loan'] = bool(issue['blocks_loan'])
    changes = build_changes(issue, {
        'detail': detail,
        'blocks_loan': blocks_loan,
        'reported_on': reported_on,
        'resolved_on': resolved_on,
        'resolution': resolution,
    })
    if not changes:
        raise DeviceActionError('変更がありません。')
    cursor.execute(
        '''
        UPDATE device_issues
        SET detail = %s, blocks_loan = %s, reported_on = %s, resolved_on = %s, resolution = %s
        WHERE id = %s
        ''',
        (detail, blocks_loan, reported_on, resolved_on, resolution, issue_id),
    )
    record_event(cursor, issue['device_id'], 'issue_edited', issue_id=issue_id, changes=changes)
