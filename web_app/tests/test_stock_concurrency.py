import pytest
import sys
import os
import datetime
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app
from db.init_db import init_database
from db.db_connection import query_db, execute_db

@pytest.fixture(autouse=True)
def setup_db():
    app.config['TESTING'] = True
    init_database()
    execute_db("DELETE FROM stock_reservations")
    execute_db("DELETE FROM order_items")
    execute_db("DELETE FROM orders")
    # 1번 상품 1번 옵션 재고=1, reserved_stock=0 으로 초기화
    execute_db("UPDATE product_options SET stock = 1, reserved_stock = 0 WHERE id = 1")

@pytest.fixture
def client():
    with app.test_client() as client:
        yield client

def test_concurrent_orders_race_condition(client):
    """재고 1개 상품에 10개 병렬 요청 동시 주문시 1건 성공, 9건 거부 및 Overselling 0건 검증"""
    results = []

    def make_order():
        with app.test_client() as thread_client:
            res = thread_client.post('/api/orders', json={
                'items': [{'product_id': 1, 'option_id': 1, 'quantity': 1}],
                'recipient_name': '동시성테스터',
                'recipient_phone': '010-1111-2222',
                'postal_code': '06123',
                'address': '서울특별시 강남구',
                'guest_name': '동시성테스터',
                'guest_phone': '010-1111-2222',
                'guest_password': 'password123'
            })
            return res.status_code

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(make_order) for _ in range(10)]
        for f in futures:
            results.append(f.result())

    success_count = results.count(201)
    fail_count = results.count(400)

    # 1건 성공, 9건 실패
    assert success_count == 1, f"Expected 1 successful reservation, got {success_count}"
    assert fail_count == 9, f"Expected 9 rejected reservations, got {fail_count}"

    # final db state check
    opt = query_db("SELECT * FROM product_options WHERE id = 1", one=True)
    assert opt['stock'] == 1
    assert opt['reserved_stock'] == 1
    assert (opt['stock'] - opt['reserved_stock']) == 0

def test_expire_reservations_worker_execution(client):
    """15분 경과한 예약건 대상 expire-reservations 실행 시 reserved_stock 0 복구 및 status='EXPIRED' 검증"""
    # 1. 예약 생성
    client.post('/api/orders', json={
        'items': [{'product_id': 1, 'option_id': 1, 'quantity': 1}],
        'recipient_name': '만료테스터',
        'recipient_phone': '010-1111-2222',
        'postal_code': '06123',
        'address': '서울특별시 강남구',
        'guest_name': '만료테스터',
        'guest_phone': '010-1111-2222',
        'guest_password': 'password123'
    })

    # 2. expires_at을 과거로 강제 변경
    past_time = (datetime.datetime.now() - datetime.timedelta(minutes=20)).strftime('%Y-%m-%d %H:%M:%S')
    execute_db("UPDATE stock_reservations SET expires_at = %s WHERE status = 'RESERVED'", (past_time,))

    # 3. CLI expire-reservations 실행
    runner = app.test_cli_runner()
    result = runner.invoke(args=["expire-reservations"])
    assert result.exit_code == 0

    # 4. 검증
    opt = query_db("SELECT * FROM product_options WHERE id = 1", one=True)
    assert opt['reserved_stock'] == 0

    res = query_db("SELECT * FROM stock_reservations ORDER BY id DESC LIMIT 1", one=True)
    assert res['status'] == 'EXPIRED'

def test_expiration_vs_webhook_stock_available(client):
    """예약 만료 후 결제 Webhook 수신 시 재고 여유가 있으면 재확보 및 CONFIRMED/PAID 검증"""
    # 1. 주문 생성
    res = client.post('/api/orders', json={
        'items': [{'product_id': 1, 'option_id': 1, 'quantity': 1}],
        'recipient_name': '만료결제테스터',
        'recipient_phone': '010-1111-2222',
        'postal_code': '06123',
        'address': '서울특별시 강남구',
        'guest_name': '만료결제테스터',
        'guest_phone': '010-1111-2222',
        'guest_password': 'password123'
    })
    order_data = res.get_json()
    order_number = order_data['order_number']

    # 2. 강제 만료 처리 (expires_at 과거로 변경 및 status EXPIRED)
    past_time = (datetime.datetime.now() - datetime.timedelta(minutes=20)).strftime('%Y-%m-%d %H:%M:%S')
    execute_db("UPDATE stock_reservations SET expires_at = %s, status = 'EXPIRED' WHERE order_id = %s", (past_time, order_data['order_id']))
    execute_db("UPDATE product_options SET reserved_stock = 0 WHERE id = 1")

    # 3. Webhook 수신
    webhook_res = client.post('/api/payment/webhook', json={
        'type': 'Transaction.Paid',
        'paymentId': 'pay_expired_stock_avail_99',
        'timestamp': '1700000000',
        'data': {
            'transactionId': 'tx_expired_stock_avail_99',
            'customData': {'order_number': order_number}
        }
    })
    assert webhook_res.status_code == 200

    order = query_db("SELECT * FROM orders WHERE order_number = %s", (order_number,), one=True)
    assert order['order_status'] == 'CONFIRMED'
    assert order['payment_status'] == 'PAID'

def test_expiration_vs_webhook_stock_unavailable(client):
    """예약 만료 후 타 고객 선점으로 재고 부족 시 자동 전액 환불 및 CANCELLED/FAILED 검증"""
    # 1. 주문 생성
    res = client.post('/api/orders', json={
        'items': [{'product_id': 1, 'option_id': 1, 'quantity': 1}],
        'recipient_name': '만료재고부족테스터',
        'recipient_phone': '010-1111-2222',
        'postal_code': '06123',
        'address': '서울특별시 강남구',
        'guest_name': '만료재고부족테스터',
        'guest_phone': '010-1111-2222',
        'guest_password': 'password123'
    })
    order_data = res.get_json()
    order_number = order_data['order_number']

    # 2. 예약 만료 처리 및 타 고객이 재고 1개 소진 (stock=0)
    past_time = (datetime.datetime.now() - datetime.timedelta(minutes=20)).strftime('%Y-%m-%d %H:%M:%S')
    execute_db("UPDATE stock_reservations SET expires_at = %s, status = 'EXPIRED' WHERE order_id = %s", (past_time, order_data['order_id']))
    execute_db("UPDATE product_options SET stock = 0, reserved_stock = 0 WHERE id = 1")

    # 3. 만료된 주문 Webhook 도착
    webhook_res = client.post('/api/payment/webhook', json={
        'type': 'Transaction.Paid',
        'paymentId': 'pay_expired_stock_unavail_88',
        'timestamp': '1700000000',
        'data': {
            'transactionId': 'tx_expired_stock_unavail_88',
            'customData': {'order_number': order_number}
        }
    })
    assert webhook_res.status_code == 200

    order = query_db("SELECT * FROM orders WHERE order_number = %s", (order_number,), one=True)
    assert order['order_status'] == 'CANCELLED'
    assert order['payment_status'] == 'FAILED'

    refund = query_db("SELECT * FROM refunds WHERE order_id = %s", (order['id'],), one=True)
    assert refund is not None
    assert refund['status'] == 'COMPLETED'
