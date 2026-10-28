"""模擬ログインと、ページごとに必要な役割の判定。

本物のログインは、このシステムを組み込む先のシステムが持っている。ここでのログインはその代わり
（組み込み先がまだ無いときに動かして試すため）で、守りにはしない。
- 管理者: config.MOCK_ADMIN_USERNAME / MOCK_ADMIN_PASSWORD の模擬アカウント（1 名）で入る
- 利用者: 在籍している社員の社員番号だけで入る（パスワードなし）。入った社員の利用者画面だけを見られる

ログイン状態は Flask のセッションに次の値を入れて持つ。組み込むときは config.MOCK_LOGIN を 0 にして、
組み込み先のログインが終わったところで log_in_admin() / log_in_user(社員) を呼ぶ
（またはセッションに同じ値を入れる）ようにすれば、画面の側はそのまま使える。
    role        'admin' か 'user'
    shain_code  利用者の社員番号（利用者のときだけ）
    name        上の帯に出す名前
"""
import hmac

from flask import session

from . import config

ADMIN = 'admin'
USER = 'user'

# ログインしなくても開けるページ（ログイン画面とその送信先、静的ファイル）
PUBLIC_ENDPOINTS = {'pages.home', 'auth.login_admin', 'auth.login_user', 'auth.logout', 'static'}


def required_role(endpoint):
    """そのページに必要な役割。ログイン不要なら None。/user 以下は利用者、それ以外はすべて管理者。"""
    if endpoint is None or endpoint in PUBLIC_ENDPOINTS:
        return None
    if endpoint.startswith('user.'):
        return USER
    return ADMIN


def mock_login_enabled():
    return config.MOCK_LOGIN


def check_mock_admin(username, password):
    """模擬の管理者アカウントの ID とパスワードが合っているか。"""
    username_ok = hmac.compare_digest((username or '').encode(), config.MOCK_ADMIN_USERNAME.encode())
    password_ok = hmac.compare_digest((password or '').encode(), config.MOCK_ADMIN_PASSWORD.encode())
    return username_ok and password_ok


def _start(role, **values):
    # 前のログイン状態（CSRF トークンも）を残さない
    session.clear()
    session['role'] = role
    session.update(values)


def log_in_admin():
    _start(ADMIN, name='管理者')


def log_in_user(employee):
    """employee は masters.find_employee の結果（shain_code と name）。"""
    _start(USER, shain_code=employee['shain_code'], name=employee['name'])


def log_out():
    session.clear()


def current_role():
    return session.get('role')


def current_shain_code():
    """ログインしている利用者の社員番号（利用者でなければ None）。"""
    return session.get('shain_code') if current_role() == USER else None


def current_user():
    """画面に出すログイン中の人（役割と名前）。ログインしていなければ None。"""
    if not current_role():
        return None
    return {'role': current_role(), 'name': session.get('name'), 'shain_code': current_shain_code()}
