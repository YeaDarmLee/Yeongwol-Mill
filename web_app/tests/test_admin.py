import pytest
import sys
import os
from werkzeug.security import generate_password_hash

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app
from db.init_db import init_database
from db.db_connection import query_db, execute_db

@pytest.fixture(autouse=True)
def setup_db():
    app.config['TESTING'] = True
    init_database()
    from middlewares.auth import hash_password
    execute_db("DELETE FROM admin_users WHERE email = 'admin@yeongwol.com'")
    execute_db("""
        INSERT INTO admin_users (email, name, password_hash, role)
        VALUES ('admin@yeongwol.com', '관리자', %s, 'ADMIN')
    """, (hash_password('admin1234'),))



@pytest.fixture
def client():
    with app.test_client() as client:
        yield client

def test_admin_login_and_order_shipping_update(client):
    # 1. 관리자 로그인
    login_res = client.post('/api/admin/login', json={
        'email': 'admin@yeongwol.com',
        'password': 'admin1234'
    })
    assert login_res.status_code == 200
    token = login_res.get_json()['token']
    headers = {'Authorization': f'Bearer {token}'}

    # 2. 대시보드 조회
    dash_res = client.get('/api/admin/dashboard', headers=headers)
    assert dash_res.status_code == 200

    # 3. 주문 생성
    option = query_db("SELECT * FROM product_options WHERE product_id = 1", one=True)
    order_res = client.post('/api/orders', json={
        'items': [{'product_id': 1, 'option_id': option['id'], 'quantity': 1}],
        'recipient_name': '강감찬',
        'recipient_phone': '010-7777-6666',
        'postal_code': '06123',
        'address': '강원특별자치도 영월군',
        'guest_name': '강감찬',
        'guest_phone': '010-7777-6666',
        'guest_password': 'password123'
    })
    order_id = order_res.get_json()['order_id']

    # State Machine 준수: PENDING -> PREPARING 변경 후 SHIPPING 운송장 등록
    execute_db("UPDATE orders SET order_status = 'PREPARING', payment_status = 'PAID' WHERE id = %s", (order_id,))

    # 4. 운송장 번호 등록 (SHIPPING 변경)

    shipping_res = client.post(f'/api/admin/orders/{order_id}/shipping', headers=headers, json={
        'courier_name': 'CJ대한통운',
        'tracking_number': '1234567890'
    })
    assert shipping_res.status_code == 200

    order = query_db("SELECT * FROM orders WHERE id = %s", (order_id,), one=True)
    assert order['courier_name'] == 'CJ대한통운'
    assert order['tracking_number'] == '1234567890'
    assert order['order_status'] == 'SHIPPING'

    # 5. CSV 내보내기 테스트
    export_res = client.get('/api/admin/orders/export', headers=headers)
    assert export_res.status_code == 200
    assert 'text/csv' in export_res.content_type
