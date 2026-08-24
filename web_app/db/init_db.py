import os
import sys
import sqlite3
import pymysql

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

def init_database():
    """MySQL 및 SQLite 데이터베이스 스키마와 초기 시드 데이터를 생성합니다."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    schema_path = os.path.join(base_dir, 'schema.sql')
    seed_path = os.path.join(base_dir, 'seed.sql')

    # 1. MySQL 연결 시도
    try:
        conn = pymysql.connect(
            host=Config.MYSQL_HOST,
            port=Config.MYSQL_PORT,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            charset='utf8mb4',
            autocommit=True
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
            autocommit=True
        )
        with conn_db.cursor() as cursor:
            # 컬럼 변경이 있을 경우 안전한 테이블 재생성을 시도합니다
            try:
                cursor.execute("SELECT shelf_life_text FROM products LIMIT 1")
            except Exception:
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
                cursor.execute("DROP TABLE IF EXISTS order_items, stock_reservations, refunds, payments, webhook_events, remote_shipping_rules, product_options, products, categories, users, admin_users, orders;")
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")

            if os.path.exists(schema_path):
                with open(schema_path, 'r', encoding='utf-8') as f:
                    for statement in f.read().split(';'):
                        stmt = statement.strip()
                        if stmt:
                            cursor.execute(stmt)
            if os.path.exists(seed_path):
                with open(seed_path, 'r', encoding='utf-8') as f:
                    for statement in f.read().split(';'):
                        stmt = statement.strip()
                        if stmt:
                            cursor.execute(stmt)
        conn_db.close()
        print(f"MySQL DB '{Config.MYSQL_DB}' 초기화 성공!")
    except Exception as e:
        print(f"MySQL DB 초기화 건너뜀 (SQLite 사용): {e}")

    # 2. SQLite 폴백 초기화
    sqlite_path = os.path.join(base_dir, 'yeongwol_mill.db')
    try:
        conn_sqlite = sqlite3.connect(sqlite_path)
        cursor = conn_sqlite.cursor()

        # SQLite 테이블 스키마 검증
        try:
            cursor.execute("SELECT shelf_life_text FROM products LIMIT 1")
        except Exception:
            # 오래된 스키마 드롭 후 새 스키마 구성
            cursor.executescript("""
                DROP TABLE IF EXISTS order_items;
                DROP TABLE IF EXISTS stock_reservations;
                DROP TABLE IF EXISTS refunds;
                DROP TABLE IF EXISTS payments;
                DROP TABLE IF EXISTS webhook_events;
                DROP TABLE IF EXISTS remote_shipping_rules;
                DROP TABLE IF EXISTS product_options;
                DROP TABLE IF EXISTS products;
                DROP TABLE IF EXISTS categories;
                DROP TABLE IF EXISTS users;
                DROP TABLE IF EXISTS admin_users;
                DROP TABLE IF EXISTS orders;
            """)
        
        # SQLite 호환 스키마 변환
        if os.path.exists(schema_path):
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema_sql = f.read()
                schema_sql = schema_sql.replace('AUTO_INCREMENT', 'AUTOINCREMENT')
                schema_sql = schema_sql.replace('ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci', '')
                schema_sql = schema_sql.replace('TINYINT(1)', 'INTEGER')
                # MySQL 고유 제약조건/인덱스 필터링
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
                    except Exception as sq_err:
                        pass
                            
        if os.path.exists(seed_path):
            with open(seed_path, 'r', encoding='utf-8') as f:
                seed_sql = f.read()
                seed_sql = seed_sql.replace('INSERT IGNORE INTO', 'INSERT OR IGNORE INTO')
                for statement in seed_sql.split(';'):
                    stmt = statement.strip()
                    if stmt:
                        try:
                            cursor.execute(stmt)
                        except Exception as sq_err:
                            pass
                            
        conn_sqlite.commit()
        conn_sqlite.close()
        print("SQLite DB 'yeongwol_mill.db' 초기화 성공!")
    except Exception as sq_e:
        print(f"SQLite DB 초기화 에러: {sq_e}")

if __name__ == '__main__':
    init_database()
