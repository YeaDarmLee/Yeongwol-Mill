import os
import sys
import sqlite3
import pymysql

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

def ensure_seed_data(cursor, is_sqlite=False):
    """products 및 product_options 데이터가 비어있을 때 항상 seed.sql을 실행하여 시드를 보장합니다."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    seed_path = os.path.join(base_dir, 'seed.sql')
    
    prod_count = 0
    opt_count = 0
    try:
        cursor.execute("SELECT COUNT(*) FROM products")
        row = cursor.fetchone()
        prod_count = row[0] if row else 0

        cursor.execute("SELECT COUNT(*) FROM product_options")
        row_opt = cursor.fetchone()
        opt_count = row_opt[0] if row_opt else 0
    except Exception:
        prod_count = 0
        opt_count = 0

    if (prod_count == 0 or opt_count == 0) and os.path.exists(seed_path):
        with open(seed_path, 'r', encoding='utf-8') as f:
            seed_sql = f.read()
            if is_sqlite:
                seed_sql = seed_sql.replace('INSERT IGNORE INTO', 'INSERT OR IGNORE INTO')
            for statement in seed_sql.split(';'):
                stmt = statement.strip()
                if stmt:
                    try:
                        cursor.execute(stmt)
                    except Exception:
                        pass

def init_database():
    """MySQL 및 SQLite 데이터베이스 스키마와 초기 시드 데이터를 생성합니다."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    schema_path = os.path.join(base_dir, 'schema.sql')

    # 1. MySQL 연결 시도
    try:
        conn = pymysql.connect(
            host=Config.MYSQL_HOST,
            port=Config.MYSQL_PORT,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            charset='utf8mb4',
            autocommit=True,
            connect_timeout=2
        )
        with conn.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{Config.MYSQL_DB}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
        conn.close()

        conn_db = pymysql.connect(
            host=Config.MYSQL_HOST,
            port=Config.MYSQL_PORT,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            database=Config.MYSQL_DB,
            charset='utf8mb4',
            autocommit=True,
            connect_timeout=2
        )
        with conn_db.cursor() as cursor:
            try:
                cursor.execute("SELECT token_version FROM users LIMIT 1")
                cursor.execute("SELECT refund_calculation_mode FROM orders LIMIT 1")
            except Exception:
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
                cursor.execute("DROP TABLE IF EXISTS order_admin_notes, password_reset_tokens, notification_outbox, notifications, refresh_tokens, revoked_access_tokens, refund_request_items, refund_requests, inventory_transactions, return_item_dispositions, return_items, return_claims, admin_audit_logs, order_items, stock_reservations, refunds, payments, webhook_events, remote_shipping_rules, product_options, products, categories, email_verifications, user_consents, users, admin_users, orders;")

                cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")

            if os.path.exists(schema_path):
                with open(schema_path, 'r', encoding='utf-8') as f:
                    for statement in f.read().split(';'):
                        stmt = statement.strip()
                        if stmt:
                            try:
                                cursor.execute(stmt)
                            except Exception:
                                pass

            # v2.3 & v2.4 컬럼 안전 추가 (MySQL)
            mysql_alters = [
                "ALTER TABLE orders ADD COLUMN refund_calculation_mode VARCHAR(20) NOT NULL DEFAULT 'AUTO'",
                "ALTER TABLE order_items ADD COLUMN cancelled_qty INT NOT NULL DEFAULT 0",
                "ALTER TABLE order_items ADD COLUMN shipped_qty INT NOT NULL DEFAULT 0",
                "ALTER TABLE order_items ADD COLUMN returned_qty INT NOT NULL DEFAULT 0",
                "ALTER TABLE order_items ADD COLUMN item_gross_amount BIGINT NULL",
                "ALTER TABLE order_items ADD COLUMN item_discount_allocated BIGINT NULL",
                "ALTER TABLE order_items ADD COLUMN item_paid_amount BIGINT NULL",
                "ALTER TABLE notification_outbox ADD COLUMN user_id INT NULL",
                "ALTER TABLE notification_outbox ADD COLUMN email VARCHAR(100) NULL",
                "ALTER TABLE notification_outbox ADD COLUMN type VARCHAR(50) NULL",
                "ALTER TABLE notification_outbox ADD COLUMN payload TEXT NULL",
                "ALTER TABLE notification_outbox MODIFY COLUMN event_type VARCHAR(50) NULL DEFAULT 'EVENT'",
                "ALTER TABLE shipments ADD COLUMN purpose VARCHAR(30) NOT NULL DEFAULT 'FULFILLMENT'",
                "ALTER TABLE shipments ADD COLUMN carrier_code VARCHAR(50) NULL",
                "ALTER TABLE shipments ADD COLUMN courier VARCHAR(50) NOT NULL DEFAULT 'EPOST'",

                "ALTER TABLE shipments ADD COLUMN tracking_last_checked_at DATETIME NULL",
                "ALTER TABLE shipments ADD COLUMN tracking_next_check_at DATETIME NULL",
                "ALTER TABLE shipments ADD COLUMN tracking_error_count INT DEFAULT 0",
                "ALTER TABLE shipments ADD COLUMN tracking_last_status VARCHAR(50) NULL",
                "ALTER TABLE shipments ADD COLUMN tracking_last_error TEXT NULL",
                "ALTER TABLE products ADD COLUMN delivery_info VARCHAR(255) DEFAULT '평일 14시 이전 주문 시 당일 발송 (1~2일 내 도착 예정)'",
                "CREATE TABLE IF NOT EXISTS order_admin_notes (id INT AUTO_INCREMENT PRIMARY KEY, order_id INT NOT NULL, admin_id INT NOT NULL DEFAULT 1, admin_email VARCHAR(100) NOT NULL DEFAULT 'admin@example.com', note TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, INDEX idx_order_notes_order (order_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
            ]
            for alt in mysql_alters:
                try:
                    cursor.execute(alt)
                except Exception:
                    pass

            migration_v23 = os.path.join(base_dir, 'migrations', 'v2.3_admin_upgrade.sql')
            if os.path.exists(migration_v23):
                with open(migration_v23, 'r', encoding='utf-8') as f:
                    for statement in f.read().split(';'):
                        stmt = statement.strip()
                        if stmt:
                            try:
                                cursor.execute(stmt)
                            except Exception:
                                pass

            # v007 마이그레이션 (shipments, shipment_items 및 CS 요청 테이블들)
            try:
                import importlib.util
                migration_007_path = os.path.join(os.path.dirname(base_dir), 'migrations', 'versions', '007_shipments_and_cs_items.py')
                spec = importlib.util.spec_from_file_location("m007", migration_007_path)
                if spec and spec.loader:
                    m007 = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(m007)
                    conn_db._db_type = 'mysql'
                    m007.upgrade(conn_db)
            except Exception as m007_err:
                print(f"Migration 007 warning: {m007_err}")


            # 시드 데이터 보장
            ensure_seed_data(cursor, is_sqlite=False)
        conn_db.close()
        print(f"MySQL DB '{Config.MYSQL_DB}' 초기화 성공!")


        # 스냅샷 백필 자동 실행
        try:
            from db.backfill_order_snapshots import backfill_snapshots
            backfill_snapshots()
        except Exception as bf_err:
            print(f"백필 실행 경고: {bf_err}")
    except Exception as e:
        print(f"MySQL DB 초기화 건너뜀 (SQLite 사용): {e}")

    # 2. SQLite 폴백 초기화
    sqlite_path = os.path.join(base_dir, 'yeongwol_mill.db')
    try:
        conn_sqlite = sqlite3.connect(sqlite_path)
        cursor = conn_sqlite.cursor()

        was_sqlite_dropped = False
        try:
            cursor.execute("SELECT token_version FROM users LIMIT 1")
            cursor.execute("SELECT refund_calculation_mode FROM orders LIMIT 1")
        except Exception:
            was_sqlite_dropped = True
            cursor.executescript("""
                DROP TABLE IF EXISTS password_reset_tokens;
                DROP TABLE IF EXISTS notification_outbox;
                DROP TABLE IF EXISTS notifications;
                DROP TABLE IF EXISTS refresh_tokens;
                DROP TABLE IF EXISTS revoked_access_tokens;
                DROP TABLE IF EXISTS refund_request_items;
                DROP TABLE IF EXISTS refund_requests;
                DROP TABLE IF EXISTS inventory_transactions;
                DROP TABLE IF EXISTS return_item_dispositions;
                DROP TABLE IF EXISTS return_items;
                DROP TABLE IF EXISTS return_claims;
                DROP TABLE IF EXISTS admin_audit_logs;
                DROP TABLE IF EXISTS order_items;
                DROP TABLE IF EXISTS stock_reservations;
                DROP TABLE IF EXISTS refunds;
                DROP TABLE IF EXISTS payments;
                DROP TABLE IF EXISTS webhook_events;
                DROP TABLE IF EXISTS remote_shipping_rules;
                DROP TABLE IF EXISTS product_options;
                DROP TABLE IF EXISTS products;
                DROP TABLE IF EXISTS categories;
                DROP TABLE IF EXISTS email_verifications;
                DROP TABLE IF EXISTS user_consents;
                DROP TABLE IF EXISTS users;
                DROP TABLE IF EXISTS admin_users;
                DROP TABLE IF EXISTS orders;
            """)
        
        if os.path.exists(schema_path):
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema_sql = f.read()
                schema_sql = schema_sql.replace('AUTO_INCREMENT', 'AUTOINCREMENT')
                schema_sql = schema_sql.replace('ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci', '')
                schema_sql = schema_sql.replace('TINYINT(1)', 'INTEGER')
                clean_stmts = []
                for statement in schema_sql.split(';'):
                    stmt = statement.strip()
                    if stmt:
                        lines = [line for line in stmt.split('\n') if not ('INDEX ' in line and 'PRIMARY KEY' not in line) and not ('CONSTRAINT chk_' in line)]
                        clean_stmt = '\n'.join(lines).rstrip(',')
                        clean_stmts.append(clean_stmt)
                
                for clean_stmt in clean_stmts:
                    try:
                        cursor.execute(clean_stmt)
                    except Exception:
                        pass

        # v2.3 & v2.4 컬럼 안전 추가 (SQLite)
        sqlite_alters = [
            "ALTER TABLE orders ADD COLUMN refund_calculation_mode VARCHAR(20) NOT NULL DEFAULT 'AUTO'",
            "ALTER TABLE order_items ADD COLUMN cancelled_qty INT NOT NULL DEFAULT 0",
            "ALTER TABLE order_items ADD COLUMN shipped_qty INT NOT NULL DEFAULT 0",
            "ALTER TABLE order_items ADD COLUMN returned_qty INT NOT NULL DEFAULT 0",
            "ALTER TABLE order_items ADD COLUMN item_gross_amount BIGINT NULL",
            "ALTER TABLE order_items ADD COLUMN item_discount_allocated BIGINT NULL",
            "ALTER TABLE order_items ADD COLUMN item_paid_amount BIGINT NULL",
            "ALTER TABLE notification_outbox ADD COLUMN user_id INT NULL",
            "ALTER TABLE notification_outbox ADD COLUMN email VARCHAR(100) NULL",
            "ALTER TABLE notification_outbox ADD COLUMN type VARCHAR(50) NULL",
            "ALTER TABLE notification_outbox ADD COLUMN payload TEXT NULL",
            "ALTER TABLE shipments ADD COLUMN purpose VARCHAR(30) NOT NULL DEFAULT 'FULFILLMENT'",
            "ALTER TABLE shipments ADD COLUMN carrier_code VARCHAR(50) NULL",
            "ALTER TABLE shipments ADD COLUMN courier VARCHAR(50) NOT NULL DEFAULT 'EPOST'",

            "ALTER TABLE shipments ADD COLUMN tracking_last_checked_at DATETIME NULL",
            "ALTER TABLE shipments ADD COLUMN tracking_next_check_at DATETIME NULL",
            "ALTER TABLE shipments ADD COLUMN tracking_error_count INT DEFAULT 0",
            "ALTER TABLE shipments ADD COLUMN tracking_last_status VARCHAR(50) NULL",
            "ALTER TABLE shipments ADD COLUMN tracking_last_error TEXT NULL",
            "ALTER TABLE products ADD COLUMN delivery_info VARCHAR(255) DEFAULT '평일 14시 이전 주문 시 당일 발송 (1~2일 내 도착 예정)'"
        ]
        for alt in sqlite_alters:
            try:
                cursor.execute(alt)
            except Exception:
                pass
                            
        # v007 마이그레이션 (SQLite)
        try:
            import importlib.util
            migration_007_path = os.path.join(os.path.dirname(base_dir), 'migrations', 'versions', '007_shipments_and_cs_items.py')
            spec = importlib.util.spec_from_file_location("m007", migration_007_path)
            if spec and spec.loader:
                m007 = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(m007)
                conn_sqlite._db_type = 'sqlite'
                m007.upgrade(conn_sqlite)
        except Exception:
            pass


        # SQLite 시드 데이터 보장
        ensure_seed_data(cursor, is_sqlite=True)

                            
        conn_sqlite.commit()
        conn_sqlite.close()
        print("SQLite DB 'yeongwol_mill.db' 초기화 성공!")
    except Exception as sq_e:
        print(f"SQLite DB 초기화 에러: {sq_e}")

if __name__ == '__main__':
    init_database()
