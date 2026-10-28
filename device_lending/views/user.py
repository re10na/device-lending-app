"""利用者画面のルート（確認と、不具合・借りたい機器の申請、紛失の報告）。

社員番号は URL やフォームからは受け取らず、ログインしている利用者のもの（auth.current_shain_code）だけを使う。
他人の社員番号を送っても、その人として申請・報告できないようにするため。
"""
import pymysql
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for

from .. import auth, losses, masters, user_page, user_requests
from ..csrf import verify_csrf_token
from ..db import transaction
from ..forms import form_int, form_text
from ..navigation import redirect_back
from .actions import perform

bp = Blueprint('user', __name__, url_prefix='/user')

# 貸出履歴は最初この件数だけ出し、「すべて見る」で全件を出す
HISTORY_PREVIEW_COUNT = 5


@bp.get('')
def index():
    shain_code = auth.current_shain_code()
    device_type = request.args.get('device_type', '').strip()
    show_all_history = request.args.get('history') == 'all'

    try:
        with transaction() as cursor:
            employee = masters.find_employee(cursor, shain_code)
            # ログインした後に退職した（または社員マスタから消えた）ときは、ログインからやり直してもらう
            if employee is None or employee['is_retired']:
                auth.log_out()
                flash('在籍している社員として確認できなかったため、ログアウトしました。', 'error')
                return redirect(url_for('pages.home'))
            types = user_page.device_types(masters.fetch_device_models(cursor))
            if device_type and device_type not in types:
                abort(400)
            available = user_page.fetch_available_models(cursor, device_type)
            # 申請できる機種は、種別の絞り込みに関係なく、今借りられる機種すべて
            all_available = (
                user_page.fetch_available_models(cursor) if device_type else available
            )
            history = user_page.fetch_loan_history(cursor, shain_code)
            requests = user_requests.fetch_requests(cursor, shain_code)
    except pymysql.MySQLError:
        current_app.logger.exception('Could not load user page')
        return render_template('load_error.html'), 503

    return render_template(
        'user.html',
        employee=employee,
        current_loans=[loan for loan in history if loan['returned_on'] is None],
        loan_history=history,
        available=available,
        requestable_models=user_page.unique_models(all_available),
        device_types=types,
        selected_type=device_type,
        requests=requests,
        # 申請中・確認済みの機器・機種には、同じ申請のボタンを出さない
        open_issue_devices={
            r['device_id'] for r in requests
            if r['request_type'] == 'issue' and r['status'] in user_requests.OPEN_STATUSES
        },
        open_loan_models={
            r['device_model_id'] for r in requests
            if r['request_type'] == 'loan' and r['status'] in user_requests.OPEN_STATUSES
        },
        show_all_history=show_all_history,
        HISTORY_PREVIEW_COUNT=HISTORY_PREVIEW_COUNT,
    )


def _back_to_user_page():
    return redirect_back(url_for('user.index'))


@bp.post('/requests/issue')
def request_issue():
    verify_csrf_token()
    shain_code = auth.current_shain_code()

    def operation(cursor):
        user_requests.submit_issue_request(
            cursor, shain_code, form_int('device_id', '機器'), form_text('detail'),
        )
        return '不具合を申請しました。管理者が確認するまでお待ちください。'

    perform(operation, '申請できませんでした。管理者に確認してください。')
    return _back_to_user_page()


@bp.post('/requests/loan')
def request_loan():
    verify_csrf_token()
    shain_code = auth.current_shain_code()

    def operation(cursor):
        model = user_requests.submit_loan_request(
            cursor, shain_code, form_int('device_model_id', '機種'), form_text('detail'),
        )
        return f'{model}を借りたいと申請しました。管理者が確認するまでお待ちください。'

    perform(operation, '申請できませんでした。管理者に確認してください。')
    return _back_to_user_page()


@bp.post('/losses')
def report_loss():
    """紛失は申請ではなく報告。送った時点で紛失中になる（情報漏えい対策を急ぐため）。"""
    verify_csrf_token()
    shain_code = auth.current_shain_code()

    def operation(cursor):
        losses.report_loss_by_user(
            cursor, shain_code, form_int('device_id', '機器'), form_text('detail'),
        )
        return '紛失を報告しました。管理者から連絡があるまでお待ちください。見つかった場合も管理者に連絡してください。'

    perform(operation, '紛失を報告できませんでした。管理者に直接連絡してください。')
    return _back_to_user_page()


@bp.post('/requests/<int:request_id>/cancel')
def cancel_request(request_id):
    verify_csrf_token()
    shain_code = auth.current_shain_code()

    def operation(cursor):
        user_requests.cancel_request(cursor, request_id, shain_code)
        return '申請を取り消しました。'

    perform(operation, '申請を取り消せませんでした。管理者に確認してください。')
    return _back_to_user_page()
