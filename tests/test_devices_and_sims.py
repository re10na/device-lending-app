"""機器の登録・照合情報・機種変更・設置・廃棄（devices.py）と SIM（sims.py）。"""
import pytest

from device_lending import devices, losses, sims, user_page
from device_lending.errors import DeviceActionError, RecordNotFound

from .factories import (
    DESK_PHONE, MOBILE_WIFI, PC, SMARTPHONE, UNKNOWN_MODEL,
    add_device, event_types, fetch_one, lend,
)


def get_device(cursor, device_id):
    return fetch_one(cursor, 'SELECT * FROM devices WHERE id = %s', (device_id,))


def get_sim(cursor, sim_id):
    return fetch_one(cursor, 'SELECT * FROM sims WHERE id = %s', (sim_id,))


def add_sim(cursor, iccid='8981100000000000001', phone_number='', extension=''):
    return sims.register_sim(
        cursor, {'iccid': iccid, 'phone_number': phone_number, 'extension': extension}
    )


# --- 登録 ---

def test_register_device(cursor):
    device_id = devices.register_device(cursor, PC, {'hostname': ' LT-01 ', 'serial_number': ''})
    device = get_device(cursor, device_id)
    assert (device['hostname'], device['serial_number'], device['status']) == ('LT-01', None, 'available')
    assert event_types(cursor, device_id) == ['registered']


def test_register_needs_known_model(cursor):
    with pytest.raises(DeviceActionError, match='マスタに見つかりません'):
        devices.register_device(cursor, UNKNOWN_MODEL, {'serial_number': 'S1'})


def test_register_needs_an_identifier(cursor):
    with pytest.raises(DeviceActionError, match='いずれか1つ以上'):
        devices.register_device(cursor, PC, {'hostname': ''})


def test_register_rejects_field_for_other_type(cursor):
    with pytest.raises(DeviceActionError, match='内線番号は使いません'):
        devices.register_device(cursor, PC, {'extension': '201'})


def test_hostname_must_be_unique_among_active_devices(cursor):
    first = add_device(cursor, hostname='LT-01')
    with pytest.raises(DeviceActionError, match='すでに D-'):
        add_device(cursor, hostname='LT-01')
    # 廃棄済みの機器の番号は再利用できる
    devices.dispose_device(cursor, first, '')
    add_device(cursor, hostname='LT-01')


def test_extension_cannot_be_shared_between_device_and_sim(cursor):
    add_sim(cursor, extension='201')
    with pytest.raises(DeviceActionError, match='すでに SIM で使われています'):
        add_device(cursor, DESK_PHONE, extension='201')


def test_register_smartphone_with_sim_only(cursor):
    sim_id = add_sim(cursor)
    device_id = devices.register_device(cursor, SMARTPHONE, {}, sim_id=sim_id)
    assert get_sim(cursor, sim_id)['device_id'] == device_id


def test_register_pc_with_sim_is_rejected(cursor):
    with pytest.raises(DeviceActionError, match='SIM を差せません'):
        devices.register_device(cursor, PC, {'hostname': 'LT-01'}, sim_id=add_sim(cursor))


# --- 照合情報の編集 ---

def test_edit_identifiers(cursor):
    device_id = add_device(cursor, hostname='LT-01')
    devices.edit_identifiers(cursor, device_id, {'hostname': 'LT-02'})
    assert get_device(cursor, device_id)['hostname'] == 'LT-02'
    assert event_types(cursor, device_id)[-1] == 'device_edited'
    with pytest.raises(DeviceActionError, match='変わっていません'):
        devices.edit_identifiers(cursor, device_id, {'hostname': 'LT-02'})


def test_edit_identifiers_cannot_remove_the_last_one(cursor):
    device_id = add_device(cursor, hostname='LT-01')
    with pytest.raises(DeviceActionError, match='いずれか1つ以上'):
        devices.edit_identifiers(cursor, device_id, {'hostname': ''})


def test_edit_identifiers_rejects_duplicates(cursor):
    add_device(cursor, hostname='LT-01')
    device_id = add_device(cursor, hostname='LT-02')
    with pytest.raises(DeviceActionError, match='すでに D-'):
        devices.edit_identifiers(cursor, device_id, {'hostname': 'LT-01'})


# --- 機種変更 ---

def test_change_model_clears_fields_the_new_type_does_not_use(cursor):
    device_id = add_device(cursor, hostname='LT-01', serial_number='S1')
    cleared = devices.change_model(cursor, device_id, SMARTPHONE)
    device = get_device(cursor, device_id)
    assert cleared == ['ホスト名']
    assert (device['device_model_id'], device['hostname'], device['serial_number']) == (SMARTPHONE, None, 'S1')


def test_change_model_to_same_model(cursor):
    with pytest.raises(DeviceActionError, match='変わっていません'):
        devices.change_model(cursor, add_device(cursor, PC), PC)


def test_change_model_with_sim_to_non_sim_type(cursor):
    sim_id = add_sim(cursor)
    device_id = devices.register_device(cursor, SMARTPHONE, {}, sim_id=sim_id)
    with pytest.raises(DeviceActionError, match='先に SIM を外して'):
        devices.change_model(cursor, device_id, PC)


# --- 設置 ---

def test_install_and_uninstall(cursor):
    device_id = add_device(cursor)
    devices.install_device(cursor, device_id, ' 会議室A ')
    assert devices.fetch_device(cursor, device_id)['placement_label'] == '設置中（会議室A）'
    devices.install_device(cursor, device_id, '会議室B')  # 場所の変更
    devices.uninstall_device(cursor, device_id)
    device = get_device(cursor, device_id)
    assert (device['status'], device['location']) == ('available', None)
    with pytest.raises(DeviceActionError, match='設置中ではありません'):
        devices.uninstall_device(cursor, device_id)


def test_install_rules(cursor):
    with pytest.raises(DeviceActionError, match='設置場所を入力'):
        devices.install_device(cursor, add_device(cursor), '  ')
    loaned = add_device(cursor)
    lend(cursor, loaned)
    with pytest.raises(DeviceActionError, match='貸出中の機器は設置できません'):
        devices.install_device(cursor, loaned, '受付')
    lost = add_device(cursor)
    losses.report_loss(cursor, lost, '')
    with pytest.raises(DeviceActionError, match='紛失中の機器は設置できません'):
        devices.install_device(cursor, lost, '受付')


# --- 廃棄 ---

def test_dispose_installed_device(cursor):
    device_id = add_device(cursor)
    devices.install_device(cursor, device_id, '受付')
    assert devices.dispose_device(cursor, device_id, '老朽化') is None
    device = get_device(cursor, device_id)
    assert device['disposed_on'] is not None
    assert (device['disposal_reason'], device['status'], device['location']) == ('老朽化', 'available', None)
    assert devices.fetch_device(cursor, device_id)['placement'] == 'disposed'
    with pytest.raises(DeviceActionError, match='すでに廃棄済み'):
        devices.dispose_device(cursor, device_id, '')


def test_cannot_dispose_loaned_device(cursor):
    device_id = add_device(cursor)
    lend(cursor, device_id)
    with pytest.raises(DeviceActionError, match='貸出中の機器は廃棄できません'):
        devices.dispose_device(cursor, device_id, '')


def test_dispose_lost_loaned_device_ends_the_loan(cursor):
    device_id = add_device(cursor)
    lend(cursor, device_id)
    losses.report_loss(cursor, device_id, '')
    devices.dispose_device(cursor, device_id, '')
    assert devices.find_open_loan(cursor, device_id) is None
    assert get_device(cursor, device_id)['disposal_reason'] == '紛失'
    assert devices.find_open_loss(cursor, device_id) is not None  # 紛失の記録は残す


def test_dispose_detaches_sim(cursor):
    sim_id = add_sim(cursor)
    device_id = devices.register_device(cursor, SMARTPHONE, {}, sim_id=sim_id)
    assert devices.dispose_device(cursor, device_id, '')['id'] == sim_id
    assert get_sim(cursor, sim_id)['device_id'] is None


def test_operations_on_missing_device(cursor):
    for operation in (
        lambda: devices.install_device(cursor, 999999, '受付'),
        lambda: devices.dispose_device(cursor, 999999, ''),
        lambda: devices.edit_identifiers(cursor, 999999, {}),
    ):
        with pytest.raises(RecordNotFound):
            operation()


# --- SIM ---

def test_register_sim_normalizes_numbers(cursor):
    sim_id = add_sim(cursor, iccid='', phone_number='090-1234-5678', extension='301')
    sim = get_sim(cursor, sim_id)
    assert (sim['iccid'], sim['phone_number'], sim['extension']) == (None, '09012345678', '301')


def test_register_sim_needs_iccid_or_phone(cursor):
    with pytest.raises(DeviceActionError, match='どちらかを入力'):
        add_sim(cursor, iccid='', phone_number='', extension='301')


def test_register_sim_rejects_duplicates(cursor):
    add_sim(cursor, phone_number='09012345678')
    with pytest.raises(DeviceActionError, match='すでに別の SIM'):
        add_sim(cursor, iccid='8981100000000000002', phone_number='090-1234-5678')


def test_sim_extension_cannot_clash_with_desk_phone(cursor):
    add_device(cursor, DESK_PHONE, extension='201')
    with pytest.raises(DeviceActionError, match='すでに D-'):
        add_sim(cursor, extension='201')


def test_attach_moves_sim_and_replaces_existing(cursor):
    phone = add_device(cursor, SMARTPHONE)
    wifi = add_device(cursor, MOBILE_WIFI)
    first = add_sim(cursor, iccid='8981100000000000001')
    second = add_sim(cursor, iccid='8981100000000000002')

    assert sims.attach_sim(cursor, first, phone) == ('SIM …0001', None)
    # 別の機器へ移す
    sims.attach_sim(cursor, first, wifi)
    assert get_sim(cursor, first)['device_id'] == wifi
    # 差している SIM を差し替えると、元の SIM は外れる
    assert sims.attach_sim(cursor, second, wifi) == ('SIM …0002', 'SIM …0001')
    assert get_sim(cursor, first)['device_id'] is None
    assert [s['id'] for s in sims.fetch_unassigned_sims(cursor)] == [first]


def test_attach_rules(cursor):
    sim_id = add_sim(cursor)
    with pytest.raises(DeviceActionError, match='SIM を差せません'):
        sims.attach_sim(cursor, sim_id, add_device(cursor, PC))
    disposed = add_device(cursor, SMARTPHONE)
    devices.dispose_device(cursor, disposed, '')
    with pytest.raises(DeviceActionError, match='廃棄済み'):
        sims.attach_sim(cursor, sim_id, disposed)
    phone = add_device(cursor, SMARTPHONE)
    sims.attach_sim(cursor, sim_id, phone)
    with pytest.raises(DeviceActionError, match='すでにこの機器'):
        sims.attach_sim(cursor, sim_id, phone)


def test_detach_and_edit_sim(cursor):
    sim_id = add_sim(cursor)
    phone = add_device(cursor, SMARTPHONE)
    sims.attach_sim(cursor, sim_id, phone)
    sims.edit_sim(cursor, sim_id, {'iccid': '8981100000000000001', 'phone_number': '08011112222'})
    assert get_sim(cursor, sim_id)['phone_number'] == '08011112222'
    sims.detach_sim(cursor, sim_id)
    assert get_sim(cursor, sim_id)['device_id'] is None
    with pytest.raises(DeviceActionError, match='どの機器にも差していません'):
        sims.detach_sim(cursor, sim_id)
    assert event_types(cursor, phone)[-3:] == ['sim_attached', 'sim_edited', 'sim_detached']


def test_fetch_device_includes_sim_numbers(cursor):
    sim_id = add_sim(cursor, phone_number='09012345678')
    device_id = devices.register_device(cursor, SMARTPHONE, {}, sim_id=sim_id)
    device = devices.fetch_device(cursor, device_id)
    assert device['display_name'] == '090-1234-5678'
    assert device['uses_sim'] is True


# --- 2 か所にある「貸し出せる」のルールが一致しているか ---

def test_available_count_matches_derived_state(cursor):
    """利用者画面は SQL（AVAILABLE_CONDITIONS）、管理者画面は Python（derive_state）で状態を決めている。
    どちらかだけ直すとずれるので、いろいろな状態の機器で数が一致することを確かめる。
    """
    from device_lending import issues, loans

    add_device(cursor)                                   # 保管中 → 貸せる
    minor = add_device(cursor)                           # 軽い不具合 → 貸せる
    issues.report_issue(cursor, minor, 'キーが固い', False)
    broken = add_device(cursor)                          # 貸出不可の故障
    issues.report_issue(cursor, broken, '起動しない', True)
    lend(cursor, add_device(cursor))                     # 貸出中
    installed = add_device(cursor)                       # 設置中
    devices.install_device(cursor, installed, '受付')
    lost = add_device(cursor)                            # 紛失中
    losses.report_loss(cursor, lost, '')
    disposed = add_device(cursor)                        # 廃棄済み
    devices.dispose_device(cursor, disposed, '')
    returned = add_device(cursor)                        # 返却済み → 貸せる
    loans.return_loan(cursor, lend(cursor, returned))
    cancelled = add_device(cursor)                       # 貸出を取り消した → 貸せる
    loans.cancel_loan(cursor, lend(cursor, cancelled))

    derived_available = [
        device for device in devices.fetch_devices(cursor)
        if device['placement'] == 'stored' and not {'broken', 'lost'} & set(device['flags'])
    ]
    assert len(derived_available) == 4
    assert user_page.count_available_devices(cursor) == 4
    assert sum(row['available_count'] for row in user_page.fetch_available_models(cursor)) == 4
