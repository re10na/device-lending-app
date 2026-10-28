"""故障・不具合の報告・解決・修正のルート（すべて POST）。"""
from flask import Blueprint, request, url_for

from .. import issues
from ..csrf import verify_csrf_token
from ..forms import form_date, form_text
from ..navigation import redirect_back
from .actions import perform

bp = Blueprint('issues', __name__)


@bp.post('/devices/<int:device_id>/issues')
def report(device_id):
    verify_csrf_token()

    def operation(cursor):
        issues.report_issue(cursor, device_id, form_text('detail'), 'blocks_loan' in request.form)
        return '故障・不具合を登録しました。'

    perform(operation, '故障・不具合を登録できませんでした。管理者に確認してください。')
    return redirect_back(url_for('devices.detail', device_id=device_id))


@bp.post('/issues/<int:issue_id>/resolve')
def resolve(issue_id):
    verify_csrf_token()

    def operation(cursor):
        issues.resolve_issue(cursor, issue_id, form_text('resolution'))
        return '故障・不具合を解決済みにしました。'

    perform(operation, '解決を登録できませんでした。管理者に確認してください。')
    return redirect_back(url_for('pages.dashboard'))


@bp.post('/issues/<int:issue_id>/edit')
def edit(issue_id):
    verify_csrf_token()

    def operation(cursor):
        issues.edit_issue(
            cursor,
            issue_id,
            form_text('detail'),
            'blocks_loan' in request.form,
            form_date('reported_on', '発生日', required=True),
            form_date('resolved_on', '解決日'),
            form_text('resolution'),
        )
        return '故障・不具合の記録を修正しました。'

    perform(operation, '記録を修正できませんでした。管理者に確認してください。')
    return redirect_back(url_for('pages.dashboard'))
