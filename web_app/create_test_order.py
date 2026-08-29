import sys
import os
import random
import datetime

# 백엔드 모듈 경로 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db.db_connection import query_db, execute_db

# 한국인 랜덤 성명 & 주소 샘플
NAMES = ["김철수", "이영희", "박상민", "최지우", "정우성", "강하늘", "윤아름", "임재현", "송민지", "오동건"]
CITIES = [
    ("06164", "서울특별시 강남구 테헤란로 123", "4층 402호"),
    ("26233", "강원특별자치도 영월군 영월읍 하송리 456", "102동 304호"),
    ("13494", "경기도 성남시 분당구 판교역로 99", "701호"),
    ("48118", "부산광역시 해운대구 마린시티1로 50", "1503호"),
    ("34134", "대전광역시 유성구 대학로 100", "201호"),
    ("42100", "대구광역시 수성구 달구벌대로 300", "505호")
]

PAYMENT_METHODS = ["CARD", "KAKAOPAY", "NAVERPAY", "TRANS"]

def clean_all_orders_data():
    """모든 기존 주문, 배송, 환불 및 알림 관련 테스트 데이터 초기화"""
    print("[CLEAN] 기존 전체 주문/배송/환불 테스트 데이터를 완전히 초기화합니다...")
    tables = [
        "notification_attempts",
        "notification_jobs",
        "cancellation_request_items",
        "cancellation_requests",
        "refund_request_items",
        "refund_requests",
        "shipment_items",
        "shipments",
        "order_items",
        "orders"
    ]
    for table in tables:
        try:
            execute_db(f"DELETE FROM {table}")
        except Exception as e:
            print(f"  - Table {table} clean warning: {e}")
    print("[CLEAN 완료] DB 초기화가 성공적으로 완료되었습니다.\n")

def create_single_test_order(status="CONFIRMED", is_paid=True):
    """영월고향방앗간 신규 테스트 주문 생성"""
    now = datetime.datetime.now()
    date_str = now.strftime("%Y%m%d")
    rand_seq = random.randint(1000, 9999)
    order_number = f"ORD-{date_str}-{rand_seq}"

    # 상품 목록 조회
    products = query_db("SELECT id, name, price FROM products LIMIT 10") or []
    if not products:
        print("❌ 상품 데이터가 없습니다. 먼저 상품 시드가 존재하는지 확인해 주세요.")
        return False

    # 랜덤 상품 1~2개 선택
    selected_prods = random.sample(products, k=random.randint(1, min(2, len(products))))
    
    subtotal = 0
    items_data = []
    for p in selected_prods:
        qty = random.randint(1, 2)
        price = p['price']
        item_gross = price * qty
        subtotal += item_gross
        items_data.append({
            'product_id': p['id'],
            'product_name': p['name'],
            'option_name': '기본 300ml' if '기름' in p['name'] else '기본선택',
            'quantity': qty,
            'price': price,
            'item_gross': item_gross
        })

    # order_name 생성 (데이터 완결성 보장)
    first_name = items_data[0]['product_name']
    first_qty = items_data[0]['quantity']
    if len(items_data) == 1:
        order_name = f"{first_name} {first_qty}개"
    else:
        order_name = f"{first_name} 외 {len(items_data) - 1}건"

    shipping_fee = 0 if subtotal >= 50000 else 3000
    total_amount = subtotal + shipping_fee

    name = random.choice(NAMES)
    phone = f"010-{random.randint(1000,9999)}-{random.randint(1000,9999)}"
    postal, addr, addr_detail = random.choice(CITIES)
    pay_method = random.choice(PAYMENT_METHODS)
    pay_status = "PAID" if is_paid else "PENDING"

    # 1. orders INSERT
    execute_db("""
        INSERT INTO orders (
            order_number, user_id, recipient_name, recipient_phone, postal_code,
            address, address_detail, delivery_memo, order_status, payment_status,
            total_amount, subtotal_amount, base_shipping_fee,
            refund_calculation_mode, created_at
        ) VALUES (%s, 1, %s, %s, %s, %s, %s, '신규 테스트 주문입니다.', %s, %s, %s, %s, %s, 'AUTO', %s)
    """, (order_number, name, phone, postal, addr, addr_detail, status, pay_status, total_amount, subtotal, shipping_fee, now))

    # 생성된 order_id 조율
    ord_row = query_db("SELECT id FROM orders WHERE order_number = %s", (order_number,), one=True)
    if not ord_row:
        print("❌ 주문 생성에 실패했습니다.")
        return False
    order_id = ord_row['id']

    # 2. order_items INSERT
    for item in items_data:
        execute_db("""
            INSERT INTO order_items (
                order_id, product_id, product_name_snapshot, option_name_snapshot,
                quantity, unit_price, final_unit_price, subtotal, item_gross_amount,
                item_discount_allocated, item_paid_amount, cancelled_qty, refunded_qty
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, 0, 0)
        """, (
            order_id, item['product_id'], item['product_name'], item['option_name'],
            item['quantity'], item['price'], item['price'], item['item_gross'],
            item['item_gross'], item['item_gross']
        ))

    print("=" * 60)
    print(f"[성공] 신규 테스트 주문이 즉시 생성되었습니다!")
    print(f"  - 주문번호: {order_number} (ID: {order_id})")
    print(f"  - 주문명: {order_name}")
    print(f"  - 주문자명: {name} ({phone})")
    print(f"  - 주문상태: {status} | 결제상태: {pay_status}")
    print(f"  - 결제금액: {total_amount:,}원 (배송비: {shipping_fee:,}원)")
    print("  - 주문상품:")
    for it in items_data:
        print(f"    * {it['product_name']} x {it['quantity']}개 ({it['item_gross']:,}원)")
    print("=" * 60)
    return True

if __name__ == '__main__':
    clean_flag = True
    count = 5

    for arg in sys.argv[1:]:
        if arg == '--noclean':
            clean_flag = False
        elif arg.isdigit():
            count = int(arg)

    if clean_flag:
        clean_all_orders_data()
    
    print(f"[START] 총 {count}건의 신규 테스트 주문 생성을 시작합니다...\n")
    for _ in range(count):
        create_single_test_order(status="CONFIRMED", is_paid=True)
