-- 社員・機種のマスタ（デモ用の架空データ）。
-- 本来は別システムが持つ読み取り専用のマスタで、アプリは書き込まない。

CREATE DATABASE IF NOT EXISTS master CHARACTER SET utf8mb4;
USE master;

CREATE TABLE m_shain (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    shain_code VARCHAR(20) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    taishoku_date DATE NULL COMMENT 'NULLなら在籍中'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='社員';

CREATE TABLE m_device_model (
    id INT UNSIGNED NOT NULL PRIMARY KEY,
    device_type VARCHAR(30) NOT NULL,
    manufacturer VARCHAR(100) NOT NULL,
    model_name VARCHAR(100) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='機種';

INSERT INTO m_shain (shain_code, name, taishoku_date) VALUES
    ('1001', '田中太郎', NULL),
    ('1002', '鈴木花子', NULL),
    ('1003', '佐藤次郎', NULL),
    ('1004', '高橋美咲', NULL),
    ('1005', '伊藤健一', NULL),
    ('1006', '渡辺さくら', NULL),
    ('1007', '山本大輔', NULL),
    ('1008', '中村あおい', NULL),
    ('1009', '小林翔太', NULL),
    ('1010', '加藤由美', NULL),
    -- ダッシュボードの「もうすぐ退職する人の貸出」に出るよう、退職日を起動日の 20 日後にする
    ('1011', '吉田誠', DATE_ADD(CURRENT_DATE(), INTERVAL 20 DAY)),
    ('1012', '山田恵', '2025-03-31');

INSERT INTO m_device_model (id, device_type, manufacturer, model_name) VALUES
    (1, 'PC', 'Dell', 'Latitude 5440'),
    (2, 'PC', 'HP', 'EliteBook 840'),
    (3, 'PC', 'Lenovo', 'ThinkPad X1 Carbon'),
    (4, 'SmartPhone', 'Apple', 'iPhone 15'),
    (5, 'SmartPhone', 'Google', 'Pixel 8'),
    (6, 'MobileWifi', 'NEC', 'Aterm MP02LN'),
    (7, 'Phone', 'NEC', 'DT400'),
    (8, 'VoIP', 'Cisco', 'IP Phone 8841');
