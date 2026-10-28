"""マスタ DB（master）の読み取り。社員と機種の取得だけを行い、書き込みはしない。"""
from .config import MASTER_DB

SHAIN_TABLE = f'{MASTER_DB}.m_shain'
MODEL_TABLE = f'{MASTER_DB}.m_device_model'



def retired_condition(column='taishoku_date'):
    """退職済みを表す SQL 条件（退職日当日から退職扱い）。"""
    return f'({column} IS NOT NULL AND {column} <= CURRENT_DATE())'


def format_model(row):
    return f"{row['manufacturer']} {row['model_name']}"


def fetch_employees(cursor):
    """全社員（退職者を含む）。is_retired で区別する。"""
    cursor.execute(
        f'''
        SELECT shain_code, name, {retired_condition()} AS is_retired
        FROM {SHAIN_TABLE}
        ORDER BY shain_code
        '''
    )
    return cursor.fetchall()


def fetch_active_employees(cursor):
    return [employee for employee in fetch_employees(cursor) if not employee['is_retired']]


def find_employee(cursor, shain_code):
    cursor.execute(
        f'''
        SELECT shain_code, name, taishoku_date, {retired_condition()} AS is_retired
        FROM {SHAIN_TABLE}
        WHERE shain_code = %s
        LIMIT 1
        ''',
        (shain_code,),
    )
    return cursor.fetchone()


def fetch_device_models(cursor):
    cursor.execute(
        f'''
        SELECT id, device_type, manufacturer, model_name
        FROM {MODEL_TABLE}
        ORDER BY device_type, manufacturer, model_name
        '''
    )
    return cursor.fetchall()


def find_device_model(cursor, model_id):
    cursor.execute(
        f'''
        SELECT id, device_type, manufacturer, model_name
        FROM {MODEL_TABLE}
        WHERE id = %s
        ''',
        (model_id,),
    )
    return cursor.fetchone()


def fetch_employee_names(cursor, shain_codes):
    """社員番号 -> 名前 の辞書。"""
    if not shain_codes:
        return {}
    placeholders = ', '.join(['%s'] * len(shain_codes))
    cursor.execute(
        f'SELECT shain_code, name FROM {SHAIN_TABLE} WHERE shain_code IN ({placeholders})',
        tuple(shain_codes),
    )
    return {row['shain_code']: row['name'] for row in cursor.fetchall()}


def fetch_model_labels(cursor, model_ids):
    """機種 id -> 「メーカー 機種名」 の辞書。"""
    if not model_ids:
        return {}
    placeholders = ', '.join(['%s'] * len(model_ids))
    cursor.execute(
        f'''
        SELECT id, manufacturer, model_name FROM {MODEL_TABLE}
        WHERE id IN ({placeholders})
        ''',
        tuple(model_ids),
    )
    return {row['id']: format_model(row) for row in cursor.fetchall()}
