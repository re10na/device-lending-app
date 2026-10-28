"""ダッシュボードの検索（1 つの欄で人と機器を探す）と、入力中の候補。"""
import pytest

from device_lending import members
from device_lending.db import transaction

from .factories import RETIRED, SUZUKI, TANAKA, add_device, device_row, lend


def employee(shain_code, name, retired=False):
    return {'shain_code': shain_code, 'name': name, 'is_retired': int(retired)}


EMPLOYEES = [
    employee('1001', '田中 太郎'),
    employee('1002', '鈴木 花子'),
    employee('1003', '田中 次郎', retired=True),
    employee('1004', '田中 三郎'),
]


def codes(people):
    return [person['shain_code'] for person in people]


def test_search_people_by_name_ignores_spaces_and_lists_active_first():
    assert codes(members.search_people(EMPLOYEES, [], '田中')) == ['1001', '1004', '1003']
    assert codes(members.search_people(EMPLOYEES, [], '鈴木花子')) == ['1002']


def test_search_people_by_code_and_loan_count():
    held = [device_row(id=1, loan_id=11, holder_code='1002'), device_row(id=2, loan_id=12, holder_code='1002')]
    people = members.search_people(EMPLOYEES, held, '1002')
    assert codes(people) == ['1002'] and people[0]['loan_count'] == 2


def test_search_people_blank_query():
    assert members.search_people(EMPLOYEES, [], '  ') == []


@pytest.fixture
def sample(client):
    with transaction() as cursor:
        lend(cursor, add_device(cursor, hostname='LT-TANAKA'), TANAKA)
        add_device(cursor, hostname='LT-SPARE')


def test_single_person_redirects_to_member_page(client, sample):
    response = client.get('/admin?q=鈴木')
    assert response.status_code == 302
    assert response.headers['Location'] == f'/members/{SUZUKI}'


def test_single_device_redirects_to_device_page(client, sample):
    response = client.get('/admin?q=lt-spare')
    assert response.status_code == 302
    assert response.headers['Location'].startswith('/devices/')


def test_several_results_show_in_search_column(client, sample):
    response = client.get('/admin?q=LT')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert '「LT」' in body and 'LT-TANAKA</strong>' in body and 'LT-SPARE</strong>' in body


def test_suggestions(client, sample):
    data = client.get('/admin/search?q=田中').get_json()
    assert [p['url'] for p in data['people']] == [f'/members/{TANAKA}']
    assert '貸出 1 台' in data['people'][0]['detail']
    assert data['devices'] == [] and data['more'] == 0

    data = client.get('/admin/search?q=lt').get_json()
    assert sorted(d['title'] for d in data['devices']) == ['LT-SPARE', 'LT-TANAKA']


def test_suggestions_mark_retired(client, sample):
    data = client.get(f'/admin/search?q={RETIRED}').get_json()
    assert '退職済み' in data['people'][0]['detail']


def test_suggestions_blank_query(client):
    assert client.get('/admin/search?q=').get_json() == {'people': [], 'devices': [], 'more': 0}
