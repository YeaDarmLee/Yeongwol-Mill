import re
import json
import uuid
import datetime
from flask import Blueprint, request, jsonify
from db.db_connection import query_db, execute_db, execute_db_conn, get_db_connection
from middlewares.auth import jwt_required, check_password, hash_password, validate_password_policy
from utils.email_service import process_notification_outbox

users_bp = Blueprint('users', __name__, url_prefix='/api/users')

def normalize_phone(phone_str):
    """휴대폰 번호에서 숫자만 추출하여 정규화 (예: 01012345678)"""
    if not phone_str:
        return ""
    return re.sub(r'[^0-9]', '', str(phone_str))

def format_phone(phone_str):
    """정규화된 휴대폰 번호를 하이픈 포맷팅 (예: 010-1234-5678)"""
    digits = normalize_phone(phone_str)
    if len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    elif len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return phone_str

@users_bp.route('/me', methods=['GET'])
@jwt_required
def get_my_profile():
    """내 회원 정보 상세 조회 API"""
    user_id = request.current_user.get('user_id')
    user = query_db("""
        SELECT id, email, name, phone, created_at, 
               marketing_email_agreed, marketing_sms_agreed, 
               marketing_email_updated_at, marketing_sms_updated_at, status
        FROM users WHERE id = %s
    """, (user_id,), one=True)

    if not user or user.get('status') != 'ACTIVE':
        return jsonify({'error': '유효하지 않거나 탈퇴된 회원 계정입니다.'}), 401

    created_at_str = str(user['created_at']).split('.')[0] if user.get('created_at') else ''

    return jsonify({
        'user': {
            'id': user['id'],
            'email': user['email'],
            'name': user['name'] or '',
            'phone': format_phone(user['phone']),
            'created_at': created_at_str,
            'marketing_email': {
                'agreed': bool(user.get('marketing_email_agreed')),
                'updated_at': str(user['marketing_email_updated_at']).split('.')[0] if user.get('marketing_email_updated_at') else ''
            },
            'marketing_sms': {
                'agreed': bool(user.get('marketing_sms_agreed')),
                'updated_at': str(user['marketing_sms_updated_at']).split('.')[0] if user.get('marketing_sms_updated_at') else ''
            }
        }
    }), 200

@users_bp.route('/me/profile', methods=['PATCH'])
@jwt_required
def update_profile():
    """개인정보 (성함, 연락처) 수정 API"""
    user_id = request.current_user.get('user_id')
    data = request.get_json() or {}
    
    name = data.get('name', '').strip()
    phone = data.get('phone', '').strip()

    if not name or len(name) < 2:
        return jsonify({'error': '성함은 최소 2자 이상 입력해 주세요.'}), 400

    clean_phone = normalize_phone(phone)
    if not clean_phone or len(clean_phone) < 10 or len(clean_phone) > 11:
        return jsonify({'error': '올바른 휴대폰 번호를 입력해 주세요. (예: 010-1234-5678)'}), 400

    execute_db("UPDATE users SET name = %s, phone = %s WHERE id = %s AND status = 'ACTIVE'", (name, clean_phone, user_id))

    return jsonify({
        'message': '개인정보가 성공적으로 수정되었습니다.',
        'user': {
            'name': name,
            'phone': format_phone(clean_phone)
        }
    }), 200

@users_bp.route('/me/password', methods=['PUT'])
@jwt_required
def change_password():
    """비밀번호 변경 API (현재 비번 검증 + token_version 증가 토큰 무효화)"""
    user_id = request.current_user.get('user_id')
    data = request.get_json() or {}

    current_password = data.get('current_password', '').strip()
    new_password = data.get('new_password', '').strip()
    new_password_confirm = data.get('new_password_confirm', '').strip()

    if not current_password:
        return jsonify({'error': '현재 비밀번호를 입력해 주세요.'}), 400

    user = query_db("SELECT password_hash FROM users WHERE id = %s AND status = 'ACTIVE'", (user_id,), one=True)
    if not user or not check_password(current_password, user['password_hash']):
        return jsonify({'error': '현재 비밀번호가 일치하지 않습니다.'}), 400

    # 비밀번호 정책 검증 (10자 이상 128자 이하)
    is_valid, err_msg = validate_password_policy(new_password)
    if not is_valid:
        return jsonify({'error': err_msg}), 400

    if new_password != new_password_confirm:
        return jsonify({'error': '새 비밀번호와 비밀번호 확인이 서로 일치하지 않습니다.'}), 400

    if current_password == new_password:
        return jsonify({'error': '새 비밀번호는 현재 비밀번호와 다르게 설정해야 합니다.'}), 400

    new_hash = hash_password(new_password)
    # 비밀번호 변경 및 token_version 원자적 증가 (기존 토큰 즉시 무효화)
    execute_db("""
        UPDATE users 
        SET password_hash = %s, token_version = token_version + 1 
        WHERE id = %s
    """, (new_hash, user_id))

    return jsonify({'message': '비밀번호가 성공적으로 변경되었습니다. 보안을 위해 다시 로그인해 주세요.'}), 200

@users_bp.route('/me/marketing-consents', methods=['PATCH'])
@jwt_required
def update_marketing_consents():
    """마케팅 동의/철회 수신 설정 API (스냅샷 + user_consents 이력 + notification_outbox 단일 트랜잭션)"""
    user_id = request.current_user.get('user_id')
    data = request.get_json() or {}

    user = query_db("SELECT email, name, marketing_email_agreed, marketing_sms_agreed FROM users WHERE id = %s AND status = 'ACTIVE'", (user_id,), one=True)
    if not user:
        return jsonify({'error': '회원 정보를 찾을 수 없습니다.'}), 404

    email_agreed = bool(data.get('marketing_email', user.get('marketing_email_agreed')))
    sms_agreed = bool(data.get('marketing_sms', user.get('marketing_sms_agreed')))

    now_dt = datetime.datetime.now()
    now_str = now_dt.strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db_connection()
    cursor = conn.cursor()
    db_type = getattr(conn, '_db_type', 'mysql')

    def p(sql):
        return sql.replace('%s', '?') if db_type == 'sqlite' else sql

    try:
        # 단일 DB 트랜잭션 시작
        cursor.execute(p("UPDATE users SET marketing_email_agreed = %s, marketing_sms_agreed = %s, marketing_email_updated_at = %s, marketing_sms_updated_at = %s WHERE id = %s"),
                       (1 if email_agreed else 0, 1 if sms_agreed else 0, now_str, now_str, user_id))

        # 이메일 마케팅 변경 감지 시 이력 & Outbox 기록
        if email_agreed != bool(user.get('marketing_email_agreed')):
            action = "AGREED" if email_agreed else "WITHDRAWN"
            cursor.execute(p("""
                INSERT INTO user_consents (user_id, consent_type, action, consent_version, agreed, agreed_at)
                VALUES (%s, 'MARKETING_EMAIL', %s, 'marketing-2026-08-v1', %s, %s)
            """), (user_id, action, 1 if email_agreed else 0, now_str))

            payload_str = json.dumps({
                'user_name': user['name'],
                'consent_type': 'MARKETING_EMAIL',
                'action': action,
                'updated_at': now_str
            })
            cursor.execute(p("""
                INSERT INTO notification_outbox (user_id, email, recipient, type, payload, status, created_at)
                VALUES (%s, %s, %s, 'MARKETING_CONSENT_NOTICE', %s, 'PENDING', %s)
            """), (user_id, user['email'], user['email'], payload_str, now_str))

        # SMS 마케팅 변경 감지 시 이력 & Outbox 기록
        if sms_agreed != bool(user.get('marketing_sms_agreed')):
            action = "AGREED" if sms_agreed else "WITHDRAWN"
            cursor.execute(p("""
                INSERT INTO user_consents (user_id, consent_type, action, consent_version, agreed, agreed_at)
                VALUES (%s, 'MARKETING_SMS', %s, 'marketing-2026-08-v1', %s, %s)
            """), (user_id, action, 1 if sms_agreed else 0, now_str))

            payload_str = json.dumps({
                'user_name': user['name'],
                'consent_type': 'MARKETING_SMS',
                'action': action,
                'updated_at': now_str
            })
            cursor.execute(p("""
                INSERT INTO notification_outbox (user_id, email, recipient, type, payload, status, created_at)
                VALUES (%s, %s, %s, 'MARKETING_CONSENT_NOTICE', %s, 'PENDING', %s)
            """), (user_id, user['email'], user['email'], payload_str, now_str))


        conn.commit()

        # 비동기 Outbox 처리 유틸 실행
        process_notification_outbox()

        return jsonify({'message': '마케팅 수신 동의 설정이 성공적으로 변경되었습니다.'}), 200
    except Exception as e:
        if db_type in ('mysql', 'sqlite'):
            conn.rollback()
        print(f"[Marketing Consent Exception] {e}")
        return jsonify({'error': '수신 설정 변경 중 오류가 발생했습니다.'}), 500
    finally:
        conn.close()

@users_bp.route('/me/withdraw', methods=['POST'])
@jwt_required
def withdraw_account():
    """회원 탈퇴 API (현재 비번 확인 + 계정 WITHDRAWN + 개인정보 파기/대체값 치환 + token_version 증가)"""
    user_id = request.current_user.get('user_id')
    data = request.get_json() or {}
    current_password = data.get('current_password', '').strip()

    if not current_password:
        return jsonify({'error': '탈퇴 진행을 위해 현재 비밀번호를 입력해 주세요.'}), 400

    user = query_db("SELECT password_hash FROM users WHERE id = %s AND status = 'ACTIVE'", (user_id,), one=True)
    if not user or not check_password(current_password, user['password_hash']):
        return jsonify({'error': '현재 비밀번호가 일치하지 않습니다.'}), 400

    random_uuid = str(uuid.uuid4())[:8]
    system_deleted_email = f"withdrawn_{user_id}_{random_uuid}@deleted.invalid"
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 회원 개인정보 파기 및 시스템용 대체값 치환 + token_version 증가
    execute_db("""
        UPDATE users 
        SET status = 'WITHDRAWN',
            deleted_at = %s,
            token_version = token_version + 1,
            password_hash = NULL,
            name = NULL,
            phone = NULL,
            email = %s
        WHERE id = %s
    """, (now_str, system_deleted_email, user_id))

    return jsonify({'message': '영월고향방앗간 회원탈퇴가 정상적으로 완료되었습니다. 그동안 이용해 주셔서 감사합니다.'}), 200
