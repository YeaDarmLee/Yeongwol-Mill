import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.db_connection import query_db, execute_db

def restore_products():
    """테스트용 시드 상품 데이터 복원"""
    prods = query_db("SELECT id FROM products LIMIT 1")
    if not prods:
        execute_db("INSERT INTO products (id, name, price) VALUES (1, '100% 국산 들기름 300ml', 25000)")
        execute_db("INSERT INTO product_options (product_id, option_name, additional_price, stock) VALUES (1, '300ml', 0, 100)")
