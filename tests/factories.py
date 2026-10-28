"""テストデータを作る道具。社員・機種は conftest.py の MASTER_SCHEMA と対応している。"""
from itertools import count

from device_lending import devices, loans

# 社員（master_test.m_shain）
TANAKA = '1001'
SUZUKI = '1002'
RETIRED = '1003'
UNKNOWN_EMPLOYEE = '9999'

# 機種（master_test.m_device_model.id）
PC = 1
PC_OTHER = 2
SMARTPHONE = 3
DESK_PHONE = 4
MOBILE_WIFI = 5
UNKNOWN_MODEL = 999

_serials = count(1)


def add_device(cursor, model_id=PC, **identifiers):
    """機器を登録して id を返す。照合情報を指定しなければ、重ならないシリアル番号を付ける。"""
    if not identifiers:
        identifiers = {'serial_number': f'SN{next(_serials):05d}'}
    return devices.register_device(cursor, model_id, identifiers)


def lend(cursor, device_id, shain_code=TANAKA):
    """貸し出して、その貸出の id を返す。"""
    loans.loan_device(cursor, device_id, shain_code)
    return devices.find_open_loan(cursor, device_id)['id']


def fetch_one(cursor, sql, params=()):
    cursor.execute(sql, params)
    return cursor.fetchone()


def latest_request(cursor):
    return fetch_one(cursor, 'SELECT * FROM user_requests ORDER BY id DESC LIMIT 1')


def get_request(cursor, request_id):
    return fetch_one(cursor, 'SELECT * FROM user_requests WHERE id = %s', (request_id,))


def event_types(cursor, device_id):
    """機器の履歴の種類（古い順）。"""
    cursor.execute(
        'SELECT event_type FROM device_events WHERE device_id = %s ORDER BY id', (device_id,)
    )
    return [row['event_type'] for row in cursor.fetchall()]


def device_row(**overrides):
    """_DEVICE_SELECT が返す 1 行と同じ形の dict（DB を使わずに derive_state などを試す用）。"""
    row = {
        'id': 1, 'device_model_id': PC, 'status': 'available', 'location': None,
        'disposed_on': None, 'disposal_reason': None,
        'hostname': None, 'extension': None, 'serial_number': None,
        'sim_id': None, 'sim_iccid': None, 'phone_number': None, 'sim_extension': None,
        'device_type': 'PC', 'manufacturer': 'Dell', 'model_name': 'Latitude 5440',
        'loan_id': None, 'holder_code': None, 'loaned_on': None, 'holder_name': None,
        'holder_missing': 0, 'holder_retired': 0,
        'has_blocking_issue': 0, 'has_minor_issue': 0, 'is_lost': 0,
    }
    row.update(overrides)
    return row
