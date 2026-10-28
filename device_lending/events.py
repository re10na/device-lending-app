"""変更履歴（device_events）の記録と、画面表示用の文章化。"""
import json
from datetime import date

from . import identifiers, masters
from .codes import format_device_code
from .config import RECENT_EVENT_LIMIT

FIELD_LABELS = {
    'device_model_id': '機種',
    'status': '状態',
    'location': '設置場所',
    'shain_code': '社員',
    'loaned_on': '貸出日',
    'returned_on': '返却日',
    'detail': '内容',
    'blocks_loan': '貸出不可',
    'reported_on': '発生日',
    'resolved_on': '解決日',
    'resolution': '対処内容',
    'hostname': 'ホスト名',
    'phone_number': '外線（電話番号）',
    'sim_iccid': 'SIM番号',
    'iccid': 'SIM番号',
    'extension': '内線番号',
    'serial_number': 'シリアル番号',
}

STATUS_LABELS = {'available': '保管中', 'installed': '設置中'}


def build_changes(old, new):
    """new に含まれる項目のうち、old と値が違うものを {列名: [変更前, 変更後]} にする。"""
    return {
        key: [_to_json_value(old[key]), _to_json_value(value)]
        for key, value in new.items()
        if old[key] != value
    }


def _to_json_value(value):
    return value.isoformat() if isinstance(value, date) else value


def record_event(cursor, device_id, event_type, *, loan_id=None, issue_id=None,
                 sim_id=None, loss_id=None, changes=None, note=None):
    """呼び出し元と同じトランザクションで履歴を 1 行追加する（SIM だけの操作は device_id なし）。"""
    cursor.execute(
        '''
        INSERT INTO device_events
            (device_id, event_type, loan_id, issue_id, sim_id, loss_id, changes, note)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''',
        (
            device_id, event_type, loan_id, issue_id, sim_id, loss_id,
            json.dumps(changes, ensure_ascii=False) if changes else None,
            note,
        ),
    )


def fetch_events(cursor, device_id=None, limit=None, sims_only=False, offset=0):
    """新しい順の履歴を、表示用の文章にして返す（device_id でその機器、sims_only で SIM の操作だけ）。

    limit を指定したときは、新しい方から offset 件飛ばした limit 件を返す。
    """
    conditions, params = [], []
    if device_id is not None:
        conditions.append('e.device_id = %s')
        params.append(device_id)
    if sims_only:
        conditions.append('e.sim_id IS NOT NULL')
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ''
    limit_sql = 'LIMIT %s OFFSET %s' if limit is not None else ''
    if limit is not None:
        params.extend((limit, offset))
    cursor.execute(
        f'''
        SELECT e.id, e.device_id, e.event_type, e.changes, e.note, e.occurred_at,
               m.manufacturer, m.model_name, m.device_type,
               d.hostname, d.extension, d.serial_number, {identifiers.SIM_COLUMNS},
               es.iccid AS event_sim_iccid, es.phone_number AS event_sim_phone,
               s.name AS loan_employee_name, l.shain_code AS loan_shain_code,
               i.detail AS issue_detail,
               ls.reported_by AS loss_reported_by, ls.detail AS loss_detail,
               ls.resolution AS loss_resolution, ls.shain_code AS loss_shain_code,
               ls_s.name AS loss_employee_name,
               COALESCE(l.cancelled_at, i.cancelled_at) AS target_cancelled_at
        FROM device_events AS e
        LEFT JOIN devices AS d ON d.id = e.device_id
        {identifiers.SIM_JOIN}
        LEFT JOIN sims AS es ON es.id = e.sim_id
        LEFT JOIN {masters.MODEL_TABLE} AS m ON m.id = d.device_model_id
        LEFT JOIN loans AS l ON l.id = e.loan_id
        LEFT JOIN {masters.SHAIN_TABLE} AS s ON s.shain_code = l.shain_code
        LEFT JOIN device_issues AS i ON i.id = e.issue_id
        LEFT JOIN device_losses AS ls ON ls.id = e.loss_id
        LEFT JOIN {masters.SHAIN_TABLE} AS ls_s ON ls_s.shain_code = ls.shain_code
        {where}
        ORDER BY e.occurred_at DESC, e.id DESC
        {limit_sql}
        ''',
        params,
    )
    rows = cursor.fetchall()
    for row in rows:
        row['changes'] = _load_changes(row['changes'])
    shain_codes, model_ids = _referenced_master_keys(rows)
    lookups = (
        masters.fetch_employee_names(cursor, shain_codes),
        masters.fetch_model_labels(cursor, model_ids),
    )
    return [describe_event(row, *lookups) for row in rows]


def fetch_recent_events(cursor):
    return fetch_events(cursor, limit=RECENT_EVENT_LIMIT)


def _load_changes(raw):
    if raw is None:
        return {}
    return json.loads(raw) if isinstance(raw, (str, bytes)) else raw


def _referenced_master_keys(rows):
    shain_codes, model_ids = set(), set()
    for row in rows:
        shain_codes.update(v for v in row['changes'].get('shain_code', []) if v)
        model_ids.update(v for v in row['changes'].get('device_model_id', []) if v)
    return shain_codes, model_ids


def _format_value(field, value, employee_names, model_labels):
    if value is None:
        return 'なし'
    if field == 'shain_code':
        name = employee_names.get(value)
        return f'{name}({value})' if name else f'不明({value})'
    if field == 'device_model_id':
        return model_labels.get(value, f'ID {value}')
    if field == 'status':
        return STATUS_LABELS.get(value, value)
    if field == 'phone_number':
        return identifiers.format_phone(value)
    if field == 'blocks_loan':
        return 'はい' if value else 'いいえ'
    return str(value)


def _change_lines(changes, employee_names, model_labels):
    return [
        '{}: {} → {}'.format(
            FIELD_LABELS.get(field, field),
            _format_value(field, old, employee_names, model_labels),
            _format_value(field, new, employee_names, model_labels),
        )
        for field, (old, new) in changes.items()
    ]


# 履歴の種類（一覧で色の印を付けるのに使う）。event_type の先頭で分ける
EVENT_KINDS = (
    ('loan', ('loaned', 'returned', 'loan_')),
    ('issue', ('issue_',)),
    ('lost', ('lost_',)),
    ('sim', ('sim_',)),
)


def event_kind(event_type):
    """貸出・故障・紛失・SIM のどれか。それ以外（登録・変更・設置・廃棄）は機器。"""
    for kind, prefixes in EVENT_KINDS:
        if event_type.startswith(prefixes):
            return kind
    return 'device'


def describe_event(row, employee_names, model_labels):
    """履歴 1 件を「<機器> … しました」の文章と補足行にする（機器が無い SIM の操作は「<SIM> …」）。"""
    holder = row['loan_employee_name'] or f"社員番号{row['loan_shain_code']}"
    sim = identifiers.sim_label(row['event_sim_iccid'], row['event_sim_phone'])
    loss_reporter = '利用者から報告' if row['loss_reported_by'] == 'user' else '登録'
    # 文は「<機器>」に続けて読む（例: LT-TANAKA01（D-0001 …）を田中さんに貸し出しました）
    sentences = {
        'registered': 'を登録しました',
        'device_edited': 'の機器情報を変更しました',
        'status_changed': 'の設置状態を変更しました',
        'disposed': 'を廃棄しました',
        'loaned': f'を{holder}さんに貸し出しました',
        'returned': f'を{holder}さんから返却しました',
        'loan_edited': 'の貸出記録を修正しました',
        'loan_cancelled': f'の{holder}さんへの貸出を取り消しました',
        'issue_reported': 'に故障・不具合が報告されました',
        'issue_resolved': 'の故障・不具合が解決されました',
        'issue_edited': 'の故障・不具合の記録を修正しました',
        'issue_cancelled': 'の故障・不具合の記録を取り消しました',
        'lost_reported': f'の紛失が{loss_reporter}されました',
        'lost_found': 'の紛失を解除しました',
        'sim_attached': f'に SIM（{sim}）を差しました',
        'sim_detached': f'から SIM（{sim}）を外しました',
        'sim_edited': f'の SIM（{sim}）の番号を変更しました',
        # 以下は機器が無いときの文（主語が SIM）
        'sim_registered': 'を登録しました',
    }
    details = _change_lines(row['changes'], employee_names, model_labels)
    if row['issue_detail']:
        details.insert(0, row['issue_detail'])
    if row['event_type'] == 'lost_reported':
        if row['loss_shain_code']:
            loss_holder = row['loss_employee_name'] or f"社員番号{row['loss_shain_code']}"
            details.append(f'紛失時の貸出先: {loss_holder}さん')
        if row['loss_detail']:
            details.append(row['loss_detail'])
    if row['event_type'] == 'lost_found' and row['loss_resolution']:
        details.append(row['loss_resolution'])
    if row['target_cancelled_at'] and not row['event_type'].endswith('_cancelled'):
        details.append('この記録は後で取り消されました')
    if row['note']:
        details.append(f"理由: {row['note']}" if row['event_type'] == 'disposed' else row['note'])
    if row['device_id'] is None:
        # SIM だけの操作（登録・差していないときの変更）
        text = 'の番号を変更しました' if row['event_type'] == 'sim_edited' else sentences[row['event_type']]
        return {
            'device_id': None,
            'subject': f'SIM（{sim}）',
            'text': text,
            'kind': 'sim',
            'details': details,
            'occurred_at': row['occurred_at'].strftime('%Y-%m-%d %H:%M'),
        }
    model = masters.format_model(row) if row['model_name'] else '不明な機種'
    code = format_device_code(row['device_id'])
    # SIM の操作では、機器を SIM 由来の番号で呼ぶと文の中で同じ番号が 2 回出るため管理番号で呼ぶ
    main = None if row['event_type'].startswith('sim_') else identifiers.describe(row)['main']
    return {
        'device_id': row['device_id'],
        'subject': f'{main}（{code} {model}）' if main else f'{code} {model}',
        'text': sentences[row['event_type']],
        'kind': event_kind(row['event_type']),
        'details': details,
        'occurred_at': row['occurred_at'].strftime('%Y-%m-%d %H:%M'),
    }
