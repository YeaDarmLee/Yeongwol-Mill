from flask import Blueprint, request, jsonify
from db.db_connection import query_db

products_bp = Blueprint('products', __name__, url_prefix='/api')

@products_bp.route('/products', methods=['GET'])
def get_products():
    """상품 목록 조회 API (카테고리 및 태그 필터링)"""
    category_id = request.args.get('category_id')
    badge = request.args.get('badge')

    sql = """
        SELECT p.*, c.name as category_name 
        FROM products p
        JOIN categories c ON p.category_id = c.id
        WHERE p.is_active = 1
    """
    args = []

    if category_id:
        sql += " AND p.category_id = %s"
        args.append(category_id)
    if badge:
        sql += " AND p.badge = %s"
        args.append(badge)

    sql += " ORDER BY p.id ASC"
    products = query_db(sql, args) or []
    
    for p in products:
        p['options'] = query_db("SELECT * FROM product_options WHERE product_id = %s", (p['id'],)) or []

    return jsonify({'products': products}), 200

@products_bp.route('/products/<int:product_id>', methods=['GET'])
def get_product(product_id):
    """상품 상세 정보 및 옵션, 식품 고시 정보 조회 API"""
    product = query_db("""
        SELECT p.*, c.name as category_name 
        FROM products p
        JOIN categories c ON p.category_id = c.id
        WHERE p.id = %s AND p.is_active = 1
    """, (product_id,), one=True)

    if not product:
        return jsonify({'error': '해당 상품을 찾을 수 없습니다.'}), 404

    options = query_db("SELECT * FROM product_options WHERE product_id = %s", (product_id,)) or []
    product_dict = dict(product)
    product_dict['options'] = options

    return jsonify({'product': product_dict}), 200

@products_bp.route('/categories', methods=['GET'])
def get_categories():
    """카테고리 목록 조회 API"""
    categories = query_db("SELECT * FROM categories ORDER BY id ASC") or []
    return jsonify({'categories': categories}), 200
