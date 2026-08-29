import io
import csv
import json
import datetime
from flask import Blueprint, request, jsonify, Response, current_app
from db.db_connection import query_db, execute_db, get_db_connection
from middlewares.auth import verify_jwt_token, generate_jwt_token, check_password, hash_password
from utils.audit_logger import log_admin_audit
from utils.refund_engine import process_refund_request, preview_refund_calculation
from utils.order_state_machine import OrderStateMachine, OrderStateMachineError

admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')

def verify_admin_auth(required_role=None):
    """관리자 권한 검증 미들웨어 헬퍼 (RBAC 지원)"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    token = auth_header.split()[1]
    payload = verify_jwt_token(token)
    if not payload or payload.get('role') not in ('ADMIN', 'SUPER_ADMIN'):
        return None
    if required_role and payload.get('role') != required_role:
        return None
    return payload

@admin_bp.route('/login', methods=['POST'])
def admin_login():
    """관리자 전용 보안 로그인 API (Rate Limit & RBAC)"""
    data = request.get_json() or {}
    email = data.get('email', '').strip()
    password = data.get('password', '').strip()

    if not email or not password:
        return jsonify({'error': '관리자 이메일과 비밀번호를 모두 입력해 주세요.'}), 400

    admin = query_db("SELECT * FROM admin_users WHERE email = %s", (email,), one=True)
    if not admin or not check_password(password, admin['password_hash']):
        log_admin_audit(0, email, 'ADMIN_LOGIN_FAILED', request_ip=request.remote_addr, user_agent=request.user_agent.string, result='FAILED')
        return jsonify({'error': '관리자 이메일 또는 비밀번호가 올바르지 않습니다.'}), 401

    token = generate_jwt_token(admin['id'], admin['email'], role=admin['role'])
    log_admin_audit(admin['id'], admin['email'], 'ADMIN_LOGIN_SUCCESS', request_ip=request.remote_addr, user_agent=request.user_agent.string)

    return jsonify({
        'message': '관리자 로그인이 완료되었습니다.',
        'token': token,
        'admin': {
            'id': admin['id'],
            'email': admin['email'],
            'name': admin['name'],
            'role': admin['role']
        }
    }), 200

@admin_bp.route('/dashboard', methods=['GET'])
def admin_dashboard():
    """관리자 실운영 대시보드 API (KST 기준 Net Payments, Work Queue, Alerts, 30일 Trend)"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    from config import Config
    kst_tz = datetime.timezone(datetime.timedelta(hours=9))
    now_kst = datetime.datetime.now(kst_tz)
    today_start_dt = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end_dt = today_start_dt + datetime.timedelta(days=1)

    today_start_str = today_start_dt.strftime('%Y-%m-%d %H:%M:%S')
    today_end_str = today_end_dt.strftime('%Y-%m-%d %H:%M:%S')

    # 1. 오늘 결제 완결 및 결제 총액 (Gross Payments) - paid_at 기준
    today_payments_row = query_db("""
        SELECT COUNT(DISTINCT order_id) as paid_orders, SUM(amount) as gross_sales
        FROM payments
        WHERE status = 'PAID' AND paid_at >= %s AND paid_at < %s
    """, (today_start_str, today_end_str), one=True)

    today_paid_orders = int(today_payments_row['paid_orders'] or 0) if today_payments_row else 0
    today_gross_sales = int(today_payments_row['gross_sales'] or 0) if today_payments_row else 0

    # 만약 payments 기록이 없는 경우 orders fallback
    if today_paid_orders == 0 and today_gross_sales == 0:
        fallback_row = query_db("""
            SELECT COUNT(*) as paid_orders, SUM(total_amount) as gross_sales
            FROM orders
            WHERE payment_status IN ('PAID', 'PARTIALLY_REFUNDED', 'REFUNDED') 
              AND created_at >= %s AND created_at < %s
        """, (today_start_str, today_end_str), one=True)
        if fallback_row:
            today_paid_orders = int(fallback_row['paid_orders'] or 0)
            today_gross_sales = int(fallback_row['gross_sales'] or 0)

    # 2. 오늘 확정 환불 총액 (Refunds) - refund_requests updated_at 시각 기준
    today_refunds_row = query_db("""
        SELECT SUM(confirmed_refund_amount) as total_refunds
        FROM refund_requests
        WHERE status = 'COMPLETED' AND updated_at >= %s AND updated_at < %s
    """, (today_start_str, today_end_str), one=True)
    today_refunds = int(today_refunds_row['total_refunds'] or 0) if today_refunds_row else 0
    today_net_sales = today_gross_sales - today_refunds

    # 3. 출고 대기 건수 (PREPARING)
    pending_shipping_row = query_db("""
        SELECT COUNT(*) as count FROM orders WHERE order_status = 'PREPARING'
    """, one=True)
    pending_shipping_count = int(pending_shipping_row['count'] or 0) if pending_shipping_row else 0

    # 4. 환불 / 대조 중 건수 breakdown (PENDING, PROCESSING, CANCEL_PENDING, RECONCILING)
    refund_stats_rows = query_db("""
        SELECT status, COUNT(*) as cnt
        FROM refund_requests
        WHERE status IN ('PENDING', 'PROCESSING', 'CANCEL_PENDING', 'RECONCILING')
        GROUP BY status
    """) or []
    refund_stat_map = {r['status']: int(r['cnt']) for r in refund_stats_rows}
    reconciling_total = sum(refund_stat_map.values())

    # 5. 재고 경고 상품 및 정합성 검증
    low_stock_options = query_db("""
        SELECT po.*, p.name as product_name
        FROM product_options po
        JOIN products p ON po.product_id = p.id
        WHERE p.is_active = 1 AND (po.stock - po.reserved_stock) <= 10 AND po.stock < 999000
        ORDER BY (po.stock - po.reserved_stock) ASC
    """) or []
    for opt in low_stock_options:
        opt['available_stock'] = opt['stock'] - opt['reserved_stock']

    critical_stock_errors = [opt for opt in low_stock_options if opt['available_stock'] < 0]

    # 6. Action Work Queue (처리해야 할 업무 - GROUP BY 일괄 집계)
    order_stats_rows = query_db("""
        SELECT order_status, COUNT(*) as cnt
        FROM orders
        GROUP BY order_status
    """) or []
    order_stat_map = {r['order_status']: int(r['cnt']) for r in order_stats_rows}

    pending_orders_cnt = int((query_db("""
        SELECT COUNT(*) as c FROM orders o
        WHERE o.order_status IN ('PENDING', 'CONFIRMED')
          AND o.payment_status IN ('PAID', 'PARTIALLY_REFUNDED')
          AND (
              (SELECT COALESCE(SUM(quantity), 0) FROM order_items WHERE order_id = o.id) -
              (SELECT COALESCE(SUM(si.quantity), 0) FROM shipment_items si JOIN shipments s ON si.shipment_id = s.id WHERE s.order_id = o.id AND s.purpose = 'FULFILLMENT')
          ) > 0
    """, one=True) or {}).get('c', 0))
    confirmed_orders_cnt = 0
    preparing_orders_cnt = int((query_db("SELECT COUNT(*) as c FROM orders WHERE order_status = 'PREPARING'", one=True) or {}).get('c', 0))
    ready_to_ship_orders_cnt = int((query_db("SELECT COUNT(*) as c FROM orders WHERE order_status = 'READY_TO_SHIP'", one=True) or {}).get('c', 0))
    shipping_orders_cnt = int((query_db("SELECT COUNT(*) as c FROM orders WHERE order_status = 'SHIPPING'", one=True) or {}).get('c', 0))
    delivered_orders_cnt = int((query_db("SELECT COUNT(*) as c FROM orders WHERE order_status = 'DELIVERED'", one=True) or {}).get('c', 0))

    stale_preparing_threshold = (now_kst - datetime.timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    stale_unregistered_cnt = int((query_db("""
        SELECT COUNT(*) as c FROM orders 
        WHERE order_status = 'PREPARING' 
          AND (tracking_number IS NULL OR tracking_number = '')
          AND created_at < %s
    """, (stale_preparing_threshold,), one=True) or {}).get('c', 0))

    unregistered_tracking_cnt = int((query_db("SELECT COUNT(*) as c FROM orders WHERE order_status = 'PREPARING' AND (tracking_number IS NULL OR tracking_number = '')", one=True) or {}).get('c', 0))
    refund_pending_cnt = refund_stat_map.get('PENDING', 0)
    refund_processing_cnt = refund_stat_map.get('PROCESSING', 0) + refund_stat_map.get('CANCEL_PENDING', 0)
    reconciling_cnt = refund_stat_map.get('RECONCILING', 0)
    amount_mismatch_cnt = int((query_db("SELECT COUNT(*) as c FROM orders WHERE integrity_status = 'AMOUNT_MISMATCH'", one=True) or {}).get('c', 0))

    work_queue = {
        'pending_orders': pending_orders_cnt,
        'confirmed_orders': confirmed_orders_cnt,
        'preparing_orders': preparing_orders_cnt,
        'shipping_orders': shipping_orders_cnt,
        'delivered_orders': delivered_orders_cnt,
        'stale_unregistered': stale_unregistered_cnt,
        'unregistered_tracking': unregistered_tracking_cnt,
        'refund_pending': refund_pending_cnt,
        'refund_processing': refund_processing_cnt,
        'reconciling': reconciling_cnt,
        'amount_mismatch': amount_mismatch_cnt
    }

    # 7. Operational Alerts (운영 주의사항)
    alerts = []
    if critical_stock_errors:
        alerts.append({
            'type': 'CRITICAL_STOCK',
            'level': 'CRITICAL',
            'title': f'⚠ 재고 정합성 오류 ({len(critical_stock_errors)}건)',
            'message': '예약재고가 보유재고를 초과하는 품목이 있습니다. 재고 조정을 실행하세요.',
            'target_filter': 'low_stock'
        })

    if reconciling_cnt > 0:
        alerts.append({
            'type': 'RECONCILING',
            'level': 'WARNING',
            'title': f'환불 상태대조 중 ({reconciling_cnt}건)',
            'message': 'PG사와 환불 상태 대조 중인 요청이 있습니다.',
            'target_filter': 'refund_status=RECONCILING'
        })

    # Stale PROCESSING 환불 (Config.REFUND_PROCESSING_STALE_SECONDS 기준)
    stale_sec = getattr(Config, 'REFUND_PROCESSING_STALE_SECONDS', 3600)
    stale_threshold_str = (now_kst - datetime.timedelta(seconds=stale_sec)).strftime('%Y-%m-%d %H:%M:%S')
    stale_processing_cnt = int((query_db("""
        SELECT COUNT(*) as c FROM refund_requests 
        WHERE status = 'PROCESSING' AND updated_at < %s
    """, (stale_threshold_str,), one=True) or {}).get('c', 0))

    if stale_processing_cnt > 0:
        alerts.append({
            'type': 'STALE_REFUND',
            'level': 'WARNING',
            'title': f'장시간 환불 처리중 ({stale_processing_cnt}건)',
            'message': f'{stale_sec // 60}분 이상 처리 중인 환불 요청이 있습니다.',
            'target_filter': 'refund_status=PROCESSING'
        })

    # Outbox 최종 발송 실패
    outbox_failed_cnt = int((query_db("""
        SELECT COUNT(*) as c FROM notification_outbox 
        WHERE status = 'FAILED' AND (retry_count >= 3 OR next_retry_at IS NULL)
    """, one=True) or {}).get('c', 0))

    if outbox_failed_cnt > 0:
        alerts.append({
            'type': 'OUTBOX_FAILED',
            'level': 'WARNING',
            'title': f'알림 Outbox 최종 발송 실패 ({outbox_failed_cnt}건)',
            'message': '고객 알림 메시지 발송 실패 건이 있습니다.',
            'target_filter': 'outbox_failed'
        })

    if stale_unregistered_cnt > 0:
        alerts.append({
            'type': 'STALE_PREPARING',
            'level': 'WARNING',
            'title': f'24시간 이상 송장 미등록 ({stale_unregistered_cnt}건)',
            'message': '배송 준비 전환 후 24시간 동안 송장이 입력되지 않은 주문이 있습니다.',
            'target_filter': 'unregistered_tracking=true'
        })

    if amount_mismatch_cnt > 0:
        alerts.append({
            'type': 'AMOUNT_MISMATCH',
            'level': 'CRITICAL',
            'title': f'결제/주문 금액 불일치 ({amount_mismatch_cnt}건)',
            'message': '주문 금액과 결제 금액이 일치하지 않는 이상 주문이 존재합니다.',
            'target_filter': 'amount_mismatch=true'
        })

    # 8. Recent Orders (최근 8건, 마스킹 적용)
    recent_orders_raw = query_db("""
        SELECT id, order_number, recipient_name, guest_name, total_amount, 
               order_status, payment_status, courier_name, tracking_number, created_at
        FROM orders
        ORDER BY id DESC LIMIT 8
    """) or []

    def mask_person_name(name):
        if not name or name == '구매자':
            return '구매자'
        name_str = str(name).strip()
        if len(name_str) <= 1:
            return name_str + '*'
        if len(name_str) == 2:
            return name_str[0] + '*'
        return name_str[0] + '*' * (len(name_str) - 2) + name_str[-1]

    recent_orders = []
    for r in recent_orders_raw:
        cname = r['recipient_name'] or r['guest_name'] or '구매자'
        recent_orders.append({
            'id': r['id'],
            'order_number': r['order_number'],
            'customer_name_masked': mask_person_name(cname),
            'total_amount': int(r['total_amount']),
            'order_status': r['order_status'],
            'payment_status': r['payment_status'],
            'has_tracking': bool(r['tracking_number']),
            'courier_name': r['courier_name'] or '',
            'created_at': r['created_at'].strftime('%Y-%m-%d %H:%M') if isinstance(r['created_at'], datetime.datetime) else str(r['created_at'])
        })

    # 9. 최근 30일 Trend 일별 집계 (DB 1회 GROUP BY 일괄 집계로 초고속 최적화)
    trend_start_dt = today_start_dt - datetime.timedelta(days=29)
    trend_start_str = trend_start_dt.strftime('%Y-%m-%d 00:00:00')

    # (1) 30일 간 일별 orders 결제 완료 주문 및 매출 일괄 집계
    daily_orders = query_db("""
        SELECT DATE(created_at) as dt, COUNT(*) as p_orders, SUM(total_amount) as p_gross
        FROM orders
        WHERE payment_status IN ('PAID', 'PARTIALLY_REFUNDED', 'REFUNDED')
          AND created_at >= %s
        GROUP BY DATE(created_at)
    """, (trend_start_str,)) or []

    order_map = {}
    for do in daily_orders:
        if do.get('dt'):
            dt_key = str(do['dt'])[:10]
            order_map[dt_key] = {
                'gross': int(do['p_gross'] or 0),
                'orders': int(do['p_orders'] or 0)
            }

    # (2) 30일 간 일별 환불 일괄 집계
    daily_refunds = query_db("""
        SELECT DATE(updated_at) as dt, SUM(confirmed_refund_amount) as r_ref
        FROM refund_requests
        WHERE status = 'COMPLETED' AND updated_at >= %s
        GROUP BY DATE(updated_at)
    """, (trend_start_str,)) or []

    refund_map = {}
    for dr in daily_refunds:
        if dr.get('dt'):
            dt_key = str(dr['dt'])[:10]
            refund_map[dt_key] = int(dr['r_ref'] or 0)

    trend_30days = []
    for i in range(29, -1, -1):
        dt_day = today_start_dt - datetime.timedelta(days=i)
        dt_key = dt_day.strftime('%Y-%m-%d')
        d_label = dt_day.strftime('%m-%d')

        o_info = order_map.get(dt_key) or {'gross': 0, 'orders': 0}
        g_sales = o_info['gross']
        p_cnt = o_info['orders']
        ref_amt = refund_map.get(dt_key, 0)
        net_amt = g_sales - ref_amt

        trend_30days.append({
            'date': d_label,
            'full_date': dt_key,
            'gross_payments': g_sales,
            'refunds': ref_amt,
            'net_payments': net_amt,
            'paid_orders': p_cnt
        })

    return jsonify({
        'kpi': {
            'today_orders': today_paid_orders,
            'today_gross_sales': today_gross_sales,
            'today_refunds': today_refunds,
            'today_net_sales': today_net_sales,
            'pending_shipping_count': pending_shipping_count,
            'reconciling_total': reconciling_total,
            'reconciling_breakdown': refund_stat_map,
            'low_stock_count': len(low_stock_options)
        },
        'work_queue': work_queue,
        'alerts': alerts,
        'recent_orders': recent_orders,
        'trend_30days': trend_30days,
        'low_stock_options': low_stock_options,
        'as_of': now_kst.strftime('%H:%M:%S')
    }), 200


# ── PRODUCT SUMMARY BATCH HELPERS (O(1) BATCH QUERY & DETERMINISTIC ORDERING) ───────

def build_order_items_summary_batch(order_ids):
    """
    주문 ID 목록을 2-Query Batching으로 일괄 조회하여 product_summary 생성
    (Deterministic Ordering: ORDER BY order_id ASC, id ASC)
    """
    if not order_ids:
        return {}

    placeholders = ", ".join(["%s"] * len(order_ids))
    sql = f"""
        SELECT id, order_id, product_name_snapshot, option_name_snapshot, quantity
        FROM order_items
        WHERE order_id IN ({placeholders})
        ORDER BY order_id ASC, id ASC
    """
    rows = query_db(sql, tuple(order_ids)) or []

    grouped = {}
    for r in rows:
        oid = r['order_id']
        if oid not in grouped:
            grouped[oid] = []
        grouped[oid].append(r)

    summaries = {}
    for oid in order_ids:
        items = grouped.get(oid, [])
        if not items:
            summaries[oid] = None
            continue

        first_item = items[0]
        first_product_name = first_item.get('product_name_snapshot') or '상품명 없음'
        first_option_name = first_item.get('option_name_snapshot')
        item_line_count = len(items)
        extra_item_count = max(item_line_count - 1, 0)
        total_quantity = sum(it.get('quantity', 1) for it in items)

        items_list = [
            {
                'order_item_id': it['id'],
                'product_name': it.get('product_name_snapshot') or '',
                'option_name': it.get('option_name_snapshot'),
                'quantity': it.get('quantity', 1)
            }
            for it in items
        ]

        first_qty = items[0].get('quantity', 1) if items else 1
        summary_text = f"{first_product_name} {first_qty}개" if extra_item_count == 0 else f"{first_product_name} 외 {extra_item_count}건"

        summaries[oid] = {
            'first_product_name': first_product_name,
            'first_option_name': first_option_name,
            'item_line_count': item_line_count,
            'extra_item_count': extra_item_count,
            'total_quantity': total_quantity,
            'summary_text': summary_text,
            'items': items_list
        }

    return summaries


def build_cs_items_summary_batch(cs_requests):
    """
    CS 목록 전용 Target Items Batch Query 헬퍼
    (Target Items Source of Truth: refund_request_items 등)
    """
    if not cs_requests:
        return {}

    cs_ids = [r['id'] for r in cs_requests if 'id' in r]
    order_ids = list(set([r['order_id'] for r in cs_requests if 'order_id' in r]))
    if not cs_ids:
        return {}

    placeholders = ", ".join(["%s"] * len(cs_ids))
    refund_items_sql = f"""
        SELECT rri.refund_request_id as cs_id, rri.order_item_id, rri.quantity,
               oi.product_name_snapshot, oi.option_name_snapshot
        FROM refund_request_items rri
        JOIN order_items oi ON rri.order_item_id = oi.id
        WHERE rri.refund_request_id IN ({placeholders})
        ORDER BY rri.refund_request_id ASC, rri.id ASC
    """
    cs_item_rows = query_db(refund_items_sql, tuple(cs_ids)) or []

    cs_grouped = {}
    for r in cs_item_rows:
        cid = r['cs_id']
        if cid not in cs_grouped:
            cs_grouped[cid] = []
        cs_grouped[cid].append(r)

    order_summaries = build_order_items_summary_batch(order_ids) if order_ids else {}

    summaries = {}
    for cs in cs_requests:
        cid = cs['id']
        oid = cs.get('order_id')
        items = cs_grouped.get(cid, [])

        if items:
            first_item = items[0]
            first_product_name = first_item.get('product_name_snapshot') or '상품명 없음'
            first_option_name = first_item.get('option_name_snapshot')
            item_line_count = len(items)
            extra_item_count = max(item_line_count - 1, 0)
            total_quantity = sum(it.get('quantity', 1) for it in items)

            items_list = [
                {
                    'order_item_id': it['order_item_id'],
                    'product_name': it.get('product_name_snapshot') or '',
                    'option_name': it.get('option_name_snapshot'),
                    'quantity': it.get('quantity', 1)
                }
                for it in items
            ]

            summaries[cid] = {
                'first_product_name': first_product_name,
                'first_option_name': first_option_name,
                'item_line_count': item_line_count,
                'extra_item_count': extra_item_count,
                'total_quantity': total_quantity,
                'items': items_list
            }
        elif oid in order_summaries and order_summaries[oid]:
            summaries[cid] = order_summaries[oid]
        else:
            summaries[cid] = None

    return summaries


@admin_bp.route('/orders', methods=['GET'])
def admin_orders():
    """전체 주문 목록 필터링, 검색 및 페이지네이션 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    status_filter = request.args.get('order_status', '').strip()
    payment_filter = request.args.get('payment_status', '').strip()
    refund_filter = request.args.get('refund_status', '').strip()
    unregistered_tracking = request.args.get('unregistered_tracking', '').strip()
    amount_mismatch = request.args.get('amount_mismatch', '').strip()
    keyword = request.args.get('keyword', '').strip()

    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1

    try:
        limit = max(1, min(100, int(request.args.get('limit', 10))))
    except (ValueError, TypeError):
        limit = 10

    offset = (page - 1) * limit

    base_sql = "FROM orders o"
    where_clauses = ["1=1"]
    args = []

    if refund_filter:
        base_sql += " JOIN refund_requests rr ON o.id = rr.order_id"
        where_clauses.append("rr.status = %s")
        args.append(refund_filter)

    if status_filter:
        statuses = [s.strip() for s in status_filter.split(',') if s.strip()]
        if len(statuses) == 1:
            where_clauses.append("o.order_status = %s")
            args.append(statuses[0])
        elif len(statuses) > 1:
            placeholders = ", ".join(["%s"] * len(statuses))
            where_clauses.append(f"o.order_status IN ({placeholders})")
            args.extend(statuses)

        if any(st in ('PENDING', 'CONFIRMED') for st in statuses):
            where_clauses.append("""
                (
                    (SELECT COALESCE(SUM(quantity), 0) FROM order_items WHERE order_id = o.id) -
                    (SELECT COALESCE(SUM(si.quantity), 0) FROM shipment_items si JOIN shipments s ON si.shipment_id = s.id WHERE s.order_id = o.id AND s.purpose = 'FULFILLMENT')
                ) > 0
            """)

    if payment_filter:
        payments = [p.strip() for p in payment_filter.split(',') if p.strip()]
        if len(payments) == 1:
            where_clauses.append("o.payment_status = %s")
            args.append(payments[0])
        elif len(payments) > 1:
            placeholders = ", ".join(["%s"] * len(payments))
            where_clauses.append(f"o.payment_status IN ({placeholders})")
            args.extend(payments)

    if unregistered_tracking == 'true':
        where_clauses.append("o.order_status = 'PREPARING' AND (o.tracking_number IS NULL OR o.tracking_number = '')")

    if amount_mismatch == 'true':
        where_clauses.append("o.integrity_status = 'AMOUNT_MISMATCH'")

    if keyword:
        where_clauses.append("(o.order_number LIKE %s OR o.recipient_name LIKE %s OR o.recipient_phone LIKE %s)")
        kw_pattern = f"%{keyword}%"
        args.extend([kw_pattern, kw_pattern, kw_pattern])

    where_str = " WHERE " + " AND ".join(where_clauses)

    count_sql = f"SELECT COUNT(DISTINCT o.id) as cnt {base_sql} {where_str}"
    count_row = query_db(count_sql, tuple(args), one=True)
    total_count = int(count_row['cnt'] or 0) if count_row else 0
    total_pages = max(1, (total_count + limit - 1) // limit)

    select_sql = f"SELECT DISTINCT o.* {base_sql} {where_str} ORDER BY o.id DESC LIMIT %s OFFSET %s"
    fetch_args = list(args) + [limit, offset]

    orders = query_db(select_sql, tuple(fetch_args)) or []

    # O(1) 2-Query Batching으로 order_items 및 product_summary 일괄 결합 (N+1 방지)
    order_ids = [o['id'] for o in orders]
    product_summaries = build_order_items_summary_batch(order_ids)

    for order in orders:
        summary = product_summaries.get(order['id'])
        if not summary:
            fallback_name = order.get('order_name') or '상품 정보 없음'
            summary = {
                'first_product_name': fallback_name,
                'first_option_name': None,
                'item_line_count': 1,
                'extra_item_count': 0,
                'total_quantity': 1,
                'summary_text': fallback_name,
                'items': [{'product_name_snapshot': fallback_name, 'quantity': 1}]
            }
        order['product_summary'] = summary
        order['items'] = query_db("SELECT * FROM order_items WHERE order_id = %s", (order['id'],)) or []
        if not order['items']:
            fallback_name = order.get('order_name') or '상품 정보 없음'
            order['items'] = [{'product_name_snapshot': fallback_name, 'quantity': 1}]

    return jsonify({
        'orders': orders,
        'pagination': {
            'page': page,
            'limit': limit,
            'total_count': total_count,
            'total_pages': total_pages
        }
    }), 200


@admin_bp.route('/orders/<int:order_id>', methods=['GET'])
def admin_order_detail(order_id):
    """주문 통합 상세 조회 API (Order, Items, Refunds, Audit, Admin Notes, Timeline)"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    order = query_db("SELECT * FROM orders WHERE id = %s", (order_id,), one=True)
    if not order:
        return jsonify({'error': '주문을 찾을 수 없습니다.'}), 404

    items = query_db("SELECT * FROM order_items WHERE order_id = %s", (order_id,)) or []
    refund_requests = query_db("SELECT * FROM refund_requests WHERE order_id = %s ORDER BY id DESC", (order_id,)) or []
    for req in refund_requests:
        req['items'] = query_db("SELECT * FROM refund_request_items WHERE refund_request_id = %s", (req['id'],)) or []

    try:
        audit_logs = query_db("SELECT * FROM admin_audit_logs WHERE target_type = 'ORDER' AND target_id = %s ORDER BY id DESC", (str(order_id),)) or []
    except Exception as e:
        logger.warning(f"admin_audit_logs query warning: {e}")
        audit_logs = []

    try:
        admin_notes = query_db("SELECT * FROM order_admin_notes WHERE order_id = %s ORDER BY id DESC", (order_id,)) or []
    except Exception as e:
        logger.warning(f"order_admin_notes query warning: {e}")
        admin_notes = []

    # 이벤트 타임라인 구성
    timeline = []
    if order.get('created_at'):
        timeline.append({'time': str(order['created_at']), 'event': 'ORDER_CREATED', 'description': '주문 접수 완료'})
    if order.get('shipped_at'):
        timeline.append({'time': str(order['shipped_at']), 'event': 'TRACKING_REGISTERED', 'description': f"운송장 등록 ({order.get('courier_name', '')} {order.get('tracking_number', '')})"})
    for log in audit_logs:
        timeline.append({'time': str(log['created_at']), 'event': log['action_type'], 'description': f"관리자 작업 ({log['admin_email']}): {log.get('reason', '')}"})

    timeline.sort(key=lambda x: x['time'], reverse=True)

    return jsonify({
        'order': order,
        'items': items,
        'refund_requests': refund_requests,
        'audit_logs': audit_logs,
        'admin_notes': admin_notes,
        'timeline': timeline
    }), 200

@admin_bp.route('/orders/<int:order_id>/refund/preview', methods=['POST'])
def admin_refund_preview(order_id):
    """환불 사전 계산 및 스냅샷 토큰 발행 API (P0-2, P0-3, LOCK 3)"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    items = data.get('items', [])
    scope = data.get('scope', 'FULL')
    if not items:
        return jsonify({'error': '환불할 상품 목록(items)이 필요합니다.'}), 400

    from utils.refund_engine import preview_refund_calculation
    res, status_code = preview_refund_calculation(order_id, items, scope)
    return jsonify(res), status_code

@admin_bp.route('/orders/<int:order_id>/refund/execute', methods=['POST'])
def admin_refund_execute(order_id):
    """3-Phase Claim-Call-Finalize 환불 실행 API (v2.2 FINAL LOCK)"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    items = data.get('items', [])
    reason = data.get('reason', '관리자 직권 취소/환불').strip()
    operation_id = data.get('operation_id') or str(uuid.uuid4())
    preview_token = data.get('preview_token')
    scope = data.get('scope', 'FULL')

    if not items:
        return jsonify({'error': '환불할 상품 목록(items)이 필요합니다.'}), 400

    from utils.refund_engine import process_refund_request
    res, status_code = process_refund_request(order_id, operation_id, items, reason, preview_token=preview_token, scope=scope, admin_id=payload.get('sub', 1))
    return jsonify(res), status_code

@admin_bp.route('/orders/<int:order_id>/refund/reconcile', methods=['POST'])
def admin_refund_reconcile(order_id):
    """RECONCILE_REQUIRED 상태 전용 PG 상태 재대조 및 DB 복구 API (LOCK 2)"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    from utils.refund_engine import reconcile_refund_request
    res, status_code = reconcile_refund_request(order_id)
    return jsonify(res), status_code

@admin_bp.route('/orders/<int:order_id>/status', methods=['PATCH', 'POST'])
def admin_update_order_status(order_id):
    """Row Lock + State Machine 기반 주문 상태 변경 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    target_status = data.get('target_status', '').strip().upper()
    reason = data.get('reason', '관리자 상태 변경').strip()

    if not target_status:
        return jsonify({'error': '변경할 목표 상태(target_status)를 지정해 주세요.'}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (order_id,))
            order = cursor.fetchone()
            if not order:
                conn.rollback()
                return jsonify({'error': '주문을 찾을 수 없습니다.'}), 404

            try:
                OrderStateMachine.validate_transition(order['order_status'], target_status, order['payment_status'])
            except OrderStateMachineError as err:
                conn.rollback()
                return jsonify({'code': err.code, 'error': err.message}), 409

            cursor.execute("UPDATE orders SET order_status = %s WHERE id = %s", (target_status, order_id))
            conn.commit()

        log_admin_audit(
            admin_id=payload['user_id'],
            admin_email=payload.get('email') or payload.get('sub', ''),
            action_type='ORDER_STATUS_CHANGED',
            target_type='ORDER',
            target_id=order_id,
            reason=f"Status changed from {order['order_status']} to {target_status} ({reason})",
            request_ip=request.remote_addr,
            user_agent=request.user_agent.string
        )

        return jsonify({'message': f"주문 상태가 [{target_status}](으)로 변경되었습니다.", 'order_id': order_id, 'order_status': target_status}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@admin_bp.route('/orders/<int:order_id>/shipping', methods=['PATCH', 'POST'])
def admin_update_shipping(order_id):
    """Row Lock + State Machine + 1-Tx Outbox 연동 운송장 최초 등록 / 수정 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    courier_name = data.get('courier_name', '').strip()
    tracking_number = data.get('tracking_number', '').strip()

    if not courier_name or not tracking_number:
        return jsonify({'error': '택배사명과 운송장 번호를 모두 입력해 주세요.'}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (order_id,))
            order = cursor.fetchone()
            if not order:
                conn.rollback()
                return jsonify({'error': '주문을 찾을 수 없습니다.'}), 404

            if order['order_status'] in ('SHIPPING', 'DELIVERED', 'CANCELLED', 'REFUNDED'):
                conn.rollback()
                return jsonify({'error': f"이미 [{order['order_status']}](으)로 진행된 주문은 운송장을 변경할 수 없습니다."}), 409

            try:
                OrderStateMachine.validate_transition(order['order_status'], 'SHIPPING', order['payment_status'])
            except OrderStateMachineError as err:
                conn.rollback()
                return jsonify({'code': err.code, 'error': err.message}), 409

            now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("""
                UPDATE orders 
                SET courier_name = %s, tracking_number = %s, order_status = 'SHIPPING', shipped_at = %s
                WHERE id = %s
            """, (courier_name, tracking_number, now_str, order_id))

            # shipments 테이블 생성/업데이트
            cursor.execute("""
                INSERT INTO shipments (order_id, courier, tracking_number, status, shipped_at)
                VALUES (%s, %s, %s, 'SHIPPED', %s)
            """, (order_id, courier_name, tracking_number, now_str))
            shipment_id = cursor.lastrowid

            # Notification Outbox & SMS Enqueue (SHIPPED:{shipment_id} 멱등키)
            try:
                from services.notification_service import NotificationService
                recipient = order.get('recipient_phone') or order.get('guest_phone') or ''
                if recipient:
                    NotificationService().enqueue(
                        event_type="SHIPPED",
                        recipient=recipient,
                        template_code="SHIPPED",
                        message=f"[영월고향방앗간] 고객님의 상품이 우체국택배({tracking_number})로 배송 시작되었습니다.",
                        idempotency_key=f"SHIPPED:{shipment_id}",
                        fallback_template_key="SHIPPED_SMS",
                        order_id=order_id,
                        shipment_id=shipment_id
                    )
            except Exception as ex:
                pass

            action_name = 'TRACKING_REGISTERED'
            conn.commit()


        log_admin_audit(
            admin_id=payload['user_id'],
            admin_email=payload.get('email') or payload.get('sub', ''),
            action_type=action_name,
            target_type='ORDER',
            target_id=order_id,
            reason=f"Couirer: {courier_name}, Tracking: {tracking_number}",
            request_ip=request.remote_addr,
            user_agent=request.user_agent.string
        )

        return jsonify({
            'message': f"운송장 번호({courier_name} {tracking_number})가 정상 등록되었습니다.",
            'order_id': order_id,
            'order_status': 'SHIPPING'
        }), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@admin_bp.route('/orders/<int:order_id>/address', methods=['PATCH', 'POST'])
def admin_update_shipping_address(order_id):
    """Row Lock 기반 출고 전 배송지 정보 수정 API (SHIPPING 이후 409 ADDRESS_CHANGE_NOT_ALLOWED)"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    recipient_name = data.get('recipient_name', '').strip()
    recipient_phone = data.get('recipient_phone', '').strip()
    postal_code = data.get('postal_code', '').strip()
    address = data.get('address', '').strip()
    address_detail = data.get('address_detail', '').strip()
    delivery_memo = data.get('delivery_memo', '').strip()

    if not recipient_name or not recipient_phone or not address:
        return jsonify({'error': '수령인, 연락처, 주소는 필수 입력 항목입니다.'}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (order_id,))
            order = cursor.fetchone()
            if not order:
                conn.rollback()
                return jsonify({'error': '주문을 찾을 수 없습니다.'}), 404

            if order['order_status'] in ('SHIPPING', 'DELIVERED', 'CANCELLED'):
                conn.rollback()
                return jsonify({
                    'code': 'ADDRESS_CHANGE_NOT_ALLOWED',
                    'error': f"[{order['order_status']}] 상태인 주문은 배송지를 변경할 수 없습니다."
                }), 409

            cursor.execute("""
                UPDATE orders
                SET recipient_name = %s, recipient_phone = %s, postal_code = %s,
                    address = %s, address_detail = %s, delivery_memo = %s
                WHERE id = %s
            """, (recipient_name, recipient_phone, postal_code, address, address_detail, delivery_memo, order_id))
            conn.commit()

        # PII 원문 미포함 보안 Audit Log
        log_admin_audit(
            admin_id=payload['user_id'],
            admin_email=payload.get('email') or payload.get('sub', ''),
            action_type='ADDRESS_UPDATED',
            target_type='ORDER',
            target_id=order_id,
            reason=json.dumps({"recipient_changed": True, "phone_changed": True, "address_changed": True}),
            request_ip=request.remote_addr,
            user_agent=request.user_agent.string
        )

        return jsonify({'message': '배송지 정보가 성공적으로 수정되었습니다.'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@admin_bp.route('/orders/<int:order_id>/refund/preview', methods=['POST'])
def admin_order_refund_preview(order_id):
    """환불 예정 금액 및 잔액 미리보기 (비확정 참고용 계산)"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    items = data.get('items', [])
    if not items:
        return jsonify({'error': '환불할 상품을 1개 이상 선택해 주세요.'}), 400

    resp, status_code = preview_refund_calculation(order_id, items)
    return jsonify(resp), status_code

@admin_bp.route('/orders/<int:order_id>/refund', methods=['POST'])
def admin_order_refund(order_id):
    """관리자 2-Phase 멱등 환불 실행 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'code': 'REFUND_PERMISSION_DENIED', 'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    operation_id = data.get('operation_id', '').strip()
    items = data.get('items', [])
    reason = data.get('reason', '고객변심').strip()

    if not items:
        return jsonify({'error': '환불할 상품을 1개 이상 선택해 주세요.'}), 400

    resp, status_code = process_refund_request(order_id, operation_id, items, reason, admin_id=payload['user_id'])

    log_admin_audit(
        admin_id=payload['user_id'],
        admin_email=payload.get('email') or payload.get('sub', ''),
        action_type='REFUND_EXECUTE',
        target_type='ORDER',
        target_id=order_id,
        reason=reason,
        result='SUCCESS' if status_code in (200, 202) else 'FAILED',
        request_ip=request.remote_addr,
        user_agent=request.user_agent.string
    )

    return jsonify(resp), status_code

@admin_bp.route('/orders/<int:order_id>/notes', methods=['POST'])
def admin_add_order_note(order_id):
    """관리자 이력 보존 메모 추가 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    note = data.get('note', '').strip()
    if not note:
        return jsonify({'error': '메모 내용을 입력해 주세요.'}), 400

    admin_email = payload.get('email') or payload.get('sub', '')
    execute_db("""
        INSERT INTO order_admin_notes (order_id, admin_id, admin_email, note)
        VALUES (%s, %s, %s, %s)
    """, (order_id, payload['user_id'], admin_email, note))

    log_admin_audit(
        admin_id=payload['user_id'],
        admin_email=admin_email,
        action_type='ADMIN_NOTE_ADDED',
        target_type='ORDER',
        target_id=order_id,
        reason=note[:50],
        request_ip=request.remote_addr,
        user_agent=request.user_agent.string
    )

    return jsonify({'message': '관리자 메모가 성공적으로 등록되었습니다.'}), 201


def can_update_shipping_address(order, active_fulfillment_shipments):
    """
    배송지 수정 가능 여부 검증 헬퍼 (Final Frozen Business Rule)
    """
    order_status = (order.get('order_status') or '').upper()
    allowed_statuses = {"PENDING", "CONFIRMED", "PREPARING", "READY_TO_SHIP", "READY_FOR_FULFILLMENT", "PREPARING_SHIPMENT", "배송 준비중", "배송준비중", "상품 준비중", "상품준비중", "주문대기", "주문확정", "결제완료"}
    if order_status not in allowed_statuses and (order.get('order_status') or '') not in allowed_statuses:
        return False, "SHIPPING_ADDRESS_UPDATE_NOT_ALLOWED", "이미 출고가 진행되었거나 취소된 주문은 배송지를 수정할 수 없습니다."

    if len(active_fulfillment_shipments) > 1:
        return False, "FULFILLMENT_STATE_CONFLICT", "활성 배송건이 복수로 존재하여 배송지를 수정할 수 없습니다."

    if len(active_fulfillment_shipments) == 1:
        shipment = active_fulfillment_shipments[0]
        shipment_status = (shipment.get('status') or '').upper()
        if shipment_status not in {"PENDING", "READY"}:
            return False, "SHIPPING_ADDRESS_UPDATE_NOT_ALLOWED", "이미 택배 출고가 진행 중인 배송건입니다."
        if shipment.get('tracking_number'):
            return False, "SHIPPING_ADDRESS_UPDATE_NOT_ALLOWED", "운송장 번호가 이미 등록된 배송건은 수정할 수 없습니다."

    return True, None, None


@admin_bp.route('/orders/<int:order_id>/address', methods=['PUT', 'PATCH'])
def admin_update_order_shipping_address(order_id):
    """
    관리자 주문 배송지 스냅샷 수정 API (Lock Ordering, Allow-list, AuditLog Atomic Transaction)
    """
    payload = verify_admin_auth()
    if not payload:
        return jsonify({
            'success': False,
            'error': {'code': 'FORBIDDEN', 'message': '관리자 권한이 필요합니다.'}
        }), 403

    data = request.get_json() or {}
    recipient_name = (data.get('recipient_name') or '').strip()
    recipient_phone_raw = (data.get('recipient_phone') or '').strip()
    postal_code = (data.get('postal_code') or '').strip()
    address = (data.get('address') or '').strip()
    address_detail = (data.get('address_detail') or '').strip()
    delivery_memo = (data.get('delivery_memo') or '').strip()
    reason_type = (data.get('reason_type') or '').strip()
    reason_detail = (data.get('reason_detail') or '').strip()

    # Normalization & Validation
    if not recipient_name or len(recipient_name) > 50:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': '수령인 이름을 입력해 주세요.'}}), 400

    phone_digits = ''.join(filter(str.isdigit, recipient_phone_raw))
    if not (9 <= len(phone_digits) <= 11):
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': '연락처는 올바른 전화번호 형태(9~11자리 숫자)여야 합니다.'}}), 400
    recipient_phone = recipient_phone_raw

    if not postal_code or len(postal_code) != 5 or not postal_code.isdigit():
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': '우편번호는 5자리 숫자로 입력해 주세요.'}}), 400

    if not address:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': '기본 주소를 입력해 주세요.'}}), 400

    if len(delivery_memo) > 100:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': '배송 메모는 최대 100자까지 작성할 수 있습니다.'}}), 400

    valid_reasons = {'CUSTOMER_REQUEST', 'ADDRESS_TYPO', 'PHONE_CHANGE', 'OTHER'}
    if reason_type not in valid_reasons:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': '올바른 변경 사유 구분을 선택해 주세요.'}}), 400

    if not reason_detail:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': '변경 사유 상세 내용을 반드시 입력해 주세요.'}}), 400

    # DB Transaction Execution
    conn = get_db_connection()
    try:
        conn.autocommit(False)
        cursor = conn.cursor()

        # 1. Order Lock 획득 (Order -> Shipment 순서 준수)
        cursor.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (order_id,))
        order = cursor.fetchone()
        if not order:
            conn.rollback()
            return jsonify({'success': False, 'error': {'code': 'ORDER_NOT_FOUND', 'message': '해당 주문을 찾을 수 없습니다.'}}), 404

        # 2. Shipment Lock 획득 (purpose='FULFILLMENT' & active 상태만)
        cursor.execute("""
            SELECT * FROM shipments 
            WHERE order_id = %s AND purpose = 'FULFILLMENT' AND status NOT IN ('CANCELLED', 'FAILED', 'RETURNED')
            FOR UPDATE
        """, (order_id,))
        active_shipments = cursor.fetchall() or []

        # 3. Allow-list 검증
        is_allowed, err_code, err_msg = can_update_shipping_address(order, active_shipments)
        if not is_allowed:
            conn.rollback()
            return jsonify({'success': False, 'error': {'code': err_code, 'message': err_msg}}), 409

        # Before Snapshot
        before_snapshot = {
            'recipient_name': order.get('recipient_name'),
            'recipient_phone': order.get('recipient_phone'),
            'postal_code': order.get('postal_code'),
            'address': order.get('address'),
            'address_detail': order.get('address_detail'),
            'delivery_memo': order.get('delivery_memo')
        }

        # 4. orders 배송지 스냅샷 갱신
        cursor.execute("""
            UPDATE orders 
            SET recipient_name = %s, recipient_phone = %s, postal_code = %s, address = %s, address_detail = %s, delivery_memo = %s
            WHERE id = %s
        """, (recipient_name, recipient_phone, postal_code, address, address_detail, delivery_memo, order_id))

        after_snapshot = {
            'recipient_name': recipient_name,
            'recipient_phone': recipient_phone,
            'postal_code': postal_code,
            'address': address,
            'address_detail': address_detail,
            'delivery_memo': delivery_memo
        }

        # 5. admin_audit_logs 기입 (동일 트랜잭션)
        admin_email = payload.get('email') or payload.get('sub', 'admin@example.com')
        reason_summary = f"[{reason_type}] {reason_detail}" if reason_detail else f"[{reason_type}]"
        
        cursor.execute("""
            INSERT INTO admin_audit_logs (admin_id, admin_email, action_type, target_type, target_id, reason, result, request_ip, user_agent, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        """, (
            payload.get('user_id', 1),
            admin_email,
            'ORDER_SHIPPING_ADDRESS_UPDATED',
            'ORDER',
            str(order_id),
            reason_summary,
            'SUCCESS',
            request.remote_addr or '127.0.0.1',
            request.user_agent.string if request.user_agent else ''
        ))

        # Commit
        conn.commit()

        # 최신 주문 단일 조회 반환 (Single Source of Truth)
        updated_order = query_db("SELECT * FROM orders WHERE id = %s", (order_id,), one=True)
        return jsonify({'success': True, 'message': '배송지 정보가 성공적으로 수정되었습니다.', 'order': updated_order}), 200

    except Exception as ex:
        if conn:
            conn.rollback()
        current_app.logger.error(f"admin_update_order_shipping_address Exception: {ex}", exc_info=True)
        return jsonify({'success': False, 'error': {'code': 'INTERNAL_SERVER_ERROR', 'message': '배송지 정보를 저장하지 못했습니다.'}}), 500
    finally:
        if conn:
            conn.close()


# ── CARRIER REGISTRY & SHIPMENT API ──────────────────────────────────────────────

CARRIER_REGISTRY = {
    'CJ_LOGISTICS': {
        'code': 'CJ_LOGISTICS',
        'name': 'CJ대한통운',
        'tracking_url': lambda num: f"https://www.cjlogistics.com/ko/tool/parcel/tracking?gnbInvcNo={num}"
    },
    'EPOST': {
        'code': 'EPOST',
        'name': '우체국택배',
        'tracking_url': lambda num: f"https://service.epost.go.kr/trace.RetrieveDomRレースTraceList.comm?sid1={num}"
    },
    'HANJIN': {
        'code': 'HANJIN',
        'name': '한진택배',
        'tracking_url': lambda num: f"https://www.hanjin.co.kr/kor/CMS/DeliveryMgr/WaybillResult.do?mCode=MN038&wblnum={num}"
    },
    'LOTTE': {
        'code': 'LOTTE',
        'name': '롯데택배',
        'tracking_url': lambda num: f"https://www.lotteglogis.com/home/reservation/tracking/linkView?InvNo={num}"
    }
}


def can_ship_order(order, active_fulfillment_shipments):
    """
    운송장 등록 및 출고 가능 여부 검증 헬퍼 (Final Frozen Business Rule)
    """
    # 1. 기존 운송장 등록 여부 최우선 검증 (TRACKING_ALREADY_REGISTERED)
    if order.get("tracking_number"):
        return False, "TRACKING_ALREADY_REGISTERED", "이미 운송장이 등록된 주문입니다."

    # 2. 활성 FULFILLMENT Shipment 0개 검증 (FULFILLMENT_NOT_FOUND)
    if len(active_fulfillment_shipments) == 0:
        return False, "FULFILLMENT_NOT_FOUND", "출고 가능한 배송건을 찾을 수 없습니다."

    # 3. 활성 FULFILLMENT Shipment 복수 검증 (FULFILLMENT_STATE_CONFLICT)
    if len(active_fulfillment_shipments) > 1:
        return False, "FULFILLMENT_STATE_CONFLICT", "활성 배송건이 복수로 존재하여 출고 처리할 수 없습니다."

    # 4. Shipment 자체의 기존 운송장 검증 (TRACKING_ALREADY_REGISTERED)
    shipment = active_fulfillment_shipments[0]
    if shipment.get("tracking_number"):
        return False, "TRACKING_ALREADY_REGISTERED", "이미 운송장이 등록된 주문입니다."

    # 5. 주문 상태 검증 (오직 '배송 준비중' 단계만 출고 허용)
    order_st = (order.get("order_status") or "").upper()
    ready_to_ship_set = {"READY_TO_SHIP", "READY_FOR_FULFILLMENT", "PREPARING_SHIPMENT", "배송 준비중", "배송준비중"}
    if order_st not in ready_to_ship_set and (order.get("order_status") or "") not in ready_to_ship_set:
        return False, "ORDER_NOT_READY_FOR_SHIPMENT", "배송 준비중 단계의 주문만 운송장을 등록하고 출고할 수 있습니다."

    # 6. Shipment 상태 검증 (SHIPMENT_STATE_CONFLICT)
    if shipment.get("status") not in {"PENDING", "READY"}:
        return False, "SHIPMENT_STATE_CONFLICT", "현재 배송건 상태에서는 출고할 수 없습니다."

    return True, None, None


@admin_bp.route('/orders/<int:order_id>/shipment', methods=['POST'])
def admin_ship_order(order_id):
    """
    관리자 운송장 등록 및 원자적 출고 처리 API (Lock Ordering, Allow-list, Carrier Registry)
    """
    payload = verify_admin_auth()
    if not payload:
        return jsonify({
            'success': False,
            'error': {'code': 'FORBIDDEN', 'message': '관리자 권한이 필요합니다.'}
        }), 403

    data = request.get_json() or {}
    carrier_code = (data.get('carrier_code') or '').strip().upper()
    tracking_number = (data.get('tracking_number') or '').strip()

    # Validation
    if not carrier_code or carrier_code not in CARRIER_REGISTRY:
        return jsonify({
            'success': False,
            'error': {'code': 'VALIDATION_ERROR', 'message': '올바른 택배사를 선택해 주세요.'}
        }), 400

    cleaned_tracking = ''.join(c for c in tracking_number if c.isalnum())
    if not cleaned_tracking or len(cleaned_tracking) < 5 or len(cleaned_tracking) > 25:
        return jsonify({
            'success': False,
            'error': {'code': 'VALIDATION_ERROR', 'message': '운송장 번호를 올바르게 입력해 주세요 (영문/숫자 5~25자리).' }
        }), 400

    carrier_info = CARRIER_REGISTRY[carrier_code]

    conn = get_db_connection()
    try:
        conn.autocommit(False)
        cursor = conn.cursor()

        # 1. Order Lock 획득 (Order -> Shipment 순서 준수)
        cursor.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (order_id,))
        order = cursor.fetchone()
        if not order:
            conn.rollback()
            return jsonify({
                'success': False,
                'error': {'code': 'ORDER_NOT_FOUND', 'message': '해당 주문을 찾을 수 없습니다.'}
            }), 404

        # 2. Shipment Lock 획득 (purpose='FULFILLMENT' & active 상태만)
        cursor.execute("""
            SELECT * FROM shipments 
            WHERE order_id = %s AND purpose = 'FULFILLMENT' AND status NOT IN ('CANCELLED', 'FAILED', 'RETURNED')
            FOR UPDATE
        """, (order_id,))
        active_shipments = cursor.fetchall() or []

        # 3. Allow-list 검증 (우선순위 준수)
        is_allowed, err_code, err_msg = can_ship_order(order, active_shipments)
        if not is_allowed:
            conn.rollback()
            return jsonify({
                'success': False,
                'error': {'code': err_code, 'message': err_msg}
            }), 409

        shipment = active_shipments[0]

        # 4. shipments 테이블 UPDATE
        cursor.execute("""
            UPDATE shipments 
            SET carrier_code = %s, courier = %s, tracking_number = %s, status = 'SHIPPED', shipped_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (carrier_code, carrier_info['name'], cleaned_tracking, shipment['id']))

        # 5. orders 테이블 Denormalized Snapshot UPDATE
        cursor.execute("""
            UPDATE orders 
            SET order_status = 'SHIPPING', courier_name = %s, tracking_number = %s
            WHERE id = %s
        """, (carrier_info['name'], cleaned_tracking, order_id))

        # 6. admin_audit_logs 기입 (동일 트랜잭션)
        admin_email = payload.get('email') or payload.get('sub', 'admin@example.com')
        reason_summary = f"[출고처리] 택배사: {carrier_info['name']}, 운송장번호: {cleaned_tracking}"
        
        cursor.execute("""
            INSERT INTO admin_audit_logs (admin_id, admin_email, action_type, target_type, target_id, reason, result, request_ip, user_agent, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        """, (
            payload.get('user_id', 1),
            admin_email,
            'ORDER_SHIPPED',
            'ORDER',
            str(order_id),
            reason_summary,
            'SUCCESS',
            request.remote_addr or '127.0.0.1',
            request.user_agent.string if request.user_agent else ''
        ))

        # Commit
        conn.commit()

        # 최신 주문 단일 조회 반환 (Single Source of Truth)
        updated_order = query_db("SELECT * FROM orders WHERE id = %s", (order_id,), one=True)
        tracking_url = carrier_info['tracking_url'](cleaned_tracking)

        return jsonify({
            'success': True,
            'message': '운송장이 성공적으로 등록되고 출고 처리되었습니다.',
            'order': updated_order,
            'carrier_code': carrier_code,
            'carrier_name': carrier_info['name'],
            'tracking_number': cleaned_tracking,
            'tracking_url': tracking_url
        }), 200

    except Exception as ex:
        if conn:
            conn.rollback()
        current_app.logger.error(f"admin_ship_order Exception: {ex}", exc_info=True)
        return jsonify({
            'success': False,
            'error': {'code': 'INTERNAL_SERVER_ERROR', 'message': '운송장 등록 및 출고 처리를 진행하지 못했습니다.'}
        }), 500
    finally:
        if conn:
            conn.close()

@admin_bp.route('/customers', methods=['GET'])
def admin_customers():
    """회원 목록 필터링, 검색 및 페이지네이션 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    keyword = request.args.get('keyword', '').strip()
    status_filter = request.args.get('status', '').strip()

    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1

    try:
        limit = max(1, min(100, int(request.args.get('limit', 10))))
    except (ValueError, TypeError):
        limit = 10

    offset = (page - 1) * limit

    where_clauses = ["1=1"]
    args = []

    if status_filter:
        where_clauses.append("status = %s")
        args.append(status_filter)

    if keyword:
        where_clauses.append("(name LIKE %s OR email LIKE %s OR phone LIKE %s)")
        kw_pattern = f"%{keyword}%"
        args.extend([kw_pattern, kw_pattern, kw_pattern])

    where_str = " WHERE " + " AND ".join(where_clauses)

    count_sql = f"SELECT COUNT(*) as cnt FROM users {where_str}"
    count_row = query_db(count_sql, tuple(args), one=True)
    total_count = int(count_row['cnt'] or 0) if count_row else 0
    total_pages = max(1, (total_count + limit - 1) // limit)

    select_sql = f"SELECT id, email, name, phone, created_at, status FROM users {where_str} ORDER BY id DESC LIMIT %s OFFSET %s"
    fetch_args = list(args) + [limit, offset]

    users = query_db(select_sql, tuple(fetch_args)) or []
    
    customer_list = []
    for u in users:
        customer_list.append({
            'id': u['id'],
            'email': u.get('email', '') or '-',
            'name': u.get('name', '') or '(이름 없음)',
            'phone': u.get('phone', '') or '-',
            'created_at': str(u.get('created_at', '')),
            'status': u.get('status', 'ACTIVE')
        })

    return jsonify({
        'customers': customer_list,
        'pagination': {
            'page': page,
            'limit': limit,
            'total_count': total_count,
            'total_pages': total_pages
        }
    }), 200


@admin_bp.route('/customers/<int:user_id>/unmask', methods=['POST'])
def admin_unmask_customer(user_id):
    """5단계 원문 조회 게이트웨이 (목적 입력 & 재인증 ➔ PII_VIEW Audit 기록)"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    password = data.get('password', '').strip()
    reason = data.get('reason', '').strip()

    if not password or not reason:
        return jsonify({'error': '비밀번호 재인증과 조회 목적을 모두 입력해 주세요.'}), 400

    admin = query_db("SELECT * FROM admin_users WHERE id = %s", (payload['user_id'],), one=True)
    if not admin or not check_password(password, admin['password_hash']):
        return jsonify({'error': '관리자 비밀번호가 올바르지 않습니다.'}), 401

    user = query_db("SELECT id, email, name, phone, created_at FROM users WHERE id = %s", (user_id,), one=True)
    if not user:
        return jsonify({'error': '회원을 찾을 수 없습니다.'}), 404

    log_admin_audit(
        admin_id=payload['user_id'],
        admin_email=payload.get('email') or payload.get('sub', ''),
        action_type='CUSTOMER_PII_VIEW',
        target_type='USER',
        target_id=user_id,
        reason=reason,
        result='SUCCESS',
        request_ip=request.remote_addr,
        user_agent=request.user_agent.string
    )

    return jsonify({
        'message': '원문 조회가 승인되었습니다.',
        'user': user
    }), 200

@admin_bp.route('/customers/<int:user_id>/status', methods=['PATCH', 'POST'])
def admin_update_customer_status(user_id):
    """회원 상태(ACTIVE / SUSPENDED) 변경 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    new_status = data.get('status', '').strip().upper()
    if new_status not in ('ACTIVE', 'SUSPENDED'):
        return jsonify({'error': '올바른 회원 상태(ACTIVE, SUSPENDED)를 지정해 주세요.'}), 400

    execute_db("UPDATE users SET status = %s WHERE id = %s", (new_status, user_id))

    log_admin_audit(
        admin_id=payload['user_id'],
        admin_email=payload.get('email') or payload.get('sub', ''),
        action_type='USER_STATUS_CHANGE',
        target_type='USER',
        target_id=user_id,
        reason=f"Status changed to {new_status}",
        request_ip=request.remote_addr,
        user_agent=request.user_agent.string
    )

    return jsonify({'message': f'회원 상태가 {new_status}(으)로 성공적으로 변경되었습니다.'}), 200

@admin_bp.route('/customers/<int:user_id>', methods=['PATCH', 'POST', 'PUT'])
def admin_update_customer(user_id):
    """회원 정보(이름, 이메일, 연락처, 계정 상태, 비밀번호) 수정 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip()
    phone = data.get('phone', '').strip()
    status = data.get('status', 'ACTIVE').strip().upper()
    new_password = data.get('new_password', '').strip()

    if not email:
        return jsonify({'error': '이메일 주소는 필수 입력 항목입니다.'}), 400

    # 이메일 중복 체크 (본인 계정 제외)
    existing = query_db("SELECT id FROM users WHERE email = %s AND id != %s", (email, user_id), one=True)
    if existing:
        return jsonify({'error': '이미 다른 회원이 사용 중인 이메일 주소입니다.'}), 400

    if new_password:
        if len(new_password) < 4:
            return jsonify({'error': '비밀번호는 최소 4자 이상이어야 합니다.'}), 400
        pass_hash = hash_password(new_password)
        execute_db(
            "UPDATE users SET name = %s, email = %s, phone = %s, status = %s, password_hash = %s WHERE id = %s",
            (name, email, phone, status, pass_hash, user_id)
        )
        msg = "회원 정보 및 비밀번호가 성공적으로 변경되었습니다."
    else:
        execute_db(
            "UPDATE users SET name = %s, email = %s, phone = %s, status = %s WHERE id = %s",
            (name, email, phone, status, user_id)
        )
        msg = "회원 정보가 성공적으로 수정되었습니다."

    log_admin_audit(
        admin_id=payload['user_id'],
        admin_email=payload.get('email') or payload.get('sub', ''),
        action_type='USER_INFO_UPDATE',
        target_type='USER',
        target_id=user_id,
        reason=f"Updated member details: name={name}, email={email}, phone={phone}, status={status}, pass_reset={'YES' if new_password else 'NO'}",
        request_ip=request.remote_addr,
        user_agent=request.user_agent.string
    )

    return jsonify({'message': msg}), 200

@admin_bp.route('/audit-logs', methods=['GET'])
def admin_audit_logs_list():
    """운영 감사로그 검색, 필터링 및 페이지네이션 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    keyword = request.args.get('keyword', '').strip()
    action_type = request.args.get('action_type', '').strip()
    target_type = request.args.get('target_type', '').strip()

    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1

    try:
        limit = max(1, min(100, int(request.args.get('limit', 15))))
    except (ValueError, TypeError):
        limit = 15

    offset = (page - 1) * limit

    where_clauses = ["1=1"]
    args = []

    if action_type:
        where_clauses.append("action_type = %s")
        args.append(action_type)

    if target_type:
        where_clauses.append("target_type = %s")
        args.append(target_type)

    if keyword:
        where_clauses.append("(admin_email LIKE %s OR action_type LIKE %s OR target_id LIKE %s OR reason LIKE %s)")
        kw_pattern = f"%{keyword}%"
        args.extend([kw_pattern, kw_pattern, kw_pattern, kw_pattern])

    where_str = " WHERE " + " AND ".join(where_clauses)

    count_sql = f"SELECT COUNT(*) as cnt FROM admin_audit_logs {where_str}"
    count_row = query_db(count_sql, tuple(args), one=True)
    total_count = int(count_row['cnt'] or 0) if count_row else 0
    total_pages = max(1, (total_count + limit - 1) // limit)

    select_sql = f"SELECT * FROM admin_audit_logs {where_str} ORDER BY id DESC LIMIT %s OFFSET %s"
    fetch_args = list(args) + [limit, offset]

    logs = query_db(select_sql, tuple(fetch_args)) or []

    formatted_logs = []
    for l in logs:
        formatted_logs.append({
            'id': l['id'],
            'admin_id': l['admin_id'],
            'admin_email': l.get('admin_email', '') or '-',
            'action_type': l.get('action_type', '') or '-',
            'target_type': l.get('target_type', '') or '-',
            'target_id': l.get('target_id', '') or '-',
            'reason': l.get('reason', '') or '-',
            'request_ip': l.get('request_ip', '') or '-',
            'result': l.get('result', 'SUCCESS'),
            'created_at': str(l.get('created_at', ''))
        })

    return jsonify({
        'audit_logs': formatted_logs,
        'pagination': {
            'page': page,
            'limit': limit,
            'total_count': total_count,
            'total_pages': total_pages
        }
    }), 200

def escape_csv_formula(val):
    """Formula Injection 방어 캐릭터 escape (`=, +, -, @, \t, \r, \n, ＝, ＋, －, ＠`)"""
    if val is None:
        return ""
    s = str(val)
    if not s:
        return ""
    
    first_char = s[0]
    dangerous_chars = ('=', '+', '-', '@', '\t', '\r', '\n', '＝', '＋', '－', '＠')
    if first_char in dangerous_chars:
        return f"'{s}"
    return s

@admin_bp.route('/orders/export', methods=['GET'])
def admin_export_orders():
    """택배사 Import용 / 관리자 Excel용 2원화 CSV 다운로드 API (Formula Escape)"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    export_type = request.args.get('type', 'excel')
    orders = query_db("SELECT * FROM orders WHERE order_status IN ('CONFIRMED', 'PREPARING') ORDER BY id ASC") or []

    output = io.StringIO()
    writer = csv.writer(output)

    if export_type == 'shipping':
        writer.writerow(['주문번호', '수령인명', '연락처', '우편번호', '주소', '상세주소', '배송메모'])
        for ord in orders:
            writer.writerow([
                ord['order_number'],
                ord['recipient_name'],
                ord['recipient_phone'],
                ord['postal_code'],
                ord['address'],
                ord['address_detail'] or '',
                ord['delivery_memo'] or ''
            ])
    else:
        writer.writerow(['주문번호', '주문일시', '수령인명', '연락처', '우편번호', '주소', '상세주소', '배송메모', '결제금액', '주문상태'])
        for ord in orders:
            writer.writerow([
                escape_csv_formula(ord['order_number']),
                escape_csv_formula(str(ord['created_at'])),
                escape_csv_formula(ord['recipient_name']),
                escape_csv_formula(ord['recipient_phone']),
                escape_csv_formula(ord['postal_code']),
                escape_csv_formula(ord['address']),
                escape_csv_formula(ord['address_detail'] or ''),
                escape_csv_formula(ord['delivery_memo'] or ''),
                escape_csv_formula(ord['total_amount']),
                escape_csv_formula(ord['order_status'])
            ])

    log_admin_audit(
        admin_id=payload['user_id'],
        admin_email=payload.get('email') or payload.get('sub', ''),
        action_type='ORDER_EXPORT',
        target_type='ORDER',
        record_count=len(orders),
        request_ip=request.remote_addr,
        user_agent=request.user_agent.string
    )

    csv_content = output.getvalue()
    filename = f"order_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        '\ufeff' + csv_content,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@admin_bp.route('/products', methods=['GET', 'POST'])
def admin_products():
    """상품 목록 조회 및 신규 등록 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    if request.method == 'GET':
        keyword = request.args.get('keyword', '').strip()
        category_id = request.args.get('category_id', '').strip()
        is_active = request.args.get('is_active', '').strip()

        try:
            page = max(1, int(request.args.get('page', 1)))
        except (ValueError, TypeError):
            page = 1

        try:
            limit = max(1, min(100, int(request.args.get('limit', 10))))
        except (ValueError, TypeError):
            limit = 10

        offset = (page - 1) * limit

        base_sql = "FROM products p JOIN categories c ON p.category_id = c.id"
        where_clauses = ["1=1"]
        args = []

        if category_id and category_id.isdigit():
            where_clauses.append("p.category_id = %s")
            args.append(int(category_id))

        if is_active in ('0', '1'):
            where_clauses.append("p.is_active = %s")
            args.append(int(is_active))

        if keyword:
            where_clauses.append("(p.name LIKE %s OR p.capacity LIKE %s OR p.description LIKE %s)")
            kw_pattern = f"%{keyword}%"
            args.extend([kw_pattern, kw_pattern, kw_pattern])

        where_str = " WHERE " + " AND ".join(where_clauses)

        count_sql = f"SELECT COUNT(*) as cnt {base_sql} {where_str}"
        count_row = query_db(count_sql, tuple(args), one=True)
        total_count = int(count_row['cnt'] or 0) if count_row else 0
        total_pages = max(1, (total_count + limit - 1) // limit)

        select_sql = f"SELECT p.*, c.name as category_name {base_sql} {where_str} ORDER BY p.id DESC LIMIT %s OFFSET %s"
        fetch_args = list(args) + [limit, offset]

        products = query_db(select_sql, tuple(fetch_args)) or []
        for p in products:
            p['options'] = query_db("SELECT * FROM product_options WHERE product_id = %s", (p['id'],)) or []

        return jsonify({
            'products': products,
            'pagination': {
                'page': page,
                'limit': limit,
                'total_count': total_count,
                'total_pages': total_pages
            }
        }), 200


    elif request.method == 'POST':
        data = request.get_json() or {}
        name = data.get('name', '').strip()
        category_id = int(data.get('category_id', 1))
        price = int(data.get('price', 0))
        capacity = data.get('capacity', '').strip()
        description = data.get('description', '').strip()
        badge = data.get('badge', '').strip()
        image_url = data.get('image_url', 'assets/product_sesame.png')
        
        shelf_life_text = data.get('shelf_life_text', '제조일로부터 12개월')
        origin_info = data.get('origin_info', '참깨/들깨: 국산(강원도 영월군 100%)')
        food_type = data.get('food_type', '식용유지류')
        contents_capacity = data.get('contents_capacity', capacity)
        raw_ingredients = data.get('raw_ingredients', '국산 100%')
        manufacturer = data.get('manufacturer', '영월고향방앗간')
        storage_method = data.get('storage_method', '직사광선을 피하고 서늘한 곳 보관')
        allergy_notice = data.get('allergy_notice', '참깨/들깨 함유')
        nutrition_facts = data.get('nutrition_facts', '100ml당 884kcal')
        delivery_info = data.get('delivery_info', '평일 14시 이전 주문 시 당일 발송 (1~2일 내 도착 예정)').strip() or '평일 14시 이전 주문 시 당일 발송 (1~2일 내 도착 예정)'

        if not name or price <= 0:
            return jsonify({'error': '상품명과 가격을 올바르게 입력해 주세요.'}), 400

        product_id = execute_db("""
            INSERT INTO products (
                category_id, name, price, capacity, description, badge, image_url,
                shelf_life_text, origin_info, food_type, contents_capacity, raw_ingredients,
                manufacturer, storage_method, allergy_notice, nutrition_facts, delivery_info
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            category_id, name, price, capacity, description, badge, image_url,
            shelf_life_text, origin_info, food_type, contents_capacity, raw_ingredients,
            manufacturer, storage_method, allergy_notice, nutrition_facts, delivery_info
        ))

        options_data = data.get('options', [])
        if options_data:
            for opt in options_data:
                opt_name = str(opt.get('option_name', '기본')).strip() or '기본'
                add_price = int(opt.get('additional_price', 0))
                stock = int(opt.get('stock', 100))
                execute_db("""
                    INSERT INTO product_options (product_id, option_name, additional_price, stock, reserved_stock)
                    VALUES (%s, %s, %s, %s, 0)
                """, (product_id, opt_name, add_price, stock))
        else:
            initial_stock = int(data.get('stock', 100))
            execute_db("""
                INSERT INTO product_options (product_id, option_name, additional_price, stock, reserved_stock)
                VALUES (%s, '300ml (기본)', 0, %s, 0)
            """, (product_id, initial_stock))

        return jsonify({'message': '신규 상품이 성공적으로 등록되었습니다.', 'product_id': product_id}), 201

@admin_bp.route('/products/<int:product_id>', methods=['GET', 'PATCH', 'PUT'])
def admin_update_product(product_id):
    """상품 상세 조회, 기본 정보 및 옵션 재고 통합 수정 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    product = query_db("SELECT * FROM products WHERE id = %s", (product_id,), one=True)
    if not product:
        return jsonify({'error': '상품을 찾을 수 없습니다.'}), 404

    if request.method == 'GET':
        options = query_db("SELECT * FROM product_options WHERE product_id = %s", (product_id,)) or []
        product['options'] = options
        return jsonify({'product': product}), 200

    data = request.get_json() or {}

    # 1. is_active / 기본 정보 수정
    fields = []
    args = []

    if 'name' in data:
        fields.append("name = %s")
        args.append(data['name'].strip())
    if 'category_id' in data:
        fields.append("category_id = %s")
        args.append(int(data['category_id']))
    if 'price' in data:
        fields.append("price = %s")
        args.append(int(data['price']))
    if 'capacity' in data:
        fields.append("capacity = %s")
        args.append(data['capacity'].strip())
    if 'description' in data:
        fields.append("description = %s")
        args.append(data['description'].strip())
    if 'badge' in data:
        fields.append("badge = %s")
        args.append(data['badge'].strip())
    if 'is_active' in data:
        fields.append("is_active = %s")
        args.append(int(data['is_active']))
    if 'food_type' in data:
        fields.append("food_type = %s")
        args.append(data['food_type'].strip())
    if 'manufacturer' in data:
        fields.append("manufacturer = %s")
        args.append(data['manufacturer'].strip())
    if 'shelf_life_text' in data:
        fields.append("shelf_life_text = %s")
        args.append(data['shelf_life_text'].strip())
    if 'contents_capacity' in data:
        fields.append("contents_capacity = %s")
        args.append(data['contents_capacity'].strip())
    if 'origin_info' in data:
        fields.append("origin_info = %s")
        args.append(data['origin_info'].strip())
    if 'storage_method' in data:
        fields.append("storage_method = %s")
        args.append(data['storage_method'].strip())
    if 'allergy_notice' in data:
        fields.append("allergy_notice = %s")
        args.append(data['allergy_notice'].strip())
    if 'cs_phone' in data:
        fields.append("cs_phone = %s")
        args.append(data['cs_phone'].strip())
    if 'delivery_info' in data:
        fields.append("delivery_info = %s")
        args.append(data['delivery_info'].strip())

    if fields:
        args.append(product_id)
        sql = f"UPDATE products SET {', '.join(fields)} WHERE id = %s"
        execute_db(sql, tuple(args))
    # 2. 옵션 등록 / 수정 / 삭제 통합 처리
    if 'options' in data:
        options_data = data.get('options', [])
        existing_opts = query_db("SELECT id FROM product_options WHERE product_id = %s", (product_id,)) or []
        existing_ids = {o['id'] for o in existing_opts}
        keep_ids = set()

        for opt in options_data:
            opt_id = opt.get('id')
            stock = int(opt.get('stock', 100))
            add_price = int(opt.get('additional_price', 0))
            opt_name = str(opt.get('option_name', '기본')).strip() or '기본'

            if opt_id and opt_id in existing_ids:
                keep_ids.add(opt_id)
                execute_db("""
                    UPDATE product_options 
                    SET option_name = %s, additional_price = %s, stock = %s 
                    WHERE id = %s AND product_id = %s
                """, (opt_name, add_price, stock, opt_id, product_id))
            else:
                execute_db("""
                    INSERT INTO product_options (product_id, option_name, additional_price, stock, reserved_stock)
                    VALUES (%s, %s, %s, %s, 0)
                """, (product_id, opt_name, add_price, stock))

        delete_ids = existing_ids - keep_ids
        for del_id in delete_ids:
            execute_db("DELETE FROM product_options WHERE id = %s AND product_id = %s", (del_id, product_id))

    log_admin_audit(
        admin_id=payload['user_id'],
        admin_email=payload.get('email') or payload.get('sub', ''),
        action_type='UPDATE_PRODUCT_STOCK',
        target_type='PRODUCT',
        target_id=product_id,
        request_ip=request.remote_addr,
        user_agent=request.user_agent.string
    )

    return jsonify({'message': '상품 및 재고 정보가 성공적으로 변경되었습니다.'}), 200

@admin_bp.route('/options/<int:option_id>/stock', methods=['PATCH'])
def admin_update_option_stock(option_id):
    """옵션 재고(stock) 단건 즉시 변경 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    new_stock = data.get('stock')

    if new_stock is None or int(new_stock) < 0:
        return jsonify({'error': '올바른 재고 수량을 입력해 주세요.'}), 400

    opt = query_db("SELECT * FROM product_options WHERE id = %s", (option_id,), one=True)
    if not opt:
        return jsonify({'error': '상품 옵션을 찾을 수 없습니다.'}), 404

    execute_db("UPDATE product_options SET stock = %s WHERE id = %s", (int(new_stock), option_id))

    log_admin_audit(
        admin_id=payload['user_id'],
        admin_email=payload['sub'],
        action_type='UPDATE_OPTION_STOCK',
        target_type='OPTION',
        target_id=option_id,
        reason=f"stock: {opt['stock']} -> {new_stock}",
        request_ip=request.remote_addr,
        user_agent=request.user_agent.string
    )

    return jsonify({
        'message': f"옵션({opt['option_name']}) 재고가 {new_stock}개로 성공적으로 변경되었습니다.",
        'option_id': option_id,
        'stock': int(new_stock)
    }), 200

# ==============================================================================
# 주문 단계별 Workflow Command & CS 관리 Batch APIs (100% Sealed Final Freeze)
# ==============================================================================

@admin_bp.route('/orders/counts', methods=['GET'])
def admin_orders_subtab_counts():
    """단계별 / CS별 서브 탭 실시간 건수 Badge 조회 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    pending_cnt = int((query_db("""
        SELECT COUNT(*) as c FROM orders o
        WHERE o.order_status IN ('PENDING', 'CONFIRMED')
          AND o.payment_status IN ('PAID', 'PARTIALLY_REFUNDED')
          AND (
              (SELECT COALESCE(SUM(quantity), 0) FROM order_items WHERE order_id = o.id) -
              (SELECT COALESCE(SUM(si.quantity), 0) FROM shipment_items si JOIN shipments s ON si.shipment_id = s.id WHERE s.order_id = o.id AND s.purpose = 'FULFILLMENT')
          ) > 0
    """, one=True) or {}).get('c', 0))
    confirmed_cnt = 0
    preparing_cnt = int((query_db("SELECT COUNT(*) as c FROM orders WHERE order_status = 'PREPARING'", one=True) or {}).get('c', 0))
    ready_to_ship_cnt = int((query_db("SELECT COUNT(*) as c FROM orders WHERE order_status = 'READY_TO_SHIP'", one=True) or {}).get('c', 0))
    shipping_cnt = int((query_db("SELECT COUNT(*) as c FROM orders WHERE order_status = 'SHIPPING'", one=True) or {}).get('c', 0))
    delivered_cnt = int((query_db("SELECT COUNT(*) as c FROM orders WHERE order_status = 'DELIVERED'", one=True) or {}).get('c', 0))

    cs_cancel_cnt = int((query_db("SELECT COUNT(DISTINCT order_id) as c FROM cancellation_requests", one=True) or {}).get('c', 0))
    if cs_cancel_cnt == 0:
        cs_cancel_cnt = int((query_db("SELECT COUNT(*) as c FROM orders WHERE order_status = 'CANCELLED'", one=True) or {}).get('c', 0))

    cs_return_cnt = int((query_db("SELECT COUNT(DISTINCT order_id) as c FROM return_requests", one=True) or {}).get('c', 0))
    cs_exchange_cnt = int((query_db("SELECT COUNT(DISTINCT order_id) as c FROM exchange_requests", one=True) or {}).get('c', 0))
    cs_refund_cnt = int((query_db("SELECT COUNT(DISTINCT order_id) as c FROM refund_requests WHERE status IN ('PENDING', 'PROCESSING', 'FAILED', 'RECONCILE_REQUIRED')", one=True) or {}).get('c', 0))
    reconcile_warning_cnt = int((query_db("SELECT COUNT(DISTINCT order_id) as c FROM refund_requests WHERE status = 'RECONCILE_REQUIRED'", one=True) or {}).get('c', 0))

    return jsonify({
        'pending': pending_cnt,
        'confirmed': confirmed_cnt,
        'preparing': preparing_cnt,
        'ready_to_ship': ready_to_ship_cnt,
        'shipping': shipping_cnt,
        'delivered': delivered_cnt,
        'cs_cancel': cs_cancel_cnt,
        'cs_return': cs_return_cnt,
        'cs_exchange': cs_exchange_cnt,
        'cs_refund': cs_refund_cnt,
        'reconcile_warning': reconcile_warning_cnt
    }), 200

def _process_batch_order_command(order_ids, target_status, admin_payload, action_type, require_shipment=False):
    conn = get_db_connection()
    success_ids = []
    failed_list = []
    try:
        for oid in order_ids:
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (oid,))
                    order = cursor.fetchone()
                    if not order:
                        failed_list.append({'order_id': oid, 'reason': 'NOT_FOUND', 'message': '주문을 찾을 수 없습니다.'})
                        continue

                    qty_info = OrderStateMachine.compute_order_quantities(conn, oid)

                    shipment = None
                    if target_status == 'SHIPPING' or require_shipment:
                        cursor.execute("SELECT * FROM shipments WHERE order_id = %s AND purpose = 'FULFILLMENT' ORDER BY id DESC LIMIT 1", (oid,))
                        shipment = cursor.fetchone()
                        if not shipment and order.get('tracking_number'):
                            shipment = {
                                'carrier_code': order.get('courier_name'),
                                'tracking_number': order.get('tracking_number')
                            }

                    # Validate transition & 2-tier context guards
                    OrderStateMachine.validate_transition(order['order_status'], target_status, order['payment_status'])
                    OrderStateMachine.validate_guards(order, target_status, shipment=shipment, qty_info=qty_info)

                    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    extra_updates = ""
                    if target_status == 'SHIPPING':
                        extra_updates = f", shipped_at = '{now_str}'"
                        if shipment and isinstance(shipment, dict) and shipment.get('id'):
                            cursor.execute("UPDATE shipments SET status = 'SHIPPED', shipped_at = %s WHERE id = %s", (now_str, shipment['id']))
                    elif target_status == 'DELIVERED':
                        extra_updates = f", delivered_at = '{now_str}'"
                        cursor.execute("UPDATE shipments SET status = 'DELIVERED', delivered_at = %s WHERE order_id = %s AND purpose = 'FULFILLMENT'", (now_str, oid))
                        
                        # Notification Outbox & SMS Enqueue (DELIVERED:{oid} 멱등키)
                        try:
                            from services.notification_service import NotificationService
                            recipient = order.get('recipient_phone') or order.get('guest_phone') or ''
                            if recipient:
                                NotificationService().enqueue(
                                    event_type="DELIVERED",
                                    recipient=recipient,
                                    template_code="DELIVERED",
                                    message=f"[영월고향방앗간] 고객님의 상품 배송이 완료되었습니다. (주문번호: {order['order_number']}, 운송장번호: {order.get('tracking_number','')})",
                                    idempotency_key=f"DELIVERED:{oid}",
                                    fallback_template_key="DELIVERED_SMS",
                                    order_id=oid,
                                    data={'order_number': order['order_number'], 'tracking_number': order.get('tracking_number', '')}
                                )
                        except Exception:
                            pass
                    elif target_status == 'READY_TO_SHIP':
                        cursor.execute("SELECT id FROM shipments WHERE order_id = %s AND purpose = 'FULFILLMENT'", (oid,))
                        if not cursor.fetchone():
                            cursor.execute("""
                                INSERT INTO shipments (order_id, purpose, carrier_code, tracking_number, status)
                                VALUES (%s, 'FULFILLMENT', %s, %s, 'READY')
                            """, (oid, order.get('courier_name'), order.get('tracking_number')))
                            ship_id = cursor.lastrowid
                            cursor.execute("SELECT id, quantity FROM order_items WHERE order_id = %s", (oid,))
                            o_items = cursor.fetchall() or []
                            for oi in o_items:
                                cursor.execute("""
                                    INSERT INTO shipment_items (shipment_id, order_item_id, quantity)
                                    VALUES (%s, %s, %s)
                                """, (ship_id, oi['id'], oi['quantity']))

                    cursor.execute(f"UPDATE orders SET order_status = %s {extra_updates} WHERE id = %s", (target_status, oid))
                    conn.commit()
                    success_ids.append(oid)

                    log_admin_audit(
                        admin_id=admin_payload['user_id'],
                        admin_email=admin_payload.get('email') or admin_payload.get('sub', ''),
                        action_type=action_type,
                        target_type='ORDER',
                        target_id=oid,
                        reason=f"Batch transition to {target_status}"
                    )
            except OrderStateMachineError as err:
                conn.rollback()
                failed_list.append({'order_id': oid, 'reason': err.code, 'message': err.message})
            except Exception as e:
                conn.rollback()
                failed_list.append({'order_id': oid, 'reason': 'INTERNAL_ERROR', 'message': str(e)})
    finally:
        conn.close()

    return jsonify({
        'success': success_ids,
        'failed': failed_list
    }), 200

@admin_bp.route('/orders/confirm', methods=['POST'])
def admin_batch_confirm_orders():
    """신규 주문대기건 ➔ 주문확정(CONFIRMED) 일괄 처리 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
    order_ids = (request.get_json() or {}).get('order_ids', [])
    return _process_batch_order_command(order_ids, 'CONFIRMED', payload, 'BATCH_CONFIRM_ORDERS')

@admin_bp.route('/orders/prepare', methods=['POST'])
def admin_batch_prepare_orders():
    """주문확정건 ➔ 상품준비중(PREPARING) 일괄 처리 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
    order_ids = (request.get_json() or {}).get('order_ids', [])
    return _process_batch_order_command(order_ids, 'PREPARING', payload, 'BATCH_PREPARE_ORDERS')

@admin_bp.route('/orders/ready-to-ship', methods=['POST'])
def admin_batch_ready_to_ship_orders():
    """상품준비중 ➔ 배송준비중(READY_TO_SHIP) 전환 API (Shipment 할당 생성)"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
    order_ids = (request.get_json() or {}).get('order_ids', [])
    return _process_batch_order_command(order_ids, 'READY_TO_SHIP', payload, 'BATCH_READY_TO_SHIP_ORDERS')

@admin_bp.route('/orders/ship', methods=['POST'])
def admin_batch_ship_orders():
    """배송준비중 ➔ 배송중(SHIPPING) 일괄 전환 API (송장/택배사 필수 검증)"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
    order_ids = (request.get_json() or {}).get('order_ids', [])
    return _process_batch_order_command(order_ids, 'SHIPPING', payload, 'BATCH_SHIP_ORDERS', require_shipment=True)

@admin_bp.route('/orders/deliver', methods=['POST'])
def admin_batch_deliver_orders():
    """배송중 ➔ 배송완료(DELIVERED) 일괄 전환 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
    order_ids = (request.get_json() or {}).get('order_ids', [])
    return _process_batch_order_command(order_ids, 'DELIVERED', payload, 'BATCH_DELIVER_ORDERS')


# ── 운송장 CSV 기능 공용 상수 ─────────────────────────────────────────────────
ALLOWED_CARRIERS = {'CJ', 'LOTTE', 'HANJIN', 'POST', 'LOGEN', 'EPOST'}
CARRIER_DISPLAY = {
    'CJ': 'CJ대한통운', 'LOTTE': '롯데택배', 'HANJIN': '한진택배',
    'POST': '우체국택배', 'LOGEN': '로젠택배', 'EPOST': 'EMS(국제우편)'
}
MAX_TRACKING_CSV_ROWS = 2000
MAX_TRACKING_CSV_BYTES = 5 * 1024 * 1024  # 5 MB


def _apply_tracking_to_shipment(cursor, shipment_id, carrier_code, tracking_number):
    """
    Shipment에 carrier_code/tracking_number를 적용하고 orders 및 shipments를 배송중(SHIPPING) 상태로 자동 전이합니다.
    """
    courier_display = CARRIER_DISPLAY.get(carrier_code, carrier_code)
    
    # 1. Source of Truth: Shipment
    cursor.execute(
        "UPDATE shipments SET carrier_code = %s, tracking_number = %s, status = 'SHIPPED', shipped_at = NOW() WHERE id = %s",
        (carrier_code, tracking_number, shipment_id)
    )
    # 2. Legacy Mirror & Order State Transition: orders -> SHIPPING
    cursor.execute(
        "UPDATE orders SET courier_name = %s, tracking_number = %s, order_status = 'SHIPPING', shipped_at = NOW() "
        "WHERE id = (SELECT order_id FROM shipments WHERE id = %s)",
        (courier_display, tracking_number, shipment_id)
    )
    # 만약 shipments에 없던 order_id로 직접 불린 경우 fallback
    cursor.execute(
        "UPDATE orders SET courier_name = %s, tracking_number = %s, order_status = 'SHIPPING', shipped_at = NOW() "
        "WHERE id = %s AND order_status = 'READY_TO_SHIP'",
        (courier_display, tracking_number, shipment_id)
    )


@admin_bp.route('/orders/tracking-template', methods=['GET'])
def admin_tracking_template():
    """READY_TO_SHIP 주문의 송장 등록 양식 CSV 다운로드 (최대 2,000건)"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    rows = query_db("""
        SELECT o.id AS order_id, COALESCE(s.id, o.id) AS shipment_id, o.order_number,
               o.recipient_name, o.recipient_phone, o.postal_code,
               CONCAT(o.address, ' ', COALESCE(o.address_detail, '')) AS full_address,
               COALESCE(o.courier_name, 'CJ대한통운') AS courier_name,
               COALESCE(o.tracking_number, '') AS tracking_number
        FROM orders o
        LEFT JOIN shipments s ON o.id = s.order_id AND s.purpose = 'FULFILLMENT' AND s.status = 'READY'
        WHERE o.order_status = 'READY_TO_SHIP'
        ORDER BY o.id ASC
    """) or []

    if len(rows) > MAX_TRACKING_CSV_ROWS:
        return jsonify({
            'error': f"현재 {len(rows):,}건입니다. 필터를 적용하여 {MAX_TRACKING_CSV_ROWS:,}건 이하로 다운로드하세요."
        }), 400

    output = io.StringIO()
    writer = csv.writer(output)

    # 순수 데이터 헤더 (1행부터 바로 시작)
    writer.writerow(['shipment_id', 'order_number', 'recipient_name', 'recipient_phone',
                     'carrier_code', 'tracking_number'])

    for r in rows:
        writer.writerow([
            r['shipment_id'],
            r['order_number'],
            escape_csv_formula(r['recipient_name'] or ''),
            escape_csv_formula(r['recipient_phone'] or ''),
            r['courier_name'] or 'CJ대한통운',  # carrier_code 기본값
            r['tracking_number'] or ''           # tracking_number 입력칸
        ])

    log_admin_audit(
        admin_id=payload['user_id'],
        admin_email=payload.get('email') or payload.get('sub', ''),
        action_type='TRACKING_TEMPLATE_EXPORT',
        target_type='ORDER',
        record_count=len(rows),
        request_ip=request.remote_addr,
        user_agent=request.user_agent.string
    )

    filename = f"tracking_template_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        '\ufeff' + output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@admin_bp.route('/orders/import-tracking-csv', methods=['POST'])
def admin_import_tracking_csv():
    """
    운송장 CSV 일괄 업로드 API.
    - 송장 등록(carrier_code/tracking_number)만 수행.
    - 배송 상태 전이(READY_TO_SHIP → SHIPPING)는 하지 않음.
    - 관리자가 [선택 배송 시작] 버튼으로 별도 처리.
    """
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    if 'file' not in request.files:
        return jsonify({'error': 'file 필드가 없습니다.'}), 400

    f = request.files['file']

    # 1. 확장자 검사 (.csv — MIME은 보조 참고만)
    filename_lower = (f.filename or '').lower()
    if not filename_lower.endswith('.csv'):
        return jsonify({'error': '.csv 파일만 업로드 가능합니다.'}), 400

    raw_bytes = f.read()

    # 2. 파일 크기 검사 (5 MB)
    if len(raw_bytes) > MAX_TRACKING_CSV_BYTES:
        return jsonify({'error': f'파일 크기는 {MAX_TRACKING_CSV_BYTES // 1024 // 1024}MB를 초과할 수 없습니다.'}), 400

    # 3. 인코딩 감지: utf-8-sig → cp949
    raw_text = None
    for enc in ('utf-8-sig', 'cp949'):
        try:
            raw_text = raw_bytes.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if raw_text is None:
        return jsonify({'error': 'INVALID_ENCODING: utf-8 또는 cp949(EUC-KR) 인코딩만 지원합니다.'}), 400

    # 4. # 주석 행 제거 후 csv.DictReader 파싱
    lines = raw_text.splitlines()
    data_lines = [l for l in lines if not l.strip().startswith('#')]
    if not data_lines:
        return jsonify({'error': 'CSV 내용이 비어 있습니다.'}), 400

    reader = csv.DictReader(data_lines)
    required_headers = {'shipment_id', 'order_number', 'carrier_code', 'tracking_number'}
    if not reader.fieldnames or not required_headers.issubset(set(reader.fieldnames)):
        missing = required_headers - set(reader.fieldnames or [])
        return jsonify({'error': f'필수 헤더가 누락되었습니다: {", ".join(sorted(missing))}'}), 400

    csv_rows = list(reader)

    # 5. Data Row 수 제한 (2,000행)
    if len(csv_rows) > MAX_TRACKING_CSV_ROWS:
        return jsonify({
            'error': f'행 수({len(csv_rows):,}건)가 최대 허용치({MAX_TRACKING_CSV_ROWS:,}건)를 초과합니다.'
        }), 400

    # 6. CSV 전체에서 shipment_id 중복 사전 검출
    seen_shipment_ids = set()
    duplicate_ids = set()
    for row in csv_rows:
        sid = (row.get('shipment_id') or '').strip()
        if sid in seen_shipment_ids:
            duplicate_ids.add(sid)
        else:
            seen_shipment_ids.add(sid)

    # 7. 행별 처리
    results = []
    success_count = 0
    failed_count = 0
    skipped_count = 0

    for row in csv_rows:
        csv_shipment_id_str = (row.get('shipment_id') or '').strip()
        csv_order_number    = (row.get('order_number') or '').strip()
        carrier_code        = (row.get('carrier_code') or '').strip().upper()
        tracking_number     = str(row.get('tracking_number') or '').strip()

        def _fail(reason, message):
            nonlocal failed_count
            failed_count += 1
            results.append({
                'shipment_id': csv_shipment_id_str,
                'order_number': csv_order_number,
                'success': False,
                'skipped': False,
                'reason': reason,
                'message': message
            })

        def _skip(reason, message):
            nonlocal skipped_count
            skipped_count += 1
            results.append({
                'shipment_id': csv_shipment_id_str,
                'order_number': csv_order_number,
                'success': None,
                'skipped': True,
                'reason': reason,
                'message': message
            })

        # 사전 중복 검출된 shipment_id
        if csv_shipment_id_str in duplicate_ids:
            _fail('DUPLICATE_SHIPMENT', 'CSV에 같은 Shipment ID가 중복되어 있습니다.')
            continue

        # shipment_id 숫자 검증
        try:
            shipment_id = int(csv_shipment_id_str)
        except (ValueError, TypeError):
            _fail('INVALID_SHIPMENT_ID', 'shipment_id가 유효하지 않습니다.')
            continue

        # carrier_code 한글/약어 유연 매핑
        carrier_raw = (row.get('carrier_code') or '').strip()
        carrier_upper = carrier_raw.upper()
        
        carrier_map = {
            'CJ': 'CJ', 'CJ대한통운': 'CJ', '대한통운': 'CJ',
            'EPOST': 'EPOST', '우체국': 'EPOST', '우체국택배': 'EPOST',
            'LOTTE': 'LOTTE', '롯데': 'LOTTE', '롯데택배': 'LOTTE',
            'HANJIN': 'HANJIN', '한진': 'HANJIN', '한진택배': 'HANJIN',
            'LOGEN': 'LOGEN', '로젠': 'LOGEN', '로젠택배': 'LOGEN'
        }
        carrier_code = carrier_map.get(carrier_raw, carrier_map.get(carrier_upper, carrier_upper))

        # carrier_code 검증
        if carrier_code not in ALLOWED_CARRIERS:
            _fail('INVALID_CARRIER', f'지원하지 않는 택배사입니다: {carrier_raw} (허용값: CJ대한통운, 우체국택배, 롯데택배, 한진택배, 로젠택배)')
            continue

        # tracking_number 검증
        if not tracking_number:
            _fail('TRACKING_REQUIRED', '운송장 번호가 비어 있습니다.')
            continue

        # 행별 독립 Transaction
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # P0-1: shipment_id 단독 FOR UPDATE → 단계별 순차 검증
                cursor.execute("""
                    SELECT s.id, s.purpose, s.status,
                           o.order_number AS o_order_number,
                           o.order_status, o.fulfillment_hold
                    FROM shipments s
                    JOIN orders o ON o.id = s.order_id
                    WHERE s.id = %s
                    FOR UPDATE
                """, (shipment_id,))
                db_row = cursor.fetchone()

                if not db_row:
                    conn.rollback()
                    _fail('SHIPMENT_NOT_FOUND', '해당 Shipment를 찾을 수 없습니다.')
                    continue

                if db_row['o_order_number'] != csv_order_number:
                    conn.rollback()
                    _fail('ORDER_MISMATCH', f"주문번호가 일치하지 않습니다. (DB: {db_row['o_order_number']})")
                    continue

                if db_row['purpose'] != 'FULFILLMENT':
                    conn.rollback()
                    _fail('INVALID_SHIPMENT_PURPOSE', 'FULFILLMENT 용도의 Shipment가 아닙니다.')
                    continue

                if db_row['order_status'] not in ('READY_TO_SHIP', 'SHIPPING'):
                    conn.rollback()
                    _skip('INVALID_ORDER_STATUS', f"처리 불가 주문 상태입니다. (현재: {db_row['order_status']})")
                    continue

                if db_row['status'] != 'READY':
                    conn.rollback()
                    _skip('INVALID_SHIPMENT_STATUS', f"이미 처리된 Shipment입니다. (현재 상태: {db_row['status']})")
                    continue

                if db_row['fulfillment_hold']:
                    conn.rollback()
                    _fail('FULFILLMENT_HELD', '주문이 이행 보류 상태입니다.')
                    continue

                # Shipment 업데이트 (Source of Truth) + orders Mirror (Legacy)
                _apply_tracking_to_shipment(cursor, shipment_id, carrier_code, tracking_number)

                conn.commit()

            # AuditLog (커밋 후)
            log_admin_audit(
                admin_id=payload['user_id'],
                admin_email=payload.get('email') or payload.get('sub', ''),
                action_type='TRACKING_CSV_IMPORTED',
                target_type='SHIPMENT',
                target_id=shipment_id,
                reason=f"CSV Import: {carrier_code} / {tracking_number} (주문: {csv_order_number})",
                request_ip=request.remote_addr,
                user_agent=request.user_agent.string
            )

            success_count += 1
            results.append({
                'shipment_id': csv_shipment_id_str,
                'order_number': csv_order_number,
                'success': True,
                'skipped': False,
                'reason': None,
                'message': f'{CARRIER_DISPLAY.get(carrier_code, carrier_code)} {tracking_number} 등록 완료'
            })

        except Exception as e:
            conn.rollback()
            _fail('INTERNAL_ERROR', str(e))
        finally:
            conn.close()

    return jsonify({
        'total': len(csv_rows),
        'success': success_count,
        'failed': failed_count,
        'skipped': skipped_count,
        'results': results
    }), 200


@admin_bp.route('/orders/batch-tracking', methods=['POST'])
def admin_batch_register_tracking():
    """인라인 송장 번호 배열 일괄 등록 및 Shipment 저장 API (헬퍼 재사용)"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    items = data.get('items', [])
    if not items or not isinstance(items, list):
        return jsonify({'error': '송장 등록 항목 배열(items)이 올바르지 않습니다.'}), 400

    conn = get_db_connection()
    success_ids = []
    failed_list = []

    try:
        for item in items:
            oid = item.get('order_id')
            carrier = str(item.get('carrier_code', '')).strip()
            tracking = str(item.get('tracking_number', '')).strip()

            if not oid or not carrier or not tracking:
                failed_list.append({'order_id': oid, 'reason': 'INVALID_INPUT', 'message': '주문ID, 택배사명, 운송장번호가 모두 필요합니다.'})
                continue

            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (oid,))
                    order = cursor.fetchone()
                    if not order:
                        failed_list.append({'order_id': oid, 'reason': 'NOT_FOUND', 'message': '주문을 찾을 수 없습니다.'})
                        continue

                    if order.get('fulfillment_hold'):
                        failed_list.append({'order_id': oid, 'reason': 'FULFILLMENT_HELD', 'message': '주문이 보류 상태입니다.'})
                        continue

                    cursor.execute("SELECT id FROM shipments WHERE order_id = %s AND purpose = 'FULFILLMENT'", (oid,))
                    ship_row = cursor.fetchone()
                    if ship_row:
                        # 헬퍼 재사용 (Source of Truth: Shipment, Mirror: orders)
                        _apply_tracking_to_shipment(cursor, ship_row['id'], carrier, tracking)
                        cursor.execute("UPDATE shipments SET status = 'READY' WHERE id = %s", (ship_row['id'],))
                    else:
                        cursor.execute("""
                            INSERT INTO shipments (order_id, purpose, carrier_code, tracking_number, status)
                            VALUES (%s, 'FULFILLMENT', %s, %s, 'READY')
                        """, (oid, carrier, tracking))
                        ship_id = cursor.lastrowid
                        # Legacy Mirror
                        cursor.execute(
                            "UPDATE orders SET courier_name = %s, tracking_number = %s WHERE id = %s",
                            (carrier, tracking, oid)
                        )
                        cursor.execute("SELECT id, quantity FROM order_items WHERE order_id = %s", (oid,))
                        o_items = cursor.fetchall() or []
                        for oi in o_items:
                            cursor.execute("""
                                INSERT INTO shipment_items (shipment_id, order_item_id, quantity)
                                VALUES (%s, %s, %s)
                            """, (ship_id, oi['id'], oi['quantity']))

                    conn.commit()
                    success_ids.append(oid)
            except Exception as e:
                conn.rollback()
                failed_list.append({'order_id': oid, 'reason': 'INTERNAL_ERROR', 'message': str(e)})
    finally:
        conn.close()

    return jsonify({
        'success': success_ids,
        'failed': failed_list
    }), 200


@admin_bp.route('/orders/cancel', methods=['POST'])
def admin_batch_cancel_orders():
    """Saga 패턴 기반 결제완료/미결제 주문 안전 취소 및 RefundEngine 연동 API"""
    payload = verify_admin_auth()
    if not payload:
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403

    data = request.get_json() or {}
    order_ids = data.get('order_ids', [])
    reason = data.get('reason', '관리자 취소').strip()

    if not order_ids or not isinstance(order_ids, list):
        return jsonify({'error': '취소할 주문 ID 목록(order_ids)을 제공해 주세요.'}), 400

    success_ids = []
    failed_list = []

    for oid in order_ids:
        # Tx 1: Lock order, verify shipped_qty == 0, set fulfillment_hold = 1
        conn_tx1 = get_db_connection()
        try:
            with conn_tx1.cursor() as cursor:
                cursor.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (oid,))
                order = cursor.fetchone()
                if not order:
                    failed_list.append({'order_id': oid, 'reason': 'NOT_FOUND', 'message': '주문을 찾을 수 없습니다.'})
                    conn_tx1.rollback()
                    continue

                qty_info = OrderStateMachine.compute_order_quantities(conn_tx1, oid)

                if qty_info['shipped_qty'] > 0:
                    failed_list.append({'order_id': oid, 'reason': 'SHIPPED_ITEMS_CANNOT_BE_CANCELLED', 'message': '이미 출고된 품목은 취소할 수 없습니다. 반품/교환 절차를 이용해 주세요.'})
                    conn_tx1.rollback()
                    continue

                if order['order_status'] in ('CANCELLED', 'REFUNDED'):
                    failed_list.append({'order_id': oid, 'reason': 'ALREADY_CANCELLED', 'message': '이미 취소/환불된 주문입니다.'})
                    conn_tx1.rollback()
                    continue

                cursor.execute("UPDATE orders SET fulfillment_hold = 1, fulfillment_hold_reason = 'CANCELLATION_IN_PROGRESS' WHERE id = %s", (oid,))

                cursor.execute("""
                    INSERT INTO cancellation_requests (order_id, reason_code, reason_detail, status)
                    VALUES (%s, 'ADMIN_CANCEL', %s, 'PENDING')
                """, (oid, reason))
                cancel_req_id = cursor.lastrowid

                cursor.execute("SELECT id, quantity FROM order_items WHERE order_id = %s", (oid,))
                o_items = cursor.fetchall() or []
                for oi in o_items:
                    cursor.execute("""
                        INSERT INTO cancellation_request_items (cancellation_request_id, order_item_id, requested_qty, approved_qty)
                        VALUES (%s, %s, %s, %s)
                    """, (cancel_req_id, oi['id'], oi['quantity'], oi['quantity']))

                # P0 Allocation Cleanup: Remove un-shipped shipment items
                cursor.execute("""
                    SELECT si.id
                    FROM shipment_items si
                    JOIN shipments s ON si.shipment_id = s.id
                    WHERE s.order_id = %s AND s.purpose = 'FULFILLMENT' AND s.status IN ('CREATED', 'READY')
                """, (oid,))
                alloc_items = cursor.fetchall() or []
                for ai in alloc_items:
                    cursor.execute("DELETE FROM shipment_items WHERE id = %s", (ai['id'],))

                conn_tx1.commit()
        except Exception as e:
            conn_tx1.rollback()
            failed_list.append({'order_id': oid, 'reason': 'TX1_FAILED', 'message': str(e)})
            conn_tx1.close()
            continue
        finally:
            conn_tx1.close()

        # Process Refund if PAID / PARTIALLY_REFUNDED
        if order['payment_status'] in ('PAID', 'PARTIALLY_REFUNDED'):
            try:
                items = query_db("SELECT * FROM order_items WHERE order_id = %s", (oid,)) or []
                items_payload = [{'order_item_id': it['id'], 'quantity': it['quantity'] - it['cancelled_qty']} for it in items if (it['quantity'] - it['cancelled_qty']) > 0]
                op_id = f"CANCEL_BATCH_{oid}_{int(datetime.datetime.now().timestamp())}"
                refund_res, http_code = process_refund_request(
                    order_id=oid,
                    operation_id=op_id,
                    items=items_payload,
                    reason=reason,
                    admin_id=payload['user_id']
                )
                refund_status = refund_res.get('status') if isinstance(refund_res, dict) else None

                conn_tx2 = get_db_connection()
                try:
                    with conn_tx2.cursor() as cursor:
                        cursor.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (oid,))
                        curr_order = cursor.fetchone()

                        if refund_status == 'SUCCEEDED' or http_code == 200:
                            cursor.execute("UPDATE cancellation_requests SET status = 'COMPLETED' WHERE id = %s", (cancel_req_id,))
                            cursor.execute("UPDATE cancellation_request_items SET approved_qty = requested_qty WHERE cancellation_request_id = %s", (cancel_req_id,))
                            
                            qty_info_after = OrderStateMachine.compute_order_quantities(conn_tx2, oid)
                            new_pay_status = OrderStateMachine.calculate_payment_status(curr_order['total_amount'], curr_order['total_amount'])

                            if qty_info_after['remaining_uncancelled_qty'] == 0 and qty_info_after['shipped_qty'] == 0:
                                target_ord_status = 'CANCELLED'
                            else:
                                target_ord_status = curr_order['order_status']

                            cursor.execute("""
                                UPDATE orders
                                SET order_status = %s, payment_status = %s, fulfillment_hold = 0, fulfillment_hold_reason = NULL
                                WHERE id = %s
                            """, (target_ord_status, new_pay_status, oid))
                            conn_tx2.commit()
                            success_ids.append(oid)

                            # Notification Outbox & SMS Enqueue (CANCEL:{oid} 멱등키)
                            try:
                                from services.notification_service import NotificationService
                                recipient = curr_order.get('recipient_phone') or curr_order.get('guest_phone') or ''
                                if recipient:
                                    NotificationService().enqueue(
                                        event_type="ORDER_CANCELLED",
                                        recipient=recipient,
                                        template_code="ORDER_CANCELLED",
                                        message=f"[영월고향방앗간] 주문이 정상 취소되었습니다. (주문번호: {curr_order['order_number']}, 사유: {reason})",
                                        idempotency_key=f"CANCEL:{oid}",
                                        fallback_template_key="ORDER_CANCELLED_SMS",
                                        order_id=oid,
                                        data={'order_number': curr_order['order_number'], 'cancel_reason': reason}
                                    )
                            except Exception:
                                pass
                        elif refund_status == 'RECONCILE_REQUIRED':
                            # P0 Invariant: Maintain fulfillment_hold = 1 during RECONCILE_REQUIRED!
                            cursor.execute("UPDATE cancellation_requests SET status = 'RECONCILING' WHERE id = %s", (cancel_req_id,))
                            cursor.execute("""
                                UPDATE orders
                                SET fulfillment_hold = 1, fulfillment_hold_reason = 'RECONCILE_REQUIRED'
                                WHERE id = %s
                            """, (oid,))
                            conn_tx2.commit()
                            failed_list.append({'order_id': oid, 'reason': 'RECONCILE_REQUIRED', 'message': 'PG 대조(RECONCILE_REQUIRED) 완료 전까지 출고가 차단됩니다.'})
                        else:
                            cursor.execute("UPDATE cancellation_requests SET status = 'FAILED' WHERE id = %s", (cancel_req_id,))
                            cursor.execute("""
                                UPDATE orders
                                SET fulfillment_hold = 0, fulfillment_hold_reason = NULL
                                WHERE id = %s
                            """, (oid,))
                            conn_tx2.commit()
                            failed_list.append({'order_id': oid, 'reason': 'REFUND_FAILED', 'message': 'PG 환불 실패로 취소가 취소되었습니다.'})
                finally:
                    conn_tx2.close()
            except Exception as ref_e:
                failed_list.append({'order_id': oid, 'reason': 'REFUND_ENGINE_ERROR', 'message': str(ref_e)})
        else:
            # Unpaid cancellation
            conn_tx2 = get_db_connection()
            try:
                with conn_tx2.cursor() as cursor:
                    cursor.execute("UPDATE cancellation_requests SET status = 'COMPLETED' WHERE id = %s", (cancel_req_id,))
                    cursor.execute("""
                        UPDATE orders
                        SET order_status = 'CANCELLED', payment_status = 'CANCELLED', fulfillment_hold = 0, fulfillment_hold_reason = NULL
                        WHERE id = %s
                    """, (oid,))
                    conn_tx2.commit()
                    success_ids.append(oid)

                    # Notification Outbox & SMS Enqueue (CANCEL:{oid} 멱등키)
                    try:
                        from services.notification_service import NotificationService
                        recipient = order.get('recipient_phone') or order.get('guest_phone') or ''
                        if recipient:
                            NotificationService().enqueue(
                                event_type="ORDER_CANCELLED",
                                recipient=recipient,
                                template_code="ORDER_CANCELLED",
                                message=f"[영월고향방앗간] 주문이 정상 취소되었습니다. (주문번호: {order['order_number']}, 사유: {reason})",
                                idempotency_key=f"CANCEL:{oid}",
                                fallback_template_key="ORDER_CANCELLED_SMS",
                                order_id=oid,
                                data={'order_number': order['order_number'], 'cancel_reason': reason}
                            )
                    except Exception:
                        pass
            finally:
                conn_tx2.close()

    return jsonify({
        'success': success_ids,
        'failed': failed_list
    }), 200

