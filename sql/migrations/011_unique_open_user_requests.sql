-- Migration 011: 同じ社員の同じ申請（同じ機器の不具合 / 同じ機種の借りたい）が、
-- 申請中・確認済みのまま 2 件以上にならないことを DB で保証する。
-- このファイルは sql/migrations/ 配下のため、app DB に適用する。007の適用後に一度だけ実行すること。
-- アプリでも事前に確認しているが、ボタンの連打などで同時に送られるとすり抜けるため、UNIQUE で止める。

-- 実行前に、すでに重複している申請がないか確認する（1 行でも出たら、片方を取り消してから実行する。
-- 重複があると下の ALTER は Duplicate entry で失敗し、テーブルは何も変わらない）
SELECT shain_code, request_type, COALESCE(device_id, device_model_id) AS target,
       GROUP_CONCAT(id ORDER BY id) AS request_ids
FROM user_requests
WHERE status IN ('pending', 'confirmed')
GROUP BY shain_code, request_type, COALESCE(device_id, device_model_id)
HAVING COUNT(*) > 1;

-- 申請中・確認済みなら対象（不具合は機器 id、借りたいは機種 id）、終わった申請は NULL。
-- UNIQUE は NULL 同士の重複を許すため、「終わった申請は何件でも、終わっていない申請は 1 件まで」になる
-- （loans.open_flag と同じ考え方。request_type も UNIQUE に含めるので、機器 id と機種 id は混ざらない）
ALTER TABLE user_requests
    ADD COLUMN open_target BIGINT UNSIGNED
        GENERATED ALWAYS AS (
            IF(status IN ('pending', 'confirmed'), COALESCE(device_id, device_model_id), NULL)
        ) STORED
        COMMENT '申請中・確認済みなら対象の機器 id / 機種 id、それ以外は NULL',
    ADD UNIQUE KEY uq_user_requests_one_open (shain_code, request_type, open_target);
