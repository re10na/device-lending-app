-- Migration 009: 重複している表・列を削除する。
-- このファイルは sql/migrations/ 配下のため、app DB に適用する。008の適用後に一度だけ実行すること。
-- 実行するとデータは戻せない。

-- mobile_devices はリポジトリ外で手動作成された旧スマホ管理の表。devices と sims に一本化したため不要
DROP TABLE IF EXISTS mobile_devices;

-- created_at は requested_at と同じく追加した時刻が入るだけで、常に同じ値になるため削除する
ALTER TABLE user_requests
    DROP COLUMN created_at;
