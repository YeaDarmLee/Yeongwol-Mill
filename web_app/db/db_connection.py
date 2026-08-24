import os
import sys
import datetime
import sqlite3
import pymysql
from pymysql.cursors import DictCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'yeongwol_mill.db')

def get_db_connection():
    """MySQL 커넥션을 반환하고, 연결 실패 시 SQLite로 폴백합니다."""
    try:
        conn = pymysql.connect(
            host=Config.MYSQL_HOST,
            port=Config.MYSQL_PORT,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            database=Config.MYSQL_DB,
            charset='utf8mb4',
            cursorclass=DictCursor,
            autocommit=True
        )
        conn._db_type = 'mysql'
        return conn
    except Exception as e:
        # MySQL 연결 불가 시 SQLite 연결
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        conn._db_type = 'sqlite'
        return conn

def _serialize_row(row):
    """datetime 객체를 JSON 직렬화 가능하도록 문자열로 변환합니다."""
    if not row:
        return row
    dict_row = dict(row) if isinstance(row, sqlite3.Row) else row
    serialized = {}
    for key, value in dict_row.items():
        if isinstance(value, (datetime.datetime, datetime.date)):
            serialized[key] = value.strftime('%Y-%m-%d %H:%M:%S')
        else:
            serialized[key] = value
    return serialized

def _adapt_query(query, db_type):
    """SQLite일 경우 %s 구문을 ? 구문으로 변환합니다."""
    if db_type == 'sqlite':
        return query.replace('%s', '?')
    return query

def query_db(query, args=(), one=False):
    """SELECT 쿼리를 실행하고 결과를 반환합니다."""
    conn = get_db_connection()
    try:
        adapted_query = _adapt_query(query, conn._db_type)
        cursor = conn.cursor()
        cursor.execute(adapted_query, args)
        if conn._db_type == 'mysql':
            rv = cursor.fetchall()
        else:
            rv = [dict(row) for row in cursor.fetchall()]
        
        if not rv:
            return None if one else []
        serialized_rv = [_serialize_row(r) for r in rv]
        return serialized_rv[0] if one else serialized_rv
    finally:
        conn.close()

def execute_db(query, args=()):
    """INSERT, UPDATE, DELETE 쿼리를 실행하고 lastrowid를 반환합니다."""
    conn = get_db_connection()
    try:
        adapted_query = _adapt_query(query, conn._db_type)
        cursor = conn.cursor()
        cursor.execute(adapted_query, args)
        if conn._db_type == 'sqlite':
            conn.commit()
            last_id = cursor.lastrowid
        else:
            last_id = cursor.lastrowid
        return last_id
    finally:
        conn.close()
