"""貸出・返却・貸出記録の修正（request には触れない）。"""
from datetime import date

from . import masters
from .devices import find_open_loan, find_open_loss, lock_device
from .errors import DeviceActionError, RecordNotFound
from .events import build_changes, record_event

FAR_FUTURE = date(9999, 12, 31)


def fetch_loans(cursor, device_id):
    """機器の貸出履歴（新しい順）。社員名は master から付ける。"""
    cursor.execute(
        f'''
        SELECT l.id, l.shain_code, l.loaned_on, l.returned_on,
               s.name AS employee_name,
               (l.shain_code IS NOT NULL AND s.id IS NULL) AS employee_missing,
               {masters.retired_condition('s.taishoku_date')} AS employee_retired
        FROM loans AS l
        LEFT JOIN {masters.SHAIN_TABLE} AS s ON s.shain_code = l.shain_code
        WHERE l.device_id = %s AND l.cancelled_at IS NULL
        ORDER BY l.loaned_on DESC, l.id DESC
        ''',
        (device_id,),
    )
    return cursor.fetchall()


def _has_blocking_issue(cursor, device_id):
    cursor.execute(
        '''
        SELECT 1 FROM device_issues
        WHERE device_id = %s AND resolved_on IS NULL AND cancelled_at IS NULL AND blocks_loan
        LIMIT 1
        ''',
        (device_id,),
    )
    return cursor.fetchone() is not None


def loan_device(cursor, device_id, shain_code):
    """貸出を登録し、借りた人の名前を返す。"""
    device = lock_device(cursor, device_id)
    if device['disposed_on']:
        raise DeviceActionError('廃棄済みの機器は貸し出せません。')
    if _has_blocking_issue(cursor, device_id):
        raise DeviceActionError('貸出不可の故障・不具合が未解決のため貸し出せません。')
    if find_open_loss(cursor, device_id):
        raise DeviceActionError('紛失中の機器は貸し出せません。')
    if device['status'] == 'installed':
        raise DeviceActionError('設置中の機器は貸し出せません。先に保管中に戻してください。')
    if find_open_loan(cursor, device_id):
        raise DeviceActionError('この機器はすでに貸出中です。')
    employee = masters.find_employee(cursor, shain_code) if shain_code else None
    if employee is None or employee['is_retired']:
        raise DeviceActionError('選択した社員が見つからないか、退職済みです。')

    cursor.execute(
        'INSERT INTO loans (device_id, shain_code, loaned_on) VALUES (%s, %s, %s)',
        (device_id, shain_code, date.today()),
    )
    record_event(cursor, device_id, 'loaned', loan_id=cursor.lastrowid)
    return employee['name']


def _lock_loan(cursor, loan_id):
    """機器 → 貸出の順にロックし、(貸出の行, 機器の行) を返す。取り消した貸出は無いものとする。"""
    cursor.execute('SELECT device_id FROM loans WHERE id = %s', (loan_id,))
    found = cursor.fetchone()
    if found is None:
        raise RecordNotFound('貸出記録が見つかりません。')
    device = lock_device(cursor, found['device_id'])
    cursor.execute('SELECT * FROM loans WHERE id = %s FOR UPDATE', (loan_id,))
    loan = cursor.fetchone()
    if loan['cancelled_at'] is not None:
        raise RecordNotFound('貸出記録が見つかりません。')
    return loan, device


def return_loan(cursor, loan_id):
    loan, _ = _lock_loan(cursor, loan_id)
    if loan['returned_on'] is not None:
        raise DeviceActionError('この貸出はすでに返却済みです。')
    if find_open_loss(cursor, loan['device_id']):
        raise DeviceActionError('紛失中の機器は返却できません。見つかった場合は先に紛失を解除してください。')
    cursor.execute(
        'UPDATE loans SET returned_on = %s WHERE id = %s', (date.today(), loan_id)
    )
    record_event(cursor, loan['device_id'], 'returned', loan_id=loan_id)


def cancel_loan(cursor, loan_id):
    """誤って登録した貸出を取り消す（行は残す）。貸し出した後に返却・修正していれば取り消せない。"""
    loan, _ = _lock_loan(cursor, loan_id)
    cursor.execute(
        '''
        SELECT 1 FROM device_events
        WHERE loan_id = %s AND event_type <> 'loaned'
        LIMIT 1
        ''',
        (loan_id,),
    )
    if loan['returned_on'] is not None or cursor.fetchone():
        raise DeviceActionError(
            '貸し出した後に返却・修正された記録があるため取り消せません。機器の画面から修正してください。'
        )
    cursor.execute(
        'UPDATE loans SET cancelled_at = CURRENT_TIMESTAMP WHERE id = %s', (loan_id,)
    )
    record_event(cursor, loan['device_id'], 'loan_cancelled', loan_id=loan_id)


def _check_loan_dates(loaned_on, returned_on):
    if loaned_on is None:
        raise DeviceActionError('貸出日を入力してください。')
    today = date.today()
    if loaned_on > today or (returned_on is not None and returned_on > today):
        raise DeviceActionError('未来の日付は入力できません。')
    if returned_on is not None and returned_on < loaned_on:
        raise DeviceActionError('返却日は貸出日以降にしてください。')


def _check_no_conflict(cursor, loan, loaned_on, returned_on):
    """同じ機器の他の貸出と期間が重ならないか確認する（返却日 NULL は期限なし）。

    期間は [貸出日, 返却日) として扱い、返却した当日に別の人へ貸すのは許す。
    """
    if returned_on is None:
        cursor.execute(
            '''
            SELECT 1 FROM loans
            WHERE device_id = %s AND id <> %s AND returned_on IS NULL AND cancelled_at IS NULL
            LIMIT 1
            ''',
            (loan['device_id'], loan['id']),
        )
        if cursor.fetchone():
            raise DeviceActionError('他の貸出がすでに貸出中のため、貸出中にはできません。')
    cursor.execute(
        '''
        SELECT 1 FROM loans
        WHERE device_id = %s AND id <> %s AND cancelled_at IS NULL
          AND loaned_on < %s
          AND %s < COALESCE(returned_on, %s)
        LIMIT 1
        ''',
        (loan['device_id'], loan['id'], returned_on or FAR_FUTURE, loaned_on, FAR_FUTURE),
    )
    if cursor.fetchone():
        raise DeviceActionError('他の貸出と期間が重なっています。')


def edit_loan(cursor, loan_id, shain_code, loaned_on, returned_on):
    loan, device = _lock_loan(cursor, loan_id)
    _check_loan_dates(loaned_on, returned_on)
    # 返却日を消して貸出中に戻す場合は、新規貸出と同じく機器の状態を確認する
    if loan['returned_on'] is not None and returned_on is None:
        if device['disposed_on']:
            raise DeviceActionError('廃棄済みの機器を貸出中に戻すことはできません。')
        if device['status'] == 'installed':
            raise DeviceActionError('設置中の機器を貸出中に戻すことはできません。')
    changes = build_changes(loan, {
        'shain_code': shain_code,
        'loaned_on': loaned_on,
        'returned_on': returned_on,
    })
    if not changes:
        raise DeviceActionError('変更がありません。')
    # 履歴の修正なので退職者は許す。すでに不明な社員番号のままなら再確認しない
    if 'shain_code' in changes and (
        not shain_code or masters.find_employee(cursor, shain_code) is None
    ):
        raise DeviceActionError('入力した社員番号が社員マスタに見つかりません。')
    _check_no_conflict(cursor, loan, loaned_on, returned_on)

    cursor.execute(
        'UPDATE loans SET shain_code = %s, loaned_on = %s, returned_on = %s WHERE id = %s',
        (shain_code, loaned_on, returned_on, loan_id),
    )
    record_event(cursor, loan['device_id'], 'loan_edited', loan_id=loan_id, changes=changes)
