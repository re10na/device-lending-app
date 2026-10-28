"""テスト全体の準備（テスト用 DB の作成と、各テストで使う fixture）。

DB を使うテストは、本番とは別のテスト用 MySQL に app_test / master_test を作り直して実行する。
テスト用 MySQL の起動（初回だけ。止めるときは docker rm -f device-lending-test-db）:

    docker run -d --name device-lending-test-db -e MYSQL_ROOT_PASSWORD=test \
        -p 127.0.0.1:3317:3306 mysql:8.4.7 --default-time-zone=+09:00

接続先は TEST_DB_HOST / TEST_DB_PORT / TEST_DB_USER / TEST_DB_PASSWORD で変えられる。
MySQL に繋がらないときは、DB を使うテストだけ skip して DB 不要のテストは実行する。
"""
import os
from pathlib import Path

# device_lending.config は import した時点で環境変数を読むので、import より前に設定する。
# 本番の DB に繋がないよう、DB_* は必ずテスト用の値で上書きする
TEST_DB = 'app_test'
TEST_ADMIN_PASSWORD = 'test-password'
TEST_MASTER_DB = 'master_test'
os.environ.update({
    'DB_HOST': os.environ.get('TEST_DB_HOST', '127.0.0.1'),
    'DB_PORT': os.environ.get('TEST_DB_PORT', '3317'),
    'DB_USER': os.environ.get('TEST_DB_USER', 'root'),
    'DB_PASSWORD': os.environ.get('TEST_DB_PASSWORD', 'test'),
    'DB_NAME': TEST_DB,
    'MASTER_DB': TEST_MASTER_DB,
    'FLASK_SECRET_KEY': 'test-secret-key',
    # テスト用の模擬の管理者（パスワードは TEST_ADMIN_PASSWORD）
    'MOCK_LOGIN': '1',
    'MOCK_ADMIN_USERNAME': 'admin',
    'MOCK_ADMIN_PASSWORD': TEST_ADMIN_PASSWORD,
})

import pymysql  # noqa: E402
import pytest  # noqa: E402

from device_lending import create_app  # noqa: E402
from device_lending.db import get_db_connection  # noqa: E402

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / 'sql' / 'migrations'

# 本番の master にある列のうち、アプリが読む列だけを作る
MASTER_SCHEMA = f'''
CREATE TABLE {TEST_MASTER_DB}.m_shain (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    shain_code VARCHAR(20) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    taishoku_date DATE NULL
);
CREATE TABLE {TEST_MASTER_DB}.m_device_model (
    id INT UNSIGNED NOT NULL PRIMARY KEY,
    device_type VARCHAR(30) NOT NULL,
    manufacturer VARCHAR(100) NOT NULL,
    model_name VARCHAR(100) NOT NULL
);
INSERT INTO {TEST_MASTER_DB}.m_shain (shain_code, name, taishoku_date) VALUES
    ('1001', '田中太郎', NULL),
    ('1002', '鈴木花子', NULL),
    ('1003', '佐藤次郎', '2020-03-31');
INSERT INTO {TEST_MASTER_DB}.m_device_model (id, device_type, manufacturer, model_name) VALUES
    (1, 'PC', 'Dell', 'Latitude 5440'),
    (2, 'PC', 'HP', 'EliteBook 840'),
    (3, 'SmartPhone', 'Apple', 'iPhone 15'),
    (4, 'Phone', 'NEC', 'DT400'),
    (5, 'MobileWifi', 'NEC', 'Aterm MP02LN');
'''

# 各テストの前に空にする app_test の表（外部キーのチェックを切って消す）
APP_TABLES = (
    'device_events', 'user_requests', 'device_losses', 'sims', 'loans', 'device_issues', 'devices',
)


def _admin_connection():
    return pymysql.connect(
        host=os.environ['DB_HOST'],
        port=int(os.environ['DB_PORT']),
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
        charset='utf8mb4',
        autocommit=True,
        client_flag=pymysql.constants.CLIENT.MULTI_STATEMENTS,
    )


def _run_script(cursor, sql):
    """複数の文を含む SQL を実行し、すべての結果を読み捨てる（途中の文のエラーもここで出る）。"""
    cursor.execute(sql)
    while cursor.nextset():
        pass


@pytest.fixture(scope='session')
def database():
    """テスト用 DB を作り直し、sql/migrations のマイグレーションを順に流す（テスト全体で 1 回）。"""
    try:
        connection = _admin_connection()
    except pymysql.MySQLError as error:
        pytest.skip(f'テスト用 MySQL に接続できません（conftest.py の説明を参照）: {error}')
    with connection, connection.cursor() as cursor:
        for name in (TEST_DB, TEST_MASTER_DB):
            cursor.execute(f'DROP DATABASE IF EXISTS {name}')
            cursor.execute(f'CREATE DATABASE {name} CHARACTER SET utf8mb4')
        _run_script(cursor, MASTER_SCHEMA)
        cursor.execute(f'USE {TEST_DB}')
        for path in sorted(MIGRATIONS_DIR.glob('*.sql')):
            _run_script(cursor, path.read_text(encoding='utf-8'))


@pytest.fixture
def clean_db(database):
    """前のテストが commit したデータを消す。"""
    connection = get_db_connection()
    with connection, connection.cursor() as cursor:
        cursor.execute('SET FOREIGN_KEY_CHECKS = 0')
        for table in APP_TABLES:
            cursor.execute(f'DELETE FROM {table}')
        cursor.execute('SET FOREIGN_KEY_CHECKS = 1')
        connection.commit()


@pytest.fixture
def cursor(clean_db):
    """1 つのトランザクションの cursor。テストが終わったら rollback して何も残さない。

    アプリの処理（loans.loan_device など）は呼び出し側の transaction の cursor を受け取るので、
    テストでも同じように cursor を渡して呼ぶ。
    """
    connection = get_db_connection()
    try:
        with connection.cursor() as cur:
            yield cur
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def app():
    flask_app = create_app()
    flask_app.config['TESTING'] = True
    return flask_app


def log_in_as_admin(test_client):
    """管理者としてログインした状態にする（CSRF トークンは csrf_token='test'）。"""
    with test_client.session_transaction() as session:
        session.clear()
        session.update({'role': 'admin', 'name': '管理者', 'csrf_token': 'test'})


def log_in_as_user(test_client, shain_code, name=''):
    """利用者（社員番号 shain_code）としてログインした状態にする。"""
    with test_client.session_transaction() as session:
        session.clear()
        session.update({'role': 'user', 'shain_code': shain_code, 'name': name, 'csrf_token': 'test'})


@pytest.fixture
def client(app, clean_db):
    """画面のテスト用。管理者としてログインした状態で始める。
    CSRF トークンをセッションに入れておくので、POST では csrf_token='test' を送る。
    利用者画面を試すときは log_in_as_user で入り直す。"""
    test_client = app.test_client()
    log_in_as_admin(test_client)
    return test_client


@pytest.fixture
def anonymous_client(app, clean_db):
    """ログインしていない画面のテスト用（CSRF トークンだけ入れておく）。"""
    test_client = app.test_client()
    with test_client.session_transaction() as session:
        session['csrf_token'] = 'test'
    return test_client
