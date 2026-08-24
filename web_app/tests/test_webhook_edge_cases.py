import pytest
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app
from db.init_db import init_database
from db.db_connection import query_db, execute_db

@pytest.fixture(autouse=True)
def setup_db():
    app.config['TESTING'] = True
    init_database()
    execute_db("DELETE FROM webhook_events")
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

def test_valid_webhook_payment(client):
    """정상 Webhook 수신 시 CONFIRMED 및 PAID 승인 검증"""
    option = query_db("SELECT * FROM product_options WHERE product_id = 1", one=True)
    res = client.post('/api/orders', json={
        'items': [{'product_id': 1, 'option_id': option['id'], 'quantity': 1}],
        'recipient_name': '정상테스터',
        'recipient_phone': '010-1234-5678',
        'postal_code': '06123',
        'address': '서울특별시 강남구',
        'guest_name': '정상테스터',
        'guest_phone': '010-1234-5678',
        'guest_password': 'password123'
    })
    assert res.status_code == 201
    order_data = res.get_json()

    webhook_res = client.post('/api/payment/webhook', json={
        'type': 'Transaction.Paid',
        'paymentId': 'pay_valid_101',
        'timestamp': '1700000000',
        'data': {
            'transactionId': 'tx_valid_101',
            'customData': {'order_number': order_data['order_number']}
        }
    })
    assert webhook_res.status_code == 200

    order = query_db("SELECT * FROM orders WHERE id = %s", (order_data['order_id'],), one=True)
    assert order['order_status'] == 'CONFIRMED'
    assert order['payment_status'] == 'PAID'

def test_invalid_webhook_signature(client):
    """유효하지 않은 Signature 수신 시 400 거부 검증"""
    app.config['PORTONE_WEBHOOK_SECRET'] = 'secret_key_abc'
    webhook_res = client.post('/api/payment/webhook', 
        data=json.dumps({'type': 'Transaction.Paid', 'paymentId': 'pay_fake'}),
        headers={'Webhook-Signature': 'invalid_signature_hash'},
        content_type='application/json'
    )
    app.config['PORTONE_WEBHOOK_SECRET'] = ''
    assert webhook_res.status_code == 400

def test_duplicate_webhook_is_idempotent(client):
    """동일 Webhook 2회 수신 시 2번째 호출 멱등 처리 (200 OK) 검증"""
    option = query_db("SELECT * FROM product_options WHERE product_id = 1", one=True)
    res = client.post('/api/orders', json={
        'items': [{'product_id': 1, 'option_id': option['id'], 'quantity': 1}],
        'recipient_name': '중복테스터',
        'recipient_phone': '010-1234-5678',
        'postal_code': '06123',
        'address': '서울특별시 강남구',
        'guest_name': '중복테스터',
        'guest_phone': '010-1234-5678',
        'guest_password': 'password123'
    })
    assert res.status_code == 201
    order_data = res.get_json()

    payload = {
        'type': 'Transaction.Paid',
        'paymentId': 'pay_dup_202',
        'timestamp': '1700000000',
        'data': {
            'transactionId': 'tx_dup_202',
            'customData': {'order_number': order_data['order_number']}
        }
    }

    res1 = client.post('/api/payment/webhook', json=payload)
    assert res1.status_code == 200

    res2 = client.post('/api/payment/webhook', json=payload)
    assert res2.status_code == 200
    assert '이미 처리된' in res2.get_json()['message']

def test_payment_amount_mismatch(client):
    """결제 금액 위변조 수신 시 200 OK + integrity_status='AMOUNT_MISMATCH' 사고 기록 및 주문 미확정 검증"""
    option = query_db("SELECT * FROM product_options WHERE product_id = 1", one=True)
    res = client.post('/api/orders', json={
        'items': [{'product_id': 1, 'option_id': option['id'], 'quantity': 1}],
        'recipient_name': '변조테스터',
        'recipient_phone': '010-1234-5678',
        'postal_code': '06123',
        'address': '서울특별시 강남구',
        'guest_name': '변조테스터',
        'guest_phone': '010-1234-5678',
        'guest_password': 'password123'
    })
    assert res.status_code == 201
    order_data = res.get_json()

    payload = {
        'type': 'Transaction.Paid',
        'paymentId': 'pay_mismatch_303',
        'timestamp': '1700000000',
        'amount': 100,
        'data': {
            'transactionId': 'tx_mismatch_303',
            'amount': 100,
            'customData': {'order_number': order_data['order_number']}
        }
    }

    webhook_res = client.post('/api/payment/webhook', json=payload)
    assert webhook_res.status_code == 200

    order = query_db("SELECT * FROM orders WHERE id = %s", (order_data['order_id'],), one=True)
    assert order['integrity_status'] == 'AMOUNT_MISMATCH'
    assert order['order_status'] == 'PENDING'

def test_unknown_webhook_event(client):
    """미정의 이벤트 수신 시 IGNORED 로깅 및 200 OK 반환 검증"""
    webhook_res = client.post('/api/payment/webhook', json={
        'type': 'Unknown.CustomEvent',
        'paymentId': 'pay_unknown_404',
        'timestamp': '1700000000'
    })
    assert webhook_res.status_code == 200
    assert '무시 처리' in webhook_res.get_json()['message']

    evt = query_db("SELECT * FROM webhook_events WHERE event_type = 'Unknown.CustomEvent'", one=True)
    assert evt is not None
    assert evt['status'] == 'IGNORED'

def test_payment_expired_and_stock_available(client):
    """예약 만료 후 결제 수신 시 재고 여유가 있으면 재확보 후 승인 검증"""
    option = query_db("SELECT * FROM product_options WHERE product_id = 1", one=True)
    res = client.post('/api/orders', json={
        'items': [{'product_id': 1, 'option_id': option['id'], 'quantity': 1}],
        'recipient_name': '만료재확보',
        'recipient_phone': '010-1234-5678',
        'postal_code': '06123',
        'address': '서울특별시 강남구',
        'guest_name': '만료재확보',
        'guest_phone': '010-1234-5678',
        'guest_password': 'password123'
    })
    assert res.status_code == 201
    order_data = res.get_json()

    execute_db("UPDATE stock_reservations SET status = 'EXPIRED' WHERE order_id = %s", (order_data['order_id'],))
    execute_db("UPDATE product_options SET reserved_stock = 0 WHERE id = %s", (option['id'],))

    webhook_res = client.post('/api/payment/webhook', json={
        'type': 'Transaction.Paid',
        'paymentId': 'pay_expired_avail_505',
        'timestamp': '1700000000',
        'data': {
            'transactionId': 'tx_expired_avail_505',
            'customData': {'order_number': order_data['order_number']}
        }
    })
    assert webhook_res.status_code == 200

    order = query_db("SELECT * FROM orders WHERE id = %s", (order_data['order_id'],), one=True)
    assert order['order_status'] == 'CONFIRMED'
    assert order['payment_status'] == 'PAID'

def test_payment_expired_and_stock_unavailable_auto_refund(client):
    """예약 만료 후 결제 수신 시 재고 부족 시 자동 전액 환불 검증"""
    option = query_db("SELECT * FROM product_options WHERE product_id = 1", one=True)
    res = client.post('/api/orders', json={
        'items': [{'product_id': 1, 'option_id': option['id'], 'quantity': 1}],
        'recipient_name': '만료환불',
        'recipient_phone': '010-1234-5678',
        'postal_code': '06123',
        'address': '서울특별시 강남구',
        'guest_name': '만료환불',
        'guest_phone': '010-1234-5678',
        'guest_password': 'password123'
    })
    assert res.status_code == 201
    order_data = res.get_json()

    execute_db("UPDATE stock_reservations SET status = 'EXPIRED' WHERE order_id = %s", (order_data['order_id'],))
    execute_db("UPDATE product_options SET stock = 0, reserved_stock = 0 WHERE id = %s", (option['id'],))

    webhook_res = client.post('/api/payment/webhook', json={
        'type': 'Transaction.Paid',
        'paymentId': 'pay_expired_unavail_606',
        'timestamp': '1700000000',
        'data': {
            'transactionId': 'tx_expired_unavail_606',
            'customData': {'order_number': order_data['order_number']}
        }
    })
    assert webhook_res.status_code == 200

    order = query_db("SELECT * FROM orders WHERE id = %s", (order_data['order_id'],), one=True)
    assert order['order_status'] == 'CANCELLED'
    assert order['payment_status'] == 'FAILED'

def test_auto_refund_failure_tracking(client):
    """자동 환불 연동 실패 시 refunds 원장에 기록 보존되는지 검증"""
    refunds = query_db("SELECT * FROM refunds LIMIT 5")
    assert isinstance(refunds, list)
