"""POST ルート共通の「トランザクション実行 → flash」処理。"""
import pymysql
from flask import abort, current_app, flash

from ..db import transaction
from ..errors import DeviceActionError, RecordNotFound


def perform(operation, failure_message):
    """operation(cursor) を 1 トランザクションで実行し、返したメッセージを flash する。

    operation は成功時の通知文を返す。ルール違反は赤いメッセージにし、
    対象が無ければ 404、想定外の DB エラーはログに残して汎用メッセージにする。
    """
    try:
        with transaction() as cursor:
            message = operation(cursor)
        flash(message, 'success')
    except RecordNotFound:
        abort(404)
    except DeviceActionError as error:
        flash(str(error), 'error')
    except pymysql.MySQLError:
        current_app.logger.exception(failure_message)
        flash(failure_message, 'error')
