import datetime
import random
import string
from flask import Blueprint, request, jsonify
from db.db_connection import query_db, execute_db, get_db_connection
from middlewares.auth import verify_jwt_token, hash_password, check_password

orders_bp = Blueprint('orders', __name__, url_prefix='/api/orders')

def generate_order_number():
    """주문번호 생성 (예: ORD-20260803-A8F2K9)"""
    today_str = datetime.datetime.now().strftime('%Y%m%d')
    random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"ORD-{today_str}-{random_str}"

@orders_bp.route('', methods=['POST'])
def create_order():
    """회원 및 비회원 주문 생성 API"""
    data = request.get_json() or {}
    
    items = data.get('items', [])
    recipient_name = data.get('recipient_name', '').strip()
    recipient_phone = data.get('recipient_phone', '').strip()
    postal_code = data.get('postal_code', '').strip()
    address = data.get('address', '').strip()
    address_detail = data.get('address_detail', '').strip()
    delivery_memo = data.get('delivery_memo', '').strip()
    
    # 회원/비회원 구분
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

    # 주문 상품 데이터 검증 및 총 금액 계산
    total_amount = 0
    order_items_to_insert = []
    
    for item in items:
        product_id = item.get('product_id')
        quantity = int(item.get('quantity', 1))
        
        product = query_db("SELECT * FROM products WHERE id = %s AND is_active = 1", (product_id,), one=True)
        if not product:
            return jsonify({'error': f"상품(ID: {product_id})이 존재하지 않거나 판매 중단되었습니다."}), 400
        
        unit_price = product['price']
        subtotal = unit_price * quantity
        total_amount += subtotal
        
        order_items_to_insert.append({
            'product_id': product_id,
            'product_name': product['name'],
            'capacity': product['capacity'],
            'quantity': quantity,
            'unit_price': unit_price,
            'subtotal': subtotal
        })

    order_number = generate_order_number()
    guest_pw_hash = hash_password(guest_password) if guest_password else None

    # MySQL 트랜잭션 처리
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 1. Orders 테이블 저장
            cursor.execute("""
                INSERT INTO orders (
                    order_number, user_id, guest_name, guest_phone, guest_password_hash,
                    total_amount, payment_status, shipping_status,
                    recipient_name, recipient_phone, postal_code, address, address_detail, delivery_memo
                ) VALUES (%s, %s, %s, %s, %s, %s, 'PENDING', 'PREPARING', %s, %s, %s, %s, %s, %s)
            """, (
                order_number, user_id, guest_name, guest_phone, guest_pw_hash,
                total_amount, recipient_name, recipient_phone, postal_code, address, address_detail, delivery_memo
            ))
            order_id = cursor.lastrowid
            
            # 2. Order Items 테이블 저장
            for item in order_items_to_insert:
                cursor.execute("""
                    INSERT INTO order_items (
                        order_id, product_id, product_name, capacity, quantity, unit_price, subtotal
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    order_id, item['product_id'], item['product_name'], item['capacity'],
                    item['quantity'], item['unit_price'], item['subtotal']
                ))
                
        return jsonify({
            'message': '주문서가 성공적으로 생성되었습니다.',
            'order_id': order_id,
            'order_number': order_number,
            'total_amount': total_amount
        }), 201
    except Exception as e:
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
    order_data = dict(order)
    order_data.pop('guest_password_hash', None)
    order_data['items'] = items

    return jsonify({'order': order_data}), 200

@orders_bp.route('/<order_number>', methods=['GET'])
def get_order_detail(order_number):
    """주문 단건 정보 상세 조회 API"""
    order = query_db("SELECT * FROM orders WHERE order_number = %s", (order_number,), one=True)
    if not order:
        return jsonify({'error': '주문을 찾을 수 없습니다.'}), 404

    items = query_db("SELECT * FROM order_items WHERE order_id = %s", (order['id'],))
    order_data = dict(order)
    order_data.pop('guest_password_hash', None)
    order_data['items'] = items

    return jsonify({'order': order_data}), 200
