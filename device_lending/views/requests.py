"""管理者による申請の処理のルート。

申請中 → 確認済み（外部ツールで利用者と調整）→ 貸し出して / 記録して対応済み。却下と申請中に戻すも行う。
"""
import pymysql
from flask import Blueprint, abort, current_app, render_template, request, url_for

from .. import user_page, user_requests
from ..csrf import verify_csrf_token
from ..db import transaction
from ..forms import form_int
from ..navigation import redirect_back
from .actions import perform

bp = Blueprint('requests', __name__, url_prefix='/admin/requests')


@bp.get('')
def index():
    try:
        with transaction() as cursor:
            pending = user_requests.fetch_pending_requests(cursor)
            confirmed = user_requests.fetch_confirmed_requests(cursor)
            model_ids = {r['device_model_id'] for r in confirmed if r['request_type'] == 'loan'}
            candidates = user_page.fetch_available_devices(cursor, sorted(model_ids))
            processed = user_requests.fetch_processed_requests(
                cursor, user_requests.PROCESSED_PREVIEW_COUNT,
            )
            processed_total = user_requests.count_processed_requests(cursor)
    except pymysql.MySQLError:
        current_app.logger.exception('Could not load requests')
        return render_template('load_error.html'), 503

    return render_template(
        'requests.html',
        pending=pending,
        confirmed=confirmed,
        candidates=candidates,
        processed=processed,
        processed_total=processed_total,
        processed_preview=user_requests.PROCESSED_PREVIEW_COUNT,
    )


@bp.get('/processed')
def processed():
    """処理済みの申請をすべて、新しい順に PROCESSED_PAGE_SIZE 件ずつ表示する。"""
    page = request.args.get('page', 1, type=int)
    if page < 1:
        abort(400)
    page_size = user_requests.PROCESSED_PAGE_SIZE
    try:
        with transaction() as cursor:
            # 1 件多く読んで、次のページがあるかを確かめる
            rows = user_requests.fetch_processed_requests(
                cursor, page_size + 1, offset=(page - 1) * page_size,
            )
            total = user_requests.count_processed_requests(cursor)
    except pymysql.MySQLError:
        current_app.logger.exception('Could not load processed requests')
        return render_template('load_error.html'), 503

    return render_template(
        'requests_processed.html',
        processed=rows[:page_size],
        processed_total=total,
        page=page,
        has_next=len(rows) > page_size,
        first_number=(page - 1) * page_size + 1,
    )


def _back():
    return redirect_back(url_for('requests.index'))


@bp.post('/<int:request_id>/confirm')
def confirm(request_id):
    verify_csrf_token()

    def operation(cursor):
        user_requests.confirm_request(cursor, request_id)
        return '申請を確認済みにしました。外部ツールで利用者に受け渡しの日時などを連絡してください。'

    perform(operation, '申請を処理できませんでした。')
    return _back()


@bp.post('/<int:request_id>/approve-loan')
def approve_loan(request_id):
    verify_csrf_token()

    def operation(cursor):
        name = user_requests.approve_loan_request(
            cursor, request_id, form_int('device_id', '貸し出す機器'),
        )
        return f'機器を{name}さんに貸し出し、申請を対応済みにしました。'

    perform(operation, '申請を処理できませんでした。')
    return _back()


@bp.post('/<int:request_id>/approve-issue')
def approve_issue(request_id):
    verify_csrf_token()

    def operation(cursor):
        user_requests.approve_issue_request(
            cursor, request_id, request.form.get('blocks_loan') == 'on',
        )
        return '故障・不具合として記録し、申請を対応済みにしました。'

    perform(operation, '申請を処理できませんでした。')
    return _back()


@bp.post('/<int:request_id>/reject')
def reject(request_id):
    verify_csrf_token()

    def operation(cursor):
        user_requests.reject_request(cursor, request_id)
        return '申請を却下しました。'

    perform(operation, '申請を処理できませんでした。')
    return _back()


@bp.post('/<int:request_id>/reopen')
def reopen(request_id):
    verify_csrf_token()

    def operation(cursor):
        return user_requests.reopen_request(cursor, request_id)

    perform(operation, '申請を申請中に戻せませんでした。')
    return _back()
