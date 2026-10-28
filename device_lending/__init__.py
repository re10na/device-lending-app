"""アプリケーションファクトリ（Flask アプリを組み立てる）。"""
import logging

import pymysql
from flask import Flask, flash, has_request_context, redirect, request, url_for
from flask.logging import default_handler

from . import auth, config
from .codes import format_device_code
from . import identifiers
from . import user_requests
from .csrf import csrf_token
from .db import transaction


class RequestFormatter(logging.Formatter):
    """ログにリクエストのメソッドとパスをつける。"""

    def format(self, record):
        if has_request_context():
            record.method = request.method
            record.path = request.path
        else:
            record.method = '-'
            record.path = '-'
        return super().format(record)


def create_app():
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.secret_key = config.SECRET_KEY
    app.jinja_env.globals['csrf_token'] = csrf_token
    app.jinja_env.filters['device_code'] = format_device_code
    app.jinja_env.globals['PLACEMENTS'] = config.PLACEMENTS
    app.jinja_env.globals['FLAGS'] = config.FLAGS
    app.jinja_env.globals['FLAG_GROUPS'] = config.FLAG_GROUPS
    app.jinja_env.globals['FILTER_FLAG_GROUPS'] = config.FILTER_FLAG_GROUPS
    app.jinja_env.globals['REQUEST_TYPES'] = config.REQUEST_TYPES
    app.jinja_env.globals['REQUEST_STATUSES'] = config.REQUEST_STATUSES
    app.jinja_env.globals['IDENTIFIER_FIELDS'] = config.IDENTIFIER_FIELDS
    app.jinja_env.globals['SIM_FIELDS'] = config.SIM_FIELDS
    app.jinja_env.globals['SIM_DEVICE_TYPES'] = config.SIM_DEVICE_TYPES
    app.jinja_env.globals['IDENTIFIER_FIELD_TYPES'] = identifiers.field_types()
    app.jinja_env.globals['type_fields'] = identifiers.type_fields

    default_handler.setFormatter(RequestFormatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(method)s %(path)s: %(message)s'
    ))

    @app.before_request
    def require_login():
        """ページごとに必要な役割（auth.required_role）でログインを確かめる。
        ログインしていなければログイン画面へ、役割が違えば自分の画面へ移動させる。"""
        role = auth.required_role(request.endpoint)
        if role is None or auth.current_role() == role:
            return None
        if auth.current_role() is None:
            flash('ログインしてください。', 'error')
            return redirect(url_for('pages.home'))
        from .views.auth import landing_url
        return redirect(landing_url(auth.current_role()))

    @app.context_processor
    def inject_current_user():
        """ログイン中の人（上の帯とサイドバーに出す）。"""
        return {'current_user': auth.current_user()}

    @app.context_processor
    def inject_pending_request_count():
        """管理者画面のサイドバーに出す未処理の申請件数。"""
        if auth.required_role(request.endpoint) != auth.ADMIN:
            return {}
        try:
            with transaction() as cursor:
                return {'pending_request_count': user_requests.count_pending_requests(cursor)}
        except pymysql.MySQLError as error:
            # 件数が出せなくても画面自体は表示する。DB 障害なら画面側が ERROR を出すので 1 行で残す
            app.logger.warning('Could not count pending requests: %s', error)
            return {}

    from .views.auth import bp as auth_bp
    from .views.devices import bp as devices_bp
    from .views.issues import bp as issues_bp
    from .views.loans import bp as loans_bp
    from .views.losses import bp as losses_bp
    from .views.members import bp as members_bp
    from .views.pages import bp as pages_bp
    from .views.requests import bp as requests_bp
    from .views.sims import bp as sims_bp
    from .views.user import bp as user_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(sims_bp)
    app.register_blueprint(loans_bp)
    app.register_blueprint(issues_bp)
    app.register_blueprint(losses_bp)
    return app
