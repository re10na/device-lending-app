-- Migration 013: 故障・不具合に「報告したときの貸出」を記録する。
-- このファイルは sql/migrations/ 配下のため、app DB に適用する。012の適用後に一度だけ実行すること。
--
-- 今までは「報告日がその人の貸出日〜返却日に入るか」で、故障を人に結びつけていた。
-- それだと、返却した日に次の人が借りて同じ日に故障が報告されると、2人とも結びついてしまう。
-- これからは報告したときの貸出（loan_id）を記録し、人はその貸出の shain_code でたどる。
-- 社員番号をコピーしないのは、貸出の社員を修正・取り消ししたときに故障側も追従させるため。

ALTER TABLE device_issues
    ADD COLUMN loan_id BIGINT UNSIGNED NULL COMMENT '報告したときの貸出（貸出中でなければNULL）'
        AFTER device_id,
    ADD CONSTRAINT fk_device_issues_loan FOREIGN KEY (loan_id) REFERENCES loans (id);

-- ===== 既存の故障を貸出に結びつける =====
-- 1 つに決まらないものは NULL のまま残し、最後に一覧を出す。

-- (1) 本人の申請で記録した故障: 申請した時点でその社員が借りていた貸出
--     （アプリの user_requests._requester_loan_id と同じ決め方）
UPDATE device_issues AS i
JOIN user_requests AS r ON r.issue_id = i.id AND r.status = 'done'
SET i.loan_id = (
    SELECT l.id FROM loans AS l
    WHERE l.device_id = i.device_id AND l.shain_code = r.shain_code AND l.cancelled_at IS NULL
      AND l.loaned_on <= DATE(r.requested_at)
    ORDER BY l.loaned_on DESC, l.id DESC
    LIMIT 1
)
WHERE i.loan_id IS NULL;

-- (2) 残りの故障: 報告日を含む貸出を候補にする
CREATE TABLE backfill_013_candidates AS
SELECT i.id AS issue_id, l.id AS loan_id,
       i.reported_on, i.created_at AS issue_created_at,
       l.loaned_on, l.returned_on, l.created_at AS loan_created_at,
       (
           SELECT MAX(e.occurred_at) FROM device_events AS e
           WHERE e.loan_id = l.id AND e.event_type = 'returned'
       ) AS returned_at
FROM device_issues AS i
JOIN loans AS l
  ON l.device_id = i.device_id AND l.cancelled_at IS NULL
 AND l.loaned_on <= i.reported_on
 AND (l.returned_on IS NULL OR i.reported_on <= l.returned_on)
WHERE i.loan_id IS NULL;

-- 報告日に貸し借りがあった候補は、登録した時刻で絞る。
-- 日付を後から修正した記録（登録した日と記録上の日付が違うもの）は時刻が当てにならないので絞らない。
-- 報告より後に貸し出した貸出は候補から外す
DELETE FROM backfill_013_candidates
WHERE loaned_on = reported_on
  AND DATE(issue_created_at) = reported_on
  AND DATE(loan_created_at) = loaned_on
  AND loan_created_at > issue_created_at;

-- 報告より前に返却した貸出は候補から外す
DELETE FROM backfill_013_candidates
WHERE returned_on = reported_on
  AND DATE(issue_created_at) = reported_on
  AND returned_at IS NOT NULL
  AND DATE(returned_at) = returned_on
  AND returned_at < issue_created_at;

UPDATE device_issues AS i
JOIN (
    SELECT issue_id, MIN(loan_id) AS loan_id
    FROM backfill_013_candidates
    GROUP BY issue_id
    HAVING COUNT(*) = 1
) AS matched ON matched.issue_id = i.id
SET i.loan_id = matched.loan_id;

-- 候補が 2 件以上残って決められなかった故障（必要なら手で loan_id を入れる）
SELECT c.issue_id, c.reported_on, c.loan_id, l.shain_code, c.loaned_on, c.returned_on
FROM backfill_013_candidates AS c
JOIN loans AS l ON l.id = c.loan_id
JOIN device_issues AS i ON i.id = c.issue_id
WHERE i.loan_id IS NULL
ORDER BY c.issue_id, c.loan_id;

DROP TABLE backfill_013_candidates;
