"""利用者に表示するメッセージを持つ操作エラー。"""


class DeviceActionError(Exception):
    """ルール違反など、利用者にそのまま伝えるエラー。"""


class RecordNotFound(DeviceActionError):
    """対象の機器・貸出・故障が存在しない（404 にする）。"""
