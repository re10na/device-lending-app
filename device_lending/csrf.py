"""CSRF トークンの発行と検証。"""
import hmac
import secrets

from flask import abort, request, session


def csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    return session['csrf_token']


def verify_csrf_token():
    submitted_token = request.form.get('csrf_token', '')
    expected_token = session.get('csrf_token', '')
    if not expected_token or not hmac.compare_digest(submitted_token, expected_token):
        abort(400, description='フォームの有効期限が切れました。ページを再読み込みしてください。')
