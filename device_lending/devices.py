"""機器の取得・状態の導出と、登録/機種変更/設置/廃棄（request には触れない）。"""
from datetime import date

from . import identifiers, masters, sims
from .config import (
    DEVICE_TYPE_ORDER, DEVICE_TYPE_SHORT, DISPOSAL_REASON_MAX_LENGTH, FLAG_GROUPS,
    LOCATION_MAX_LENGTH,
)
from .codes import format_device_code, parse_device_code
from .errors import DeviceActionError, RecordNotFound
from .events import build_changes, record_event

_DEVICE_SELECT = f'''
    SELECT d.id, d.device_model_id, d.status, d.location, d.disposed_on, d.disposal_reason,
           d.hostname, d.extension, d.serial_number, {identifiers.SIM_COLUMNS},
           m.device_type, m.manufacturer, m.model_name,
           l.id AS loan_id, l.shain_code AS holder_code, l.loaned_on,
           s.name AS holder_name,
           (l.id IS NOT NULL AND s.id IS NULL) AS holder_missing,
           COALESCE({masters.retired_condition('s.taishoku_date')}, 0)
               AS holder_retired,
           EXISTS (
               SELECT 1 FROM device_issues AS i
               WHERE i.device_id = d.id AND i.resolved_on IS NULL AND i.cancelled_at IS NULL
                 AND i.blocks_loan
           ) AS has_blocking_issue,
           EXISTS (
               SELECT 1 FROM device_issues AS i
               WHERE i.device_id = d.id AND i.resolved_on IS NULL AND i.cancelled_at IS NULL
                 AND NOT i.blocks_loan
           ) AS has_minor_issue,
           EXISTS (
               SELECT 1 FROM device_losses AS ls
               WHERE ls.device_id = d.id AND ls.found_on IS NULL
           ) AS is_lost
    FROM devices AS d
    LEFT JOIN {masters.MODEL_TABLE} AS m ON m.id = d.device_model_id
    LEFT JOIN loans AS l
           ON l.device_id = d.id AND l.returned_on IS NULL AND l.cancelled_at IS NULL
    LEFT JOIN {masters.SHAIN_TABLE} AS s ON s.shain_code = l.shain_code
    {identifiers.SIM_JOIN}
'''


def derive_state(row):
    """DB の行から、配置（1 つ）と注意フラグ（0 個以上）を導出して足す。"""
    row['code'] = format_device_code(row['id'])
    row['model_label'] = masters.format_model(row) if row['model_name'] else '不明な機種'
    # 一覧の種別アイコン（短い名前と、DEVICE_TYPE_ORDER の何番目の色か。ない種別は 0 = 灰色）
    row['type_short'] = DEVICE_TYPE_SHORT.get(row['device_type'], row['device_type'] or '?')
    row['type_slot'] = (
        DEVICE_TYPE_ORDER.index(row['device_type']) + 1
        if row['device_type'] in DEVICE_TYPE_ORDER else 0
    )
    info = identifiers.describe(row)
    row['main_identifier'] = info['main']
    row['identifier_summary'] = info['summary']
    row['phone_display'] = identifiers.format_phone(row['phone_number'])
    row['identifier_fields'] = identifiers.type_fields(row['device_type'])
    row['uses_sim'] = identifiers.uses_sim(row['device_type'])
    if row['sim_id']:
        row['sim_label'] = identifiers.sim_label(row['sim_iccid'], row['phone_number'])
    # 画面の主な呼び名。照合情報があればそれ、なければ管理番号
    row['display_name'] = info['main'] or row['code']
    holder = row['holder_name'] or f"社員番号{row['holder_code']}"
    if row['disposed_on']:
        row['placement'], row['placement_label'] = 'disposed', '廃棄済み'
    elif row['loan_id']:
        row['placement'], row['placement_label'] = 'loaned', f'貸出中（{holder}）'
    elif row['status'] == 'installed':
        row['placement'], row['placement_label'] = 'installed', f"設置中（{row['location']}）"
    else:
        row['placement'], row['placement_label'] = 'stored', '保管中'

    flags = []
    if not row['disposed_on']:
        if row['is_lost']:
            flags.append('lost')
        if row['has_blocking_issue']:
            flags.append('broken')
        elif row['has_minor_issue']:
            flags.append('minor')
        if row['loan_id'] and (row['holder_retired'] or row['holder_missing']):
            flags.append('review')
    row['flags'] = flags
    return row


def fetch_devices(cursor):
    cursor.execute(_DEVICE_SELECT + ' ORDER BY d.id')
    return [derive_state(row) for row in cursor.fetchall()]


def fetch_device(cursor, device_id):
    cursor.execute(_DEVICE_SELECT + ' WHERE d.id = %s', (device_id,))
    row = cursor.fetchone()
    return derive_state(row) if row else None


def count_active_devices(cursor):
    """未廃棄の機器の台数だけを DB で数える（状態の導出がいらない画面用）。"""
    cursor.execute('SELECT COUNT(*) AS n FROM devices WHERE disposed_on IS NULL')
    return cursor.fetchone()['n']


def visible_devices(devices):
    return [device for device in devices if device['placement'] != 'disposed']


def count_devices(devices):
    """未廃棄の機器だけを数える。"""
    active = visible_devices(devices)
    counts = {'total': len(active)}
    for placement in ('loaned', 'installed', 'stored'):
        counts[placement] = sum(1 for d in active if d['placement'] == placement)
    for flag in ('broken', 'minor', 'review', 'lost'):
        counts[flag] = sum(1 for d in active if flag in d['flags'])
    # 故障と不具合ありは 1 台にどちらか一方だけ付くので、足すと「どちらかがある台数」になる
    counts['issue'] = counts['broken'] + counts['minor']
    return counts


def filter_devices(devices, placement='all', flag='', holder='', keyword='', device_type=''):
    """状態・注意・借りている人（社員番号）・キーワード・種別の AND で絞り込む。"""
    if placement == 'all':
        result = visible_devices(devices)
    else:
        result = [d for d in devices if d['placement'] == placement]
    if flag:
        wanted = FLAG_GROUPS[flag][1] if flag in FLAG_GROUPS else (flag,)
        result = [d for d in result if any(f in d['flags'] for f in wanted)]
    if holder:
        result = [d for d in result if d['loan_id'] and d['holder_code'] == holder]
    if keyword:
        result = [d for d in result if _matches_keyword(d, keyword)]
    if device_type:
        result = [d for d in result if d['device_type'] == device_type]
    return result


def types_in_use(devices):
    """機器が 1 台以上ある種別（絞り込みの選択肢）。"""
    return sorted({device['device_type'] for device in devices if device['device_type']})


def _type_sort_key(device_type):
    """DEVICE_TYPE_ORDER の順。ない種別はその後ろに名前順（種別不明は最後）。"""
    if device_type in DEVICE_TYPE_ORDER:
        return (0, DEVICE_TYPE_ORDER.index(device_type), '')
    return (1, 0, device_type) if device_type else (2, 0, '')


def type_breakdown(devices):
    """配置（貸出中・設置中・保管中）ごとの、種別ごとの台数（廃棄済みは除く）。

    {'loaned': [{'device_type': 'PC', 'short_name': 'PC', 'count': 8, 'slot': 1}, ...], ...} の形で返す。
    short_name は円グラフの丸に書く短い名前。
    slot は円グラフの色の番号（DEVICE_TYPE_ORDER の何番目か。ない種別は 0 = 灰色）。
    """
    counts = {}
    for device in visible_devices(devices):
        by_type = counts.setdefault(device['placement'], {})
        by_type[device['device_type']] = by_type.get(device['device_type'], 0) + 1
    return {
        placement: [
            {
                'device_type': device_type,
                'short_name': DEVICE_TYPE_SHORT.get(device_type, device_type or '不明'),
                'count': count,
                'slot': DEVICE_TYPE_ORDER.index(device_type) + 1
                if device_type in DEVICE_TYPE_ORDER else 0,
            }
            for device_type, count in sorted(by_type.items(), key=lambda item: _type_sort_key(item[0]))
        ]
        for placement, by_type in counts.items()
    }


def current_holders(devices):
    """今機器を借りている社員の一覧（絞り込みの選択肢）。社員番号順。

    flags は借りている機器に付いた注意フラグ（まとめた絞り込みのキーも含む）、types は
    借りている機器の種別。画面で「注意」「種別」を選んだとき、該当する人だけを残すのに使う。
    """
    holders = {}
    for device in devices:
        if not device['loan_id']:
            continue
        holder = holders.setdefault(device['holder_code'], {
            'shain_code': device['holder_code'],
            'name': device['holder_name'],
            'retired': device['holder_retired'],
            'flags': set(),
            'types': set(),
        })
        holder['flags'].update(device['flags'])
        if device['device_type']:
            holder['types'].add(device['device_type'])
    for holder in holders.values():
        holder['flags'].update(
            key for key, (_, included) in FLAG_GROUPS.items()
            if holder['flags'] & set(included)
        )
    return sorted(holders.values(), key=lambda holder: holder['shain_code'])


def _matches_keyword(device, keyword):
    """照合情報・管理番号に加えて、機種・借りている人・設置場所の部分一致。"""
    if _matches_identifier(device, keyword):
        return True
    text = ' '.join(
        str(device[key] or '')
        for key in ('device_type', 'manufacturer', 'model_name',
                    'holder_name', 'holder_code', 'location')
    ).casefold()
    return keyword.casefold() in text


def _matches_identifier(device, needle):
    """ホスト名・内線・シリアルと差している SIM の番号の部分一致、または管理番号（D-0007）の一致。"""
    folded = needle.casefold()
    for field in ('hostname', 'extension', 'sim_extension', 'serial_number'):
        if device[field] and folded in device[field].casefold():
            return True
    digits = identifiers.normalize_digits_needle(needle)
    if digits and any(digits in (device[f] or '') for f in ('phone_number', 'sim_iccid')):
        return True
    # 管理番号は「D-7」「d0007」のように D 付きのときだけ（数字だけの検索は内線などと紛れるため）
    return folded.startswith('d') and parse_device_code(needle) == device['id']


def search_devices(devices, query):
    """ダッシュボードの検索。照合情報・管理番号か、機種（種別・メーカー・機種名）に当たる機器（廃棄済みは除く）。

    借りている人では探さない（人は人物の候補として別に出す）。
    """
    needle = query.casefold()
    results = []
    for device in visible_devices(devices):
        model_text = ' '.join(
            str(device[key] or '') for key in ('device_type', 'manufacturer', 'model_name')
        ).casefold()
        if needle in model_text or _matches_identifier(device, query):
            results.append(device)
    return results


# --- 書き込み系（すべて呼び出し側の transaction 内で実行する） ---

def lock_device(cursor, device_id):
    """機器の行をロックして返す。なければ RecordNotFound。"""
    cursor.execute('SELECT * FROM devices WHERE id = %s FOR UPDATE', (device_id,))
    device = cursor.fetchone()
    if device is None:
        raise RecordNotFound('機器が見つかりません。')
    return device


def find_open_loan(cursor, device_id):
    cursor.execute(
        '''
        SELECT id, shain_code FROM loans
        WHERE device_id = %s AND returned_on IS NULL AND cancelled_at IS NULL
        ''',
        (device_id,),
    )
    return cursor.fetchone()


def find_open_loss(cursor, device_id):
    """見つかっていない紛失の記録（なければ None）。"""
    cursor.execute(
        'SELECT id FROM device_losses WHERE device_id = %s AND found_on IS NULL',
        (device_id,),
    )
    return cursor.fetchone()


def _reject_if_disposed(device, action):
    if device['disposed_on']:
        raise DeviceActionError(f'廃棄済みの機器は{action}できません。')


def _require_model(cursor, model_id):
    if model_id is None or masters.find_device_model(cursor, model_id) is None:
        raise DeviceActionError('選択した機種がマスタに見つかりません。')


def _device_type(cursor, model_id):
    model = masters.find_device_model(cursor, model_id) if model_id is not None else None
    if model is None:
        raise DeviceActionError('選択した機種がマスタに見つかりません。')
    return model['device_type']


def register_device(cursor, model_id, raw_identifiers=None, sim_id=None):
    """機器を登録し、新しい機器 id を返す。照合情報は {項目名: 入力文字列}、sim_id は差す SIM。"""
    device_type = _device_type(cursor, model_id)
    values = identifiers.clean_for_type(device_type, raw_identifiers or {})
    values = {f: values.get(f) for f in identifiers.ALL_FIELDS}
    if sim_id is not None and not identifiers.uses_sim(device_type):
        raise DeviceActionError('この種別の機器には SIM を差せません。')
    identifiers.require_one(device_type, values, has_sim=sim_id is not None)
    identifiers.check_duplicates(cursor, values)
    given = {f: v for f, v in values.items() if v is not None}
    columns = ', '.join(['device_model_id', *given])
    placeholders = ', '.join(['%s'] * (1 + len(given)))
    identifiers.execute_guarded(
        cursor, f'INSERT INTO devices ({columns}) VALUES ({placeholders})',
        (model_id, *given.values()), values,
    )
    device_id = cursor.lastrowid
    # 登録時の値も履歴に残す（[変更前, 変更後] = [なし, 値]）
    record_event(
        cursor, device_id, 'registered',
        changes={f: [None, v] for f, v in given.items()} or None,
    )
    if sim_id is not None:
        sims.attach_sim(cursor, sim_id, device_id)
    return device_id


def edit_identifiers(cursor, device_id, raw_identifiers):
    """照合情報を更新する。送られてきた項目だけを対象にし、変わったものだけ記録する。"""
    device = lock_device(cursor, device_id)
    _reject_if_disposed(device, '照合情報の編集')
    device_type = _device_type(cursor, device['device_model_id'])
    new_values = identifiers.clean_for_type(device_type, raw_identifiers)
    merged = {f: new_values.get(f, device[f]) for f in identifiers.ALL_FIELDS}
    identifiers.require_one(device_type, merged, has_sim=sims.device_has_sim(cursor, device_id))
    changes = build_changes(device, new_values)
    if not changes:
        raise DeviceActionError('照合情報が変わっていません。')
    identifiers.check_duplicates(cursor, {f: new_values[f] for f in changes}, exclude_id=device_id)
    assignments = ', '.join(f'{field} = %s' for field in changes)
    identifiers.execute_guarded(
        cursor, f'UPDATE devices SET {assignments} WHERE id = %s',
        (*(new_values[f] for f in changes), device_id), new_values,
    )
    record_event(cursor, device_id, 'device_edited', changes=changes)


def change_model(cursor, device_id, model_id):
    device = lock_device(cursor, device_id)
    _reject_if_disposed(device, '機種変更')
    _require_model(cursor, model_id)
    if device['device_model_id'] == model_id:
        raise DeviceActionError('機種が変わっていません。')
    # 種別が変わると使わなくなる照合情報（例: PC→スマホのホスト名）は消す。
    # 残すと画面に出ないまま重複チェックにだけ引っかかり、原因が分からなくなるため
    new_type = _device_type(cursor, model_id)
    if not identifiers.uses_sim(new_type) and sims.device_has_sim(cursor, device_id):
        raise DeviceActionError('この種別には SIM を差せません。先に SIM を外してください。')
    kept_fields = identifiers.type_fields(new_type)
    new_values = {'device_model_id': model_id}
    for field in identifiers.ALL_FIELDS:
        if field not in kept_fields:
            new_values[field] = None
    changes = build_changes(device, new_values)
    assignments = ', '.join(f'{field} = %s' for field in changes)
    cursor.execute(
        f'UPDATE devices SET {assignments} WHERE id = %s',
        (*(new_values[f] for f in changes), device_id),
    )
    record_event(cursor, device_id, 'device_edited', changes=changes)
    return [identifiers.label(f) for f in changes if f != 'device_model_id']


def _set_placement(cursor, device, status, location):
    """status と location を更新し、変わった項目を status_changed として記録する。"""
    changes = build_changes(device, {'status': status, 'location': location})
    if not changes:
        raise DeviceActionError('設置状態が変わっていません。')
    cursor.execute(
        'UPDATE devices SET status = %s, location = %s WHERE id = %s',
        (status, location, device['id']),
    )
    record_event(cursor, device['id'], 'status_changed', changes=changes)


def install_device(cursor, device_id, location):
    """設置中にする（すでに設置中なら場所の変更）。"""
    location = (location or '').strip()
    if not location or len(location) > LOCATION_MAX_LENGTH:
        raise DeviceActionError(
            f'設置場所を入力してください（{LOCATION_MAX_LENGTH}文字以内）。'
        )
    device = lock_device(cursor, device_id)
    _reject_if_disposed(device, '設置')
    if find_open_loan(cursor, device_id):
        raise DeviceActionError('貸出中の機器は設置できません。先に返却してください。')
    if find_open_loss(cursor, device_id):
        raise DeviceActionError('紛失中の機器は設置できません。見つかった場合は先に紛失を解除してください。')
    _set_placement(cursor, device, 'installed', location)


def uninstall_device(cursor, device_id):
    """設置中から保管中（available）に戻す。"""
    device = lock_device(cursor, device_id)
    _reject_if_disposed(device, '設置状態の変更')
    if device['status'] != 'installed':
        raise DeviceActionError('この機器は設置中ではありません。')
    _set_placement(cursor, device, 'available', None)


def dispose_device(cursor, device_id, reason):
    """廃棄済みにし、外した SIM を返す。

    貸出中の機器は廃棄できない。ただし紛失中の機器は戻ってこないので、貸出をその日で終える。
    借りていた社員は貸出と紛失の記録に残る。紛失の記録は「見つかっていない」のまま残す。
    """
    reason = (reason or '').strip()
    if len(reason) > DISPOSAL_REASON_MAX_LENGTH:
        raise DeviceActionError(
            f'廃棄理由は{DISPOSAL_REASON_MAX_LENGTH}文字以内で入力してください。'
        )
    device = lock_device(cursor, device_id)
    if device['disposed_on']:
        raise DeviceActionError('この機器はすでに廃棄済みです。')
    loan = find_open_loan(cursor, device_id)
    lost = find_open_loss(cursor, device_id) is not None
    if loan and not lost:
        raise DeviceActionError('貸出中の機器は廃棄できません。先に返却してください。')
    if lost and not reason:
        reason = '紛失'
    if loan:
        cursor.execute(
            'UPDATE loans SET returned_on = %s WHERE id = %s', (date.today(), loan['id'])
        )
        record_event(
            cursor, device_id, 'returned', loan_id=loan['id'],
            note='紛失したまま廃棄したため貸出を終了しました（返却はされていません）',
        )
    changes = build_changes(device, {'status': 'available', 'location': None})
    cursor.execute(
        '''
        UPDATE devices
        SET disposed_on = %s, disposal_reason = %s, status = 'available', location = NULL
        WHERE id = %s
        ''',
        (date.today(), reason or None, device_id),
    )
    record_event(cursor, device_id, 'disposed', changes=changes or None, note=reason or None)
    # 差していた SIM は外して未使用に戻す（別の機器で使えるように）
    return sims.detach_from_device(cursor, device_id)
