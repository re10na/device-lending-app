"""貸出・返却・貸出記録の修正のルート（すべて POST）。"""
from flask import Blueprint, url_for

from .. import loans
from ..csrf import verify_csrf_token
from ..forms import form_date, form_text
from ..navigation import redirect_back
from .actions import perform

bp = Blueprint('loans', __name__)


@bp.post('/devices/<int:device_id>/loans')
def loan(device_id):
    verify_csrf_token()

    def operation(cursor):
        name = loans.loan_device(cursor, device_id, form_text('shain_code'))
        return f'機器を{name}さんに貸し出しました。'

    perform(operation, '貸出を登録できませんでした。管理者に確認してください。')
    return redirect_back(url_for('devices.detail', device_id=device_id))


@bp.post('/loans/<int:loan_id>/return')
def return_loan(loan_id):
    verify_csrf_token()

    def operation(cursor):
        loans.return_loan(cursor, loan_id)
        return '機器を返却済みにしました。'

    perform(operation, '返却を登録できませんでした。管理者に確認してください。')
    return redirect_back(url_for('pages.dashboard'))


@bp.post('/loans/<int:loan_id>/edit')
def edit_loan(loan_id):
    verify_csrf_token()

    def operation(cursor):
        loans.edit_loan(
            cursor,
            loan_id,
            form_text('shain_code'),
            form_date('loaned_on', '貸出日', required=True),
            form_date('returned_on', '返却日'),
        )
        return '貸出記録を修正しました。'

    perform(operation, '貸出記録を修正できませんでした。管理者に確認してください。')
    return redirect_back(url_for('pages.dashboard'))
