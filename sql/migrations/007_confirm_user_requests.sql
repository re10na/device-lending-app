-- Migration 007: 申請に「確認済み」を足し、管理者コメントをなくす。
-- このファイルは sql/migrations/ 配下のため、app DB に適用する。005・006の適用後に一度だけ実行すること。
-- 流れ: 申請中 → 確認済み（外部ツールで利用者と日時などを調整）→ 対応済み（ここで貸出・故障を記録）
-- 管理者から利用者への連絡は外部ツールで行うため、admin_comment は列ごと削除する（中身は戻せない）。

-- 状態・コメントを使っている CHECK を先に外す（使われている列は変更・削除できないため）
ALTER TABLE user_requests
    DROP CHECK chk_user_requests_closed_at,
    DROP CHECK chk_user_requests_admin_comment,
    DROP CHECK chk_user_requests_text_not_empty;

ALTER TABLE user_requests
    DROP COLUMN admin_comment;

-- pending: 申請中 / confirmed: 確認済み / done: 対応済み / rejected: 却下 / cancelled: 利用者が取り消し
ALTER TABLE user_requests
    MODIFY COLUMN status ENUM('pending', 'confirmed', 'done', 'rejected', 'cancelled')
        NOT NULL DEFAULT 'pending',
    ADD COLUMN confirmed_at DATETIME NULL COMMENT '確認済みにした日時（申請中に戻すと消える）'
        AFTER requested_at;

ALTER TABLE user_requests
    -- 申請中・確認済みなら終了日時なし、それ以外なら終了日時あり（両方向）
    ADD CONSTRAINT chk_user_requests_closed_at
        CHECK ((status IN ('pending', 'confirmed')) = (closed_at IS NULL)),
    -- 確認済みなら確認した日時がある（対応済みなどになった後も残す）
    ADD CONSTRAINT chk_user_requests_confirmed_at
        CHECK (status <> 'confirmed' OR confirmed_at IS NOT NULL),
    -- 申請中なら確認した日時はない
    ADD CONSTRAINT chk_user_requests_pending_not_confirmed
        CHECK (status <> 'pending' OR confirmed_at IS NULL),
    -- 空文字は「未入力」と区別がつかなくなるため禁止（未入力は NULL）
    ADD CONSTRAINT chk_user_requests_text_not_empty CHECK (detail <> '');
