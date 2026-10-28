"""一覧の CSV 出力。Excel でそのまま開けるよう、BOM 付き UTF-8 にする。"""
import csv
import io

from . import identifiers
from .config import FLAGS, PLACEMENTS

DEVICE_COLUMNS = ['機器', '管理番号', '照合情報', '種別', 'メーカー / 機種', '状態', '保有者', '設置場所']
MEMBER_COLUMNS = ['社員番号', '氏名', '在籍', '退職日', '貸出台数', '注意', '紛失したことがある', '故障・不具合があったことがある']

# Excel が数式として実行してしまう先頭文字（CSV インジェクション対策）
_FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def _cell(value):
    text = '' if value is None else str(value)
    return f"'{text}" if text.startswith(_FORMULA_PREFIXES) else text


def _identifiers(device):
    """照合情報を省略せずに並べる（画面の一覧は SIM を末尾 4 桁にしているが、記録用なので全桁）。"""
    labels = {'extension': '内線 ', 'serial_number': 'S/N '}
    parts = []
    for field in identifiers.type_fields(device['device_type']):
        if device[field]:
            parts.append(labels.get(field, '') + device[field])
    # 差している SIM の番号
    if device['phone_number']:
        parts.append(identifiers.format_phone(device['phone_number']))
    if device['sim_iccid']:
        parts.append(f"SIM {device['sim_iccid']}")
    if device['sim_extension']:
        parts.append(f"内線 {device['sim_extension']}")
    return ' / '.join(parts)


def _holder(device):
    if not device['loan_id']:
        return ''
    name = device['holder_name'] or '社員マスタに無し'
    retired = ' 退職済み' if device['holder_retired'] else ''
    return f"{name}（{device['holder_code']}）{retired}"


def _write_csv(header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell(value) for value in row])
    return '﻿' + buffer.getvalue()


def members_csv(members):
    """fetch_members 済みの社員の行から、CSV の文字列を作る。"""
    return _write_csv(MEMBER_COLUMNS, (
        (
            member['shain_code'],
            member['name'],
            '退職済み' if member['is_retired'] else '在籍',
            member['taishoku_date'],
            member['loan_count'],
            ' '.join(FLAGS[mark] for mark in member['marks']),
            'あり' if member['ever_lost'] else '',
            'あり' if member['ever_issue'] else '',
        )
        for member in members
    ))


def devices_csv(devices):
    """derive_state 済みの機器の行から、CSV の文字列を作る。"""
    return _write_csv(DEVICE_COLUMNS, (
        (
            device['display_name'],
            device['code'],
            _identifiers(device),
            device['device_type'],
            device['model_label'],
            PLACEMENTS[device['placement']],
            _holder(device),
            device['location'],
        )
        for device in devices
    ))
