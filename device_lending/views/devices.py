"""機器の一覧・詳細ページ、一覧の CSV 出力と、登録/機種変更/設置/廃棄のルート。"""
from datetime import date

import pymysql
from flask import Blueprint, Response, abort, current_app, render_template, request, url_for

from .. import devices, events, exports, issues, loans, losses, masters, sims
from ..codes import format_device_code
from ..config import FLAG_GROUPS, FLAGS, PLACEMENTS, SEARCH_MAX_LENGTH
from ..csrf import verify_csrf_token
from ..db import transaction
from ..forms import form_identifiers, form_int, form_text
from ..navigation import redirect_back
from .actions import perform

bp = Blueprint('devices', __name__, url_prefix='/devices')


def _filter_args():
    """一覧と CSV 出力で共通の絞り込み条件（状態, 注意, 借りている人, キーワード, 種別）。"""
    placement = request.args.get('placement', 'all')
    flag = request.args.get('flag', '')
    holder = request.args.get('holder', '').strip()
    keyword = request.args.get('q', '').strip()
    device_type = request.args.get('type', '').strip()
    if placement not in {'all', *PLACEMENTS} or flag not in {'', *FLAGS, *FLAG_GROUPS}:
        abort(400)
    if any(len(value) > SEARCH_MAX_LENGTH for value in (holder, keyword, device_type)):
        abort(400)
    return placement, flag, holder, keyword, device_type


@bp.get('')
def index():
    placement, flag, holder, keyword, device_type = _filter_args()

    try:
        with transaction() as cursor:
            all_devices = devices.fetch_devices(cursor)
            models = masters.fetch_device_models(cursor)
            free_sims = sims.fetch_unassigned_sims(cursor)
    except pymysql.MySQLError:
        current_app.logger.exception('Could not load device list')
        return render_template('load_error.html'), 503

    counts = devices.count_devices(all_devices)
    # 状態のタイルに出す廃棄済みの台数（count_devices は未廃棄だけを数える）
    counts['disposed'] = sum(1 for d in all_devices if d['placement'] == 'disposed')
    counts['any'] = sum(1 for d in devices.visible_devices(all_devices) if d['flags'])
    return render_template(
        'devices/list.html',
        devices=devices.filter_devices(all_devices, placement, flag, holder, keyword, device_type),
        total=len(devices.visible_devices(all_devices)),
        counts=counts,
        holders=devices.current_holders(all_devices),
        filter_types=devices.types_in_use(all_devices),
        models=models,
        free_sims=free_sims,
        selected_placement=placement,
        selected_flag=flag,
        selected_holder=holder,
        selected_type=device_type,
        keyword=keyword,
        filtered=placement != 'all' or bool(flag or holder or keyword or device_type),
    )


@bp.get('/export.csv')
def export_csv():
    """今の絞り込み条件で、一覧の機器を CSV にしてダウンロードさせる。"""
    placement, flag, holder, keyword, device_type = _filter_args()
    try:
        with transaction() as cursor:
            all_devices = devices.fetch_devices(cursor)
    except pymysql.MySQLError:
        current_app.logger.exception('Could not export device list')
        return render_template('load_error.html'), 503

    rows = devices.filter_devices(all_devices, placement, flag, holder, keyword, device_type)
    filename = f'devices_{date.today():%Y%m%d}.csv'
    return Response(
        exports.devices_csv(rows),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@bp.get('/<int:device_id>')
def detail(device_id):
    try:
        with transaction() as cursor:
            device = devices.fetch_device(cursor, device_id)
            if device is None:
                abort(404)
            context = {
                'device': device,
                'loan_history': loans.fetch_loans(cursor, device_id),
                'issue_history': issues.fetch_issues(cursor, device_id),
                'loss_history': losses.fetch_losses(cursor, device_id),
                'event_history': events.fetch_events(cursor, device_id=device_id),
                'employees': masters.fetch_employees(cursor),
                'models': masters.fetch_device_models(cursor),
                'free_sims': sims.fetch_unassigned_sims(cursor),
            }
    except pymysql.MySQLError:
        current_app.logger.exception('Could not load device detail')
        return render_template('load_error.html'), 503

    context['active_employees'] = [e for e in context['employees'] if not e['is_retired']]
    context['unresolved_minor_issues'] = [
        issue for issue in context['issue_history']
        if issue['resolved_on'] is None and not issue['blocks_loan']
    ]
    return render_template('devices/detail.html', **context)


@bp.post('')
def register():
    verify_csrf_token()

    def operation(cursor):
        sim_id = form_text('sim_id')
        device_id = devices.register_device(
            cursor, form_int('device_model_id', '機種'), form_identifiers(),
            sim_id=form_int('sim_id', 'SIM') if sim_id else None,
        )
        return f'機器「{format_device_code(device_id)}」を登録しました。'

    perform(operation, '機器を登録できませんでした。管理者に確認してください。')
    return redirect_back(url_for('devices.index'))


def _device_page(device_id):
    return url_for('devices.detail', device_id=device_id)


@bp.post('/<int:device_id>/model')
def change_model(device_id):
    verify_csrf_token()

    def operation(cursor):
        cleared = devices.change_model(cursor, device_id, form_int('device_model_id', '機種'))
        if cleared:
            return (
                f'機種を変更しました。種別が変わったため{"・".join(cleared)}を消しました。'
                '「照合情報の編集」から新しい種別の照合情報を入力してください。'
            )
        return '機種を変更しました。'

    perform(operation, '機種を変更できませんでした。管理者に確認してください。')
    return redirect_back(_device_page(device_id))


@bp.post('/<int:device_id>/identifiers')
def edit_identifiers(device_id):
    verify_csrf_token()

    def operation(cursor):
        devices.edit_identifiers(cursor, device_id, form_identifiers())
        return '照合情報を変更しました。'

    perform(operation, '照合情報を変更できませんでした。管理者に確認してください。')
    return redirect_back(_device_page(device_id))


@bp.post('/<int:device_id>/install')
def install(device_id):
    verify_csrf_token()

    def operation(cursor):
        devices.install_device(cursor, device_id, form_text('location'))
        return '設置中として登録しました。'

    perform(operation, '設置状態を変更できませんでした。管理者に確認してください。')
    return redirect_back(_device_page(device_id))


@bp.post('/<int:device_id>/uninstall')
def uninstall(device_id):
    verify_csrf_token()

    def operation(cursor):
        devices.uninstall_device(cursor, device_id)
        return '保管中に戻しました。'

    perform(operation, '設置状態を変更できませんでした。管理者に確認してください。')
    return redirect_back(_device_page(device_id))


@bp.post('/<int:device_id>/dispose')
def dispose(device_id):
    verify_csrf_token()

    def operation(cursor):
        detached = devices.dispose_device(cursor, device_id, form_text('disposal_reason'))
        if detached:
            return '機器を廃棄済みにしました。差していた SIM は外して未使用にしました。'
        return '機器を廃棄済みにしました。'

    perform(operation, '廃棄を登録できませんでした。管理者に確認してください。')
    return redirect_back(_device_page(device_id))
