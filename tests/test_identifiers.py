"""照合情報の正規化・検証・表示（identifiers.py）。DB を使わない部分。"""
import pytest

from device_lending import identifiers
from device_lending.errors import DeviceActionError


def test_type_fields():
    assert identifiers.type_fields('PC') == ('hostname', 'serial_number')
    assert identifiers.type_fields('Phone') == ('extension', 'serial_number')
    assert identifiers.type_fields('SmartPhone') == ('serial_number',)
    # 設定に無い種別は全項目
    assert identifiers.type_fields('Tablet') == identifiers.ALL_FIELDS


@pytest.mark.parametrize('device_type, expected', [
    ('SmartPhone', True),
    ('MobileWifi', True),
    ('Tablet', True),  # 設定に無い種別にも差せる
    ('PC', False),
    ('Phone', False),
])
def test_uses_sim(device_type, expected):
    assert identifiers.uses_sim(device_type) is expected


def test_clean_value_strips_and_empty_is_none():
    assert identifiers.clean_value('  LT-01 ', 'ホスト名', 63) == 'LT-01'
    assert identifiers.clean_value('   ', 'ホスト名', 63) is None
    assert identifiers.clean_value(None, 'ホスト名', 63) is None


def test_clean_value_max_length():
    assert identifiers.clean_value('a' * 5, '項目', 5) == 'aaaaa'
    with pytest.raises(DeviceActionError, match='5文字以内'):
        identifiers.clean_value('a' * 6, '項目', 5)


@pytest.mark.parametrize('raw', ['090-1234-5678', '０９０ー１２３４ー５６７８', '090 1234 5678'])
def test_clean_value_digits_normalizes_phone_numbers(raw):
    assert identifiers.clean_value(raw, '外線', 20, digits=True) == '09012345678'


def test_clean_value_digits_rejects_letters():
    with pytest.raises(DeviceActionError, match='数字のみ'):
        identifiers.clean_value('090-ABCD', '外線', 20, digits=True)


def test_normalize_digits_needle():
    assert identifiers.normalize_digits_needle('090-1234') == '0901234'
    assert identifiers.normalize_digits_needle('LT-01') == ''
    assert identifiers.normalize_digits_needle('') == ''


def test_clean_for_type_rejects_fields_the_type_does_not_use():
    assert identifiers.clean_for_type('PC', {'hostname': ' LT-01 '}) == {'hostname': 'LT-01'}
    with pytest.raises(DeviceActionError, match='内線番号は使いません'):
        identifiers.clean_for_type('PC', {'extension': '201'})
    # 空なら使わない項目でもエラーにしない（フォームに出ていない項目が空で届くため）
    assert identifiers.clean_for_type('PC', {'extension': ''}) == {'extension': None}


def test_require_one():
    identifiers.require_one('PC', {'hostname': 'LT-01'})
    identifiers.require_one('PC', {'serial_number': 'S1'})
    with pytest.raises(DeviceActionError, match='ホスト名・シリアル番号のいずれか'):
        identifiers.require_one('PC', {})


def test_require_one_accepts_sim_for_sim_types():
    identifiers.require_one('SmartPhone', {}, has_sim=True)
    with pytest.raises(DeviceActionError, match='シリアル番号・SIM'):
        identifiers.require_one('SmartPhone', {})
    # PC は SIM を差せないので、has_sim でも照合情報は必要
    with pytest.raises(DeviceActionError):
        identifiers.require_one('PC', {}, has_sim=True)


@pytest.mark.parametrize('digits, expected', [
    ('09012345678', '090-1234-5678'),
    ('08012345678', '080-1234-5678'),
    ('0312345678', '0312345678'),  # 携帯以外はそのまま
    (None, None),
])
def test_format_phone(digits, expected):
    assert identifiers.format_phone(digits) == expected


def test_sim_label():
    assert identifiers.sim_label('8981100000000000001', '09012345678') == '090-1234-5678 / SIM …0001'
    assert identifiers.sim_label('8981100000000000001', None) == 'SIM …0001'
    assert identifiers.sim_label(None, None) == 'SIM'


def test_describe_pc():
    info = identifiers.describe({'device_type': 'PC', 'hostname': 'LT-01', 'serial_number': 'S1'})
    assert info == {'main': 'LT-01', 'summary': 'LT-01', 'serial': 'S1'}


def test_describe_smartphone_uses_sim_numbers():
    info = identifiers.describe({
        'device_type': 'SmartPhone', 'phone_number': '09012345678',
        'sim_iccid': '8981100000000000001', 'sim_extension': '301',
    })
    assert info['main'] == '090-1234-5678'
    assert info['summary'] == '090-1234-5678 / SIM …0001 / 内線 301'


def test_describe_without_identifiers():
    assert identifiers.describe({'device_type': 'PC'})['main'] is None
