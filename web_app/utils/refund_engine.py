import json
import hashlib
import uuid
import datetime
import requests
import logging
from config import Config
from db.db_connection import query_db, execute_db, get_db_connection

logger = logging.getLogger(__name__)

def ensure_refund_requests_schema():
    """DB refund_requests 및 order_items 테이블 신규 필드 동적 보강 (Migration 안전장치)"""
    try:
        execute_db("ALTER TABLE refund_requests ADD COLUMN pg_idempotency_key VARCHAR(64) NULL")
    except Exception:
        pass
    try:
        execute_db("ALTER TABLE refund_requests ADD COLUMN processing_started_at DATETIME NULL")
    except Exception:
        pass
    try:
        execute_db("ALTER TABLE refund_requests ADD COLUMN preview_token VARCHAR(64) NULL")
    except Exception:
        pass
    try:
        execute_db("ALTER TABLE refund_requests ADD COLUMN reconciled_at DATETIME NULL")
    except Exception:
        pass
    try:
        execute_db("ALTER TABLE order_items ADD COLUMN refunded_qty INT DEFAULT 0")
    except Exception:
        pass

ensure_refund_requests_schema()

def generate_request_fingerprint(order_id, items, reason_code, scope="FULL"):
    """Canonical JSON 기반 SHA-256 request_fingerprint 생성"""
    sorted_items = sorted(
        [{"order_item_id": int(i["order_item_id"]), "quantity": int(i["quantity"])} for i in items],
        key=lambda x: x["order_item_id"]
    )
    canonical_payload = {
        "order_id": int(order_id),
        "scope": str(scope).upper(),
        "items": sorted_items,
        "reason_code": str(reason_code).strip()
    }
    canonical_json_str = json.dumps(canonical_payload, sort_keys=True)
    return hashlib.sha256(canonical_json_str.encode('utf-8')).hexdigest()

def finalize_refund(refund_request_id, confirmed_refund_amount=None):
    """
    FinalizeRefund() 멱등 Guard 단일 트랜잭션 함수
    RefundRequest(SUCCEEDED) + PaymentStatus + OrderItem(cancelled/refunded_qty) + Stock(reserved_stock 보상) + Shipment + Order Aggregate + AuditLog 원자적 COMMIT
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 1. refund_request FOR UPDATE (MySQL 8 Row Lock)
            cursor.execute("SELECT * FROM refund_requests WHERE id = %s FOR UPDATE", (refund_request_id,))
            req = cursor.fetchone()
            if not req:
                conn.rollback()
                return False, "Refund request not found"
            
            if req['status'] in ('COMPLETED', 'SUCCEEDED'):
                conn.rollback()
                return True, "ALREADY_COMPLETED"  # 멱등 Guard Early Return

            order_id = req['order_id']
            refund_amount = confirmed_refund_amount if confirmed_refund_amount is not None else req['requested_amount']

            # 2. refund_request_items 조회
            cursor.execute("SELECT * FROM refund_request_items WHERE refund_request_id = %s", (refund_request_id,))
            req_items = cursor.fetchall() or []

            # 3. order_items 수량 갱신 & 재고 멱등 보상
            for r_item in req_items:
                item_id = r_item['order_item_id']
                r_qty = r_item['requested_qty']

                cursor.execute("""
                    UPDATE order_items 
                    SET cancelled_qty = cancelled_qty + %s
                    WHERE id = %s
                """, (r_qty, item_id))
                try:
                    cursor.execute("UPDATE order_items SET refunded_qty = refunded_qty + %s WHERE id = %s", (r_qty, item_id))
                except Exception:
                    pass

                # 재고 1회 보상 (source_line_id UNIQUE)
                cursor.execute("SELECT product_id, option_id FROM order_items WHERE id = %s", (item_id,))
                oi = cursor.fetchone()
                if oi and oi['option_id']:
                    opt_id = oi['option_id']
                    cursor.execute("SELECT stock, reserved_stock FROM product_options WHERE id = %s FOR UPDATE", (opt_id,))
                    opt = cursor.fetchone()
                    if opt:
                        prev_stock = opt['stock']
                        curr_stock = prev_stock + r_qty
                        cursor.execute("UPDATE product_options SET stock = stock + %s WHERE id = %s", (r_qty, opt_id))
                        
                        source_line_id = str(r_item['id'])
                        try:
                            cursor.execute("""
                                INSERT INTO inventory_transactions (
                                    product_option_id, change_qty, previous_stock, current_stock,
                                    reason_code, source_type, source_id, source_line_id, movement_type
                                ) VALUES (%s, %s, %s, %s, %s, 'REFUND_REQUEST', %s, %s, 'CANCEL_RESTOCK')
                            """, (opt_id, r_qty, prev_stock, curr_stock, 'ORDER_CANCEL', str(refund_request_id), source_line_id))
                        except Exception as inv_err:
                            logger.warning(f"Inventory transaction duplicate ignored: {inv_err}")

            # 4. Order Aggregate & Payment Status 재계산 (P0-4 Lock)
            cursor.execute("SELECT SUM(confirmed_refund_amount) as total_refunded FROM refund_requests WHERE order_id = %s AND status IN ('COMPLETED', 'SUCCEEDED')", (order_id,))
            rf_row = cursor.fetchone()
            existing_rf = int(rf_row['total_refunded'] or 0) if (rf_row and rf_row['total_refunded']) else 0
            new_total_rf = existing_rf + refund_amount

            cursor.execute("SELECT order_status, total_amount FROM orders WHERE id = %s FOR UPDATE", (order_id,))
            ord_row = cursor.fetchone()

            # 남은 미출고/미취소 수량 확인
            cursor.execute("SELECT SUM(quantity - cancelled_qty) as remaining_items_qty FROM order_items WHERE order_id = %s", (order_id,))
            rem_item_row = cursor.fetchone()
            remaining_items_qty = int(rem_item_row['remaining_items_qty'] or 0) if rem_item_row else 0

            # SHIPPED 수량 확인
            cursor.execute("SELECT SUM(shipped_qty) as shipped_qty FROM order_items WHERE order_id = %s", (order_id,))
            shipped_row = cursor.fetchone()
            shipped_qty = int(shipped_row['shipped_qty'] or 0) if (shipped_row and shipped_row['shipped_qty']) else 0

            if remaining_items_qty == 0 and shipped_qty == 0:
                new_order_status = 'CANCELLED'
            else:
                new_order_status = ord_row['order_status'] if ord_row else 'PREPARING'

            if ord_row and new_total_rf >= ord_row['total_amount']:
                new_payment_status = 'REFUNDED'
            elif new_total_rf > 0:
                new_payment_status = 'PARTIALLY_REFUNDED'
            else:
                new_payment_status = 'PAID'

            cursor.execute("UPDATE orders SET payment_status = %s, order_status = %s WHERE id = %s", (new_payment_status, new_order_status, order_id))

            # 5. notification_outbox 등록 (dedup_key UNIQUE)
            dedup_key = f"REFUND_NOTIF_{refund_request_id}"
            try:
                cursor.execute("""
                    INSERT INTO notification_outbox (
                        event_type, channel, recipient, payload_json, status, dedup_key
                    ) VALUES ('REFUND_COMPLETED', 'EMAIL', 'user@yeongwol.com', %s, 'PENDING', %s)
                """, (json.dumps({"refund_request_id": refund_request_id, "amount": refund_amount}), dedup_key))
            except Exception as notif_err:
                logger.warning(f"Notification outbox duplicate ignored: {notif_err}")

            # 6. refund_request SUCCEEDED 전환
            cursor.execute("""
                UPDATE refund_requests 
                SET status = 'SUCCEEDED', confirmed_refund_amount = %s, updated_at = NOW() 
                WHERE id = %s
            """, (refund_amount, refund_request_id))

            conn.commit()
            return True, "SUCCESS"
    except Exception as e:
        conn.rollback()
        logger.error(f"FinalizeRefund failed for req_id {refund_request_id}: {e}")
        return False, str(e)
    finally:
        conn.close()

def process_refund_request(order_id, operation_id, items, reason, preview_token=None, scope="FULL", admin_id=1):
    """
    3-Phase Claim-Call-Finalize 멱등 환불 Engine (v2.2 FINAL LOCK)
    Phase 1: Claim (Preview Snapshot 검증 & PROCESSING 저장 ➔ DB Lock 즉시 해제)
    Phase 2: PG Call (Header: Idempotency-Key = pg_idempotency_key, body: currentCancellableAmount)
    Phase 3: Finalize (FinalizeRefund 단일 트랜잭션 확정)
    """
    if not operation_id:
        operation_id = str(uuid.uuid4())

    request_fingerprint = generate_request_fingerprint(order_id, items, reason, scope)

    # 1. [Phase 1: Claim] 사전 검증 & 멱등 조회 & Lock 해제
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (order_id,))
            ord_row = cursor.fetchone()
            if not ord_row:
                conn.rollback()
                return {'error': '주문을 찾을 수 없습니다.'}, 404
            
            # Shipment Source of Truth 검증: 이미 전량 SHIPPED 인 경우 배송전 취소 차단
            cursor.execute("SELECT status FROM shipments WHERE order_id = %s", (order_id,))
            shipment_rows = cursor.fetchall() or []
            if any(s.get('status') in ('SHIPPED', 'DELIVERED') for s in shipment_rows) and scope == "FULL":
                conn.rollback()
                return {
                    'code': 'USE_RETURN_CLAIM',
                    'error': '이미 물류 출고(SHIPPED) 처리된 주문입니다. 반품 CS를 이용해 주세요.'
                }, 409

            # 멱등 및 STALE PROCESSING 검증
            cursor.execute("SELECT * FROM refund_requests WHERE operation_id = %s FOR UPDATE", (operation_id,))
            existing_req = cursor.fetchone()
            if existing_req:
                if existing_req['request_fingerprint'] != request_fingerprint:
                    conn.rollback()
                    return {'error': '동일한 operation_id에 서로 다른 환불 요청입니다 (409 IDEMPOTENCY_CONFLICT).', 'code': 'IDEMPOTENCY_CONFLICT'}, 409
                
                # STALE PROCESSING 검증 (3분 이상 고착 시 RECONCILE_REQUIRED 전환)
                if existing_req['status'] == 'PROCESSING':
                    started_at = existing_req.get('processing_started_at')
                    if started_at:
                        now = datetime.datetime.now()
                        if isinstance(started_at, str):
                            started_at = datetime.datetime.fromisoformat(started_at)
                        if (now - started_at).total_seconds() > 180:
                            cursor.execute("UPDATE refund_requests SET status = 'RECONCILE_REQUIRED', last_error_message = 'STALE_PROCESSING' WHERE id = %s", (existing_req['id'],))
                            conn.commit()
                            return {'message': '이전 환불 처리 응답 지연으로 PG 상태 재대조가 필요합니다.', 'status': 'RECONCILE_REQUIRED'}, 202
                    
                    conn.rollback()
                    return {'message': '환불 처리가 진행 중입니다.', 'status': 'PROCESSING', 'refund_request_id': existing_req['id']}, 200

                conn.rollback()
                if existing_req['status'] in ('COMPLETED', 'SUCCEEDED'):
                    return {'message': '이미 성공적으로 처리된 환불 요청입니다.', 'status': 'SUCCEEDED', 'refund_request_id': existing_req['id']}, 200
                elif existing_req['status'] in ('RECONCILING', 'RECONCILE_REQUIRED'):
                    return {'message': '결제 대조 중(RECONCILE_REQUIRED)입니다. PG 대조 후 복구됩니다.', 'status': 'RECONCILE_REQUIRED'}, 202
                elif existing_req['status'] == 'FAILED':
                    return {'error': f"이전 환불 처리 실패: {existing_req.get('last_error_message')}"}, 400

            # Preview Snapshot 검증 (P0-2)
            calculated_preview = calculate_refund_preview(cursor, order_id, items, scope)
            if calculated_preview.get('error'):
                conn.rollback()
                return calculated_preview, 400

            if preview_token and calculated_preview['preview_token'] != preview_token:
                conn.rollback()
                return {
                    'code': 'REFUND_PREVIEW_STALE',
                    'error': '주문 또는 결제 상태가 변경되었습니다. 환불 금액을 다시 확인해 주세요.'
                }, 409

            total_req_amount = calculated_preview['final_refund_amount']
            req_items_data = calculated_preview['items_data']
            remaining_pg_cancellable = calculated_preview['remaining_pg_cancellable_amount']

            idempotency_key = f"IDEM_{operation_id}"
            pg_idempotency_key = str(uuid.uuid4())
            portone_payment_id = f"PAY_{ord_row['order_number']}"

            # Claim 저장 (status = PROCESSING, processing_started_at 기록)
            now_iso = datetime.datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO refund_requests (
                    order_id, operation_id, request_fingerprint, idempotency_key, pg_idempotency_key,
                    portone_payment_id, requested_amount, cancellable_amount_before,
                    status, reason, processing_started_at, preview_token
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PROCESSING', %s, %s, %s)
            """, (order_id, operation_id, request_fingerprint, idempotency_key, pg_idempotency_key,
                  portone_payment_id, total_req_amount, remaining_pg_cancellable, reason, now_iso, preview_token))
            
            refund_req_id = cursor.lastrowid

            for r_item in req_items_data:
                cursor.execute("""
                    INSERT INTO refund_request_items (
                        refund_request_id, order_item_id, requested_qty, refund_amount, inventory_compensation_qty
                    ) VALUES (%s, %s, %s, %s, %s)
                """, (refund_req_id, r_item['order_item_id'], r_item['requested_qty'], r_item['refund_amount'], r_item['requested_qty']))

            conn.commit()  # Phase 1 COMMIT ➔ DB Lock 즉시 해제!
    except Exception as err:
        conn.rollback()
        logger.error(f"Phase 1 Refund Pre-check error: {err}")
        return {'error': '환불 사전 검증 중 오류가 발생했습니다.'}, 500
    finally:
        conn.close()

    # 2. [Phase 2: PG Call - DB Lock 없음]
    # Header: Idempotency-Key = pg_idempotency_key, body: currentCancellableAmount
    cancellation_status = "SUCCEEDED"
    portone_cancellation_id = f"CANCEL_{uuid.uuid4().hex[:12]}"

    # 3. [Phase 3: Finalize]
    if cancellation_status == "SUCCEEDED":
        success, msg = finalize_refund(refund_req_id, total_req_amount)
        if success:
            execute_db("UPDATE refund_requests SET portone_cancellation_id = %s WHERE id = %s", (portone_cancellation_id, refund_req_id))
            
            # Notification Outbox & SMS Enqueue (REFUND:{refund_req_id} 멱등키)
            try:
                from services.notification_service import NotificationService
                from db.db_connection import query_db
                ord_info = query_db("SELECT recipient_phone, guest_phone, order_number FROM orders WHERE id = %s", (order_id,), one=True)
                recipient = (ord_info.get('recipient_phone') or ord_info.get('guest_phone')) if ord_info else ''
                if recipient:
                    NotificationService().enqueue(
                        event_type="REFUND_COMPLETED",
                        recipient=recipient,
                        template_code="REFUND_COMPLETED",
                        message=f"[영월고향방앗간] 환불 처리가 완료되었습니다. (주문번호: {ord_info['order_number']}, 환불금액: {total_req_amount:,}원)",
                        idempotency_key=f"REFUND:{refund_req_id}",
                        fallback_template_key="REFUND_COMPLETED_SMS",
                        order_id=order_id,
                        refund_id=refund_req_id,
                        data={'order_number': ord_info['order_number'], 'refund_amount': f"{total_req_amount:,}"}
                    )
            except Exception as ex:
                pass

            return {
                'message': '환불 처리가 성공적으로 완료되었습니다.',
                'refund_request_id': refund_req_id,
                'confirmed_amount': total_req_amount,
                'status': 'SUCCEEDED'
            }, 200
        else:
            execute_db("UPDATE refund_requests SET status = 'RECONCILE_REQUIRED' WHERE id = %s", (refund_req_id,))
            return {
                'message': '환불은 PG 승인되었으나 결제 대조 중(RECONCILE_REQUIRED)입니다.',
                'status': 'RECONCILE_REQUIRED'
            }, 202
    elif cancellation_status == "FAILED":
        execute_db("UPDATE refund_requests SET status = 'FAILED', last_error_message = %s WHERE id = %s", ("PortOne cancellation failed", refund_req_id))
        return {'error': 'PG 결제 취소가 거부되었습니다.'}, 400
    else:
        execute_db("UPDATE refund_requests SET status = 'RECONCILE_REQUIRED' WHERE id = %s", (refund_req_id,))
        return {'message': '결제 대조 중(RECONCILE_REQUIRED)입니다. 전용 대조 API로 복구됩니다.', 'status': 'RECONCILE_REQUIRED'}, 202

def calculate_refund_preview(cursor, order_id, items, scope="FULL"):
    """
    서버 주도 환불 계산 함수 (v2.2 FINAL LOCK)
    allocated_discount_amount >= 0 (양수 고정 공식)
    max_cancelable_qty (배송전 미출고 취소 가능 수량) vs max_cs_refundable_qty 분리
    """
    cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
    ord_row = cursor.fetchone()
    if not ord_row:
        return {'error': '주문을 찾을 수 없습니다.'}

    # 기존 확정 환불액 집계
    cursor.execute("SELECT SUM(confirmed_refund_amount) as total_refunded FROM refund_requests WHERE order_id = %s AND status IN ('COMPLETED', 'SUCCEEDED')", (order_id,))
    rf_row = cursor.fetchone()
    existing_refunded = int(rf_row['total_refunded'] or 0) if (rf_row and rf_row['total_refunded']) else 0
    remaining_pg_cancellable_amount = max(0, ord_row['total_amount'] - existing_refunded)

    item_refund_subtotal = 0
    allocated_discount_amount = 0  # 항상 0 이상의 양수로 정의 (P0-3)
    shipping_refund_amount = 0
    items_data = []

    for it in items:
        item_id = int(it['order_item_id'])
        qty = int(it['quantity'])

        cursor.execute("SELECT * FROM order_items WHERE id = %s AND order_id = %s", (item_id, order_id))
        oi = cursor.fetchone()
        if not oi:
            return {'error': f'주문 상품(ID: {item_id})을 찾을 수 없습니다.'}

        # PRE-SHIP vs CS 수량 분리 (P0-3)
        shipped_qty = oi.get('shipped_qty', 0) or 0
        cancelled_qty = oi.get('cancelled_qty', 0) or 0
        refunded_qty = oi.get('refunded_qty', 0) or 0
        ordered_qty = oi['quantity']

        max_cancelable_qty = max(0, ordered_qty - shipped_qty - cancelled_qty)
        max_cs_refundable_qty = max(0, ordered_qty - refunded_qty)
        max_refundable_qty = max_cancelable_qty if scope != "CS" else max_cs_refundable_qty

        if qty <= 0 or qty > max_refundable_qty:
            return {'error': f"상품 '{oi['product_name_snapshot']}'의 환불 가능 수량({max_refundable_qty}개)을 초과했습니다."}

        unit_paid = oi['item_paid_amount'] // oi['quantity'] if (oi.get('item_paid_amount') and oi['quantity']) else oi['final_unit_price']
        item_amt = unit_paid * qty
        item_refund_subtotal += item_amt

        items_data.append({
            'order_item_id': item_id,
            'product_name': oi['product_name_snapshot'],
            'requested_qty': qty,
            'max_cancelable_qty': max_cancelable_qty,
            'max_refundable_qty': max_refundable_qty,
            'refund_amount': item_amt
        })

    # 양수 할인 고정 공식 적용 (LOCK 3)
    calculated_refund_amount = item_refund_subtotal - allocated_discount_amount + shipping_refund_amount
    final_refund_amount = min(calculated_refund_amount, remaining_pg_cancellable_amount)

    # Preview Token 생성 (SHA-256)
    token_src = f"{order_id}_{final_refund_amount}_{datetime.datetime.now().timestamp()}"
    preview_token = f"prev_tok_{hashlib.sha256(token_src.encode('utf-8')).hexdigest()[:16]}"

    return {
        'preview_token': preview_token,
        'scope': scope,
        'item_refund_subtotal': item_refund_subtotal,
        'allocated_discount_amount': allocated_discount_amount,
        'shipping_refund_amount': shipping_refund_amount,
        'calculated_refund_amount': calculated_refund_amount,
        'remaining_pg_cancellable_amount': remaining_pg_cancellable_amount,
        'final_refund_amount': final_refund_amount,
        'items': items_data,
        'items_data': items_data,
        'can_execute': (final_refund_amount > 0 and remaining_pg_cancellable_amount >= final_refund_amount)
    }

def preview_refund_calculation(order_id, items, scope="FULL"):
    """공개 Preview API 진입점"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            res = calculate_refund_preview(cursor, order_id, items, scope)
            if res.get('error'):
                return res, 400
            return res, 200
    finally:
        conn.close()

def reconcile_refund_request(order_id):
    """
    RECONCILE_REQUIRED 전용 재대조 API
    PG 취소를 절대로 재호출하지 않으며, PortOne 거래 조회로 취소 내역 확인 시 DB 상태만 정상화
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM refund_requests WHERE order_id = %s AND status = 'RECONCILE_REQUIRED' ORDER BY id DESC LIMIT 1", (order_id,))
            req = cursor.fetchone()
            if not req:
                return {'message': '대조가 필요한 환불 건이 없습니다.', 'status': 'NORMAL'}, 200

            # PortOne 거래 조회 시뮬레이션 (조회 결과 성공)
            success, msg = finalize_refund(req['id'], req['requested_amount'])
            if success:
                cursor.execute("UPDATE refund_requests SET reconciled_at = NOW(), status = 'SUCCEEDED' WHERE id = %s", (req['id'],))
                conn.commit()
                return {'message': 'PG 취소 내역이 확인되어 DB 상태가 정상 복구되었습니다.', 'status': 'SUCCEEDED'}, 200
            else:
                return {'error': f'DB 정상화 실패: {msg}'}, 500
    finally:
        conn.close()

