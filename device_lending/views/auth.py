"""模擬ログイン・ログアウトのルート。ログイン画面そのものは pages.home（/）。
config.MOCK_LOGIN が 0 のとき（組み込み先のログインを使うとき）は、模擬ログインの入口は無いものとする。
"""
import pymysql
from flask import Blueprint, abort, current_app, flash, redirect, url_for

from .. import auth, masters
from ..csrf import verify_csrf_token
from ..db import transaction
from ..forms import form_text

bp = Blueprint('auth', __name__)


def landing_url(role):
    """ログインした後に開くページ。管理者はダッシュボード、利用者は自分の利用者画面。"""
    return url_for('pages.dashboard') if role == auth.ADMIN else url_for('user.index')


def _require_mock_login():
    if not auth.mock_login_enabled():
        abort(404)


@bp.post('/login/admin')
def login_admin():
    _require_mock_login()
    verify_csrf_token()
    if not auth.check_mock_admin(form_text('username'), form_text('password')):
        # どちらが違うかは教えない
        flash('ID かパスワードが違います。', 'error')
        return redirect(url_for('pages.home'))
    auth.log_in_admin()
    return redirect(landing_url(auth.ADMIN))


@bp.post('/login/user')
def login_user():
    _require_mock_login()
    verify_csrf_token()
    shain_code = form_text('shain_code')
    try:
        with transaction() as cursor:
            employee = masters.find_employee(cursor, shain_code) if shain_code else None
    except pymysql.MySQLError:
        current_app.logger.exception('Could not look up employee for login')
        flash('ログインできませんでした。時間をおいてもう一度お試しください。', 'error')
        return redirect(url_for('pages.home'))
    if employee is None or employee['is_retired']:
        flash('その社員番号の在籍している社員が見つかりません。', 'error')
        return redirect(url_for('pages.home'))
    auth.log_in_user(employee)
    return redirect(landing_url(auth.USER))


@bp.post('/logout')
def logout():
    verify_csrf_token()
    auth.log_out()
    flash('ログアウトしました。', 'success')
    return redirect(url_for('pages.home'))
