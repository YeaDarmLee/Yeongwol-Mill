import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app
from db.init_db import init_database
from db.db_connection import query_db, execute_db

@pytest.fixture(autouse=True)
def setup_db():
    app.config['TESTING'] = True
    init_database()

@pytest.fixture
def client():
    with app.test_client() as client:
        yield client

def test_create_order_with_stock_reservation(client):
    # 1. 1번 상품 옵션 획득
    option = query_db("SELECT * FROM product_options WHERE product_id = 1", one=True)
    assert option is not None, "Product option 1 must exist after seed"
    initial_reserved = option['reserved_stock']

    # 2. 비회원 주문서 생성
    response = client.post('/api/orders', json={
        'items': [{'product_id': 1, 'option_id': option['id'], 'quantity': 2}],
        'recipient_name': '홍길동',
        'recipient_phone': '010-1234-5678',
        'postal_code': '06123',
        'address': '서울특별시 강남구 테헤란로 123',
        'address_detail': '101호',
        'guest_name': '홍길동',
        'guest_phone': '010-1234-5678',
        'guest_password': 'password123'
    })

    assert response.status_code == 201
    data = response.get_json()
    assert 'order_number' in data
    assert data['total_amount'] > 0

    # 3. reserved_stock 증가 검증 (+2)
    updated_option = query_db("SELECT * FROM product_options WHERE id = %s", (option['id'],), one=True)
    assert updated_option['reserved_stock'] == initial_reserved + 2
