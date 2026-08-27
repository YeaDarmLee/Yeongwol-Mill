"""add shipments, shipment_items, cancellation_requests, return_requests, exchange_requests and fulfillment_hold

Revision ID: 007
Revises: 006
Create Date: 2026-08-27
"""

def upgrade(conn):
    cursor = conn.cursor()
    db_type = getattr(conn, '_db_type', 'sqlite')
    
    # 1. orders 테이블 컬럼 추가
    add_order_cols = [
        ("fulfillment_hold", "TINYINT(1) NOT NULL DEFAULT 0" if db_type == 'mysql' else "INTEGER NOT NULL DEFAULT 0"),
        ("fulfillment_hold_reason", "VARCHAR(100) NULL" if db_type == 'mysql' else "TEXT NULL")
    ]
    for col_name, col_def in add_order_cols:
        try:
            cursor.execute(f"ALTER TABLE orders ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass

    # 2. refund_requests 테이블 컬럼 추가
    add_refund_cols = [
        ("source_type", "VARCHAR(30) NULL"),
        ("source_id", "INT NULL" if db_type == 'mysql' else "INTEGER NULL")
    ]
    for col_name, col_def in add_refund_cols:
        try:
            cursor.execute(f"ALTER TABLE refund_requests ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass

    # 3. SQLite / MySQL 호환 테이블 생성 구문
    if db_type == 'sqlite':
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shipments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                purpose TEXT NOT NULL DEFAULT 'FULFILLMENT',
                carrier_code TEXT NULL,
                tracking_number TEXT NULL,
                status TEXT NOT NULL DEFAULT 'READY',
                shipped_at DATETIME NULL,
                delivered_at DATETIME NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shipment_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shipment_id INTEGER NOT NULL,
                order_item_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cancellation_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                reason_code TEXT NULL,
                reason_detail TEXT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cancellation_request_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cancellation_request_id INTEGER NOT NULL,
                order_item_id INTEGER NOT NULL,
                requested_qty INTEGER NOT NULL,
                approved_qty INTEGER NOT NULL DEFAULT 0
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS return_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                reason_code TEXT NULL,
                reason_detail TEXT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS return_request_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                return_request_id INTEGER NOT NULL,
                order_item_id INTEGER NOT NULL,
                requested_qty INTEGER NOT NULL,
                approved_qty INTEGER NOT NULL DEFAULT 0
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exchange_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                reason_code TEXT NULL,
                reason_detail TEXT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exchange_request_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exchange_request_id INTEGER NOT NULL,
                order_item_id INTEGER NOT NULL,
                requested_qty INTEGER NOT NULL,
                approved_qty INTEGER NOT NULL DEFAULT 0
            );
        """)
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shipments (
                id INT AUTO_INCREMENT PRIMARY KEY,
                order_id INT NOT NULL,
                purpose VARCHAR(30) NOT NULL DEFAULT 'FULFILLMENT',
                carrier_code VARCHAR(50) NULL,
                tracking_number VARCHAR(100) NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'READY',
                shipped_at DATETIME NULL,
                delivered_at DATETIME NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_shipment_order (order_id),
                INDEX idx_shipment_status (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shipment_items (
                id INT AUTO_INCREMENT PRIMARY KEY,
                shipment_id INT NOT NULL,
                order_item_id INT NOT NULL,
                quantity INT NOT NULL DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_shipment_item_shipment (shipment_id),
                INDEX idx_shipment_item_order_item (order_item_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cancellation_requests (
                id INT AUTO_INCREMENT PRIMARY KEY,
                order_id INT NOT NULL,
                reason_code VARCHAR(50) NULL,
                reason_detail TEXT NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_cancel_order (order_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cancellation_request_items (
                id INT AUTO_INCREMENT PRIMARY KEY,
                cancellation_request_id INT NOT NULL,
                order_item_id INT NOT NULL,
                requested_qty INT NOT NULL,
                approved_qty INT NOT NULL DEFAULT 0,
                INDEX idx_cancel_item_req (cancellation_request_id),
                INDEX idx_cancel_item_order_item (order_item_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS return_requests (
                id INT AUTO_INCREMENT PRIMARY KEY,
                order_id INT NOT NULL,
                reason_code VARCHAR(50) NULL,
                reason_detail TEXT NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_return_order (order_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS return_request_items (
                id INT AUTO_INCREMENT PRIMARY KEY,
                return_request_id INT NOT NULL,
                order_item_id INT NOT NULL,
                requested_qty INT NOT NULL,
                approved_qty INT NOT NULL DEFAULT 0,
                INDEX idx_return_item_req (return_request_id),
                INDEX idx_return_item_order_item (order_item_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exchange_requests (
                id INT AUTO_INCREMENT PRIMARY KEY,
                order_id INT NOT NULL,
                reason_code VARCHAR(50) NULL,
                reason_detail TEXT NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_exchange_order (order_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exchange_request_items (
                id INT AUTO_INCREMENT PRIMARY KEY,
                exchange_request_id INT NOT NULL,
                order_item_id INT NOT NULL,
                requested_qty INT NOT NULL,
                approved_qty INT NOT NULL DEFAULT 0,
                INDEX idx_exchange_item_req (exchange_request_id),
                INDEX idx_exchange_item_order_item (order_item_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

    conn.commit()

def downgrade(conn):
    pass
