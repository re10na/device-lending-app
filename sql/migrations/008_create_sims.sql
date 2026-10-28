-- Migration 008: SIM を機器から独立させ、SIM ごとに外線・内線を持たせる。
-- このファイルは sql/migrations/ 配下のため、app DB に適用する。007の適用後に一度だけ実行すること。
-- これまで機器の照合情報だった SIM番号・電話番号（外線）と、SIM を使う機器の内線は SIM に移す。
-- SIM は機器に差し替えられる（1台に1枚まで）。固定電話・VoIP の内線は SIM が無いので機器に残す。

-- SIM。機器に差していなければ「未使用」。
CREATE TABLE sims (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    iccid VARCHAR(22) NULL COMMENT 'SIMカードのICCID（数字のみ）',
    phone_number VARCHAR(20) NULL COMMENT '外線（数字のみ）',
    extension VARCHAR(20) NULL COMMENT '内線',
    device_id BIGINT UNSIGNED NULL COMMENT '差している機器（NULLなら未使用）',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    -- 1台の機器に差せる SIM は1枚まで（NULL = 未使用 は何枚でもよい）
    UNIQUE KEY uq_sims_device (device_id),
    UNIQUE KEY uq_sims_iccid (iccid),
    UNIQUE KEY uq_sims_phone_number (phone_number),
    UNIQUE KEY uq_sims_extension (extension),
    CONSTRAINT fk_sims_device FOREIGN KEY (device_id) REFERENCES devices (id),
    -- 現物と照合できるよう、SIM番号か外線のどちらかは必ず持つ
    CONSTRAINT chk_sims_has_number CHECK (iccid IS NOT NULL OR phone_number IS NOT NULL),
    -- 空文字は「未入力」と区別がつかなくなるため禁止（未入力は NULL）
    CONSTRAINT chk_sims_not_empty CHECK (iccid <> '' AND phone_number <> '' AND extension <> ''),
    CONSTRAINT chk_sims_digits_only CHECK (iccid REGEXP '^[0-9]+$' AND phone_number REGEXP '^[0-9]+$')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='SIM';

-- SIM の操作も履歴に残す。登録・変更は機器が無くても記録できるよう device_id を NULL 可にする
ALTER TABLE device_events
    DROP CHECK chk_device_events_loan_id,
    DROP CHECK chk_device_events_issue_id;

ALTER TABLE device_events
    MODIFY COLUMN device_id BIGINT UNSIGNED NULL,
    MODIFY COLUMN event_type ENUM(
        'registered',
        'device_edited',
        'status_changed',
        'disposed',
        'loaned',
        'returned',
        'loan_edited',
        'loan_cancelled',
        'issue_reported',
        'issue_resolved',
        'issue_edited',
        'issue_cancelled',
        'sim_registered',
        'sim_edited',
        'sim_attached',
        'sim_detached'
    ) NOT NULL,
    ADD COLUMN sim_id BIGINT UNSIGNED NULL AFTER issue_id,
    ADD CONSTRAINT fk_device_events_sim FOREIGN KEY (sim_id) REFERENCES sims (id);

ALTER TABLE device_events
    ADD CONSTRAINT chk_device_events_loan_id
        CHECK ((event_type IN ('loaned', 'returned', 'loan_edited', 'loan_cancelled')) = (loan_id IS NOT NULL)),
    ADD CONSTRAINT chk_device_events_issue_id
        CHECK ((event_type IN ('issue_reported', 'issue_resolved', 'issue_edited', 'issue_cancelled')) = (issue_id IS NOT NULL)),
    ADD CONSTRAINT chk_device_events_sim_id
        CHECK ((event_type IN ('sim_registered', 'sim_edited', 'sim_attached', 'sim_detached')) = (sim_id IS NOT NULL)),
    -- 機器が無くてよいのは SIM だけの操作（差す・外すは必ず機器がある）
    ADD CONSTRAINT chk_device_events_device_id
        CHECK (device_id IS NOT NULL OR event_type IN ('sim_registered', 'sim_edited'));

-- 機器の SIM番号・電話番号を SIM に移す。SIM を使う機器（番号がある機器）の内線も SIM に移す。
-- 未廃棄の機器の番号はもともと重複していないので、そのまま差した状態の SIM にする
INSERT INTO sims (iccid, phone_number, extension, device_id)
SELECT sim_iccid, phone_number, extension, id
FROM devices
WHERE (sim_iccid IS NOT NULL OR phone_number IS NOT NULL) AND disposed_on IS NULL
ORDER BY id;

-- 廃棄済みの機器の SIM は、廃棄すると SIM を外すルールに合わせて「未使用」として残す。
-- ただし番号が今使っている SIM や固定電話の内線と重なるものは移さない（最後に一覧で表示する）。
-- 廃棄済みの機器どうしで番号が重なるときは、最近廃棄した方を残す（IGNORE で後の重複を飛ばす）
INSERT IGNORE INTO sims (iccid, phone_number, extension)
SELECT d.sim_iccid, d.phone_number, d.extension
FROM devices AS d
WHERE (d.sim_iccid IS NOT NULL OR d.phone_number IS NOT NULL) AND d.disposed_on IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM sims AS sm
      WHERE sm.iccid = d.sim_iccid OR sm.phone_number = d.phone_number
         OR sm.extension = d.extension
  )
  AND NOT EXISTS (
      SELECT 1 FROM devices AS active
      WHERE active.disposed_on IS NULL AND active.extension = d.extension
        AND active.sim_iccid IS NULL AND active.phone_number IS NULL
  )
ORDER BY d.disposed_on DESC, d.id DESC;

-- 番号が重なったため SIM に移さなかった、廃棄済みの機器（0 件なら全部移せている）
SELECT d.id AS device_id, d.sim_iccid, d.phone_number, d.extension, d.disposed_on
FROM devices AS d
WHERE (d.sim_iccid IS NOT NULL OR d.phone_number IS NOT NULL) AND d.disposed_on IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM sims AS sm
      WHERE sm.iccid <=> d.sim_iccid AND sm.phone_number <=> d.phone_number
  );

INSERT INTO device_events (device_id, event_type, sim_id, note)
SELECT device_id, 'sim_attached', id, '機器の照合情報から移行'
FROM sims
WHERE device_id IS NOT NULL
ORDER BY id;

UPDATE devices SET extension = NULL
WHERE sim_iccid IS NOT NULL OR phone_number IS NOT NULL;

-- 機器から SIM番号・電話番号の列を外す（使っている CHECK を先に外す）
ALTER TABLE devices
    DROP CHECK chk_devices_identifiers_not_empty,
    DROP CHECK chk_devices_numbers_digits_only;

ALTER TABLE devices
    DROP COLUMN active_phone_number,
    DROP COLUMN active_sim_iccid,
    DROP COLUMN phone_number,
    DROP COLUMN sim_iccid,
    ADD CONSTRAINT chk_devices_identifiers_not_empty
        CHECK (hostname <> '' AND extension <> '' AND serial_number <> '');

-- 移した SIM の数（確認用）
SELECT
    SUM(device_id IS NOT NULL) AS attached_sims,
    SUM(device_id IS NULL) AS unassigned_sims
FROM sims;
