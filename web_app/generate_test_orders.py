import datetime
import random
import sys
import os

# web_app 경로 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from db.db_connection import query_db, execute_db
from middlewares.auth import hash_password

def generate_mock_orders():
    print("=== 테스트 주문 데이터 30건 생성 시작 ===")
    
    # 1. 테스트용 상품 목록 확보
    products = query_db("SELECT p.*, o.id as opt_id, o.option_name, o.additional_price FROM products p JOIN product_options o ON p.id = o.product_id WHERE p.is_active = 1")
    if not products:
        products = query_db("SELECT p.*, o.id as opt_id, o.option_name, o.additional_price FROM products p JOIN product_options o ON p.id = o.product_id")
    
    if not products:
        print("오류: DB에 등록된 상품이 없습니다.")
        return

    # 2. 테스트용 고객 몇 명 생성/선택
    customers_data = [
        ('김철수', 'chulsoo@example.com', '010-1234-5678'),
        ('이영희', 'younghee@example.com', '010-2345-6789'),
        ('박민수', 'minsoo@example.com', '010-3456-7890'),
        ('최지은', 'jieun@example.com', '010-4567-8901'),
        ('정다은', 'daeun@example.com', '010-5678-9012'),
        ('강동원', 'dongwon@example.com', '010-6789-0123'),
        ('한소희', 'sohee@example.com', '010-7890-1234'),
        ('윤서준', 'seojun@example.com', '010-8901-2345')
    ]
    
    user_ids = []
    for name, email, phone in customers_data:
        u = query_db("SELECT id FROM users WHERE email = %s", (email,), one=True)
        if not u:
            pass_h = hash_password('test1234!')
            uid = execute_db(
                "INSERT INTO users (email, password_hash, name, phone, status) VALUES (%s, %s, %s, %s, 'ACTIVE')",
                (email, pass_h, name, phone)
            )
            user_ids.append(uid)
        else:
            user_ids.append(u['id'])

    # 주문 상태 & 결제 상태 패턴 조합 (총 30건)
    # (order_status, payment_status, days_ago, tracking_number, courier_name, integrity_status, refund_status)
    scenarios = [
        # 오늘자 주문 8건 (대시보드 KPI 및 Work Queue 바로 반영)
        ('PREPARING', 'PAID', 0, None, None, 'NORMAL', None),
        ('PREPARING', 'PAID', 0, None, None, 'NORMAL', None),
        ('PREPARING', 'PAID', 0, '1234567890', 'CJ대한통운', 'NORMAL', None),
        ('PENDING', 'PENDING', 0, None, None, 'NORMAL', None),
        ('CONFIRMED', 'PAID', 0, None, None, 'NORMAL', None),
        ('CONFIRMED', 'PAID', 0, None, None, 'AMOUNT_MISMATCH', None),
        ('CANCELLED', 'REFUNDED', 0, None, None, 'NORMAL', 'COMPLETED'),
        ('PREPARING', 'PAID', 0, None, None, 'NORMAL', 'PROCESSING'),
        
        # 최근 1~7일 주문 12건
        ('SHIPPING', 'PAID', 1, '9876543210', '우체국택배', 'NORMAL', None),
        ('SHIPPING', 'PAID', 1, '5544332211', '한진택배', 'NORMAL', None),
        ('DELIVERED', 'PAID', 2, '1122334455', 'CJ대한통운', 'NORMAL', None),
        ('DELIVERED', 'PAID', 3, '9988776655', '롯데택배', 'NORMAL', None),
        ('DELIVERED', 'PAID', 3, '7766554433', 'CJ대한통운', 'NORMAL', None),
        ('CANCELLED', 'REFUNDED', 4, '4433221100', 'CJ대한통운', 'NORMAL', 'COMPLETED'),
        ('PREPARING', 'PARTIALLY_REFUNDED', 4, None, None, 'NORMAL', 'COMPLETED'),
        ('PREPARING', 'PAID', 5, None, None, 'NORMAL', 'RECONCILING'),
        ('DELIVERED', 'PAID', 5, '3322114455', '우체국택배', 'NORMAL', None),
        ('DELIVERED', 'PAID', 6, '6677889900', 'CJ대한통운', 'NORMAL', None),
        ('CANCELLED', 'FAILED', 6, None, None, 'NORMAL', None),
        ('PENDING', 'PENDING', 7, None, None, 'NORMAL', None),

        # 8~30일 전 주문 10건
        ('DELIVERED', 'PAID', 10, '1020304050', 'CJ대한통운', 'NORMAL', None),
        ('DELIVERED', 'PAID', 12, '2030405060', '우체국택배', 'NORMAL', None),
        ('DELIVERED', 'PAID', 15, '3040506070', '한진택배', 'NORMAL', None),
        ('DELIVERED', 'PAID', 18, '4050607080', 'CJ대한통운', 'NORMAL', None),
        ('CANCELLED', 'REFUNDED', 20, '5060708090', '롯데택배', 'NORMAL', 'COMPLETED'),
        ('DELIVERED', 'PAID', 22, '6070809000', 'CJ대한통운', 'NORMAL', None),
        ('DELIVERED', 'PAID', 25, '7080900011', '우체국택배', 'NORMAL', None),
        ('DELIVERED', 'PAID', 27, '8090001122', 'CJ대한통운', 'NORMAL', None),
        ('DELIVERED', 'PAID', 29, '9000112233', '한진택배', 'NORMAL', None),
        ('DELIVERED', 'PAID', 30, '0011223344', 'CJ대한통운', 'NORMAL', None),
    ]

    now_dt = datetime.datetime.now()
    created_count = 0

    for idx, sc in enumerate(scenarios, start=1):
        ord_status, pay_status, days_ago, tracking_no, courier, integrity, refund_st = sc
        
        # 날짜 세팅
        target_dt = now_dt - datetime.timedelta(days=days_ago, hours=random.randint(1, 10), minutes=random.randint(1, 59))
        dt_str = target_dt.strftime('%Y-%m-%d %H:%M:%S')

        # 무작위 고객
        cust_idx = random.randint(0, len(customers_data) - 1)
        cust_name, cust_email, cust_phone = customers_data[cust_idx]
        uid = user_ids[cust_idx]

        # 무작위 상품 선택 (1~3개)
        item_count = random.randint(1, 2)
        selected_prods = random.sample(products, min(item_count, len(products)))

        subtotal = 0
        items_payload = []
        for p in selected_prods:
            qty = random.randint(1, 3)
            b_price = p['price']
            a_price = p['additional_price'] or 0
            final_u = b_price + a_price
            item_sub = final_u * qty
            subtotal += item_sub
            items_payload.append({
                'prod_id': p['id'],
                'opt_id': p['opt_id'],
                'name': p['name'],
                'opt_name': p['option_name'] or '기본옵션',
                'capacity': p.get('capacity', '300ml'),
                'qty': qty,
                'b_price': b_price,
                'a_price': a_price,
                'final_u': final_u,
                'subtotal': item_sub
            })

        order_num = f"YW-{target_dt.strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
        
        # orders insert
        order_id = execute_db(
            """INSERT INTO orders (
                order_number, user_id, recipient_name, recipient_phone,
                postal_code, address, address_detail, delivery_memo,
                subtotal_amount, discount_amount, total_amount,
                payment_status, order_status, courier_name, tracking_number,
                shipped_at, integrity_status, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                order_num, uid, cust_name, cust_phone,
                '25000', '강원특별자치도 영월군 영월읍 방앗간길 88', f'{random.randint(101, 502)}호',
                '부재시 문앞에 두세요', subtotal, 0, subtotal,
                pay_status, ord_status, courier, tracking_no,
                dt_str if tracking_no else None, integrity, dt_str
            )
        )

        # order_items insert
        for it in items_payload:
            execute_db(
                """INSERT INTO order_items (
                    order_id, product_id, option_id,
                    product_name_snapshot, option_name_snapshot, capacity,
                    quantity, unit_price, option_price, final_unit_price, subtotal
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    order_id, it['prod_id'], it['opt_id'],
                    it['name'], it['opt_name'], it['capacity'],
                    it['qty'], it['b_price'], it['a_price'], it['final_u'], it['subtotal']
                )
            )

        # 결제 내역 (payments)
        if pay_status in ('PAID', 'PARTIALLY_REFUNDED', 'REFUNDED'):
            execute_db(
                """INSERT INTO payments (
                    order_id, payment_id, transaction_id, pg_provider, method, status, amount, paid_at, created_at
                ) VALUES (%s, %s, %s, 'PORTONE', 'CARD', 'PAID', %s, %s, %s)""",
                (order_id, f"PAY_{order_num}", f"TX_{order_num}", subtotal, dt_str, dt_str)
            )

        # 환불 내역 (refund_requests) - 환불 관련 시나리오인 경우
        if refund_st:
            ref_amt = subtotal if refund_st == 'COMPLETED' else int(subtotal * 0.5)
            execute_db(
                """INSERT INTO refund_requests (
                    order_id, operation_id, request_fingerprint, idempotency_key,
                    portone_payment_id, requested_amount, confirmed_refund_amount,
                    cancellable_amount_before, status, reason, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    order_id, f"OP_{order_id}", f"FP_{order_id}", f"IDEM_{order_id}",
                    f"PAY_{order_num}", ref_amt, ref_amt if refund_st == 'COMPLETED' else 0,
                    subtotal, refund_st, '고객 단순 변심 및 상품 변경 요청', dt_str, dt_str
                )
            )

        created_count += 1
        print(f"[{created_count}/30] 주문 생성 완료 - ID: {order_id}, 번호: {order_num}, 상태: {ord_status}/{pay_status}, 수령인: {cust_name}, 금액: {subtotal:,}원")

    print(f"\n총 {created_count}건의 다양한 테스트 주문 데이터가 성공적으로 생성되었습니다!")

if __name__ == '__main__':
    generate_mock_orders()
