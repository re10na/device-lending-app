"""データベース接続とトランザクション管理。"""
from contextlib import contextmanager

import pymysql

from .config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER


def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )


@contextmanager
def transaction():
    """正常終了で commit、例外で rollback（再送出）、最後に必ず close する。"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            yield cursor
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
