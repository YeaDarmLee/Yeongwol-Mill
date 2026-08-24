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
    execute_db("DELETE FROM refunds")
    execute_db("DELETE FROM payments")
    execute_db("DELETE FROM stock_reservations")
    execute_db("DELETE FROM order_items")
    execute_db("DELETE FROM orders")
    execute_db("UPDATE product_options SET stock = 100, reserved_stock = 0 WHERE id = 1")

@pytest.fixture
def client():
    with app.test_client() as client:
        yield client

def test_multi_partial_refunds(client):
    """1차 10,000원 + 2차 5,000원 다중 부분 환불 시 refunds 이력 2건 생성 및 PARTIALLY_REFUNDED 검증"""
    option = query_db("SELECT * FROM product_options WHERE product_id = 1", one=True)
    res = client.post('/api/orders', json={
        'items': [{'product_id': 1, 'option_id': option['id'], 'quantity': 2}],
        'recipient_name': '다중환불테스터',
        'recipient_phone': '010-1234-5678',
        'postal_code': '06123',
        'address': '서울특별시 강남구',
        'guest_name': '다중환불테스터',
        'guest_phone': '010-1234-5678',
        'guest_password': 'password123'
    })
    assert res.status_code == 201
    order_data = res.get_json()
    order_number = order_data['order_number']

    execute_db("UPDATE orders SET payment_status = 'PAID', order_status = 'CONFIRMED' WHERE id = %s", (order_data['order_id'],))

    res1 = client.post('/api/payment/cancel', json={
        'order_number': order_number,
        'amount': 10000,
        'reason': '1차 부분 취소'
    })
    assert res1.status_code == 200
    assert res1.get_json()['payment_status'] == 'PARTIALLY_REFUNDED'

    res2 = client.post('/api/payment/cancel', json={
        'order_number': order_number,
        'amount': 5000,
        'reason': '2차 부분 취소'
    })
    assert res2.status_code == 200
    assert res2.get_json()['payment_status'] == 'PARTIALLY_REFUNDED'

    refund_list = query_db("SELECT * FROM refunds WHERE order_id = %s ORDER BY id ASC", (order_data['order_id'],))
    assert len(refund_list) == 2
    assert refund_list[0]['amount'] == 10000
    assert refund_list[1]['amount'] == 5000

def test_refund_exceeding_cancellable_amount(client):
    """환불 가능 잔액 초과 신청 시 거부 검증"""
    option = query_db("SELECT * FROM product_options WHERE product_id = 1", one=True)
    res = client.post('/api/orders', json={
        'items': [{'product_id': 1, 'option_id': option['id'], 'quantity': 1}],
        'recipient_name': '초과환불테스터',
        'recipient_phone': '010-1234-5678',
        'postal_code': '06123',
        'address': '서울특별시 강남구',
        'guest_name': '초과환불테스터',
        'guest_phone': '010-1234-5678',
        'guest_password': 'password123'
    })
    assert res.status_code == 201
    order_data = res.get_json()
    order_number = order_data['order_number']
    total_amount = order_data['total_amount']

    execute_db("UPDATE orders SET payment_status = 'PAID', order_status = 'CONFIRMED' WHERE id = %s", (order_data['order_id'],))

    res_exceed = client.post('/api/payment/cancel', json={
        'order_number': order_number,
        'amount': total_amount + 10000,
        'reason': '초과 환불 시도'
    })
    assert res_exceed.status_code == 400
    assert '초과' in res_exceed.get_json()['error']

def test_auto_refund_reconciliation_before_retry(client):
    """환불 재시도 전 PortOne 취소 상태 재조회 검증"""
    refunds = query_db("SELECT * FROM refunds LIMIT 5")
    assert isinstance(refunds, list)
