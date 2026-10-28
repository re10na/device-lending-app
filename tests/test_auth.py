"""模擬ログイン（管理者 1 名と、社員番号だけで入る利用者）と、ページごとの入れる・入れないの確認。"""
import pytest

from device_lending import config
from device_lending.db import transaction

from .conftest import TEST_ADMIN_PASSWORD, log_in_as_user
from .factories import PC, RETIRED, SUZUKI, TANAKA, UNKNOWN_EMPLOYEE, add_device

CSRF = {'csrf_token': 'test'}


def role_of(client):
    with client.session_transaction() as session:
        return session.get('role'), session.get('shain_code')


def flashed(client):
    with client.session_transaction() as session:
        return session.get('_flashes', [])


# --- ログイン画面 ---

def test_login_page_for_anonymous(anonymous_client):
    body = anonymous_client.get('/').get_data(as_text=True)
    assert 'action="/login/admin"' in body and 'action="/login/user"' in body
    # ログイン画面にはサイドバーを出さない
    assert 'class="sidebar"' not in body


def test_logged_in_user_skips_login_page(client):
    assert client.get('/').headers['Location'] == '/admin'
    log_in_as_user(client, TANAKA)
    assert client.get('/').headers['Location'] == '/user'


# --- 管理者のログイン ---

def test_admin_login(anonymous_client):
    response = anonymous_client.post(
        '/login/admin', data={**CSRF, 'username': 'admin', 'password': TEST_ADMIN_PASSWORD}
    )
    assert response.headers['Location'] == '/admin'
    assert role_of(anonymous_client) == ('admin', None)
    assert anonymous_client.get('/admin').status_code == 200


@pytest.mark.parametrize('username, password', [
    ('admin', 'wrong-password'),
    ('someone', TEST_ADMIN_PASSWORD),
    ('', ''),
])
def test_admin_login_fails(anonymous_client, username, password):
    response = anonymous_client.post(
        '/login/admin', data={**CSRF, 'username': username, 'password': password}
    )
    assert response.headers['Location'] == '/'
    assert flashed(anonymous_client)[-1] == ('error', 'ID かパスワードが違います。')
    assert role_of(anonymous_client) == (None, None)


def test_mock_login_can_be_turned_off(anonymous_client, monkeypatch):
    """組み込み先のログインを使うとき（MOCK_LOGIN=0）は、模擬ログインの入口を使えない。"""
    monkeypatch.setattr(config, 'MOCK_LOGIN', False)
    body = anonymous_client.get('/').get_data(as_text=True)
    assert 'action="/login/admin"' not in body and '組み込み先のシステムからログインしてください' in body
    response = anonymous_client.post(
        '/login/admin', data={**CSRF, 'username': 'admin', 'password': TEST_ADMIN_PASSWORD}
    )
    assert response.status_code == 404
    assert anonymous_client.post('/login/user', data={**CSRF, 'shain_code': TANAKA}).status_code == 404
    assert role_of(anonymous_client) == (None, None)


def test_session_set_by_host_system_works_without_mock_login(client, monkeypatch):
    """模擬ログインをオフにしても、組み込み先がセッションに役割を入れれば画面はそのまま使える。"""
    monkeypatch.setattr(config, 'MOCK_LOGIN', False)
    assert client.get('/admin').status_code == 200
    log_in_as_user(client, TANAKA)
    assert client.get('/user').status_code == 200


def test_login_requires_csrf_token(anonymous_client):
    response = anonymous_client.post(
        '/login/admin', data={'username': 'admin', 'password': TEST_ADMIN_PASSWORD}
    )
    assert response.status_code == 400


# --- 利用者のログイン（社員番号だけ） ---

def test_user_login_with_shain_code(anonymous_client):
    response = anonymous_client.post('/login/user', data={**CSRF, 'shain_code': f' {TANAKA} '})
    assert response.headers['Location'] == '/user'
    assert role_of(anonymous_client) == ('user', TANAKA)
    body = anonymous_client.get('/user').get_data(as_text=True)
    assert '田中太郎' in body
    # 社員を選ぶ欄は出さない
    assert 'name="shain_code"' not in body


@pytest.mark.parametrize('shain_code', [RETIRED, UNKNOWN_EMPLOYEE, ''])
def test_user_login_rejects_retired_and_unknown(anonymous_client, shain_code):
    response = anonymous_client.post('/login/user', data={**CSRF, 'shain_code': shain_code})
    assert response.headers['Location'] == '/'
    assert role_of(anonymous_client) == (None, None)


def test_user_page_ignores_shain_code_in_url(client):
    """URL の社員番号を書き換えても、ログインしている本人の画面しか出ない。"""
    log_in_as_user(client, TANAKA)
    body = client.get(f'/user?shain_code={SUZUKI}').get_data(as_text=True)
    assert '田中太郎' in body and '鈴木花子' not in body


def test_user_actions_use_logged_in_employee(client):
    """フォームに他人の社員番号を入れて送っても、本人の申請になる。"""
    log_in_as_user(client, TANAKA)
    client.post('/user/requests/loan', data={**CSRF, 'shain_code': SUZUKI, 'device_model_id': PC})
    with transaction() as cursor:
        cursor.execute('SELECT shain_code FROM user_requests ORDER BY id DESC LIMIT 1')
        assert cursor.fetchone()['shain_code'] == TANAKA


def test_user_logged_out_after_retiring(client):
    with transaction() as cursor:
        cursor.execute(
            'UPDATE master_test.m_shain SET taishoku_date = CURRENT_DATE() WHERE shain_code = %s',
            (SUZUKI,),
        )
    try:
        log_in_as_user(client, SUZUKI)
        assert client.get('/user').headers['Location'] == '/'
        assert role_of(client) == (None, None)
    finally:
        with transaction() as cursor:
            cursor.execute(
                'UPDATE master_test.m_shain SET taishoku_date = NULL WHERE shain_code = %s', (SUZUKI,)
            )


# --- 入れるページ・入れないページ ---

@pytest.mark.parametrize('path', ['/admin', '/devices', '/members', '/admin/sims', '/admin/search?q=a', '/user'])
def test_anonymous_is_sent_to_login(anonymous_client, path):
    response = anonymous_client.get(path)
    assert response.status_code == 302 and response.headers['Location'] == '/'


def test_anonymous_cannot_post_admin_actions(anonymous_client):
    device_id = add_device_committed()
    response = anonymous_client.post(f'/devices/{device_id}/install', data={**CSRF, 'location': '受付'})
    assert response.headers['Location'] == '/'
    with transaction() as cursor:
        cursor.execute('SELECT status FROM devices WHERE id = %s', (device_id,))
        assert cursor.fetchone()['status'] == 'available'


@pytest.mark.parametrize('path', ['/admin', '/devices', '/members/1001', '/admin/requests'])
def test_user_cannot_open_admin_pages(client, path):
    log_in_as_user(client, TANAKA)
    assert client.get(path).headers['Location'] == '/user'


def test_admin_is_sent_to_dashboard_from_user_page(client):
    assert client.get('/user').headers['Location'] == '/admin'


def test_static_files_need_no_login(anonymous_client):
    assert anonymous_client.get('/static/css/base.css').status_code == 200


# --- ログアウト ---

def test_logout(client):
    response = client.post('/logout', data=CSRF)
    assert response.headers['Location'] == '/'
    assert role_of(client) == (None, None)
    assert client.get('/admin').headers['Location'] == '/'


def test_logged_in_pages_show_name_and_logout(client):
    assert '>管理者<' in client.get('/admin').get_data(as_text=True)
    log_in_as_user(client, TANAKA, '田中太郎')
    body = client.get('/user').get_data(as_text=True)
    assert '田中太郎さん' in body and 'action="/logout"' in body


def add_device_committed():
    with transaction() as cursor:
        return add_device(cursor)
