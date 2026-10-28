"""機器の管理番号（D-0007 形式）の整形と解釈。"""
import re

_CODE_PATTERN = re.compile(r'^(?:d-?)?0*(\d+)$', re.IGNORECASE)


def format_device_code(device_id):
    return f'D-{int(device_id):04d}'


def parse_device_code(text):
    """'D-7' 'd-0007' '7' から機器 id を取り出す。解釈できなければ None。"""
    matched = _CODE_PATTERN.match(text.strip())
    return int(matched.group(1)) if matched else None
