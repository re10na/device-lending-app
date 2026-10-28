"""照合情報（ホスト名・内線・シリアルと、差している SIM の番号）の正規化・検証・表示用の整形。"""
import re
import unicodedata

import pymysql

from .config import (
    ALWAYS_IDENTIFIER_FIELDS, IDENTIFIER_FIELDS, IDENTIFIER_FIELDS_BY_TYPE,
    SIM_DEVICE_TYPES, UNIQUE_IDENTIFIER_FIELDS,
)
from .codes import format_device_code
from .errors import DeviceActionError

ALL_FIELDS = tuple(IDENTIFIER_FIELDS)

# 機器（d）に差している SIM の番号を、機器の行に一緒に読み込むための SQL。
# 表示・検索では phone_number / sim_iccid / sim_extension を機器の照合情報として扱う
SIM_COLUMNS = 'sm.id AS sim_id, sm.iccid AS sim_iccid, sm.phone_number, sm.extension AS sim_extension'
SIM_JOIN = 'LEFT JOIN sims AS sm ON sm.device_id = d.id'


def label(field):
    return IDENTIFIER_FIELDS[field][0]


def uses_sim(device_type):
    """SIM を差せる種別か（設定にない種別にも差せる）。"""
    return device_type in SIM_DEVICE_TYPES or device_type not in IDENTIFIER_FIELDS_BY_TYPE


def type_fields(device_type):
    """その種別で使う項目（種別固有の項目 + シリアル）。未知の種別は全項目。"""
    specific = IDENTIFIER_FIELDS_BY_TYPE.get(device_type)
    if specific is None:
        return ALL_FIELDS
    return tuple(f for f in ALL_FIELDS if f in specific or f in ALWAYS_IDENTIFIER_FIELDS)


def field_types():
    """項目名 -> その項目を使う種別の一覧（画面の data-types 用。シリアルは空 = 常に表示）。"""
    return {
        field: [t for t, fields in IDENTIFIER_FIELDS_BY_TYPE.items() if field in fields]
        for field in ALL_FIELDS
    }


def clean_value(value, name, max_length, digits=False):
    """1 項目を正規化する。空は None、不正は DeviceActionError。digits なら数字だけにする。"""
    text = (value or '').strip()
    if digits:
        text = unicodedata.normalize('NFKC', text)
        text = re.sub(r'[\s\-‐‑‒–—―ー−]', '', text)
        if text and not (text.isascii() and text.isdigit()):
            raise DeviceActionError(f'{name}は数字のみで入力してください。')
    if not text:
        return None
    if len(text) > max_length:
        raise DeviceActionError(f'{name}は{max_length}文字以内で入力してください。')
    return text


def normalize(field, value):
    """機器の照合情報 1 項目を正規化する。"""
    return clean_value(value, label(field), IDENTIFIER_FIELDS[field][1])


def normalize_digits_needle(text):
    """検索語を電話番号・ICCID と比べられる数字だけの文字列にする（数字以外が混じれば空）。"""
    text = re.sub(r'[\s\-‐‑‒–—―ー−]', '', unicodedata.normalize('NFKC', text or ''))
    return text if text.isascii() and text.isdigit() else ''


def clean_for_type(device_type, raw):
    """フォーム入力 {項目名: 文字列} を正規化する。その種別で使わない項目に値があればエラー。"""
    allowed = type_fields(device_type)
    cleaned = {}
    for field, value in raw.items():
        normalized = normalize(field, value)
        if normalized is not None and field not in allowed:
            raise DeviceActionError(f'この機種では{label(field)}は使いません。')
        cleaned[field] = normalized
    return cleaned


def require_one(device_type, values, has_sim=False):
    """種別の項目 + シリアル（SIM を差せる種別なら SIM も）のうち、少なくとも 1 つはあること。"""
    if has_sim and uses_sim(device_type):
        return
    if not any(values.get(field) for field in type_fields(device_type)):
        names = '・'.join(label(f) for f in type_fields(device_type))
        if uses_sim(device_type):
            names += '・SIM'
        raise DeviceActionError(
            f'現物と照合できるよう、{names}のいずれか1つ以上を入力してください。'
        )


def check_duplicates(cursor, values, exclude_id=None):
    """未廃棄の他の機器が同じ値を使っていないか確認する（UNIQUE の前に分かりやすく伝える）。"""
    for field in UNIQUE_IDENTIFIER_FIELDS:
        value = values.get(field)
        if value is None:
            continue
        # field は定数のホワイトリストから来る（SQL に埋め込んでよい）
        cursor.execute(
            f'SELECT id FROM devices WHERE {field} = %s AND disposed_on IS NULL '
            'AND id <> %s LIMIT 1',
            (value, exclude_id or 0),
        )
        other = cursor.fetchone()
        if other:
            raise _duplicate_error(field, value, other['id'])
        if field == 'extension':
            reject_extension_on_sim(cursor, value)


def reject_extension_on_sim(cursor, value, exclude_sim_id=None):
    """内線は機器（固定電話など）と SIM のどちらか 1 か所でしか使えない。"""
    cursor.execute(
        'SELECT id FROM sims WHERE extension = %s AND id <> %s LIMIT 1',
        (value, exclude_sim_id or 0),
    )
    if cursor.fetchone():
        raise DeviceActionError(f'内線番号「{value}」はすでに SIM で使われています。')


def reject_extension_on_device(cursor, value):
    """SIM の内線が、未廃棄の機器（固定電話など）の内線と重ならないこと。"""
    cursor.execute(
        'SELECT id FROM devices WHERE extension = %s AND disposed_on IS NULL LIMIT 1', (value,)
    )
    other = cursor.fetchone()
    if other:
        raise _duplicate_error('extension', value, other['id'])


def _duplicate_error(field, value, device_id):
    return DeviceActionError(
        f'{label(field)}「{value}」はすでに {format_device_code(device_id)} で使われています。'
    )


def translate_integrity_error(error, values):
    """uq_devices_active_* の違反を分かりやすいエラーにする（それ以外はそのまま再送出）。"""
    text = str(error)
    for field in UNIQUE_IDENTIFIER_FIELDS:
        if f'uq_devices_active_{field}' in text:
            return DeviceActionError(
                f'{label(field)}「{values.get(field)}」はすでに別の機器で使われています。'
            )
    return error


def execute_guarded(cursor, sql, params, values):
    """UNIQUE 違反を DeviceActionError に変えて実行する。"""
    try:
        cursor.execute(sql, params)
    except pymysql.err.IntegrityError as error:
        translated = translate_integrity_error(error, values)
        if translated is error:
            raise
        raise translated from error


def format_phone(digits):
    """11 桁で 0[789]0 始まりなら 090-1234-5678 形式、それ以外は数字のまま。"""
    if digits and re.fullmatch(r'0[789]0\d{8}', digits):
        return f'{digits[:3]}-{digits[3:7]}-{digits[7:]}'
    return digits


def sim_label(iccid, phone_number):
    """SIM の短い呼び名（例: 090-1234-5678 / SIM …0001）。"""
    parts = []
    if phone_number:
        parts.append(format_phone(phone_number))
    if iccid:
        parts.append(f'SIM …{iccid[-4:]}')
    return ' / '.join(parts) or 'SIM'


def describe(row):
    """機器の行から、画面に出す照合情報を作る。

    機器そのものの項目（ホスト名・内線）のあとに、差している SIM の外線・SIM番号・内線を並べる。
    main: 一番の目印（無ければ None） / summary: 一覧用のまとめ / serial: シリアル番号
    """
    parts = []
    for field in type_fields(row.get('device_type')):
        value = row.get(field)
        if not value or field == 'serial_number':
            continue
        parts.append(f'内線 {value}' if field == 'extension' else value)
    if row.get('phone_number'):
        parts.append(format_phone(row['phone_number']))
    if row.get('sim_iccid'):
        parts.append(f"SIM …{row['sim_iccid'][-4:]}")
    if row.get('sim_extension'):
        parts.append(f"内線 {row['sim_extension']}")
    return {
        'main': parts[0] if parts else None,
        'summary': ' / '.join(parts),
        'serial': row.get('serial_number'),
    }
