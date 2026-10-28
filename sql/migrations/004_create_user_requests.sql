-- Migration 004: 利用者からの申請（不具合の申請・借りたい機器の申請）のテーブルを作る。
-- このファイルは sql/migrations/ 配下のため、app DB に適用する。一度だけ実行すること。
-- 申請はあくまで「お願い」で、device_issues や loans には管理者が確認してから記録する。

CREATE TABLE user_requests (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    -- issue: 借りている機器の不具合 / loan: 借りたい機種
    request_type ENUM('issue', 'loan') NOT NULL,
    shain_code VARCHAR(20) NOT NULL COMMENT 'master.m_shain.shain_code（申請した社員）',
    device_id BIGINT UNSIGNED NULL COMMENT '不具合の申請のときだけ入る',
    device_model_id INT UNSIGNED NULL COMMENT '借りたい申請のときだけ入る（master.m_device_model.id）',
    detail VARCHAR(1000) NULL COMMENT '不具合の内容（必須）/ 借りたい理由（任意）',
    -- pending: 申請中 / done: 対応済み / rejected: 却下 / cancelled: 利用者が取り消し
    status ENUM('pending', 'done', 'rejected', 'cancelled') NOT NULL DEFAULT 'pending',
    admin_comment VARCHAR(1000) NULL COMMENT '対応済み・却下のときの管理者コメント（利用者に見せる）',
    requested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at DATETIME NULL COMMENT '申請中でなくなった日時',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_user_requests_shain_code (shain_code, requested_at),
    KEY ix_user_requests_status (status, requested_at),
    CONSTRAINT fk_user_requests_device FOREIGN KEY (device_id) REFERENCES devices (id),
    -- 不具合の申請は機器、借りたい申請は機種を必ず持ち、もう一方は持たない
    CONSTRAINT chk_user_requests_issue_target
        CHECK ((request_type = 'issue') = (device_id IS NOT NULL)),
    CONSTRAINT chk_user_requests_loan_target
        CHECK ((request_type = 'loan') = (device_model_id IS NOT NULL)),
    CONSTRAINT chk_user_requests_issue_detail
        CHECK (request_type <> 'issue' OR detail IS NOT NULL),
    -- 空文字は「未入力」と区別がつかなくなるため禁止（未入力は NULL）
    CONSTRAINT chk_user_requests_text_not_empty CHECK (detail <> '' AND admin_comment <> ''),
    -- 申請中なら終了日時なし、それ以外なら終了日時あり（両方向）
    CONSTRAINT chk_user_requests_closed_at
        CHECK ((status = 'pending') = (closed_at IS NULL)),
    -- 管理者コメントは管理者が対応・却下したときだけ
    CONSTRAINT chk_user_requests_admin_comment
        CHECK (admin_comment IS NULL OR status IN ('done', 'rejected'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='利用者からの申請';
