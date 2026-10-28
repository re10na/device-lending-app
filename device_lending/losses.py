"""紛失の報告・解除（request には触れない）。

紛失は注意フラグで、配置（貸出中・設置中・保管中）はそのまま。貸出中に紛失しても貸出は続く。
利用者の報告は申請の流れを通さず、その場で紛失中にする（情報漏えい対策を急ぐため）。
誤報告は管理者が解除する。
"""
from datetime import date

import pymysql

from . import masters
from .config import ISSUE_TEXT_MAX_LENGTH
from .devices import find_open_loan, find_open_loss, lock_device
from .errors import DeviceActionError, RecordNotFound
from .events import record_event

_ALREADY_LOST = 'この機器はすでに紛失中として登録されています。'


def fetch_losses(cursor, device_id):
    """機器の紛失履歴（新しい順）。紛失時に借りていた社員の名前は master から付ける。"""
    cursor.execute(
        f'''
        SELECT ls.id, ls.shain_code, ls.reported_by, ls.reported_on, ls.detail,
               ls.found_on, ls.resolution, s.name AS employee_name
        FROM device_losses AS ls
        LEFT JOIN {masters.SHAIN_TABLE} AS s ON s.shain_code = ls.shain_code
        WHERE ls.device_id = %s
        ORDER BY ls.reported_on DESC, ls.id DESC
        ''',
        (device_id,),
    )
    return cursor.fetchall()


def _clean_text(text, label):
    text = (text or '').strip()
    if len(text) > ISSUE_TEXT_MAX_LENGTH:
        raise DeviceActionError(f'{label}は{ISSUE_TEXT_MAX_LENGTH}文字以内で入力してください。')
    return text or None


def _insert_loss(cursor, device_id, loan, reported_by, detail):
    """紛失中として登録する。呼び出し側で機器の行をロックしておくこと。"""
    if find_open_loss(cursor, device_id):
        raise DeviceActionError(_ALREADY_LOST)
    try:
        cursor.execute(
            '''
            INSERT INTO device_losses
                (device_id, loan_id, shain_code, reported_by, reported_on, detail)
            VALUES (%s, %s, %s, %s, %s, %s)
            ''',
            (
                device_id,
                loan['id'] if loan else None,
                loan['shain_code'] if loan else None,
                reported_by,
                date.today(),
                detail,
            ),
        )
    except pymysql.err.IntegrityError as error:
        # 同時に送られた報告（事前の確認をすり抜けたもの）
        if 'uq_device_losses_one_open_per_device' in str(error):
            raise DeviceActionError(_ALREADY_LOST) from error
        raise
    loss_id = cursor.lastrowid
    record_event(cursor, device_id, 'lost_reported', loss_id=loss_id)
    return loss_id


def report_loss(cursor, device_id, detail):
    """管理者が紛失中にする。貸出中なら、その貸出と借りている社員も記録する。"""
    detail = _clean_text(detail, '紛失の状況')
    device = lock_device(cursor, device_id)
    if device['disposed_on']:
        raise DeviceActionError('廃棄済みの機器は紛失にできません。')
    return _insert_loss(cursor, device_id, find_open_loan(cursor, device_id), 'admin', detail)


def report_loss_by_user(cursor, shain_code, device_id, detail):
    """利用者が、自分が借りている機器の紛失を報告する（その場で紛失中になる）。"""
    detail = _clean_text(detail, '紛失の状況')
    employee = masters.find_employee(cursor, shain_code) if shain_code else None
    if employee is None or employee['is_retired']:
        raise DeviceActionError('社員を選択してください。')
    lock_device(cursor, device_id)
    loan = find_open_loan(cursor, device_id)
    if loan is None or loan['shain_code'] != shain_code:
        raise DeviceActionError('紛失を報告できるのは、今借りている機器だけです。')
    return _insert_loss(cursor, device_id, loan, 'user', detail)


def resolve_loss(cursor, loss_id, resolution):
    """見つかった・誤報告だったときに紛失を解除する。貸出中だった機器は貸出中のまま。"""
    resolution = _clean_text(resolution, '見つかった場所・理由')
    cursor.execute('SELECT device_id FROM device_losses WHERE id = %s', (loss_id,))
    found = cursor.fetchone()
    if found is None:
        raise RecordNotFound('紛失の記録が見つかりません。')
    # 他の操作と同じく、機器 → 紛失の順にロックする
    device = lock_device(cursor, found['device_id'])
    if device['disposed_on']:
        raise DeviceActionError('廃棄済みの機器の紛失は解除できません。')
    cursor.execute('SELECT found_on FROM device_losses WHERE id = %s FOR UPDATE', (loss_id,))
    if cursor.fetchone()['found_on'] is not None:
        raise DeviceActionError('この紛失はすでに解除されています。')
    cursor.execute(
        'UPDATE device_losses SET found_on = %s, resolution = %s WHERE id = %s',
        (date.today(), resolution, loss_id),
    )
    record_event(cursor, found['device_id'], 'lost_found', loss_id=loss_id)
