"""SIM の取得と、登録/外線・内線の変更/機器への差し替え/外す。

SIM は機器から独立していて、機器に差し替えられる（1 台に 1 枚まで）。外線・内線は SIM が持つので、
別の機器に差し替えると一緒に移る。ロックは他の処理と同じく機器 → SIM の順に取る。
"""
import pymysql

from . import devices, identifiers, masters
from .codes import format_device_code
from .config import SIM_FIELDS
from .errors import DeviceActionError, RecordNotFound
from .events import build_changes, record_event

_DIGIT_FIELDS = ('iccid', 'phone_number')


def _with_labels(row):
    row['label'] = identifiers.sim_label(row['iccid'], row['phone_number'])
    row['phone_display'] = identifiers.format_phone(row['phone_number'])
    if row['device_id']:
        row['device_code'] = format_device_code(row['device_id'])
        row['device_name'] = row['hostname'] or row['device_code']
        row['device_model_label'] = (
            masters.format_model(row) if row['model_name'] else '不明な機種'
        )
    return row


def fetch_sims(cursor):
    """SIM の一覧（登録順）。差している機器の情報も付ける。"""
    cursor.execute(
        f'''
        SELECT sm.id, sm.iccid, sm.phone_number, sm.extension, sm.device_id,
               d.hostname, m.device_type, m.manufacturer, m.model_name
        FROM sims AS sm
        LEFT JOIN devices AS d ON d.id = sm.device_id
        LEFT JOIN {masters.MODEL_TABLE} AS m ON m.id = d.device_model_id
        ORDER BY sm.id
        '''
    )
    return [_with_labels(row) for row in cursor.fetchall()]


def fetch_unassigned_sims(cursor):
    """どの機器にも差していない SIM。"""
    return [sim for sim in fetch_sims(cursor) if sim['device_id'] is None]


def _clean(raw):
    """フォーム入力 {項目名: 文字列} を正規化する。SIM番号か外線のどちらかは必須。"""
    values = {
        field: identifiers.clean_value(
            raw.get(field), name, max_length, digits=field in _DIGIT_FIELDS
        )
        for field, (name, max_length, _) in SIM_FIELDS.items()
    }
    if not (values['iccid'] or values['phone_number']):
        raise DeviceActionError('SIM番号（ICCID）か外線（電話番号）のどちらかを入力してください。')
    return values


def _shown(field, value):
    return identifiers.format_phone(value) if field == 'phone_number' else value


def _check_duplicates(cursor, values, exclude_id=None):
    """他の SIM や、機器の内線と番号が重ならないこと（UNIQUE の前に分かりやすく伝える）。"""
    for field in SIM_FIELDS:
        value = values.get(field)
        if value is None:
            continue
        # field は定数のホワイトリストから来る（SQL に埋め込んでよい）
        cursor.execute(
            f'SELECT id, iccid, phone_number FROM sims WHERE {field} = %s AND id <> %s LIMIT 1',
            (value, exclude_id or 0),
        )
        other = cursor.fetchone()
        if other:
            raise DeviceActionError(
                f'{SIM_FIELDS[field][0]}「{_shown(field, value)}」はすでに別の SIM'
                f'（{identifiers.sim_label(other["iccid"], other["phone_number"])}）で使われています。'
            )
    if values.get('extension'):
        identifiers.reject_extension_on_device(cursor, values['extension'])


def _execute_guarded(cursor, sql, params, values):
    """uq_sims_* の違反を分かりやすいエラーにして実行する。

    _check_duplicates をすり抜ける、同時に同じ番号を登録・変更した場合のため。
    """
    try:
        cursor.execute(sql, params)
    except pymysql.err.IntegrityError as error:
        for field in SIM_FIELDS:
            if f'uq_sims_{field}' in str(error):
                raise DeviceActionError(
                    f'{SIM_FIELDS[field][0]}「{_shown(field, values.get(field))}」は'
                    'すでに別の SIM で使われています。'
                ) from error
        raise


def register_sim(cursor, raw):
    """SIM を登録し、新しい SIM の id を返す（どの機器にも差していない状態）。"""
    values = _clean(raw)
    _check_duplicates(cursor, values)
    _execute_guarded(
        cursor, 'INSERT INTO sims (iccid, phone_number, extension) VALUES (%s, %s, %s)',
        (values['iccid'], values['phone_number'], values['extension']), values,
    )
    sim_id = cursor.lastrowid
    record_event(
        cursor, None, 'sim_registered', sim_id=sim_id,
        changes={f: [None, v] for f, v in values.items() if v is not None},
    )
    return sim_id


def _find(cursor, sim_id):
    cursor.execute('SELECT * FROM sims WHERE id = %s', (sim_id,))
    sim = cursor.fetchone()
    if sim is None:
        raise RecordNotFound('SIM が見つかりません。')
    return sim


def _lock(cursor, sim_id, expected_device_id):
    """SIM をロックし、読んだときから差している機器が変わっていないか確かめる。"""
    cursor.execute('SELECT * FROM sims WHERE id = %s FOR UPDATE', (sim_id,))
    sim = cursor.fetchone()
    if sim['device_id'] != expected_device_id:
        raise DeviceActionError('この SIM は他の操作で変更されました。画面を読み込み直してください。')
    return sim


def edit_sim(cursor, sim_id, raw):
    """SIM番号・外線・内線を変更する。変わった項目だけ記録する。"""
    values = _clean(raw)
    found = _find(cursor, sim_id)
    if found['device_id']:
        devices.lock_device(cursor, found['device_id'])
    sim = _lock(cursor, sim_id, found['device_id'])
    changes = build_changes(sim, values)
    if not changes:
        raise DeviceActionError('SIM の番号が変わっていません。')
    _check_duplicates(cursor, {f: values[f] for f in changes}, exclude_id=sim_id)
    assignments = ', '.join(f'{field} = %s' for field in changes)
    _execute_guarded(
        cursor, f'UPDATE sims SET {assignments} WHERE id = %s',
        (*(values[f] for f in changes), sim_id), values,
    )
    record_event(cursor, sim['device_id'], 'sim_edited', sim_id=sim_id, changes=changes)


def _detach(cursor, sim):
    cursor.execute('UPDATE sims SET device_id = NULL WHERE id = %s', (sim['id'],))
    record_event(cursor, sim['device_id'], 'sim_detached', sim_id=sim['id'])


def attach_sim(cursor, sim_id, device_id):
    """SIM を機器に差す。別の機器に差していれば移し、機器に別の SIM があれば外す。

    差した SIM のラベルと、外した SIM のラベル（なければ None）を返す。
    """
    found = _find(cursor, sim_id)
    if found['device_id'] == device_id:
        raise DeviceActionError('この SIM はすでにこの機器に差しています。')
    # 2 台の機器をロックするときは id の小さい順（同時に逆向きの差し替えをしても止まらない）
    locked = {
        locked_id: devices.lock_device(cursor, locked_id)
        for locked_id in sorted({device_id, found['device_id']} - {None})
    }
    target = locked[device_id]
    if target['disposed_on']:
        raise DeviceActionError('廃棄済みの機器には SIM を差せません。')
    model = masters.find_device_model(cursor, target['device_model_id'])
    if model is None or not identifiers.uses_sim(model['device_type']):
        raise DeviceActionError('この種別の機器には SIM を差せません。')
    sim = _lock(cursor, sim_id, found['device_id'])

    if sim['device_id']:
        _detach(cursor, sim)
    cursor.execute('SELECT * FROM sims WHERE device_id = %s FOR UPDATE', (device_id,))
    replaced = cursor.fetchone()
    if replaced:
        _detach(cursor, replaced)
    cursor.execute('UPDATE sims SET device_id = %s WHERE id = %s', (device_id, sim_id))
    record_event(cursor, device_id, 'sim_attached', sim_id=sim_id)
    label = identifiers.sim_label(sim['iccid'], sim['phone_number'])
    replaced_label = (
        identifiers.sim_label(replaced['iccid'], replaced['phone_number']) if replaced else None
    )
    return label, replaced_label


def detach_sim(cursor, sim_id):
    """SIM を機器から外して未使用にする。"""
    found = _find(cursor, sim_id)
    if found['device_id'] is None:
        raise DeviceActionError('この SIM はどの機器にも差していません。')
    devices.lock_device(cursor, found['device_id'])
    _detach(cursor, _lock(cursor, sim_id, found['device_id']))


def detach_from_device(cursor, device_id):
    """機器に差している SIM があれば外す（機器は呼び出し側でロック済み）。外した SIM を返す。"""
    cursor.execute('SELECT * FROM sims WHERE device_id = %s FOR UPDATE', (device_id,))
    sim = cursor.fetchone()
    if sim:
        _detach(cursor, sim)
    return sim


def device_has_sim(cursor, device_id):
    cursor.execute('SELECT 1 FROM sims WHERE device_id = %s', (device_id,))
    return cursor.fetchone() is not None

