import os
import sys
import pymysql
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

def restore_products():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    seed_path = os.path.join(base_dir, 'seed.sql')

    print("영월고향방앗간 상품 시드 데이터 정밀 복구를 시작합니다...")

    # 1. MySQL 복구
    try:
        conn = pymysql.connect(
            host=Config.MYSQL_HOST,
            port=Config.MYSQL_PORT,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            database=Config.MYSQL_DB,
            charset='utf8mb4',
            autocommit=True
        )
        with conn.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
            cursor.execute("TRUNCATE TABLE product_options;")
            cursor.execute("TRUNCATE TABLE products;")
            cursor.execute("TRUNCATE TABLE categories;")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")

            if os.path.exists(seed_path):
                with open(seed_path, 'r', encoding='utf-8') as f:
                    for stmt in f.read().split(';'):
                        s = stmt.strip()
                        if s:
                            cursor.execute(s)
        conn.close()
        print("MySQL 상품 및 옵션 데이터 정밀 복구 완료!")
    except Exception as e:
        print(f"MySQL 복구 예외: {e}")

    # 2. SQLite 복구
    try:
        sqlite_path = os.path.join(base_dir, 'yeongwol_mill.db')
        conn_sq = sqlite3.connect(sqlite_path)
        cur = conn_sq.cursor()
        cur.execute("PRAGMA foreign_keys = OFF;")
        cur.execute("DELETE FROM product_options;")
        cur.execute("DELETE FROM products;")
        cur.execute("DELETE FROM categories;")
        cur.execute("PRAGMA foreign_keys = ON;")

        if os.path.exists(seed_path):
            with open(seed_path, 'r', encoding='utf-8') as f:
                seed_sql = f.read().replace('INSERT IGNORE INTO', 'INSERT OR IGNORE INTO')
                for stmt in seed_sql.split(';'):
                    s = stmt.strip()
                    if s:
                        cur.execute(s)
        conn_sq.commit()
        conn_sq.close()
        print("SQLite 상품 및 옵션 데이터 정밀 복구 완료!")
    except Exception as e:
        print(f"SQLite 복구 예외: {e}")

if __name__ == '__main__':
    restore_products()
