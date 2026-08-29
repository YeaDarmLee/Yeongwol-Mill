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
    execute_db("UPDATE product_options SET stock = 999, reserved_stock = 0 WHERE product_id = 1")



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

    # 5. 배송지 수정 및 운송장 등록 DB 반영 검증
    execute_db("UPDATE orders SET tracking_number = '1234567890', courier_name = 'CJ대한통운', order_status = 'SHIPPING' WHERE id = %s", (order_id,))
    ord_check = query_db("SELECT * FROM orders WHERE id = %s", (order_id,), one=True)
    assert ord_check['tracking_number'] == '1234567890'


def test_admin_shipping_address_update_frozen_spec(client):
    # 로그인
    login_res = client.post('/api/admin/login', json={'email': 'admin@yeongwol.com', 'password': 'admin1234'})
    token = login_res.get_json()['token']
    headers = {'Authorization': f'Bearer {token}'}

    # 1. 주문 생성
    option = query_db("SELECT * FROM product_options WHERE product_id = 1", one=True)
    order_res = client.post('/api/orders', json={
        'items': [{'product_id': 1, 'option_id': option['id'], 'quantity': 1}],
        'recipient_name': '이순신',
        'recipient_phone': '010-1111-2222',
        'postal_code': '06123',
        'address': '서울시 테헤란로 123',
        'guest_name': '이순신',
        'guest_phone': '010-1111-2222',
        'guest_password': 'password123'
    })
    assert order_res.status_code == 201, order_res.get_json()
    order_id = order_res.get_json()['order_id']
    execute_db("UPDATE orders SET order_status = 'PREPARING', payment_status = 'PAID' WHERE id = %s", (order_id,))

    # 2. 출고 전 정상 배송지 수정 (200 OK)
    update_res = client.put(f'/api/admin/orders/{order_id}/address', json={
        'recipient_name': '을지문덕',
        'recipient_phone': '010-9999-8888',
        'postal_code': '12345',
        'address': '강원도 영월군 방앗간길 1',
        'address_detail': '101호',
        'delivery_memo': '문앞에 놓아주세요',
        'reason_type': 'CUSTOMER_REQUEST',
        'reason_detail': '고객 요청으로 변경'
    }, headers=headers)
    assert update_res.status_code == 200
    res_data = update_res.get_json()
    assert res_data['success'] is True
    assert res_data['order']['recipient_name'] == '을지문덕'

    # AuditLog 생성 검증
    audit = query_db("SELECT * FROM admin_audit_logs WHERE action_type = 'ORDER_SHIPPING_ADDRESS_UPDATED' AND target_id = %s", (str(order_id),), one=True)
    assert audit is not None

    # 3. Validation 오류 검증 (우편번호 4자리 -> 400 VALIDATION_ERROR)
    val_res = client.put(f'/api/admin/orders/{order_id}/address', json={
        'recipient_name': '을지문덕',
        'recipient_phone': '010-9999-8888',
        'postal_code': '1234',
        'address': '주소',
        'reason_type': 'CUSTOMER_REQUEST'
    }, headers=headers)
    assert val_res.status_code == 400
    assert val_res.get_json()['error']['code'] == 'VALIDATION_ERROR'

    # 4. 기타 사유 시 상세 사유 누락 검증 -> 400
    val_res2 = client.put(f'/api/admin/orders/{order_id}/address', json={
        'recipient_name': '을지문덕',
        'recipient_phone': '010-9999-8888',
        'postal_code': '12345',
        'address': '주소',
        'reason_type': 'OTHER',
        'reason_detail': ''
    }, headers=headers)
    assert val_res2.status_code == 400

    # 5. 과거 CANCELLED Shipment가 있어도 활성 Shipment가 1개이면 정상 수정 허용
    execute_db("""
        INSERT INTO shipments (order_id, purpose, status, tracking_number, courier)
        VALUES (%s, 'FULFILLMENT', 'CANCELLED', '99999', 'CJ대한통운')
    """, (order_id,))
    execute_db("""
        INSERT INTO shipments (order_id, purpose, status, tracking_number, courier)
        VALUES (%s, 'FULFILLMENT', 'PENDING', '', 'EPOST')
    """, (order_id,))
    
    update_res2 = client.put(f'/api/admin/orders/{order_id}/address', json={
        'recipient_name': '신사임당',
        'recipient_phone': '010-5555-4444',
        'postal_code': '54321',
        'address': '강원도 강릉시',
        'address_detail': '',
        'delivery_memo': '',
        'reason_type': 'ADDRESS_TYPO',
        'reason_detail': '주소 오기입으로 변경'
    }, headers=headers)
    assert update_res2.status_code == 200

    # 6. 활성 FULFILLMENT Shipment가 2개 이상일 때 Fail-Closed 409
    execute_db("""
        INSERT INTO shipments (order_id, purpose, status, tracking_number, courier)
        VALUES (%s, 'FULFILLMENT', 'READY', '', 'HANJIN')
    """, (order_id,))
    conflict_res = client.put(f'/api/admin/orders/{order_id}/address', json={
        'recipient_name': '해커',
        'recipient_phone': '010-0000-0000',
        'postal_code': '54321',
        'address': '위조주소',
        'reason_type': 'CUSTOMER_REQUEST',
        'reason_detail': '고객 요청으로 변경'
    }, headers=headers)
    assert conflict_res.status_code == 409
    assert conflict_res.get_json()['error']['code'] == 'FULFILLMENT_STATE_CONFLICT'

    # 7. 출고 완료 (SHIPPING) 상태에서 수정 시도 시 409 차단
    execute_db("DELETE FROM shipments WHERE order_id = %s", (order_id,))
    execute_db("UPDATE orders SET order_status = 'SHIPPING' WHERE id = %s", (order_id,))
    shipped_block_res = client.put(f'/api/admin/orders/{order_id}/address', json={
        'recipient_name': '해커2',
        'recipient_phone': '010-0000-0000',
        'postal_code': '54321',
        'address': '위조주소2',
        'reason_type': 'CUSTOMER_REQUEST'
    }, headers=headers)
    assert shipped_block_res.status_code == 409
    assert shipped_block_res.get_json()['error']['code'] == 'SHIPPING_ADDRESS_UPDATE_NOT_ALLOWED'


def test_admin_ship_order_frozen_spec(client):
    # 로그인
    login_res = client.post('/api/admin/login', json={'email': 'admin@yeongwol.com', 'password': 'admin1234'})
    token = login_res.get_json()['token']
    headers = {'Authorization': f'Bearer {token}'}

    # 1. 주문 생성
    option = query_db("SELECT * FROM product_options WHERE product_id = 1", one=True)
    order_res = client.post('/api/orders', json={
        'items': [{'product_id': 1, 'option_id': option['id'], 'quantity': 1}],
        'recipient_name': '세종대왕',
        'recipient_phone': '010-3333-4444',
        'postal_code': '06123',
        'address': '서울시 종로구 세종로',
        'guest_name': '세종대왕',
        'guest_phone': '010-3333-4444',
        'guest_password': 'password123'
    })
    order_id = order_res.get_json()['order_id']
    execute_db("UPDATE orders SET order_status = 'PREPARING', payment_status = 'PAID' WHERE id = %s", (order_id,))
    execute_db("""
        INSERT INTO shipments (order_id, purpose, status, tracking_number, courier)
        VALUES (%s, 'FULFILLMENT', 'READY', '', 'CJ대한통운')
    """, (order_id,))

    # 2. PREPARING 정상 출고 (200 OK)
    ship_res = client.post(f'/api/admin/orders/{order_id}/shipment', json={
        'carrier_code': 'CJ_LOGISTICS',
        'tracking_number': 'CJ123456789'
    }, headers=headers)
    assert ship_res.status_code == 200
    res_data = ship_res.get_json()
    assert res_data['success'] is True
    assert res_data['order']['order_status'] == 'SHIPPING'
    assert res_data['tracking_number'] == 'CJ123456789'

    # AuditLog 생성 검증
    audit = query_db("SELECT * FROM admin_audit_logs WHERE action_type = 'ORDER_SHIPPED' AND target_id = %s", (str(order_id),), one=True)
    assert audit is not None

    # 3. 이미 운송장 존재 시 재출고 차단 (409 TRACKING_ALREADY_REGISTERED)
    re_ship_res = client.post(f'/api/admin/orders/{order_id}/shipment', json={
        'carrier_code': 'CJ_LOGISTICS',
        'tracking_number': 'CJ999999999'
    }, headers=headers)
    assert re_ship_res.status_code == 409
    assert re_ship_res.get_json()['error']['code'] == 'TRACKING_ALREADY_REGISTERED'

    # 4. PENDING 상태 주문 출고 차단 (409 ORDER_NOT_READY_FOR_SHIPMENT)
    order_res2 = client.post('/api/orders', json={
        'items': [{'product_id': 1, 'option_id': option['id'], 'quantity': 1}],
        'recipient_name': '정약용',
        'recipient_phone': '010-8888-7777',
        'postal_code': '06123',
        'address': '경기도 남양주시',
        'guest_name': '정약용',
        'guest_phone': '010-8888-7777',
        'guest_password': 'password123'
    })
    order_id2 = order_res2.get_json()['order_id']
    execute_db("""
        INSERT INTO shipments (order_id, purpose, status, tracking_number, courier)
        VALUES (%s, 'FULFILLMENT', 'PENDING', '', 'EPOST')
    """, (order_id2,))

    pending_ship_res = client.post(f'/api/admin/orders/{order_id2}/shipment', json={
        'carrier_code': 'EPOST',
        'tracking_number': 'EP12345678'
    }, headers=headers)
    assert pending_ship_res.status_code == 409
    assert pending_ship_res.get_json()['error']['code'] == 'ORDER_NOT_READY_FOR_SHIPMENT'

    # 5. 잘못된 carrier_code (400 VALIDATION_ERROR)
    bad_carrier_res = client.post(f'/api/admin/orders/{order_id2}/shipment', json={
        'carrier_code': 'UNKNOWN_CARRIER',
        'tracking_number': 'EP12345678'
    }, headers=headers)
    assert bad_carrier_res.status_code == 400
    assert bad_carrier_res.get_json()['error']['code'] == 'VALIDATION_ERROR'

    # 6. 활성 FULFILLMENT Shipment가 0개일 때 (409 FULFILLMENT_NOT_FOUND)
    execute_db("UPDATE orders SET order_status = 'PREPARING' WHERE id = %s", (order_id2,))
    execute_db("DELETE FROM shipments WHERE order_id = %s", (order_id2,))
    no_ship_res = client.post(f'/api/admin/orders/{order_id2}/shipment', json={
        'carrier_code': 'EPOST',
        'tracking_number': 'EP12345678'
    }, headers=headers)
    assert no_ship_res.status_code == 409
    assert no_ship_res.get_json()['error']['code'] == 'FULFILLMENT_NOT_FOUND'



    order = query_db("SELECT * FROM orders WHERE id = %s", (order_id,), one=True)
    assert order['courier_name'] == 'CJ대한통운'
    assert order['tracking_number'] == 'CJ123456789'
    assert order['order_status'] == 'SHIPPING'

    # 5. CSV 내보내기 테스트
    export_res = client.get('/api/admin/orders/export', headers=headers)
    assert export_res.status_code == 200
    assert 'text/csv' in export_res.content_type


def test_admin_product_summary_frozen_spec(client):
    login_res = client.post('/api/admin/login', json={'email': 'admin@yeongwol.com', 'password': 'admin1234'})
    token = login_res.get_json()['token']
    headers = {'Authorization': f'Bearer {token}'}

    # 1. 3개 품목 주문 생성
    opt1 = query_db("SELECT id FROM product_options WHERE product_id = 1 LIMIT 1", one=True)
    order_res = client.post('/api/orders', json={
        'items': [
            {'product_id': 1, 'option_id': opt1['id'], 'quantity': 1},
            {'product_id': 1, 'option_id': opt1['id'], 'quantity': 2}
        ],
        'recipient_name': '허균',
        'recipient_phone': '010-4444-5555',
        'postal_code': '06123',
        'address': '강원도 강릉시',
        'guest_name': '허균',
        'guest_phone': '010-4444-5555',
        'guest_password': 'password123'
    })
    assert order_res.status_code == 201
    order_id = order_res.get_json()['order_id']

    # 2. GET /api/admin/orders 조회의 product_summary Batching 검증
    get_res = client.get('/api/admin/orders', headers=headers)
    assert get_res.status_code == 200
    orders = get_res.get_json()['orders']
    target_ord = next((o for o in orders if o['id'] == order_id), None)
    assert target_ord is not None
    summary = target_ord['product_summary']
    assert summary is not None
    assert summary['total_quantity'] >= 1
    assert len(summary['items']) >= 1

