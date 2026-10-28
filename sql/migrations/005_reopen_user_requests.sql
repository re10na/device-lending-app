-- Migration 005: 管理者が誤って処理した申請を「申請中」に戻せるようにする。
-- このファイルは sql/migrations/ 配下のため、app DB に適用する。一度だけ実行すること。
-- 対応済みを戻すときは、そのとき作った貸出・故障の記録を取り消す（行は消さない論理削除）。

-- 貸出・故障に「取り消した日時」を足す。取り消した行は画面・ルールのどこでも数えない
ALTER TABLE loans
    ADD COLUMN cancelled_at DATETIME NULL COMMENT '誤登録として取り消した日時（NULLなら有効）'
        AFTER returned_on;

-- 取り消した貸出は「貸出中」に数えない（1台につき貸出中は1件まで、の対象から外す）
ALTER TABLE loans
    MODIFY COLUMN open_flag TINYINT UNSIGNED
        GENERATED ALWAYS AS (IF(returned_on IS NULL AND cancelled_at IS NULL, 1, NULL)) STORED;

ALTER TABLE device_issues
    ADD COLUMN cancelled_at DATETIME NULL COMMENT '誤登録として取り消した日時（NULLなら有効）'
        AFTER resolution;

-- 取り消しも履歴に残す
ALTER TABLE device_events
    DROP CHECK chk_device_events_loan_id,
    DROP CHECK chk_device_events_issue_id;

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
        'issue_cancelled'
    ) NOT NULL;

ALTER TABLE device_events
    ADD CONSTRAINT chk_device_events_loan_id
        CHECK ((event_type IN ('loaned', 'returned', 'loan_edited', 'loan_cancelled')) = (loan_id IS NOT NULL)),
    ADD CONSTRAINT chk_device_events_issue_id
        CHECK ((event_type IN ('issue_reported', 'issue_resolved', 'issue_edited', 'issue_cancelled')) = (issue_id IS NOT NULL));

-- 申請を対応済みにしたとき作った貸出・故障を覚えておく（戻すときに取り消す相手）。
-- 005 より前に対応済みにした申請は NULL のままなので、申請中には戻せない
ALTER TABLE user_requests
    ADD COLUMN loan_id BIGINT UNSIGNED NULL COMMENT '借りたい申請を対応済みにしたときの貸出'
        AFTER device_model_id,
    ADD COLUMN issue_id BIGINT UNSIGNED NULL COMMENT '不具合の申請を対応済みにしたときの故障・不具合'
        AFTER loan_id,
    ADD CONSTRAINT fk_user_requests_loan FOREIGN KEY (loan_id) REFERENCES loans (id),
    ADD CONSTRAINT fk_user_requests_issue FOREIGN KEY (issue_id) REFERENCES device_issues (id),
    ADD CONSTRAINT chk_user_requests_loan_id
        CHECK (loan_id IS NULL OR (request_type = 'loan' AND status = 'done')),
    ADD CONSTRAINT chk_user_requests_issue_id
        CHECK (issue_id IS NULL OR (request_type = 'issue' AND status = 'done'));
