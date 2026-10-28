-- Migration 002: 旧PC貸出管理のテーブルを削除する。
-- このファイルは sql/migrations/ 配下のため、app DB に適用する。001の適用後に一度だけ実行すること。
-- 白紙から始めるため、旧データは移行しない（実行するとデータは戻せない）。
-- 社員は master.m_shain に一本化したため users も不要。
-- computer_lending_history はリポジトリ外で手動作成された旧貸出履歴テーブル。

-- 外部キーで参照している側から先に削除する（参照されている表は先に消せないため）
DROP TABLE IF EXISTS computer_lending_history;
DROP TABLE IF EXISTS computers;
DROP TABLE IF EXISTS users;
