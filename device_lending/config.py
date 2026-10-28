"""設定値と定数。"""
import os
import secrets

# セッション（ログイン状態）の署名に使う鍵。設定しないと起動のたびに変わり、再起動でログインが切れる
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)

# 模擬ログイン（device_lending/auth.py）。本物のログインは組み込み先のシステムが持つので、
# ここではその代わりに「誰としてログインしたか」を作るだけ。共有の docker-compose.yml には何も足さない。
# 組み込むときは MOCK_LOGIN を 0 にして、組み込み先のログインからセッションに役割を入れてもらう
MOCK_LOGIN = os.environ.get('MOCK_LOGIN', '1') != '0'
# 模擬の管理者アカウント（1 名）。模擬なのでパスワードもそのまま置く（本物の守りにはしない）
MOCK_ADMIN_USERNAME = os.environ.get('MOCK_ADMIN_USERNAME', 'admin')
MOCK_ADMIN_PASSWORD = os.environ.get('MOCK_ADMIN_PASSWORD', 'admin')

# docker-compose.yml の environment で設定した値を読み込む
DB_HOST = os.environ.get('DB_HOST', 'db')
DB_PORT = int(os.environ.get('DB_PORT', '3306'))
DB_USER = os.environ.get('DB_USER', 'app')
DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
DB_NAME = os.environ.get('DB_NAME', 'app')

# 社員・機種マスタのあるスキーマ（読み取り専用。SQL に埋め込む信頼できる定数）
MASTER_DB = os.environ.get('MASTER_DB', 'master')

PLACEMENTS = {
    'loaned': '貸出中',
    'installed': '設置中',
    'stored': '保管中',
    'disposed': '廃棄済み',
}

FLAGS = {
    'broken': '🔴 故障',
    'minor': '⚠ 不具合あり',
    'review': '❗ 要確認',
    'lost': '🚨 紛失中',
}

# 絞り込みだけで使う、注意フラグをまとめた選択肢（キー -> (表示名, 含めるフラグ)）
FLAG_GROUPS = {
    'any': ('すべて（注意あり）', tuple(FLAGS)),
    # 機器一覧の選択肢には出さないが、リンク（「対応が必要なこと」の故障・不具合）からの絞り込みに使う
    'issue': ('故障・不具合（両方）', ('broken', 'minor')),
}
# 機器一覧の「注意」の選択肢に出すまとめ（「指定なし」のすぐ下に出す）
FILTER_FLAG_GROUPS = ('any',)

# 利用者からの申請（user_requests）の種類と状態
REQUEST_TYPES = {
    'issue': '不具合',
    'loan': '借りたい',
}

REQUEST_STATUSES = {
    'pending': '申請中',
    'confirmed': '確認済み',
    'done': '対応済み',
    'rejected': '却下',
    'cancelled': '取り消し',
}

SEARCH_MAX_LENGTH = 100
LOCATION_MAX_LENGTH = 120
DISPOSAL_REASON_MAX_LENGTH = 255
ISSUE_TEXT_MAX_LENGTH = 1000
RECENT_EVENT_LIMIT = 5
# ダッシュボードの「もうすぐ退職する人の貸出」に出す範囲（退職日の何日前から出すか）
RETIREMENT_NOTICE_DAYS = 30
# ダッシュボードの「対応待ちの申請」に並べる件数（古い順）
WAITING_REQUEST_PREVIEW = 3
# 「すべての変更履歴」の 1 ページの件数
EVENT_PAGE_SIZE = 100

# ダッシュボードの円グラフで種別を並べる順（この順で色も固定する。ここにない種別は灰色で最後）
DEVICE_TYPE_ORDER = ('PC', 'SmartPhone', 'MobileWifi', 'Phone', 'VoIP')
# 円グラフの丸に書く短い名前（ここにない種別はそのまま出す）
DEVICE_TYPE_SHORT = {
    'PC': 'PC',
    'SmartPhone': 'スマホ',
    'MobileWifi': 'Wi-Fi',
    'Phone': '電話',
    'VoIP': 'IP電話',
}

# --- 現物との照合情報 ---
# 管理番号シールを貼れないため、機器に元からある番号で現物と照合する。
# 種別（master.m_device_model.device_type）ごとに機器そのものが持つ照合情報。
# ここにない種別は全項目を表示する。スマホ・モバイル Wi-Fi の番号は SIM が持つ（SIM_DEVICE_TYPES）
IDENTIFIER_FIELDS_BY_TYPE = {
    'PC': ('hostname',),
    'SmartPhone': (),
    'MobileWifi': (),
    'Phone': ('extension',),
    'VoIP': ('extension',),
}

# 項目名 -> (表示名, 最大文字数, 入力例)。並び順がそのまま画面の並び順になる
IDENTIFIER_FIELDS = {
    'hostname': ('ホスト名', 63, '例: LT-TANAKA01'),
    'extension': ('内線番号', 20, '例: 201'),
    'serial_number': ('シリアル番号', 120, '例: PF3ABCDE'),
}
# 種別に関係なく使える項目（任意）
ALWAYS_IDENTIFIER_FIELDS = ('serial_number',)
# 未廃棄の機器の間で重複を禁止する項目（DB の uq_devices_active_* と対応）
UNIQUE_IDENTIFIER_FIELDS = ('hostname', 'extension')

# SIM を差して使う種別（IDENTIFIER_FIELDS_BY_TYPE にない種別にも差せる）
SIM_DEVICE_TYPES = ('SmartPhone', 'MobileWifi')
# SIM の項目名 -> (表示名, 最大文字数, 入力例)
SIM_FIELDS = {
    'iccid': ('SIM番号（ICCID）', 22, '例: 8981100000000000001'),
    'phone_number': ('外線（電話番号）', 20, '例: 090-1234-5678'),
    'extension': ('内線番号', 20, '例: 201'),
}
