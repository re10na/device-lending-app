"""SIM の一覧と、登録/番号の変更/機器への差し替え/外すのルート。"""
import pymysql
from flask import Blueprint, abort, current_app, render_template, request, url_for

from .. import devices, events, sims
from ..config import RECENT_EVENT_LIMIT, SIM_FIELDS
from ..csrf import verify_csrf_token
from ..db import transaction
from ..forms import form_int
from ..navigation import redirect_back
from .actions import perform
from .pages import render_event_history

bp = Blueprint('sims', __name__, url_prefix='/admin/sims')


@bp.get('/events')
def event_history():
    """SIM の変更履歴（登録・番号の変更・差し替えなど）。"""
    return render_event_history(
        sims_only=True,
        eyebrow='SIM ACTIVITY',
        title='SIM の変更履歴',
        description='SIM の登録、番号の変更、機器への差し替え・外すの記録です。',
        back_url=url_for('sims.index'),
        back_label='SIM 一覧へ戻る',
        empty_text='SIM を登録すると、ここに変更内容が表示されます。',
    )


def _form_sim():
    return {field: request.form.get(field, '') for field in SIM_FIELDS}


@bp.get('')
def index():
    # 上のタイルで選ぶ絞り込み（used = 機器に差している、free = 未使用）
    state = request.args.get('state', '')
    if state not in ('', 'used', 'free'):
        abort(400)
    try:
        with transaction() as cursor:
            sim_list = sims.fetch_sims(cursor)
            # 差し替え先に選べる機器（SIM を差せる種別で、廃棄していないもの）
            sim_devices = [
                device for device in devices.fetch_devices(cursor)
                if device['uses_sim'] and device['placement'] != 'disposed'
            ]
            sim_events = events.fetch_events(cursor, limit=RECENT_EVENT_LIMIT, sims_only=True)
    except pymysql.MySQLError:
        current_app.logger.exception('Could not load SIM list')
        return render_template('load_error.html'), 503

    used = [sim for sim in sim_list if sim['device_id']]
    return render_template(
        'sims.html',
        sims=[sim for sim in sim_list if (state == 'used') == bool(sim['device_id'])] if state else sim_list,
        counts={'all': len(sim_list), 'used': len(used), 'free': len(sim_list) - len(used)},
        selected_state=state,
        sim_devices=sim_devices,
        sim_events=sim_events,
    )


def _back():
    return redirect_back(url_for('sims.index'))


@bp.post('')
def register():
    verify_csrf_token()

    def operation(cursor):
        sims.register_sim(cursor, _form_sim())
        return 'SIM を登録しました。機器に差すときは、一覧の「機器に差す」から選んでください。'

    perform(operation, 'SIM を登録できませんでした。')
    return _back()


@bp.post('/<int:sim_id>/edit')
def edit(sim_id):
    verify_csrf_token()

    def operation(cursor):
        sims.edit_sim(cursor, sim_id, _form_sim())
        return 'SIM の番号を変更しました。'

    perform(operation, 'SIM の番号を変更できませんでした。')
    return _back()


@bp.post('/attach')
def attach():
    """SIM を機器に差す（SIM ページからも、機器詳細からも使う）。"""
    verify_csrf_token()

    def operation(cursor):
        label, replaced = sims.attach_sim(
            cursor, form_int('sim_id', 'SIM'), form_int('device_id', '機器'),
        )
        if replaced:
            return f'SIM（{label}）を差しました。元の SIM（{replaced}）は外して未使用にしました。'
        return f'SIM（{label}）を差しました。'

    perform(operation, 'SIM を差せませんでした。')
    return _back()


@bp.post('/<int:sim_id>/detach')
def detach(sim_id):
    verify_csrf_token()

    def operation(cursor):
        sims.detach_sim(cursor, sim_id)
        return 'SIM を外して未使用にしました。'

    perform(operation, 'SIM を外せませんでした。')
    return _back()

