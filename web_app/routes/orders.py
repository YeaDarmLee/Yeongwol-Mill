import datetime
import random
import string
from flask import Blueprint, request, jsonify
from config import Config
from db.db_connection import query_db, execute_db, execute_db_conn, get_db_connection
from middlewares.auth import verify_jwt_token, hash_password, check_password

orders_bp = Blueprint('orders', __name__, url_prefix='/api/orders')

def generate_order_number():
    """주문번호 생성 (예: ORD-20260824-A8F2K9)"""
    today_str = datetime.datetime.now().strftime('%Y%m%d')
    random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"ORD-{today_str}-{random_str}"

def calculate_remote_surcharge(postal_code):
    """우편번호 앞자리를 기반으로 도서산간 추가 배송비를 계산합니다."""
    if not postal_code:
        return 0
    clean_code = postal_code.strip()
    rules = query_db("SELECT * FROM remote_shipping_rules") or []
    for rule in rules:
        prefix = rule['postal_code_prefix']
        if clean_code.startswith(prefix):
            return rule['surcharge']
    return 0

@orders_bp.route('', methods=['POST'])
def create_order():
    """회원 및 비회원 주문 생성 API (단일 트랜잭션 Atomic 재고 차감 & 금액 스냅샷)"""
    data = request.get_json() or {}
    
    items = data.get('items', [])
    recipient_name = data.get('recipient_name', '').strip()
    recipient_phone = data.get('recipient_phone', '').strip()
    postal_code = data.get('postal_code', '').strip()
    address = data.get('address', '').strip()
    address_detail = data.get('address_detail', '').strip()
    delivery_memo = data.get('delivery_memo', '').strip()
    
    user_id = None
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split()[1]
        payload = verify_jwt_token(token)
        if payload:
            user_id = payload.get('user_id')
    
    guest_name = data.get('guest_name', '').strip()
    guest_phone = data.get('guest_phone', '').strip()
    guest_password = data.get('guest_password', '').strip()
    
    if not items or not recipient_name or not recipient_phone or not address:
        return jsonify({'error': '필수 주문 정보(상품 목록, 수령인, 연락처, 배송지 주소)가 누락되었습니다.'}), 400

    if not user_id:
        if not guest_name or not guest_phone or not guest_password:
            return jsonify({'error': '비회원 주문 조회를 위해 성함, 연락처, 비밀번호를 입력해 주세요.'}), 400

    subtotal_amount = 0
    order_items_to_insert = []
    reservation_targets = []
    
    for item in items:
        product_id = item.get('product_id')
        option_id = item.get('option_id')
        quantity = int(item.get('quantity', 1))
        
        product = query_db("SELECT * FROM products WHERE id = %s AND is_active = 1", (product_id,), one=True)
        if not product:
            return jsonify({'error': f"상품(ID: {product_id})이 존재하지 않거나 판매 중단되었습니다."}), 400
        
        if option_id:
            option = query_db("SELECT * FROM product_options WHERE id = %s AND product_id = %s", (option_id, product_id), one=True)
        else:
            option = query_db("SELECT * FROM product_options WHERE product_id = %s LIMIT 1", (product_id,), one=True)
            
        if not option:
            return jsonify({'error': f"상품 '{product['name']}'의 선택 가능한 옵션이 없습니다."}), 400
            
        available_stock = option['stock'] - option['reserved_stock']
        if available_stock < quantity:
            return jsonify({'error': f"상품 '{product['name']}' ({option['option_name']}) 재고가 부족합니다. (가능 재고: {available_stock}개)"}), 400

        unit_price = product['price']
        option_price = option['additional_price']
        final_unit_price = unit_price + option_price
        item_subtotal = final_unit_price * quantity
        subtotal_amount += item_subtotal

        order_items_to_insert.append({
            'product_id': product_id,
            'option_id': option['id'],
            'product_name_snapshot': product['name'],
            'option_name_snapshot': option['option_name'],
            'capacity': product['capacity'],
            'quantity': quantity,
            'unit_price': unit_price,
            'option_price': option_price,
            'final_unit_price': final_unit_price,
            'subtotal': item_subtotal
        })

        reservation_targets.append({
            'option_id': option['id'],
            'quantity': quantity
        })

    base_shipping_fee = 0 if subtotal_amount >= Config.FREE_SHIPPING_THRESHOLD else Config.BASE_SHIPPING_FEE
    remote_area_surcharge = calculate_remote_surcharge(postal_code)
    discount_amount = 0
    total_amount = subtotal_amount + base_shipping_fee + remote_area_surcharge - discount_amount

    order_number = generate_order_number()
    guest_pw_hash = hash_password(guest_password) if guest_password else None
    expires_at = (datetime.datetime.now() + datetime.timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')

    # 단일 Connection 트랜잭션 수행
    conn = get_db_connection(autocommit=False)
    try:
        if conn._db_type == 'mysql':
            conn.begin()

        # 1. 재고 원자적 차감 (Atomic UPDATE)
        for res in reservation_targets:
            affected, _ = execute_db_conn(conn, """
                UPDATE product_options
                SET reserved_stock = reserved_stock + %s
                WHERE id = %s AND (stock - reserved_stock) >= %s
            """, (res['quantity'], res['option_id'], res['quantity']))

            if affected == 0:
                if conn._db_type == 'sqlite':
                    conn.rollback()
                elif conn._db_type == 'mysql':
                    conn.rollback()
                return jsonify({'error': f"상품 옵션(ID: {res['option_id']})의 재고가 부족합니다."}), 400

        # 2. Orders 테이블 저장
        _, order_id = execute_db_conn(conn, """
            INSERT INTO orders (
                order_number, user_id, guest_name, guest_phone, guest_password_hash,
                subtotal_amount, base_shipping_fee, remote_area_surcharge, discount_amount, total_amount,
                order_status, payment_status, integrity_status,
                recipient_name, recipient_phone, postal_code, address, address_detail, delivery_memo
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', 'READY', 'NORMAL', %s, %s, %s, %s, %s, %s)
        """, (
            order_number, user_id, guest_name, guest_phone, guest_pw_hash,
            subtotal_amount, base_shipping_fee, remote_area_surcharge, discount_amount, total_amount,
            recipient_name, recipient_phone, postal_code, address, address_detail, delivery_memo
        ))

        # 3. Order Items 및 Stock Reservations 저장
        for item in order_items_to_insert:
            execute_db_conn(conn, """
                INSERT INTO order_items (
                    order_id, product_id, option_id, product_name_snapshot, option_name_snapshot,
                    capacity, quantity, unit_price, option_price, final_unit_price, subtotal
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                order_id, item['product_id'], item['option_id'], item['product_name_snapshot'],
                item['option_name_snapshot'], item['capacity'], item['quantity'],
                item['unit_price'], item['option_price'], item['final_unit_price'], item['subtotal']
            ))

        for res in reservation_targets:
            execute_db_conn(conn, """
                INSERT INTO stock_reservations (order_id, product_option_id, quantity, expires_at, status)
                VALUES (%s, %s, %s, %s, 'RESERVED')
            """, (order_id, res['option_id'], res['quantity'], expires_at))

        conn.commit()

        return jsonify({
            'message': '주문서가 성공적으로 생성되었습니다. (15분간 재고 예약)',
            'order_id': order_id,
            'order_number': order_number,
            'subtotal_amount': subtotal_amount,
            'base_shipping_fee': base_shipping_fee,
            'remote_area_surcharge': remote_area_surcharge,
            'total_amount': total_amount,
            'expires_at': expires_at
        }), 201
    except Exception as e:
        if conn._db_type in ('mysql', 'sqlite'):
            conn.rollback()
        print(f"Order Creation Exception: {e}")
        return jsonify({'error': '주문 처리 중 오류가 발생했습니다.'}), 500
    finally:
        conn.close()

@orders_bp.route('/guest-lookup', methods=['POST'])
def guest_order_lookup():
    """비회원 주문 조회 API (주문번호 + 연락처 + 비밀번호 검증)"""
    data = request.get_json() or {}
    order_number = data.get('order_number', '').strip()
    guest_phone = data.get('guest_phone', '').strip()
    guest_password = data.get('guest_password', '').strip()

    if not order_number or not guest_phone or not guest_password:
        return jsonify({'error': '주문번호, 연락처, 비회원 비밀번호를 모두 입력해 주세요.'}), 400

    order = query_db("""
        SELECT * FROM orders 
        WHERE order_number = %s AND guest_phone = %s
    """, (order_number, guest_phone), one=True)

    if not order or not order['guest_password_hash'] or not check_password(guest_password, order['guest_password_hash']):
        return jsonify({'error': '일치하는 비회원 주문 정보를 찾을 수 없습니다. 정보를 다시 확인해 주세요.'}), 404

    items = query_db("SELECT * FROM order_items WHERE order_id = %s", (order['id'],))
    payments = query_db("SELECT * FROM payments WHERE order_id = %s", (order['id'],))
    refunds = query_db("SELECT * FROM refunds WHERE order_id = %s", (order['id'],))
    
    order_data = dict(order)
    order_data.pop('guest_password_hash', None)
    order_data['items'] = items
    order_data['payments'] = payments
    order_data['refunds'] = refunds

    return jsonify({'order': order_data}), 200

@orders_bp.route('/<order_number>', methods=['GET'])
def get_order_detail(order_number):
    """주문 단건 정보 상세 조회 API"""
    order = query_db("SELECT * FROM orders WHERE order_number = %s", (order_number,), one=True)
    if not order:
        return jsonify({'error': '주문을 찾을 수 없습니다.'}), 404

    items = query_db("SELECT * FROM order_items WHERE order_id = %s", (order['id'],))
    payments = query_db("SELECT * FROM payments WHERE order_id = %s", (order['id'],))
    refunds = query_db("SELECT * FROM refunds WHERE order_id = %s", (order['id'],))

    order_data = dict(order)
    order_data.pop('guest_password_hash', None)
    order_data['items'] = items
    order_data['payments'] = payments
    order_data['refunds'] = refunds

    return jsonify({'order': order_data}), 200
