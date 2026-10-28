-- Migration 010: 利用者が申請に書いた内容（不具合の内容・借りたい理由）を消す。
-- このファイルは sql/migrations/ 配下のため、app DB に適用する。009の適用後に一度だけ実行すること。
-- 列は残すので、これからの申請では今までどおり書ける。実行すると内容は戻せない。
-- 不具合の申請を対応済みにすると内容が故障・不具合の記録にコピーされるため、そちらも消す。

-- 申請からコピーされた故障・不具合。申請と結びついているものに加え、
-- 005 より前に対応済みにして結びついていないものも「同じ機器・同じ内容」で探す
-- （申請の内容を書き換える前に探しておく）
CREATE TABLE clear_010_issues AS
SELECT DISTINCT i.id AS issue_id
FROM device_issues AS i
JOIN user_requests AS r
  ON r.request_type = 'issue'
 AND (r.issue_id = i.id OR (r.device_id = i.device_id AND r.detail = i.detail));

-- CREATE TABLE はその時点で確定してしまうため、作業表を作ってからトランザクションを始める
START TRANSACTION;

-- 内容は必須（NOT NULL）のため、空にはせず「削除済み」と書く
UPDATE device_issues
SET detail = '（削除済み）'
WHERE id IN (SELECT issue_id FROM clear_010_issues);

-- 故障・不具合を修正した履歴には、変更前・変更後の内容が残っているので項目ごと外す
UPDATE device_events
SET changes = JSON_REMOVE(changes, '$.detail')
WHERE event_type = 'issue_edited'
  AND issue_id IN (SELECT issue_id FROM clear_010_issues)
  AND JSON_CONTAINS_PATH(changes, 'one', '$.detail');

-- 不具合の申請は内容が必須、借りたい申請の理由は任意（NULL にする）
UPDATE user_requests
SET detail = IF(request_type = 'issue', '（削除済み）', NULL);

COMMIT;

DROP TABLE clear_010_issues;

-- 確認用（すべて 0 なら消せている）
SELECT
    (SELECT COUNT(*) FROM user_requests
     WHERE detail IS NOT NULL AND detail <> '（削除済み）') AS remaining_request_details,
    (SELECT COUNT(*) FROM device_events
     WHERE event_type = 'issue_edited' AND JSON_CONTAINS_PATH(changes, 'one', '$.detail')
       AND issue_id IN (SELECT issue_id FROM user_requests WHERE issue_id IS NOT NULL))
        AS remaining_event_details;
