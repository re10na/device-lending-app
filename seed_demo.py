"""デモ用の架空データを入れる（機器が 1 台もないときだけ）。

社員・機種は sql/seed/master.sql の架空のマスタを使う。アプリの関数を通して登録するので、
変更履歴も画面から操作したときと同じ形で残る。貸出日だけは、それらしく見えるよう後から過去にずらす。
"""
from datetime import date, timedelta

from device_lending import devices, issues, loans, losses, sims, user_requests
from device_lending.db import transaction

# 機種（master.m_device_model.id）
DELL, HP, LENOVO, IPHONE, PIXEL, WIFI, DESK_PHONE, VOIP = range(1, 9)


def lend(cursor, device_id, shain_code, days_ago):
    loans.loan_device(cursor, device_id, shain_code)
    loan_id = devices.find_open_loan(cursor, device_id)['id']
    cursor.execute(
        'UPDATE loans SET loaned_on = %s WHERE id = %s',
        (date.today() - timedelta(days=days_ago), loan_id),
    )
    return loan_id


def seed(cursor):
    pcs = [
        devices.register_device(cursor, model, {'hostname': f'LT-{n:04d}', 'serial_number': f'DEMO{n:05d}'})
        for n, model in enumerate([DELL, DELL, DELL, HP, HP, LENOVO, LENOVO, DELL, HP, LENOVO], start=1)
    ]
    lend(cursor, pcs[0], '1001', 400)
    lend(cursor, pcs[1], '1002', 210)
    lend(cursor, pcs[2], '1003', 95)
    lend(cursor, pcs[3], '1004', 30)
    lend(cursor, pcs[4], '1011', 700)
    lend(cursor, pcs[5], '1005', 12)
    devices.install_device(cursor, pcs[6], '会議室A（Web会議用）')
    issues.report_issue(cursor, pcs[2], 'キーボードの一部のキーが反応しにくい', blocks_loan=False)
    issues.report_issue(cursor, pcs[8], '電源が入らない', blocks_loan=True)
    losses.report_loss(cursor, pcs[5], '出張先からの帰りの電車で紛失')
    devices.dispose_device(cursor, pcs[9], '液晶の破損（修理不可）')

    sim_ids = [
        sims.register_sim(cursor, {'iccid': f'898100000000000000{n}', 'phone_number': f'090-0000-000{n}', 'extension': f'30{n}'})
        for n in range(1, 5)
    ]
    phone1 = devices.register_device(cursor, IPHONE, {'serial_number': 'DEMOSP001'}, sim_id=sim_ids[0])
    phone2 = devices.register_device(cursor, PIXEL, {'serial_number': 'DEMOSP002'}, sim_id=sim_ids[1])
    devices.register_device(cursor, IPHONE, {'serial_number': 'DEMOSP003'}, sim_id=sim_ids[2])
    devices.register_device(cursor, WIFI, {'serial_number': 'DEMOWF001'})
    lend(cursor, phone1, '1001', 380)
    lend(cursor, phone2, '1006', 60)

    for extension, location in (('201', '受付'), ('202', '総務')):
        device_id = devices.register_device(cursor, DESK_PHONE, {'extension': extension})
        devices.install_device(cursor, device_id, location)
    devices.register_device(cursor, VOIP, {'extension': '401'})

    user_requests.submit_issue_request(cursor, '1002', pcs[1], 'バッテリーが 1 時間ほどしか持たない')
    user_requests.submit_loan_request(cursor, '1007', PIXEL, '外回りの連絡用')
    user_requests.submit_loan_request(cursor, '1008', DELL, '')


def main():
    with transaction() as cursor:
        if devices.count_active_devices(cursor):
            print('seed_demo: 機器が登録済みのため何もしません')
            return
        seed(cursor)
    print('seed_demo: デモ用のデータを登録しました')


if __name__ == '__main__':
    main()
