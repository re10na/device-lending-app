-- Migration 006: 005 より前に対応済みにした申請にも、そのとき作った貸出・故障を結びつける。
-- このファイルは sql/migrations/ 配下のため、app DB に適用する。005の適用後に一度だけ実行すること。
-- 結びつけた申請は管理者画面から申請中に戻せるようになる。
--
-- 対応済みにした処理は 1 トランザクションで「貸出・故障の登録 → 申請を閉じる」を行うため、
-- 履歴（device_events）の時刻と申請の closed_at はほぼ同じになる。それを手がかりに探す。
-- 候補が 1 件に決まらないもの（同じ記録に複数の申請が当たる場合も）は結びつけない。

-- 借りたい申請: 同じ社員・同じ機種への貸出で、貸出の履歴が申請を閉じた時刻と同じもの
CREATE TABLE backfill_006_loan_match AS
SELECT r.id AS request_id, l.id AS loan_id
FROM user_requests AS r
JOIN loans AS l
  ON l.shain_code = r.shain_code
 AND l.loaned_on = DATE(r.closed_at)
 AND l.cancelled_at IS NULL
JOIN devices AS d ON d.id = l.device_id AND d.device_model_id = r.device_model_id
JOIN device_events AS e
  ON e.loan_id = l.id
 AND e.event_type = 'loaned'
 AND ABS(TIMESTAMPDIFF(SECOND, e.occurred_at, r.closed_at)) <= 2
WHERE r.request_type = 'loan' AND r.status = 'done' AND r.loan_id IS NULL
  AND NOT EXISTS (SELECT 1 FROM user_requests AS u WHERE u.loan_id = l.id);

UPDATE user_requests AS r
JOIN backfill_006_loan_match AS m ON m.request_id = r.id
JOIN (SELECT request_id FROM backfill_006_loan_match GROUP BY request_id HAVING COUNT(*) = 1)
     AS one_loan ON one_loan.request_id = m.request_id
JOIN (SELECT loan_id FROM backfill_006_loan_match GROUP BY loan_id HAVING COUNT(*) = 1)
     AS one_request ON one_request.loan_id = m.loan_id
SET r.loan_id = m.loan_id;

DROP TABLE backfill_006_loan_match;

-- 不具合の申請: 同じ機器・同じ内容の故障で、登録の履歴が申請を閉じた時刻と同じもの
CREATE TABLE backfill_006_issue_match AS
SELECT r.id AS request_id, i.id AS issue_id
FROM user_requests AS r
JOIN device_issues AS i
  ON i.device_id = r.device_id
 AND i.detail = r.detail
 AND i.reported_on = DATE(r.closed_at)
 AND i.cancelled_at IS NULL
JOIN device_events AS e
  ON e.issue_id = i.id
 AND e.event_type = 'issue_reported'
 AND ABS(TIMESTAMPDIFF(SECOND, e.occurred_at, r.closed_at)) <= 2
WHERE r.request_type = 'issue' AND r.status = 'done' AND r.issue_id IS NULL
  AND NOT EXISTS (SELECT 1 FROM user_requests AS u WHERE u.issue_id = i.id);

UPDATE user_requests AS r
JOIN backfill_006_issue_match AS m ON m.request_id = r.id
JOIN (SELECT request_id FROM backfill_006_issue_match GROUP BY request_id HAVING COUNT(*) = 1)
     AS one_issue ON one_issue.request_id = m.request_id
JOIN (SELECT issue_id FROM backfill_006_issue_match GROUP BY issue_id HAVING COUNT(*) = 1)
     AS one_request ON one_request.issue_id = m.issue_id
SET r.issue_id = m.issue_id;

DROP TABLE backfill_006_issue_match;

-- 結びつけられなかった対応済みの申請（0 件なら全部戻せる状態）
SELECT id, request_type, shain_code, closed_at
FROM user_requests
WHERE status = 'done' AND loan_id IS NULL AND issue_id IS NULL;
