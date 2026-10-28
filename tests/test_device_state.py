"""機器の状態の導出と、一覧の絞り込み・検索・集計（DB を使わない部分）。

ダッシュボードや一覧の数字は、すべて derive_state が決めた placement / flags から作られる。
"""
from datetime import date

import pytest

from device_lending.devices import (
    count_devices, current_holders, derive_state, filter_devices, search_devices, types_in_use,
)
from device_lending.events import build_changes
from device_lending.exports import _cell, devices_csv

from .factories import device_row


def derived(**overrides):
    return derive_state(device_row(**overrides))


# --- derive_state: 配置 ---

def test_stored_by_default():
    device = derived()
    assert (device['placement'], device['placement_label']) == ('stored', '保管中')
    assert device['flags'] == []


def test_loaned_shows_holder_name():
    device = derived(loan_id=10, holder_code='1001', holder_name='田中太郎')
    assert (device['placement'], device['placement_label']) == ('loaned', '貸出中（田中太郎）')


def test_loaned_to_unknown_employee_shows_code():
    device = derived(loan_id=10, holder_code='9999', holder_missing=1)
    assert device['placement_label'] == '貸出中（社員番号9999）'


def test_installed_shows_location():
    device = derived(status='installed', location='会議室A')
    assert (device['placement'], device['placement_label']) == ('installed', '設置中（会議室A）')


def test_disposed_wins_over_everything():
    device = derived(disposed_on=date(2026, 1, 1), loan_id=10, holder_code='1001',
                     is_lost=1, has_blocking_issue=1)
    assert device['placement'] == 'disposed'
    assert device['flags'] == []  # 廃棄済みには注意フラグを付けない


# --- derive_state: 注意フラグ ---

def test_broken_takes_priority_over_minor():
    assert derived(has_blocking_issue=1, has_minor_issue=1)['flags'] == ['broken']
    assert derived(has_minor_issue=1)['flags'] == ['minor']


def test_lost_is_a_flag_and_keeps_placement():
    device = derived(is_lost=1, loan_id=10, holder_code='1001', holder_name='田中太郎')
    assert device['placement'] == 'loaned'
    assert device['flags'] == ['lost']


@pytest.mark.parametrize('overrides', [{'holder_retired': 1}, {'holder_missing': 1}])
def test_review_when_holder_retired_or_missing(overrides):
    device = derived(loan_id=10, holder_code='1003', **overrides)
    assert device['flags'] == ['review']


def test_review_needs_an_open_loan():
    assert derived(holder_retired=1)['flags'] == []


def test_display_name():
    assert derived(hostname='LT-01')['display_name'] == 'LT-01'
    assert derived(id=7)['display_name'] == 'D-0007'
    assert derived(model_name=None)['model_label'] == '不明な機種'


# --- count_devices ---

def sample_devices():
    return [
        derived(id=1, hostname='LT-TANAKA', loan_id=11, holder_code='1001', holder_name='田中太郎'),
        derived(id=2, hostname='LT-SUZUKI', loan_id=12, holder_code='1002', holder_name='鈴木花子',
                has_minor_issue=1),
        derived(id=3, status='installed', location='会議室A', has_blocking_issue=1),
        derived(id=4, device_type='SmartPhone', manufacturer='Apple', model_name='iPhone 15',
                phone_number='09012345678', is_lost=1),
        derived(id=5, serial_number='SX-A'),
        derived(id=6, hostname='LT-OLD', disposed_on=date(2025, 1, 1)),
        derived(id=7, hostname='LT-SATO', loan_id=13, holder_code='1003', holder_name='佐藤次郎',
                holder_retired=1),
    ]


def test_count_devices_excludes_disposed():
    assert count_devices(sample_devices()) == {
        'total': 6, 'loaned': 3, 'installed': 1, 'stored': 2,
        'broken': 1, 'minor': 1, 'review': 1, 'lost': 1, 'issue': 2,
    }


def test_count_devices_empty():
    assert count_devices([])['total'] == 0


# --- filter_devices ---

def ids(devices):
    return [device['id'] for device in devices]


def test_filter_all_hides_disposed():
    assert ids(filter_devices(sample_devices())) == [1, 2, 3, 4, 5, 7]


def test_filter_by_placement():
    assert ids(filter_devices(sample_devices(), placement='loaned')) == [1, 2, 7]
    assert ids(filter_devices(sample_devices(), placement='disposed')) == [6]


def test_filter_by_flag_and_flag_group():
    assert ids(filter_devices(sample_devices(), flag='lost')) == [4]
    assert ids(filter_devices(sample_devices(), flag='issue')) == [2, 3]
    # すべて（注意あり）: 故障・不具合あり・要確認・紛失中のどれかが付いている機器（廃棄済みは除く）
    assert ids(filter_devices(sample_devices(), flag='any')) == [2, 3, 4, 7]


def test_filter_by_holder_keyword_and_type():
    assert ids(filter_devices(sample_devices(), holder='1002')) == [2]
    assert ids(filter_devices(sample_devices(), keyword='会議室')) == [3]
    assert ids(filter_devices(sample_devices(), device_type='SmartPhone')) == [4]


def test_filters_are_combined_with_and():
    assert ids(filter_devices(sample_devices(), placement='loaned', flag='minor')) == [2]
    assert ids(filter_devices(sample_devices(), placement='stored', flag='minor')) == []


# --- search_devices（ダッシュボードの検索）---

def test_search_by_model_is_case_insensitive():
    assert ids(search_devices(sample_devices(), 'iphone')) == [4]
    # 廃棄済み（6）は出さない
    assert ids(search_devices(sample_devices(), 'DELL')) == [1, 2, 3, 5, 7]


def test_search_does_not_match_holder():
    """借りている人は人物の候補として別に出すので、機器の検索では探さない。"""
    assert ids(search_devices(sample_devices(), '鈴木')) == []


def test_search_by_identifier():
    assert ids(search_devices(sample_devices(), 'lt-tanaka')) == [1]
    # 電話番号はハイフンを付けても付けなくても見つかる
    assert ids(search_devices(sample_devices(), '090-1234')) == [4]


def test_search_by_device_code_needs_d_prefix():
    assert ids(search_devices(sample_devices(), 'D-5')) == [5]
    # 数字だけなら管理番号としては探さない（4 は電話番号に 1234 を含むので当たる）
    assert ids(search_devices(sample_devices(), '1234')) == [4]


def test_search_never_returns_disposed():
    assert search_devices(sample_devices(), 'LT-OLD') == []


# --- 絞り込みの選択肢 ---

def test_types_in_use():
    assert types_in_use(sample_devices()) == ['PC', 'SmartPhone']


def test_current_holders():
    holders = current_holders(sample_devices())
    assert [h['shain_code'] for h in holders] == ['1001', '1002', '1003']
    suzuki = holders[1]
    # 不具合ありの機器を借りている人は、まとめた絞り込み（issue と any）にも出る
    assert suzuki['flags'] == {'minor', 'issue', 'any'}
    assert holders[2]['retired'] == 1


# --- 変更履歴の差分 ---

def test_build_changes_only_includes_changed_values():
    old = {'shain_code': '1001', 'loaned_on': date(2026, 1, 1), 'returned_on': None}
    new = {'shain_code': '1002', 'loaned_on': date(2026, 1, 1), 'returned_on': date(2026, 2, 1)}
    assert build_changes(old, new) == {
        'shain_code': ['1001', '1002'],
        'returned_on': [None, '2026-02-01'],  # 日付は JSON に入れられる文字列にする
    }


# --- CSV ---

@pytest.mark.parametrize('value, expected', [
    ('=SUM(A1)', "'=SUM(A1)"),
    ('+81', "'+81"),
    ('-1', "'-1"),
    ('@x', "'@x"),
    ('LT-01', 'LT-01'),
    (None, ''),
])
def test_csv_cell_escapes_formulas(value, expected):
    assert _cell(value) == expected


def test_devices_csv():
    text = devices_csv([sample_devices()[0]])
    assert text.startswith('﻿')  # Excel で文字化けしないよう BOM を付ける
    lines = text.lstrip('﻿').splitlines()
    assert lines[0] == '機器,管理番号,照合情報,種別,メーカー / 機種,状態,保有者,設置場所'
    assert lines[1] == 'LT-TANAKA,D-0001,LT-TANAKA,PC,Dell Latitude 5440,貸出中,田中太郎（1001）,'
