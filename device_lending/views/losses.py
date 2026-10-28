"""紛失の登録・解除のルート（すべて POST）。"""
from flask import Blueprint, url_for

from .. import losses
from ..csrf import verify_csrf_token
from ..forms import form_text
from ..navigation import redirect_back
from .actions import perform

bp = Blueprint('losses', __name__)


@bp.post('/devices/<int:device_id>/losses')
def report(device_id):
    verify_csrf_token()

    def operation(cursor):
        losses.report_loss(cursor, device_id, form_text('detail'))
        return '紛失中として登録しました。'

    perform(operation, '紛失を登録できませんでした。管理者に確認してください。')
    return redirect_back(url_for('devices.detail', device_id=device_id))


@bp.post('/losses/<int:loss_id>/resolve')
def resolve(loss_id):
    verify_csrf_token()

    def operation(cursor):
        losses.resolve_loss(cursor, loss_id, form_text('resolution'))
        return '紛失を解除しました。'

    perform(operation, '紛失を解除できませんでした。管理者に確認してください。')
    return redirect_back(url_for('pages.dashboard'))
