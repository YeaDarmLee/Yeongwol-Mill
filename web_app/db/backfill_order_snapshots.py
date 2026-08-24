import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.db_connection import query_db, execute_db

def backfill_snapshots():
    """기존 주문 데이터의 item snapshot을 안전하게 계산 및 채우기 수행"""
    print("[SNAPSHOT BACKFILL] 기존 주문 스냅샷 마이그레이션 시작...")
    
    # 1. 모든 주문 가져오기
    orders = query_db("SELECT * FROM orders") or []
    updated_count = 0
    manual_review_count = 0

    for ord in orders:
        order_id = ord['id']
        paid_amount = int(ord.get('total_amount', 0))
        shipping_fee = int(ord.get('shipping_fee', 0))
        remote_fee = int(ord.get('remote_area_fee', 0))

        items = query_db("SELECT * FROM order_items WHERE order_id = %s", (order_id,)) or []
        if not items:
            continue

        # item_gross_amount 수량 * 단가 계산
        gross_sum = 0
        for item in items:
            gross = int(item.get('price', 0)) * int(item.get('quantity', 1))
            item['gross'] = gross
            gross_sum += gross

        # 할인 배분 및 item_paid_amount 계산
        net_goods_paid = max(0, paid_amount - shipping_fee - remote_fee)
        calc_paid_sum = 0

        for i, item in enumerate(items):
            if gross_sum > 0:
                # 총 상품금액 대비 비례 배분
                item_paid = int(round((item['gross'] / gross_sum) * net_goods_paid))
            else:
                item_paid = 0

            # 소수점 오차 보정 (마지막 항목에 잔여 할당)
            if i == len(items) - 1:
                item_paid = net_goods_paid - calc_paid_sum
            
            calc_paid_sum += item_paid
            item_discount = max(0, item['gross'] - item_paid)

            execute_db("""
                UPDATE order_items 
                SET item_gross_amount = %s,
                    item_discount_allocated = %s,
                    item_paid_amount = %s
                WHERE id = %s
            """, (item['gross'], item_discount, item_paid, item['id']))

        # 백필 검증: SUM(item_paid_amount) + shipping_fee + remote_fee == paid_amount
        verified = (calc_paid_sum + shipping_fee + remote_fee) == paid_amount

        if not verified:
            print(f"  ⚠️ [WARNING] Order #{ord['order_number']} (ID: {order_id}) 백필 검증 불일치 ➔ MANUAL_REVIEW 지정")
            execute_db("UPDATE orders SET refund_calculation_mode = 'MANUAL_REVIEW' WHERE id = %s", (order_id,))
            manual_review_count += 1
        else:
            execute_db("UPDATE orders SET refund_calculation_mode = 'AUTO' WHERE id = %s", (order_id,))
            updated_count += 1

    print(f"[SNAPSHOT BACKFILL 완료] 성공: {updated_count}건, 수동검토(MANUAL_REVIEW): {manual_review_count}건")

if __name__ == '__main__':
    backfill_snapshots()
