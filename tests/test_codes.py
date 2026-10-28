"""管理番号（D-0007 形式）の整形と解釈。"""
import pytest

from device_lending.codes import format_device_code, parse_device_code


@pytest.mark.parametrize('device_id, expected', [
    (7, 'D-0007'),
    (1234, 'D-1234'),
    (12345, 'D-12345'),  # 4 桁を超えても切らない
    ('7', 'D-0007'),
])
def test_format_device_code(device_id, expected):
    assert format_device_code(device_id) == expected


@pytest.mark.parametrize('text, expected', [
    ('D-7', 7),
    ('d-0007', 7),
    ('D0007', 7),
    ('7', 7),
    ('  D-7  ', 7),
    ('D-0', 0),
])
def test_parse_device_code(text, expected):
    assert parse_device_code(text) == expected


@pytest.mark.parametrize('text', ['', 'D-', 'X-7', 'D-7a', 'D--7', '7-D', 'D 7'])
def test_parse_device_code_rejects_other_text(text):
    assert parse_device_code(text) is None


def test_format_then_parse_round_trip():
    assert parse_device_code(format_device_code(42)) == 42
