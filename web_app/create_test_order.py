import datetime
import random
from db.db_connection import query_db, execute_db
from middlewares.auth import hash_password

def create_order_for_test():
    user = query_db("SELECT * FROM users WHERE email = %s", ('test@test.com',), one=True)
    if not user:
        pass_h = hash_password('test1234!')
        user_id = execute_db(
            "INSERT INTO users (email, password_hash, name, phone, status, role) VALUES (%s, %s, %s, %s, %s, %s)",
            ('test@test.com', pass_h, '테스트유저', '010-1234-5678', 'ACTIVE', 'CUSTOMER')
        )
        user = query_db("SELECT * FROM users WHERE id = %s", (user_id,), one=True)
        print(f"새 회원 생성됨: ID {user['id']}, test@test.com")
    else:
        print(f"기존 회원 발견: ID {user['id']}, test@test.com")

    prod = query_db("SELECT * FROM products WHERE is_active = 1 LIMIT 1", one=True)
    if not prod:
        prod = query_db("SELECT * FROM products LIMIT 1", one=True)
        
    opt = query_db("SELECT * FROM product_options WHERE product_id = %s LIMIT 1", (prod['id'],), one=True)
    
    base_price = prod['price']
    add_price = opt['additional_price'] if opt else 0
    final_unit = base_price + add_price
    qty = 2
    subtotal = final_unit * qty

    order_num = f"YW-{datetime.datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
    
    order_id = execute_db(
        """INSERT INTO orders (
            order_number, user_id, recipient_name, recipient_phone, 
            postal_code, address, address_detail, delivery_memo,
            subtotal_amount, discount_amount, total_amount, 
            payment_status, order_status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            order_num, user['id'], '테스트유저', '010-1234-5678',
            '25000', '강원특별자치도 영월군 영월읍 방앗간길 100', '101호', '문 앞에 놓아주세요',
            subtotal, 0, subtotal, 'PAID', 'CONFIRMED'
        )
    )

    execute_db(
        """INSERT INTO order_items (
            order_id, product_id, option_id, 
            product_name_snapshot, option_name_snapshot, capacity,
            quantity, unit_price, option_price, final_unit_price, subtotal
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            order_id, prod['id'], opt['id'] if opt else None,
            prod['name'], opt['option_name'] if opt else '기본옵션', prod.get('capacity', '300ml'),
            qty, base_price, add_price, final_unit, subtotal
        )
    )

    print(f"SUCCESS_ORDER_CREATED: 주문ID={order_id}, 주문번호={order_num}, 총액={subtotal:,}원, 유저=test@test.com")

if __name__ == '__main__':
    create_order_for_test()
