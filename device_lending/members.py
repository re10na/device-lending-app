"""人物一覧・人物詳細の読み取り（社員ごとの貸出台数と注意マーク、紛失・故障の履歴）。書き込みはしない。

社員マスタにいる人だけを扱う。マスタに無い社員番号の貸出は、機器一覧の「要確認」で見つける。
故障・不具合は、次のどちらかに当てはまるものをその人の故障とみなす。
  - 本人が申請して、対応済みになった（user_requests.issue_id）
  - 報告したとき、その機器をその人が借りていた（device_issues.loan_id の貸出の社員）
"""
from collections import Counter

from . import identifiers, masters
from .codes import format_device_code
from .config import SEARCH_MAX_LENGTH

MEMBER_STATUSES = {
    'active': '在籍',
    'retired': '退職済み',
}

MEMBER_LOAN_STATES = {
    'with': '貸出あり',
    'without': '貸出なし',
}

# 一覧に出す注意マーク（機器の FLAGS と同じキー・表示名を使う）
MEMBER_MARKS = ('review', 'lost')

# 絞り込みの「注意」の選択肢。キー -> 表示名
MEMBER_FLAGS = {
    'review': '❗ 要確認（退職済みで貸出あり）',
    'lost': '🚨 紛失中',
    'ever_lost': '紛失したことがある',
    'ever_issue': '故障・不具合があったことがある',
}

# 「本人の申請で記録された故障」の条件（社員の列を shain で渡す）
_ISSUE_BY_REQUEST = '''
    SELECT r.issue_id FROM user_requests AS r
    WHERE r.shain_code = {shain} AND r.status = 'done' AND r.issue_id IS NOT NULL
'''

# 「その人の貸出中に報告された故障」の条件（device_issues を i、社員の列を shain で渡す）。
# 取り消した貸出（誤登録）は、借りていなかったものとする
_ISSUE_DURING_LOAN = '''
    SELECT 1 FROM loans AS l
    WHERE l.id = i.loan_id AND l.shain_code = {shain} AND l.cancelled_at IS NULL
'''


def _issue_conditions(shain):
    return (
        _ISSUE_BY_REQUEST.format(shain=shain),
        _ISSUE_DURING_LOAN.format(shain=shain),
    )


def fetch_members(cursor):
    """社員マスタの全員と、貸出台数・紛失・故障の有無。社員番号順。"""
    by_request, during_loan = _issue_conditions('s.shain_code')
    cursor.execute(
        f'''
        SELECT s.shain_code, s.name, s.taishoku_date,
               {masters.retired_condition('s.taishoku_date')} AS is_retired,
               (
                   SELECT COUNT(*) FROM loans AS l
                   WHERE l.shain_code = s.shain_code
                     AND l.returned_on IS NULL AND l.cancelled_at IS NULL
               ) AS loan_count,
               -- 廃棄済みの機器は機器一覧でも紛失中に数えないので、ここでも除く
               EXISTS (
                   SELECT 1 FROM device_losses AS ls
                   JOIN devices AS d ON d.id = ls.device_id
                   WHERE ls.shain_code = s.shain_code AND ls.found_on IS NULL
                     AND d.disposed_on IS NULL
               ) AS is_losing,
               EXISTS (
                   SELECT 1 FROM device_losses AS ls WHERE ls.shain_code = s.shain_code
               ) AS ever_lost,
               EXISTS (
                   SELECT 1 FROM device_issues AS i
                   WHERE i.cancelled_at IS NULL
                     AND (i.id IN ({by_request}) OR EXISTS ({during_loan}))
               ) AS ever_issue
        FROM {masters.SHAIN_TABLE} AS s
        ORDER BY s.shain_code
        '''
    )
    return [_derive_marks(row) for row in cursor.fetchall()]


def _derive_marks(row):
    marks = []
    if row['is_retired'] and row['loan_count']:
        marks.append('review')
    if row['is_losing']:
        marks.append('lost')
    row['marks'] = marks
    return row


def filter_members(members, status='', loan_state='', flag='', keyword=''):
    """在籍・貸出の有無・注意・キーワード（社員番号か氏名の一部）の AND で絞り込む。"""
    result = members
    if status:
        retired = status == 'retired'
        result = [m for m in result if bool(m['is_retired']) == retired]
    if loan_state:
        with_loans = loan_state == 'with'
        result = [m for m in result if bool(m['loan_count']) == with_loans]
    if flag in MEMBER_MARKS:
        result = [m for m in result if flag in m['marks']]
    elif flag:
        result = [m for m in result if m[flag]]
    if keyword:
        needle = keyword.casefold()
        result = [
            m for m in result
            if needle in m['shain_code'].casefold() or needle in (m['name'] or '').casefold()
        ]
    return result


def valid_filters(status, loan_state, flag, keyword):
    return (
        status in {'', *MEMBER_STATUSES}
        and loan_state in {'', *MEMBER_LOAN_STATES}
        and flag in {'', *MEMBER_FLAGS}
        and len(keyword) <= SEARCH_MAX_LENGTH
    )


def _without_spaces(text):
    return ''.join((text or '').split()).casefold()


def search_people(employees, all_devices, query):
    """ダッシュボードの検索。社員番号か氏名（空白は無視）の一部に当たる社員。在籍者を先に並べる。

    employees は masters.fetch_employees、all_devices は devices.fetch_devices の結果。
    人物一覧の fetch_members より軽いので、入力中の候補にも使える。
    """
    needle = _without_spaces(query)
    if not needle:
        return []
    loan_counts = Counter(d['holder_code'] for d in all_devices if d['loan_id'])
    people = [
        dict(employee, loan_count=loan_counts[employee['shain_code']])
        for employee in employees
        if needle in employee['shain_code'].casefold() or needle in _without_spaces(employee['name'])
    ]
    return sorted(people, key=lambda person: (bool(person['is_retired']), person['shain_code']))


def fetch_upcoming_retirements(cursor, days):
    """退職日が今日から days 日以内で、まだ機器を借りている社員（退職日の近い順）。

    退職日を過ぎると機器一覧の「要確認」になるので、その前に返却を頼むために使う。
    """
    cursor.execute(
        f'''
        SELECT s.shain_code, s.name, s.taishoku_date,
               DATEDIFF(s.taishoku_date, CURRENT_DATE()) AS days_left,
               COUNT(*) AS loan_count
        FROM {masters.SHAIN_TABLE} AS s
        JOIN loans AS l
          ON l.shain_code = s.shain_code AND l.returned_on IS NULL AND l.cancelled_at IS NULL
        WHERE s.taishoku_date > CURRENT_DATE()
          AND s.taishoku_date <= CURRENT_DATE() + INTERVAL %s DAY
        GROUP BY s.shain_code, s.name, s.taishoku_date
        ORDER BY s.taishoku_date, s.shain_code
        ''',
        (days,),
    )
    return cursor.fetchall()


def fetch_losses(cursor, shain_code):
    """社員が借りている間に起きた紛失（新しい順）。"""
    cursor.execute(
        f'''
        SELECT ls.id, ls.reported_by, ls.reported_on, ls.detail, ls.found_on, ls.resolution,
               d.id AS device_id, d.disposed_on, d.hostname, d.extension, d.serial_number,
               {identifiers.SIM_COLUMNS},
               m.device_type, m.manufacturer, m.model_name
        FROM device_losses AS ls
        JOIN devices AS d ON d.id = ls.device_id
        LEFT JOIN {masters.MODEL_TABLE} AS m ON m.id = d.device_model_id
        {identifiers.SIM_JOIN}
        WHERE ls.shain_code = %s
        ORDER BY ls.reported_on DESC, ls.id DESC
        ''',
        (shain_code,),
    )
    return [_describe_device(row) for row in cursor.fetchall()]


def fetch_issues(cursor, shain_code):
    """社員に結びつく故障・不具合（新しい順）。by_request / during_loan でどう結びついたかを示す。"""
    by_request, during_loan = _issue_conditions('%(shain)s')
    cursor.execute(
        f'''
        SELECT i.id, i.reported_on, i.detail, i.blocks_loan, i.resolved_on, i.resolution,
               i.id IN ({by_request}) AS by_request,
               EXISTS ({during_loan}) AS during_loan,
               d.id AS device_id, d.hostname, d.extension, d.serial_number,
               {identifiers.SIM_COLUMNS},
               m.device_type, m.manufacturer, m.model_name
        FROM device_issues AS i
        JOIN devices AS d ON d.id = i.device_id
        LEFT JOIN {masters.MODEL_TABLE} AS m ON m.id = d.device_model_id
        {identifiers.SIM_JOIN}
        WHERE i.cancelled_at IS NULL
          AND (i.id IN ({by_request}) OR EXISTS ({during_loan}))
        ORDER BY i.reported_on DESC, i.id DESC
        ''',
        {'shain': shain_code},
    )
    return [_describe_device(row) for row in cursor.fetchall()]


def _describe_device(row):
    row['model_label'] = masters.format_model(row) if row['model_name'] else '不明な機種'
    # 照合情報が無い機器は管理番号（D-0007）で示す
    row['identifier_summary'] = (
        identifiers.describe(row)['summary'] or format_device_code(row['device_id'])
    )
    return row
