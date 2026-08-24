import os
import sys
import datetime
import pymysql
from pymysql.cursors import DictCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

def get_db_connection():
    """MySQL 커넥션을 반환합니다."""
    return pymysql.connect(
        host=Config.MYSQL_HOST,
        port=Config.MYSQL_PORT,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        database=Config.MYSQL_DB,
        charset='utf8mb4',
        cursorclass=DictCursor,
        autocommit=True
    )

def _serialize_row(row):
    """datetime 객체를 JSON 직렬화 가능하도록 문자열로 변환합니다."""
    if not row:
        return row
    serialized = {}
    for key, value in row.items():
        if isinstance(value, (datetime.datetime, datetime.date)):
            serialized[key] = value.strftime('%Y-%m-%d %H:%M:%S')
        else:
            serialized[key] = value
    return serialized

def query_db(query, args=(), one=False):
    """MySQL SELECT 쿼리를 실행하고 JSON 직렬화 가능한 객체로 반환합니다."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, args)
            rv = cursor.fetchall()
            if not rv:
                return None if one else []
            serialized_rv = [_serialize_row(r) for r in rv]
            return serialized_rv[0] if one else serialized_rv
    finally:
        conn.close()

def execute_db(query, args=()):
    """MySQL INSERT, UPDATE, DELETE 쿼리를 실행합니다."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, args)
            return cursor.lastrowid
    finally:
        conn.close()
