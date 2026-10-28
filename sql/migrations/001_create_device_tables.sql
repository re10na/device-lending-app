-- Migration 001: 機器貸出管理のテーブルを新規作成する。
-- このファイルは sql/migrations/ 配下のため、app DB に適用する。一度だけ実行すること。
-- 社員は master.m_shain、機種は master.m_device_model を参照する（app には複製しない）。
-- app には master の読み取り権限しかないため、master への外部キーは張らずアプリ側で存在を確認する。

-- 機器（実物の1台ずつ）。廃棄しても行は消さない（論理削除）。
CREATE TABLE devices (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    device_model_id INT UNSIGNED NOT NULL COMMENT 'master.m_device_model.id',
    status ENUM('available', 'installed') NOT NULL DEFAULT 'available',
    location VARCHAR(120) NULL COMMENT '設置中のときだけ入る',
    disposed_on DATE NULL COMMENT 'NULLでなければ廃棄済み',
    disposal_reason VARCHAR(255) NULL,
    -- 現物との照合情報。管理番号シールを貼れないため、機器に元からある番号で照合する。
    -- 種別ごとに使う項目が違う（PC: hostname / スマホ・Wi-Fi: phone_number + sim_iccid /
    -- 固定電話・VoIP: extension）。種別は master 側にあるため、どれを必須にするかはアプリで判断する
    hostname VARCHAR(63) NULL,
    phone_number VARCHAR(20) NULL COMMENT '数字のみで保存',
    sim_iccid VARCHAR(22) NULL COMMENT 'SIMカードのICCID（数字のみ）',
    extension VARCHAR(20) NULL COMMENT '内線番号',
    serial_number VARCHAR(120) NULL,
    -- 廃棄済みの機器の番号は再利用できるよう、未廃棄の機器だけを重複禁止にする。
    -- 廃棄済みなら NULL になる生成列に UNIQUE を付ける（loans.open_flag と同じ考え方）
    active_hostname VARCHAR(63) GENERATED ALWAYS AS (IF(disposed_on IS NULL, hostname, NULL)) STORED,
    active_phone_number VARCHAR(20) GENERATED ALWAYS AS (IF(disposed_on IS NULL, phone_number, NULL)) STORED,
    active_sim_iccid VARCHAR(22) GENERATED ALWAYS AS (IF(disposed_on IS NULL, sim_iccid, NULL)) STORED,
    active_extension VARCHAR(20) GENERATED ALWAYS AS (IF(disposed_on IS NULL, extension, NULL)) STORED,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_devices_device_model_id (device_model_id),
    UNIQUE KEY uq_devices_active_hostname (active_hostname),
    UNIQUE KEY uq_devices_active_phone_number (active_phone_number),
    UNIQUE KEY uq_devices_active_sim_iccid (active_sim_iccid),
    UNIQUE KEY uq_devices_active_extension (active_extension),
    KEY ix_devices_serial_number (serial_number),
    -- 空文字は「未入力」と区別がつかなくなるため禁止（未入力は NULL）
    CONSTRAINT chk_devices_identifiers_not_empty CHECK (
        hostname <> '' AND phone_number <> '' AND sim_iccid <> ''
        AND extension <> '' AND serial_number <> ''
    ),
    CONSTRAINT chk_devices_numbers_digits_only CHECK (
        phone_number REGEXP '^[0-9]+$' AND sim_iccid REGEXP '^[0-9]+$'
    ),
    -- 設置中なら場所あり、設置中でなければ場所なし（両方向）
    CONSTRAINT chk_devices_location_when_installed
        CHECK ((status = 'installed') = (location IS NOT NULL)),
    CONSTRAINT chk_devices_location_not_empty CHECK (location <> ''),
    CONSTRAINT chk_devices_disposal_reason_needs_date
        CHECK (disposed_on IS NOT NULL OR disposal_reason IS NULL)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='機器';

-- 貸出。貸すたびに1行追加し、返却しても消さない。
CREATE TABLE loans (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    device_id BIGINT UNSIGNED NOT NULL,
    shain_code VARCHAR(20) NOT NULL COMMENT 'master.m_shain.shain_code',
    loaned_on DATE NOT NULL,
    returned_on DATE NULL COMMENT 'NULLなら貸出中',
    -- 貸出中なら1、返却済みならNULL。UNIQUEはNULL同士の重複を許すため、
    -- 「返却済みは何件でも、貸出中は1台につき1件まで」をDBで保証できる
    open_flag TINYINT UNSIGNED GENERATED ALWAYS AS (IF(returned_on IS NULL, 1, NULL)) STORED,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_loans_one_open_per_device (device_id, open_flag),
    KEY ix_loans_shain_code (shain_code),
    CONSTRAINT fk_loans_device FOREIGN KEY (device_id) REFERENCES devices (id),
    CONSTRAINT chk_loans_returned_after_loaned
        CHECK (returned_on IS NULL OR returned_on >= loaned_on)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='貸出';

-- 故障・不具合。発生するたびに1行追加する。
CREATE TABLE device_issues (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    device_id BIGINT UNSIGNED NOT NULL,
    reported_on DATE NOT NULL,
    detail VARCHAR(1000) NOT NULL COMMENT '例: キーボードの一部のキーが反応しない',
    -- 登録時のチェック忘れで貸してしまわないよう、既定は「貸出不可」
    blocks_loan BOOLEAN NOT NULL DEFAULT TRUE,
    resolved_on DATE NULL COMMENT 'NULLなら未解決',
    resolution VARCHAR(1000) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT fk_device_issues_device FOREIGN KEY (device_id) REFERENCES devices (id),
    CONSTRAINT chk_device_issues_resolved_after_reported
        CHECK (resolved_on IS NULL OR resolved_on >= reported_on)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='故障・不具合';

-- 変更履歴。追記のみで、更新・削除はしない。メイン画面の「最新の変更」に使う。
CREATE TABLE device_events (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    device_id BIGINT UNSIGNED NOT NULL,
    event_type ENUM(
        'registered',
        'device_edited',
        'status_changed',
        'disposed',
        'loaned',
        'returned',
        'loan_edited',
        'issue_reported',
        'issue_resolved',
        'issue_edited'
    ) NOT NULL,
    loan_id BIGINT UNSIGNED NULL,
    issue_id BIGINT UNSIGNED NULL,
    -- 編集前の値を残すため、変わった項目を {"列名": [変更前, 変更後]} で記録する
    changes JSON NULL COMMENT '例: {"shain_code": ["1002", "1012"]}',
    note VARCHAR(255) NULL,
    occurred_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_device_events_occurred_at (occurred_at),
    -- CHECKで使う列には ON DELETE CASCADE / SET NULL を付けられない（MySQLの制限）
    CONSTRAINT fk_device_events_device FOREIGN KEY (device_id) REFERENCES devices (id),
    CONSTRAINT fk_device_events_loan FOREIGN KEY (loan_id) REFERENCES loans (id),
    CONSTRAINT fk_device_events_issue FOREIGN KEY (issue_id) REFERENCES device_issues (id),
    -- 貸出系のイベントは必ずどの貸出かを持ち、それ以外は持たない（故障系も同じ）
    CONSTRAINT chk_device_events_loan_id
        CHECK ((event_type IN ('loaned', 'returned', 'loan_edited')) = (loan_id IS NOT NULL)),
    CONSTRAINT chk_device_events_issue_id
        CHECK ((event_type IN ('issue_reported', 'issue_resolved', 'issue_edited')) = (issue_id IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='変更履歴';
