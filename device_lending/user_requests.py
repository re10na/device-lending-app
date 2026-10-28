"""利用者からの申請（不具合・借りたい機器）の申請・取り消しと、管理者による処理。

利用者の申請はあくまで「お願い」で、device_issues や loans には触れない。
流れは「申請中 → 確認済み → 対応済み」。確認済みにしたら、管理者が外部ツールで利用者と
受け渡しの日時などを調整する。対応済みにするときに、同じトランザクションで故障・貸出として記録する。
誤って処理した申請は申請中に戻せる（対応済みなら、そのとき作った記録を取り消す）。
"""
import pymysql

from . import identifiers, issues, loans, masters
from .codes import format_device_code
from .config import ISSUE_TEXT_MAX_LENGTH
from .devices import find_open_loan, lock_device
from .errors import DeviceActionError, RecordNotFound

# 申請の画面に出す処理済みの件数と、「すべて見る」ページの 1 ページの件数
PROCESSED_PREVIEW_COUNT = 10
PROCESSED_PAGE_SIZE = 50

# まだ終わっていない申請の状態（同じ申請の二重登録を防ぐ範囲でもある）
OPEN_STATUSES = ('pending', 'confirmed')
_OPEN_STATUSES_SQL = "('pending', 'confirmed')"


def fetch_requests(cursor, shain_code):
    """社員の申請（新しい順）。不具合は機器の機種、借りたい申請は指定した機種を出す。"""
    cursor.execute(
        f'''
        SELECT r.id, r.request_type, r.status, r.detail, r.device_model_id,
               r.requested_at, r.confirmed_at, r.closed_at,
               d.id AS device_id, d.hostname, d.extension, d.serial_number,
               {identifiers.SIM_COLUMNS},
               m.device_type, m.manufacturer, m.model_name
        FROM user_requests AS r
        LEFT JOIN devices AS d ON d.id = r.device_id
        {identifiers.SIM_JOIN}
        LEFT JOIN {masters.MODEL_TABLE} AS m
               ON m.id = COALESCE(r.device_model_id, d.device_model_id)
        WHERE r.shain_code = %s
        ORDER BY r.requested_at DESC, r.id DESC
        ''',
        (shain_code,),
    )
    rows = cursor.fetchall()
    for row in rows:
        row['model_label'] = masters.format_model(row) if row['model_name'] else '不明な機種'
        if row['device_id']:
            row['identifier_summary'] = (
                identifiers.describe(row)['summary'] or format_device_code(row['device_id'])
            )
        else:
            row['identifier_summary'] = None
    return rows


def _execute_unique_open(cursor, sql, params, message):
    """uq_user_requests_one_open（同じ申請は終わるまで 1 件）の違反を message のエラーにして実行する。

    事前の SELECT ですり抜ける、同時に送られた申請を止めるため（Migration 011）。
    """
    try:
        cursor.execute(sql, params)
    except pymysql.err.IntegrityError as error:
        if 'uq_user_requests_one_open' in str(error):
            raise DeviceActionError(message) from error
        raise


def _clean_text(text, label, required=False):
    text = (text or '').strip()
    if required and not text:
        raise DeviceActionError(f'{label}を入力してください。')
    if len(text) > ISSUE_TEXT_MAX_LENGTH:
        raise DeviceActionError(f'{label}は{ISSUE_TEXT_MAX_LENGTH}文字以内で入力してください。')
    return text or None


def _require_active_employee(cursor, shain_code):
    employee = masters.find_employee(cursor, shain_code) if shain_code else None
    if employee is None or employee['is_retired']:
        raise DeviceActionError('社員を選択してください。')
    return employee


def submit_issue_request(cursor, shain_code, device_id, detail):
    """自分が借りている機器の不具合を申請する。"""
    detail = _clean_text(detail, '不具合の内容', required=True)
    _require_active_employee(cursor, shain_code)
    # 他の操作と同じく、機器の行を先にロックする（同じ申請の二重送信も防げる）
    lock_device(cursor, device_id)
    cursor.execute(
        '''
        SELECT 1 FROM loans
        WHERE device_id = %s AND shain_code = %s
          AND returned_on IS NULL AND cancelled_at IS NULL
        ''',
        (device_id, shain_code),
    )
    if cursor.fetchone() is None:
        raise DeviceActionError('不具合を申請できるのは、今借りている機器だけです。')
    cursor.execute(
        f'''
        SELECT 1 FROM user_requests
        WHERE request_type = 'issue' AND device_id = %s AND shain_code = %s
          AND status IN {_OPEN_STATUSES_SQL}
        ''',
        (device_id, shain_code),
    )
    if cursor.fetchone():
        raise DeviceActionError('この機器の不具合はすでに申請しています。')
    _execute_unique_open(
        cursor,
        '''
        INSERT INTO user_requests (request_type, shain_code, device_id, detail)
        VALUES ('issue', %s, %s, %s)
        ''',
        (shain_code, device_id, detail),
        'この機器の不具合はすでに申請しています。',
    )


def submit_loan_request(cursor, shain_code, model_id, reason):
    """借りたい機種を申請する。実際に渡す 1 台は管理者が決める。"""
    reason = _clean_text(reason, '理由')
    _require_active_employee(cursor, shain_code)
    model = masters.find_device_model(cursor, model_id)
    if model is None:
        raise DeviceActionError('機種を選択してください。')
    cursor.execute(
        f'''
        SELECT 1 FROM user_requests
        WHERE request_type = 'loan' AND device_model_id = %s AND shain_code = %s
          AND status IN {_OPEN_STATUSES_SQL}
        ''',
        (model_id, shain_code),
    )
    if cursor.fetchone():
        raise DeviceActionError('この機種はすでに申請しています。')
    _execute_unique_open(
        cursor,
        '''
        INSERT INTO user_requests (request_type, shain_code, device_model_id, detail)
        VALUES ('loan', %s, %s, %s)
        ''',
        (shain_code, model_id, reason),
        'この機種はすでに申請しています。',
    )
    return masters.format_model(model)


def cancel_request(cursor, request_id, shain_code):
    """申請中・確認済みの申請を取り消す。選んでいる社員の申請でなければ取り消せない。"""
    cursor.execute(
        'SELECT shain_code, status FROM user_requests WHERE id = %s FOR UPDATE',
        (request_id,),
    )
    found = cursor.fetchone()
    if found is None or found['shain_code'] != shain_code:
        raise RecordNotFound('申請が見つかりません。')
    if found['status'] not in OPEN_STATUSES:
        raise DeviceActionError('申請中・確認済みの申請だけ取り消せます。')
    cursor.execute(
        '''
        UPDATE user_requests SET status = 'cancelled', closed_at = CURRENT_TIMESTAMP
        WHERE id = %s
        ''',
        (request_id,),
    )


# --- 管理者による処理 ---

def _fetch_for_admin(cursor, where, order, limit=None, offset=0):
    cursor.execute(
        f'''
        SELECT r.id, r.request_type, r.shain_code, r.device_id, r.device_model_id,
               r.loan_id, r.issue_id, r.status, r.detail,
               r.requested_at, r.confirmed_at, r.closed_at,
               s.name AS employee_name,
               COALESCE({masters.retired_condition('s.taishoku_date')}, 0)
                   AS employee_retired,
               d.hostname, d.extension, d.serial_number, {identifiers.SIM_COLUMNS},
               m.id AS model_id, m.device_type, m.manufacturer, m.model_name
        FROM user_requests AS r
        LEFT JOIN {masters.SHAIN_TABLE} AS s ON s.shain_code = r.shain_code
        LEFT JOIN devices AS d ON d.id = r.device_id
        {identifiers.SIM_JOIN}
        LEFT JOIN {masters.MODEL_TABLE} AS m
               ON m.id = COALESCE(r.device_model_id, d.device_model_id)
        WHERE {where}
        ORDER BY {order}
        {'LIMIT %s OFFSET %s' if limit is not None else ''}
        ''',
        (limit, offset) if limit is not None else (),
    )
    rows = cursor.fetchall()
    for row in rows:
        row['model_label'] = masters.format_model(row) if row['model_name'] else '不明な機種'
        if row['device_id']:
            row['code'] = format_device_code(row['device_id'])
            row['identifier_summary'] = identifiers.describe(row)['summary'] or row['code']
    return rows


def fetch_pending_requests(cursor):
    """申請中の申請（古い順 = 待たせている順）。"""
    return _fetch_for_admin(cursor, "r.status = 'pending'", 'r.requested_at, r.id')


def fetch_confirmed_requests(cursor):
    """確認済みの申請（確認した順）。"""
    return _fetch_for_admin(cursor, "r.status = 'confirmed'", 'r.confirmed_at, r.id')


def fetch_processed_requests(cursor, limit, offset=0):
    """終わった申請（新しい順）。新しい方から offset 件飛ばした limit 件を返す。"""
    return _fetch_for_admin(
        cursor, f"r.status NOT IN {_OPEN_STATUSES_SQL}", 'r.closed_at DESC, r.id DESC',
        limit, offset,
    )


def count_processed_requests(cursor):
    cursor.execute(
        f"SELECT COUNT(*) AS n FROM user_requests WHERE status NOT IN {_OPEN_STATUSES_SQL}"
    )
    return cursor.fetchone()['n']


def count_pending_requests(cursor):
    """まだ確認していない申請の件数（サイドバーのバッジ）。"""
    cursor.execute("SELECT COUNT(*) AS n FROM user_requests WHERE status = 'pending'")
    return cursor.fetchone()['n']


_STATUS_ERRORS = {
    ('pending',): 'この申請は申請中ではありません。画面を読み込み直してください。',
    ('confirmed',): 'この申請は確認済みではありません。画面を読み込み直してください。',
}


def _find(cursor, request_id, status, request_type=None):
    """ロックせずに申請を読み、指定した状態（タプル）のどれかであることを確かめる。"""
    cursor.execute('SELECT * FROM user_requests WHERE id = %s', (request_id,))
    found = cursor.fetchone()
    if found is None or (request_type and found['request_type'] != request_type):
        raise RecordNotFound('申請が見つかりません。')
    if found['status'] not in status:
        raise DeviceActionError(_STATUS_ERRORS.get(status, 'この申請はすでに処理されています。'))
    return found


def _lock_in_status(cursor, request_id, status):
    """申請をロックして、まだ指定した状態（タプル）のままか確かめる（ロックは機器 → 申請の順）。"""
    cursor.execute(
        'SELECT status FROM user_requests WHERE id = %s FOR UPDATE', (request_id,)
    )
    if cursor.fetchone()['status'] not in status:
        raise DeviceActionError('この申請は他の操作で変更されました。画面を読み込み直してください。')


def _lock_request_device(cursor, request):
    if request['device_id']:
        # 他の処理と同じく機器を先にロックする（同じ申請を同時に処理しても安全）
        lock_device(cursor, request['device_id'])


def _close(cursor, request_id, from_status, status, loan_id=None, issue_id=None):
    """申請を終わった状態にする。loan_id / issue_id は対応済みにしたとき作った記録。"""
    _lock_in_status(cursor, request_id, from_status)
    cursor.execute(
        '''
        UPDATE user_requests
        SET status = %s, closed_at = CURRENT_TIMESTAMP, loan_id = %s, issue_id = %s
        WHERE id = %s
        ''',
        (status, loan_id, issue_id, request_id),
    )


def confirm_request(cursor, request_id):
    """申請を確認済みにする（機器の状態はまだ変えない）。"""
    request = _find(cursor, request_id, ('pending',))
    _lock_request_device(cursor, request)
    _lock_in_status(cursor, request_id, ('pending',))
    cursor.execute(
        '''
        UPDATE user_requests SET status = 'confirmed', confirmed_at = CURRENT_TIMESTAMP
        WHERE id = %s
        ''',
        (request_id,),
    )


def approve_loan_request(cursor, request_id, device_id):
    """確認済みの申請の機種から 1 台貸し出して、対応済みにする。借りた人の名前を返す。"""
    request = _find(cursor, request_id, ('confirmed',), 'loan')
    # 貸出のルール（廃棄・故障・設置中・貸出中・退職者）は loan_device が確かめる
    device = lock_device(cursor, device_id)
    if device['device_model_id'] != request['device_model_id']:
        raise DeviceActionError('申請された機種と違う機器は選べません。')
    name = loans.loan_device(cursor, device_id, request['shain_code'])
    loan_id = find_open_loan(cursor, device_id)['id']
    _close(cursor, request_id, ('confirmed',), 'done', loan_id=loan_id)
    return name


def _requester_loan_id(cursor, request):
    """不具合を申請した社員が、申請した時点でその機器を借りていた貸出（見つからなければ None）。"""
    cursor.execute(
        '''
        SELECT id FROM loans
        WHERE device_id = %s AND shain_code = %s AND cancelled_at IS NULL
          AND loaned_on <= DATE(%s)
        ORDER BY loaned_on DESC, id DESC
        LIMIT 1
        ''',
        (request['device_id'], request['shain_code'], request['requested_at']),
    )
    loan = cursor.fetchone()
    return loan['id'] if loan else None


def approve_issue_request(cursor, request_id, blocks_loan):
    """確認済みの申請の内容で故障・不具合を記録して、対応済みにする。"""
    request = _find(cursor, request_id, ('confirmed',), 'issue')
    # 申請から対応までの間に返却・貸し替えがあっても、故障は申請した人の貸出に結びつける
    issue_id = issues.report_issue(
        cursor, request['device_id'], request['detail'], blocks_loan,
        loan_id=_requester_loan_id(cursor, request),
    )
    _close(cursor, request_id, ('confirmed',), 'done', issue_id=issue_id)


def reject_request(cursor, request_id):
    """申請中・確認済みの申請を却下する。"""
    request = _find(cursor, request_id, OPEN_STATUSES)
    _lock_request_device(cursor, request)
    _close(cursor, request_id, OPEN_STATUSES, 'rejected')


def _reject_if_same_open(cursor, request):
    """戻すと同じ申請が 2 件になる場合は戻さない（却下後に申請し直した場合など）。"""
    if request['request_type'] == 'issue':
        target_column, target = 'device_id', request['device_id']
    else:
        target_column, target = 'device_model_id', request['device_model_id']
    cursor.execute(
        f'''
        SELECT 1 FROM user_requests
        WHERE request_type = %s AND shain_code = %s AND {target_column} = %s
          AND status IN {_OPEN_STATUSES_SQL} AND id <> %s
        ''',
        (request['request_type'], request['shain_code'], target, request['id']),
    )
    if cursor.fetchone():
        raise DeviceActionError('同じ社員の同じ申請がすでにあるため、申請中に戻せません。')


def reopen_request(cursor, request_id):
    """確認済み・対応済み・却下にした申請を申請中に戻し、通知文を返す。

    対応済みなら、そのとき作った貸出・故障の記録を取り消す（その後に返却・解決・修正して
    いれば取り消せない）。ロックは他の処理と同じく機器 → 貸出・故障 → 申請の順。
    """
    cursor.execute('SELECT * FROM user_requests WHERE id = %s', (request_id,))
    found = cursor.fetchone()
    if found is None:
        raise RecordNotFound('申請が見つかりません。')
    if found['status'] not in ('confirmed', 'done', 'rejected'):
        raise DeviceActionError('確認済み・対応済み・却下の申請だけ申請中に戻せます。')

    message = '申請を申請中に戻しました。'
    if found['status'] in ('confirmed', 'rejected'):
        _lock_request_device(cursor, found)
    elif found['loan_id']:
        loans.cancel_loan(cursor, found['loan_id'])
        message = '貸出記録を取り消し、申請を申請中に戻しました。'
    elif found['issue_id']:
        issues.cancel_issue(cursor, found['issue_id'])
        message = '故障・不具合の記録を取り消し、申請を申請中に戻しました。'
    else:
        raise DeviceActionError(
            'この申請は取り消し機能を入れる前に対応したため、申請中に戻せません。機器の画面から修正してください。'
        )
    if found['status'] != 'confirmed':
        _reject_if_same_open(cursor, found)

    # 待っている間に他の操作で状態が変わっていないか、ロックしてから確かめる
    cursor.execute(
        'SELECT status, loan_id, issue_id FROM user_requests WHERE id = %s FOR UPDATE',
        (request_id,),
    )
    locked = cursor.fetchone()
    if (locked['status'], locked['loan_id'], locked['issue_id']) != (
        found['status'], found['loan_id'], found['issue_id']
    ):
        raise DeviceActionError('この申請は他の操作で変更されました。画面を読み込み直してください。')
    _execute_unique_open(
        cursor,
        '''
        UPDATE user_requests
        SET status = 'pending', confirmed_at = NULL, closed_at = NULL,
            loan_id = NULL, issue_id = NULL
        WHERE id = %s
        ''',
        (request_id,),
        '同じ社員の同じ申請がすでにあるため、申請中に戻せません。',
    )
    return message
