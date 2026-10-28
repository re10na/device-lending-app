"""人物（社員）の一覧・詳細ページと、一覧の CSV 出力。読み取りだけで、操作は機器の画面で行う。"""
from datetime import date

import pymysql
from flask import Blueprint, Response, abort, current_app, render_template, request

from .. import exports, masters, members, user_page, user_requests
from ..db import transaction

bp = Blueprint('members', __name__, url_prefix='/members')


def _filter_args():
    """一覧と CSV 出力で共通の絞り込み条件（在籍, 貸出の有無, 注意, キーワード）。"""
    status = request.args.get('status', '')
    loan_state = request.args.get('loans', '')
    flag = request.args.get('flag', '')
    keyword = request.args.get('q', '').strip()
    if not members.valid_filters(status, loan_state, flag, keyword):
        abort(400)
    return status, loan_state, flag, keyword


@bp.get('')
def index():
    status, loan_state, flag, keyword = _filter_args()

    try:
        with transaction() as cursor:
            all_members = members.fetch_members(cursor)
    except pymysql.MySQLError:
        current_app.logger.exception('Could not load member list')
        return render_template('load_error.html'), 503

    # 在籍のタイルと注意の札に出す人数
    counts = {
        'active': sum(1 for m in all_members if not m['is_retired']),
        'retired': sum(1 for m in all_members if m['is_retired']),
        'review': sum(1 for m in all_members if 'review' in m['marks']),
        'lost': sum(1 for m in all_members if 'lost' in m['marks']),
        'ever_lost': sum(1 for m in all_members if m['ever_lost']),
        'ever_issue': sum(1 for m in all_members if m['ever_issue']),
    }
    return render_template(
        'members/list.html',
        members=members.filter_members(all_members, status, loan_state, flag, keyword),
        total=len(all_members),
        counts=counts,
        statuses=members.MEMBER_STATUSES,
        loan_states=members.MEMBER_LOAN_STATES,
        flags=members.MEMBER_FLAGS,
        selected_status=status,
        selected_loans=loan_state,
        selected_flag=flag,
        keyword=keyword,
        filtered=bool(status or loan_state or flag or keyword),
    )


@bp.get('/export.csv')
def export_csv():
    """今の絞り込み条件で、一覧の社員を CSV にしてダウンロードさせる。"""
    status, loan_state, flag, keyword = _filter_args()
    try:
        with transaction() as cursor:
            all_members = members.fetch_members(cursor)
    except pymysql.MySQLError:
        current_app.logger.exception('Could not export member list')
        return render_template('load_error.html'), 503

    rows = members.filter_members(all_members, status, loan_state, flag, keyword)
    filename = f'members_{date.today():%Y%m%d}.csv'
    return Response(
        exports.members_csv(rows),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@bp.get('/<shain_code>')
def detail(shain_code):
    try:
        with transaction() as cursor:
            employee = masters.find_employee(cursor, shain_code)
            if employee is None:
                abort(404)
            loan_history = user_page.fetch_loan_history(cursor, shain_code)
            context = {
                'employee': employee,
                'current_loans': [loan for loan in loan_history if loan['returned_on'] is None],
                'past_loans': [loan for loan in loan_history if loan['returned_on'] is not None],
                'requests': user_requests.fetch_requests(cursor, shain_code),
                'loss_history': members.fetch_losses(cursor, shain_code),
                'issue_history': members.fetch_issues(cursor, shain_code),
            }
    except pymysql.MySQLError:
        current_app.logger.exception('Could not load member detail')
        return render_template('load_error.html'), 503

    return render_template('members/detail.html', **context)
