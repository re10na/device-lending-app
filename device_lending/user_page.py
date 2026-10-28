"""利用者画面の読み取り（借りれる機器の集計と、社員ごとの貸出履歴）。書き込みはしない。"""
from . import identifiers, masters
from .codes import format_device_code

# 未解決の「貸出を止めない不具合」を 1 台 1 行にまとめる。
# JOIN 前にまとめておかないと、不具合が複数ある機器で台数が増えてしまう
_MINOR_ISSUES = '''
    SELECT device_id,
           GROUP_CONCAT(detail ORDER BY reported_on, id SEPARATOR ' / ') AS details
    FROM device_issues
    WHERE resolved_on IS NULL AND cancelled_at IS NULL AND NOT blocks_loan
    GROUP BY device_id
'''

# 「今貸し出せる機器」の条件（devices を d として使う）。管理者の申請処理でも使う
AVAILABLE_CONDITIONS = '''
    d.disposed_on IS NULL
    AND d.status = 'available'
    AND NOT EXISTS (
        SELECT 1 FROM loans AS l
        WHERE l.device_id = d.id AND l.returned_on IS NULL AND l.cancelled_at IS NULL
    )
    AND NOT EXISTS (
        SELECT 1 FROM device_issues AS i
        WHERE i.device_id = d.id AND i.resolved_on IS NULL AND i.cancelled_at IS NULL
          AND i.blocks_loan
    )
    AND NOT EXISTS (
        SELECT 1 FROM device_losses AS ls
        WHERE ls.device_id = d.id AND ls.found_on IS NULL
    )
'''


def count_available_devices(cursor):
    """今貸し出せる機器の台数だけを数える（画面選択ページ用）。"""
    cursor.execute(f'SELECT COUNT(*) AS n FROM devices AS d WHERE {AVAILABLE_CONDITIONS}')
    return cursor.fetchone()['n']


def fetch_available_models(cursor, device_type=''):
    """借りれる機器を機種ごとに数える。不具合ありの機器だけは 1 台ずつ別の行にする。

    GROUP BY に minor.device_id を入れることで、正常な機器（NULL）は機種ごとに 1 行、
    不具合ありの機器は 1 台ずつの行になる。並びは機種ごとに「正常 → 不具合あり」。
    """
    cursor.execute(
        f'''
        SELECT m.id AS model_id, m.device_type, m.manufacturer, m.model_name,
               (minor.device_id IS NOT NULL) AS has_minor_issue,
               COUNT(*) AS available_count,
               minor.details AS issue_details
        FROM devices AS d
        JOIN {masters.MODEL_TABLE} AS m ON m.id = d.device_model_id
        LEFT JOIN ({_MINOR_ISSUES}) AS minor ON minor.device_id = d.id
        WHERE {AVAILABLE_CONDITIONS}
          AND (%s = '' OR m.device_type = %s)
        GROUP BY m.id, m.device_type, m.manufacturer, m.model_name,
                 minor.device_id, minor.details
        ORDER BY m.device_type, m.manufacturer, m.model_name, m.id,
                 has_minor_issue, minor.device_id
        ''',
        (device_type, device_type),
    )
    rows = cursor.fetchall()
    for row in rows:
        row['model_label'] = masters.format_model(row)
    return rows


def fetch_available_devices(cursor, model_ids):
    """指定した機種の、今貸し出せる機器を 1 台ずつ返す（機種 id -> 機器の一覧）。"""
    if not model_ids:
        return {}
    placeholders = ', '.join(['%s'] * len(model_ids))
    cursor.execute(
        f'''
        SELECT d.id, d.device_model_id, d.hostname, d.extension, d.serial_number,
               {identifiers.SIM_COLUMNS}, m.device_type,
               minor.details AS issue_details
        FROM devices AS d
        JOIN {masters.MODEL_TABLE} AS m ON m.id = d.device_model_id
        LEFT JOIN ({_MINOR_ISSUES}) AS minor ON minor.device_id = d.id
        {identifiers.SIM_JOIN}
        WHERE {AVAILABLE_CONDITIONS}
          AND d.device_model_id IN ({placeholders})
        ORDER BY (minor.device_id IS NOT NULL), d.id
        ''',
        tuple(model_ids),
    )
    devices = {}
    for row in cursor.fetchall():
        row['code'] = format_device_code(row['id'])
        row['identifier_summary'] = identifiers.describe(row)['summary'] or row['code']
        devices.setdefault(row['device_model_id'], []).append(row)
    return devices


def fetch_loan_history(cursor, shain_code):
    """社員の貸出履歴（今借りている機器を含む）。貸出中を先頭に、貸出日の新しい順。"""
    cursor.execute(
        f'''
        SELECT l.id, l.loaned_on, l.returned_on,
               d.id AS device_id, d.hostname, d.extension, d.serial_number,
               {identifiers.SIM_COLUMNS},
               m.device_type, m.manufacturer, m.model_name,
               EXISTS (
                   SELECT 1 FROM device_losses AS ls
                   WHERE ls.loan_id = l.id AND ls.found_on IS NULL
               ) AS is_lost
        FROM loans AS l
        JOIN devices AS d ON d.id = l.device_id
        LEFT JOIN {masters.MODEL_TABLE} AS m ON m.id = d.device_model_id
        {identifiers.SIM_JOIN}
        WHERE l.shain_code = %s AND l.cancelled_at IS NULL
        ORDER BY (l.returned_on IS NULL) DESC, l.loaned_on DESC, l.id DESC
        ''',
        (shain_code,),
    )
    rows = cursor.fetchall()
    for row in rows:
        row['model_label'] = masters.format_model(row) if row['model_name'] else '不明な機種'
        # 照合情報が無い機器は管理番号（D-0007）で示す
        row['identifier_summary'] = (
            identifiers.describe(row)['summary'] or format_device_code(row['device_id'])
        )
    return rows


def unique_models(available):
    """借りれる機器の行（正常・不具合ありで分かれている）から、機種を 1 つずつ取り出す。"""
    models = {}
    for row in available:
        models.setdefault(row['model_id'], row)
    return list(models.values())


def device_types(models):
    """機種一覧から、絞り込みに使う種別の一覧を作る。"""
    return sorted({model['device_type'] for model in models if model['device_type']})
