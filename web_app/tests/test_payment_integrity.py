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

@pytest.fixture
def client():
    with app.test_client() as client:
        yield client

def test_webhook_processing_and_payment_completion(client):
    # 1. 주문 생성
    option = query_db("SELECT * FROM product_options WHERE product_id = 1", one=True)
    res = client.post('/api/orders', json={
        'items': [{'product_id': 1, 'option_id': option['id'], 'quantity': 1}],
        'recipient_name': '이순신',
        'recipient_phone': '010-9999-8888',
        'postal_code': '06123',
        'address': '서울특별시 강남구 테헤란로 456',
        'guest_name': '이순신',
        'guest_phone': '010-9999-8888',
        'guest_password': 'password123'
    })
    order_data = res.get_json()
    order_number = order_data['order_number']
    total_amount = order_data['total_amount']

    # 2. Webhook 결제 통지 송신
    webhook_payload = {
        'type': 'Transaction.Paid',
        'paymentId': 'pay_test_webhook_unique_999',
        'timestamp': '1700000000',
        'data': {
            'transactionId': 'tx_test_999',
            'customData': {'order_number': order_number}
        }
    }

    webhook_res = client.post('/api/payment/webhook',
        data=json.dumps(webhook_payload),
        content_type='application/json'
    )
    assert webhook_res.status_code == 200

    # 3. DB 상태 검증 (CONFIRMED, PAID)
    order = query_db("SELECT * FROM orders WHERE order_number = %s", (order_number,), one=True)
    assert order['order_status'] == 'CONFIRMED'
    assert order['payment_status'] == 'PAID'

    # 4. 결제 취소 (환불 API) 검증
    cancel_res = client.post('/api/payment/cancel', json={
        'order_number': order_number,
        'amount': total_amount,
        'reason': '테스트 환불 요청'
    })
    assert cancel_res.status_code == 200
    cancel_data = cancel_res.get_json()
    assert cancel_data['payment_status'] == 'REFUNDED'

    updated_order = query_db("SELECT * FROM orders WHERE order_number = %s", (order_number,), one=True)
    assert updated_order['payment_status'] == 'REFUNDED'
    assert updated_order['order_status'] == 'CANCELLED'
