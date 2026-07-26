-- 010_feedback_image.sql —— Tell Lawrence More 反馈支持图片附件。
--
-- 背景：2026-07-26 深夜，Lawrence 要求反馈输入框可以传图片，且"如果真的产生了
-- 数据，及时推送到我的邮箱"。图片本身不进这张表（BLOB 存数据库不利于备份/
-- 迁移），只存文件名；实际文件落在 VM 磁盘的 feedback_uploads/ 目录，
-- api/history_tools.py 负责读写。
--
-- 幂等写法同 004/008：MySQL 8.0 无 ADD COLUMN IF NOT EXISTS，用存储过程包一层。

USE crypto_news;

DROP PROCEDURE IF EXISTS add_feedback_image_columns;
DELIMITER //
CREATE PROCEDURE add_feedback_image_columns()
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'feedback_submissions'
                     AND COLUMN_NAME = 'image_filename') THEN
        ALTER TABLE feedback_submissions
            ADD COLUMN image_filename VARCHAR(128) NULL
                COMMENT '磁盘文件名（feedback_uploads/ 下），无附件则 NULL',
            ADD COLUMN notified_at DATETIME NULL
                COMMENT '邮件通知发送成功的时间，NULL 表示未发或发送失败';
    END IF;
END //
DELIMITER ;

CALL add_feedback_image_columns();
DROP PROCEDURE add_feedback_image_columns;
