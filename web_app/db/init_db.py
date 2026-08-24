import os
import sys
import pymysql

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

def init_database():
    """MySQL 데이터베이스, 스키마 및 초기 시드 데이터를 자동 생성합니다."""
    print("MySQL 데이터베이스 초기화를 진행합니다...")
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    schema_path = os.path.join(base_dir, 'schema.sql')
    seed_path = os.path.join(base_dir, 'seed.sql')

    # 1. DB 생성
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

    # 2. Schema 및 Seed 데이터 실행
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
        if os.path.exists(schema_path):
            with open(schema_path, 'r', encoding='utf-8') as f:
                for statement in f.read().split(';'):
                    stmt = statement.strip()
                    if stmt:
                        cursor.execute(stmt)
            print("schema.sql 실행 완료.")

        if os.path.exists(seed_path):
            with open(seed_path, 'r', encoding='utf-8') as f:
                for statement in f.read().split(';'):
                    stmt = statement.strip()
                    if stmt:
                        cursor.execute(stmt)
            print("seed.sql 실행 완료.")

    conn_db.close()
    print(f"MySQL DB '{Config.MYSQL_DB}' 전용 초기화 성공!")

if __name__ == '__main__':
    init_database()
