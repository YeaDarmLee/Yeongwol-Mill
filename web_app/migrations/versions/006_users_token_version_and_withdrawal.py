"""users token_version, marketing email/sms, withdrawal and notification_outbox

Revision ID: 006
Revises: 005
Create Date: 2026-08-24
"""

def upgrade(conn):
    cursor = conn.cursor()
    
    # 1. users 테이블 컬럼 추가
    add_columns = [
        ("token_version", "INT NOT NULL DEFAULT 0"),
        ("marketing_email_agreed", "TINYINT(1) NOT NULL DEFAULT 0"),
        ("marketing_sms_agreed", "TINYINT(1) NOT NULL DEFAULT 0"),
        ("marketing_email_updated_at", "DATETIME NULL"),
        ("marketing_sms_updated_at", "DATETIME NULL"),
        ("status", "VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'"),
        ("deleted_at", "DATETIME NULL")
    ]
    
    for col_name, col_def in add_columns:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass  # 이미 존재할 경우 무시

    # 2. users 테이블 password_hash, name, phone 컬럼 NULL 허용으로 수정
    try:
        cursor.execute("ALTER TABLE users MODIFY COLUMN password_hash VARCHAR(255) NULL")
        cursor.execute("ALTER TABLE users MODIFY COLUMN name VARCHAR(50) NULL")
        cursor.execute("ALTER TABLE users MODIFY COLUMN phone VARCHAR(20) NULL")
    except Exception:
        pass

    # 3. user_consents 테이블 action 컬럼 추가
    try:
        cursor.execute("ALTER TABLE user_consents ADD COLUMN action VARCHAR(20) NOT NULL DEFAULT 'AGREED'")
    except Exception:
        pass

    # 4. notification_outbox 테이블 생성
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notification_outbox (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NULL,
            email VARCHAR(100) NOT NULL,
            type VARCHAR(50) NOT NULL,
            payload TEXT NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            retry_count INT NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            sent_at DATETIME NULL,
            INDEX idx_outbox_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    conn.commit()

def downgrade(conn):
    pass
