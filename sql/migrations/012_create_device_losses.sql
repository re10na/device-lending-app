-- Migration 012: 機器の紛失を記録できるようにする。
-- このファイルは sql/migrations/ 配下のため、app DB に適用する。008の適用後に一度だけ実行すること。
-- 紛失は配置ではなく注意フラグ（故障と同じ扱い）。貸出中に紛失しても貸出は続いたままにする。
-- 個人情報が入っている機器もあるため、廃棄とは分けて「いつ・誰の貸出中に・誰が報告し・いつ見つかったか」を残す。

-- 紛失。紛失するたびに1行追加する（同じ機器が2回なくなることもある）。
CREATE TABLE device_losses (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    device_id BIGINT UNSIGNED NOT NULL,
    -- 紛失したときの貸出と借りていた社員。貸出記録は後から修正できるため、社員は別に控えておく
    loan_id BIGINT UNSIGNED NULL COMMENT '紛失時の貸出（貸出中でなければNULL）',
    shain_code VARCHAR(20) NULL COMMENT '紛失時に借りていた社員 master.m_shain.shain_code',
    reported_by ENUM('user', 'admin') NOT NULL COMMENT '利用者画面からの報告か、管理者の登録か',
    reported_on DATE NOT NULL,
    detail VARCHAR(1000) NULL COMMENT '例: 10/12 の帰りの電車で紛失',
    found_on DATE NULL COMMENT 'NULLなら紛失中',
    resolution VARCHAR(1000) NULL COMMENT '例: 駅の忘れ物センターで見つかった / 誤報告',
    -- 紛失中なら1、解除済みならNULL。「1台につき紛失中は1件まで」をDBで保証する（loans の open_flag と同じ）
    open_flag TINYINT UNSIGNED GENERATED ALWAYS AS (IF(found_on IS NULL, 1, NULL)) STORED,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_device_losses_one_open_per_device (device_id, open_flag),
    CONSTRAINT fk_device_losses_device FOREIGN KEY (device_id) REFERENCES devices (id),
    CONSTRAINT fk_device_losses_loan FOREIGN KEY (loan_id) REFERENCES loans (id),
    CONSTRAINT chk_device_losses_found_after_reported
        CHECK (found_on IS NULL OR found_on >= reported_on),
    CONSTRAINT chk_device_losses_holder
        CHECK ((loan_id IS NULL) = (shain_code IS NULL)),
    -- 利用者が報告できるのは自分が借りている機器だけ
    CONSTRAINT chk_device_losses_user_has_loan
        CHECK (reported_by <> 'user' OR loan_id IS NOT NULL),
    CONSTRAINT chk_device_losses_text_not_empty CHECK (detail <> '' AND resolution <> '')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='紛失';

-- 紛失の報告・解除も履歴に残す。故障の issue_id と同じく、どの紛失かを loss_id で持つ
ALTER TABLE device_events
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
        'sim_detached',
        'lost_reported',
        'lost_found'
    ) NOT NULL,
    ADD COLUMN loss_id BIGINT UNSIGNED NULL AFTER sim_id,
    ADD CONSTRAINT fk_device_events_loss FOREIGN KEY (loss_id) REFERENCES device_losses (id);

ALTER TABLE device_events
    ADD CONSTRAINT chk_device_events_loss_id
        CHECK ((event_type IN ('lost_reported', 'lost_found')) = (loss_id IS NOT NULL));
