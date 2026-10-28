"""フォーム入力の取り出しと型変換（不正な入力は DeviceActionError にする）。"""
from datetime import date

from flask import request

from .config import IDENTIFIER_FIELDS
from .errors import DeviceActionError


def form_text(name):
    return request.form.get(name, '').strip()


def form_date(name, label, required=False):
    text = form_text(name)
    if not text:
        if required:
            raise DeviceActionError(f'{label}を入力してください。')
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise DeviceActionError(f'{label}の日付の形式が正しくありません。') from error


def form_int(name, label):
    try:
        return int(form_text(name))
    except ValueError as error:
        raise DeviceActionError(f'{label}を選択してください。') from error


def form_identifiers():
    """送られてきた照合情報の項目だけを {項目名: 入力文字列} で返す（無い項目は触らない）。"""
    return {
        field: request.form[field]
        for field in IDENTIFIER_FIELDS
        if field in request.form
    }
