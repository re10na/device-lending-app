"""フォーム入力の変換（forms.py）と、操作後の戻り先（navigation.py）。"""
from datetime import date

import pytest

from device_lending.errors import DeviceActionError
from device_lending.forms import form_date, form_identifiers, form_int, form_text
from device_lending.navigation import safe_next_url


def post_context(app, data):
    return app.test_request_context(method='POST', data=data)


def test_form_text_strips_and_defaults_to_empty(app):
    with post_context(app, {'name': '  田中  '}):
        assert form_text('name') == '田中'
        assert form_text('missing') == ''


def test_form_int(app):
    with post_context(app, {'id': ' 12 ', 'bad': 'abc', 'empty': ''}):
        assert form_int('id', '機器') == 12
        with pytest.raises(DeviceActionError, match='機器を選択してください'):
            form_int('bad', '機器')
        with pytest.raises(DeviceActionError):
            form_int('empty', '機器')


def test_form_date(app):
    with post_context(app, {'day': '2026-10-01', 'bad': '2026/10/01', 'empty': ''}):
        assert form_date('day', '貸出日') == date(2026, 10, 1)
        assert form_date('empty', '返却日') is None
        with pytest.raises(DeviceActionError, match='貸出日を入力してください'):
            form_date('empty', '貸出日', required=True)
        with pytest.raises(DeviceActionError, match='形式が正しくありません'):
            form_date('bad', '貸出日')


def test_form_identifiers_returns_only_sent_fields(app):
    with post_context(app, {'hostname': 'LT-01', 'serial_number': '', 'other': 'x'}):
        # 送られていない extension は含めない（＝変更しない）。空文字は「消す」なので含める
        assert form_identifiers() == {'hostname': 'LT-01', 'serial_number': ''}


@pytest.mark.parametrize('target, expected', [
    ('/devices/3', '/devices/3'),
    ('/admin?employee=田中', '/admin?employee=田中'),
    ('', None),
    ('https://evil.example.com/', None),
    ('//evil.example.com/', None),
    ('/\\evil.example.com', None),
    ('devices/3', None),
])
def test_safe_next_url_allows_only_own_paths(app, target, expected):
    with post_context(app, {'next': target}):
        assert safe_next_url() == expected
