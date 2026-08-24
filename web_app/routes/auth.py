import datetime
import secrets
import hashlib
import uuid
import re
import jwt
from flask import Blueprint, request, jsonify, make_response
from config import Config
from db.db_connection import query_db, execute_db, get_db_connection, execute_db_conn
from middlewares.auth import hash_password, check_password, generate_jwt_token, verify_jwt_token, jwt_required, validate_password_policy
from utils.email_service import send_email

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

RESET_TOKENS = {}

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')
PHONE_REGEX = re.compile(r'^(01[016789])[-. ]?(\d{3,4})[-. ]?(\d{4})$')

def set_refresh_cookie(response, refresh_token):
    """Refresh Token을 HttpOnly, Secure, SameSite 속성을 가진 Cookie로 세팅합니다."""
    response.set_cookie(
        'refresh_token',
        refresh_token,
        httponly=True,
        samesite='Lax',
        secure=False,  # 개발 환경 및 HTTPS 환경 공용
        max_age=7 * 24 * 3600,
        path='/api/auth'
    )
    return response

def create_refresh_token(user_id, conn=None):
    """Refresh Token 생성 및 DB 저장 (7일 유효)"""
    token_str = secrets.token_urlsafe(64)
    token_hash = hashlib.sha256(token_str.encode('utf-8')).hexdigest()
    expires_at = (datetime.datetime.now() + datetime.timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    
    query = """
        INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
        VALUES (%s, %s, %s)
    """
    if conn:
        execute_db_conn(conn, query, (user_id, token_hash, expires_at))
    else:
        execute_db(query, (user_id, token_hash, expires_at))
    return token_str

@auth_bp.route('/send-otp', methods=['POST'])
def send_otp():
    """이메일 OTP 인증번호 발송 API"""
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()

    if not email or not EMAIL_REGEX.match(email):
        return jsonify({'error': '유효한 이메일 주소를 입력해 주세요.'}), 400

    # 이미 가입된 이메일 사전 확인
    existing_user = query_db("SELECT id FROM users WHERE email = %s", (email,), one=True)
    if existing_user:
        return jsonify({'error': '이미 등록된 이메일 주소입니다.'}), 400

    # 1분 재전송 rate limit 검사
    last_verification = query_db(
        "SELECT last_sent_at FROM email_verifications WHERE email = %s ORDER BY id DESC LIMIT 1",
        (email,),
        one=True
    )
    if last_verification and last_verification.get('last_sent_at'):
        try:
            last_sent_str = str(last_verification['last_sent_at']).split('.')[0]
            last_sent_dt = datetime.datetime.strptime(last_sent_str, '%Y-%m-%d %H:%M:%S')
            if (datetime.datetime.now() - last_sent_dt).total_seconds() < 60:
                return jsonify({'error': '인증번호 재전송은 1분 후에 가능합니다. 잠시 후 다시 시도해 주세요.'}), 429
        except Exception:
            pass

    # 6자리 숫자의 무작위 OTP 생성 및 SHA-256 해시 저장
    raw_otp = f"{secrets.randbelow(900000) + 100000}"
    code_hash = hashlib.sha256(raw_otp.encode('utf-8')).hexdigest()
    expires_at = (datetime.datetime.now() + datetime.timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')

    execute_db("""
        INSERT INTO email_verifications (email, code_hash, expires_at, attempt_count, last_sent_at)
        VALUES (%s, %s, %s, 0, NOW())
    """, (email, code_hash, expires_at))

    # 이메일 발송
    subject = f"[{Config.BUSINESS_NAME}] 회원가입 이메일 인증번호 안내"
    body_html = f"""
        <div style="max-width:600px; margin:0 auto; padding:20px; font-family:'Noto Sans KR', sans-serif; border:1px solid #e0e0e0; border-radius:8px;">
            <h2 style="color:#915a28; margin-bottom:20px;">{Config.BUSINESS_NAME} 회원가입 인증번호</h2>
            <p style="font-size:15px; color:#333;">안녕하세요. {Config.BUSINESS_NAME}을 방문해 주셔서 감사합니다.</p>
            <p style="font-size:15px; color:#333;">아래의 6자리 인증번호를 회원가입 화면에 입력해 주세요.</p>
            <div style="background-color:#f8f5f0; padding:15px; text-align:center; font-size:24px; font-weight:bold; letter-spacing:4px; color:#915a28; margin:20px 0; border-radius:6px;">
                {raw_otp}
            </div>
            <p style="font-size:13px; color:#777;">* 본 인증번호는 5분간 유효합니다.</p>
        </div>
    """
    send_email(email, subject, body_html)

    return jsonify({
        'message': '인증번호가 입력하신 이메일로 발송되었습니다. (유효시간: 5분)',
        'expires_in': 300,
        'dev_otp': raw_otp  # 테스트/개발 환경 편의제공
    }), 200

@auth_bp.route('/verify-otp', methods=['POST'])
def verify_otp():
    """이메일 OTP 인증번호 검증 API"""
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    code = data.get('code', '').strip()

    if not email or not code:
        return jsonify({'error': '이메일과 인증번호를 모두 입력해 주세요.'}), 400

    record = query_db(
        "SELECT * FROM email_verifications WHERE email = %s AND consumed_at IS NULL ORDER BY id DESC LIMIT 1",
        (email,),
        one=True
    )
    if not record:
        return jsonify({'error': '발송된 인증번호가 없습니다. 인증번호 받기를 진행해 주세요.'}), 400

    # 만료 검증
    exp_str = str(record['expires_at']).split('.')[0]
    exp_dt = datetime.datetime.strptime(exp_str, '%Y-%m-%d %H:%M:%S')
    if exp_dt < datetime.datetime.now():
        return jsonify({'error': '인증번호가 만료되었습니다. 다시 인증번호를 전송해 주세요.'}), 400

    # 최대 시도 횟수(5회) 초과 검증
    attempt_count = record.get('attempt_count', 0)
    if attempt_count >= 5:
        return jsonify({'error': '인증 시도 횟수(5회)를 초과하였습니다. 인증번호를 다시 받아주세요.'}), 400

    # 해시 비교
    code_hash = hashlib.sha256(code.encode('utf-8')).hexdigest()
    if code_hash != record['code_hash']:
        execute_db("UPDATE email_verifications SET attempt_count = attempt_count + 1 WHERE id = %s", (record['id'],))
        remaining = 4 - attempt_count
        if remaining > 0:
            return jsonify({'error': f'인증번호가 일치하지 않습니다.\n(남은 시도 횟수: {remaining}회)'}), 400
        else:
            return jsonify({'error': '인증 시도 횟수를 초과하였습니다. 인증번호를 다시 받아주세요.'}), 400

    # 인증 성공 처리
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    execute_db("UPDATE email_verifications SET verified_at = %s WHERE id = %s", (now_str, record['id']))

    return jsonify({'message': '이메일 인증이 완료되었습니다.'}), 200

@auth_bp.route('/register', methods=['POST'])
def register():
    """회원가입 API (이메일 인증 검증, 트랜잭션, 약관 동의 저장, HttpOnly Cookie 포함)"""
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()
    password_confirm = data.get('password_confirm', '').strip()
    name = data.get('name', '').strip()
    phone = data.get('phone', '').strip()

    terms_agreed = data.get('terms_agreed', False)
    privacy_agreed = data.get('privacy_agreed', False)
    age_agreed = data.get('age_agreed', False)
    marketing_email_agreed = data.get('marketing_email_agreed', data.get('marketing_agreed', False))
    marketing_sms_agreed = data.get('marketing_sms_agreed', data.get('marketing_agreed', False))

    # 1. 입력 검증
    if not email or not EMAIL_REGEX.match(email):
        return jsonify({'error': '올바른 이메일 주소를 입력해 주세요.'}), 400

    # 공통 비밀번호 검증 (10자 이상 128자 이하)
    is_valid_pwd, pwd_err = validate_password_policy(password)
    if not is_valid_pwd:
        return jsonify({'error': pwd_err}), 400

    if password != password_confirm:
        return jsonify({'error': '비밀번호와 비밀번호 확인이 일치하지 않습니다.'}), 400

    if not name:
        return jsonify({'error': '성함을 입력해 주세요.'}), 400

    if not phone or not PHONE_REGEX.match(phone):
        return jsonify({'error': '올바른 휴대폰 번호 형식(010-XXXX-XXXX)으로 입력해 주세요.'}), 400

    clean_phone = re.sub(r'[^0-9]', '', phone)

    if not terms_agreed or not privacy_agreed or not age_agreed:
        return jsonify({'error': '필수 이용약관, 개인정보 수집안내, 만 14세 이상 확인에 모두 동의해 주세요.'}), 400

    # 2. 서버 사이드 이메일 인증 완료 검증
    verification = query_db(
        """
        SELECT * FROM email_verifications 
        WHERE email = %s AND verified_at IS NOT NULL AND consumed_at IS NULL 
        ORDER BY id DESC LIMIT 1
        """,
        (email,),
        one=True
    )
    if not verification:
        return jsonify({'error': '이메일 인증이 완료되지 않았습니다. 이메일 인증을 진행해 주세요.'}), 400

    # 3. 사전 중복 체크
    existing_user = query_db("SELECT id FROM users WHERE email = %s", (email,), one=True)
    if existing_user:
        return jsonify({'error': '이미 등록된 이메일 주소입니다.'}), 400

    # 4. 단일 DB 트랜잭션 수행
    conn = get_db_connection(autocommit=False)
    try:
        password_hash = hash_password(password)
        
        # a) users INSERT
        rowcount, user_id = execute_db_conn(
            conn,
            "INSERT INTO users (email, password_hash, name, phone) VALUES (%s, %s, %s, %s)",
            (email, password_hash, name, phone)
        )

        # b) user_consents INSERT (약관 동의 내역 버전 및 기록 저장)
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        consents = [
            ('TERMS_OF_SERVICE', 'v1.0', 'AGREED', 1),
            ('PRIVACY_POLICY', 'v1.0', 'AGREED', 1),
            ('AGE_OVER_14', 'v1.0', 'AGREED', 1),
            ('MARKETING_EMAIL', 'marketing-2026-08-v1', 'AGREED' if marketing_email_agreed else 'WITHDRAWN', 1 if marketing_email_agreed else 0),
            ('MARKETING_SMS', 'marketing-2026-08-v1', 'AGREED' if marketing_sms_agreed else 'WITHDRAWN', 1 if marketing_sms_agreed else 0)
        ]
        for consent_type, version, action_val, agreed in consents:
            execute_db_conn(
                conn,
                """
                INSERT INTO user_consents (user_id, consent_type, action, consent_version, agreed, agreed_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (user_id, consent_type, action_val, version, agreed, now_str)
            )

        # c) Refresh Token 생성 및 DB 저장
        refresh_token = create_refresh_token(user_id, conn=conn)

        # d) 이메일 인증 정보 consume (소모) 처리
        execute_db_conn(
            conn,
            "UPDATE email_verifications SET consumed_at = %s WHERE id = %s",
            (now_str, verification['id'])
        )

        # 커밋
        conn.commit()

    except Exception as e:
        conn.rollback()
        print(f"[Register Error] Transaction rolled back: {e}")
        if "UNIQUE" in str(e).upper() or "DUPLICATE" in str(e).upper():
            return jsonify({'error': '이미 등록된 이메일 주소입니다.'}), 400
        return jsonify({'error': '회원가입 처리 중 오류가 발생했습니다. 다시 시도해 주세요.'}), 500
    finally:
        conn.close()

    # 5. Access Token 및 쿠키 세팅 응답 생성
    token = generate_jwt_token(user_id, email, token_version=0)
    resp = jsonify({
        'message': '영월고향방앗간 회원가입이 성공적으로 완료되었습니다.',
        'token': token,
        'refresh_token': refresh_token,
        'user': {'id': user_id, 'email': email, 'name': name, 'phone': clean_phone}
    })
    return set_refresh_cookie(resp, refresh_token), 201

@auth_bp.route('/login', methods=['POST'])
def login():
    """JWT 기반 보안 로그인 API (Cookie 세팅 포함)"""
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()

    if not email or not password:
        return jsonify({'error': '이메일과 비밀번호를 입력해 주세요.'}), 400

    user = query_db("SELECT * FROM users WHERE email = %s", (email,), one=True)
    if not user or user.get('status') != 'ACTIVE' or not user.get('password_hash') or not check_password(password, user['password_hash']):
        return jsonify({'error': '이메일 또는 비밀번호가 올바르지 않습니다.'}), 401

    token_ver = user.get('token_version', 0)
    token = generate_jwt_token(user['id'], user['email'], token_version=token_ver)
    refresh_token = create_refresh_token(user['id'])

    resp = jsonify({
        'message': '로그인 성공',
        'token': token,
        'refresh_token': refresh_token,
        'user': {
            'id': user['id'],
            'email': user['email'],
            'name': user['name'],
            'phone': user['phone']
        }
    })
    return set_refresh_cookie(resp, refresh_token), 200

@auth_bp.route('/refresh', methods=['POST'])
def refresh():
    """Refresh Token Rotation 기반 Access Token 재발급 API (Cookie 하이브리드 지원)"""
    data = request.get_json() or {}
    refresh_token = request.cookies.get('refresh_token') or data.get('refresh_token', '').strip()

    if not refresh_token:
        return jsonify({'error': 'Refresh Token이 필요합니다.'}), 400

    token_hash = hashlib.sha256(refresh_token.encode('utf-8')).hexdigest()
    record = query_db("SELECT * FROM refresh_tokens WHERE token_hash = %s AND revoked_at IS NULL", (token_hash,), one=True)

    if not record:
        return jsonify({'error': '유효하지 않거나 취소된 Refresh Token입니다.'}), 401

    # 만료 검증
    exp_dt = datetime.datetime.strptime(str(record['expires_at']).split('.')[0], '%Y-%m-%d %H:%M:%S')
    if exp_dt < datetime.datetime.now():
        return jsonify({'error': '만료된 Refresh Token입니다. 다시 로그인해 주세요.'}), 401

    # 기존 Refresh Token 취소 (Rotation)
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    execute_db("UPDATE refresh_tokens SET revoked_at = %s WHERE id = %s", (now_str, record['id']))

    user = query_db("SELECT * FROM users WHERE id = %s", (record['user_id'],), one=True)
    if not user:
        return jsonify({'error': '사용자를 찾을 수 없습니다.'}), 404

    new_access_token = generate_jwt_token(user['id'], user['email'])
    new_refresh_token = create_refresh_token(user['id'])

    resp = jsonify({
        'token': new_access_token,
        'refresh_token': new_refresh_token
    })
    return set_refresh_cookie(resp, new_refresh_token), 200

@auth_bp.route('/logout', methods=['POST'])
@jwt_required
def logout():
    """로그아웃 API (Access Token jti Blacklist 차단 & Refresh Token Revoke & Cookie 삭제)"""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header.split()[1]
        try:
            payload = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=['HS256'])
            jti = payload.get('jti')
            exp = payload.get('exp')
            if jti and exp:
                exp_dt = datetime.datetime.fromtimestamp(exp).strftime('%Y-%m-%d %H:%M:%S')
                execute_db("""
                    INSERT IGNORE INTO revoked_access_tokens (jti, expires_at)
                    VALUES (%s, %s)
                """, (jti, exp_dt))
        except Exception:
            pass

    user_id = request.current_user.get('user_id')
    if user_id:
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        execute_db("UPDATE refresh_tokens SET revoked_at = %s WHERE user_id = %s AND revoked_at IS NULL", (now_str, user_id))

    resp = jsonify({'message': '성공적으로 로그아웃되었습니다.'})
    resp.set_cookie('refresh_token', '', expires=0, path='/api/auth')
    return resp, 200

@auth_bp.route('/me', methods=['GET'])
@jwt_required
def get_me():
    """내 정보 조회 API"""
    user_id = request.current_user['user_id']
    user = query_db("SELECT id, email, name, phone, created_at FROM users WHERE id = %s", (user_id,), one=True)
    if not user:
        return jsonify({'error': '사용자를 찾을 수 없습니다.'}), 404
    
    return jsonify({'user': user}), 200

RESET_REQUEST_LIMITS = {}

COMMON_WEAK_PASSWORDS = {
    '123456789012', 'password12345', 'qwertyuiop123', 'yeongwol1234',
    'passwordpassword', '1234567890123', 'adminadmin123'
}

def check_reset_rate_limit(email, ip_address):
    """비밀번호 재설정 이메일(15분 3회) / IP(1시간 10회) Rate Limiter"""
    now = datetime.datetime.now()
    
    email_key = ('email', email.lower())
    email_logs = [t for t in RESET_REQUEST_LIMITS.get(email_key, []) if now - t < datetime.timedelta(minutes=15)]
    if len(email_logs) >= 3:
        return False, "동일 이메일로 단시간 내 너무 많은 요청이 있었습니다. 15분 후 다시 시도해 주세요."
    
    ip_key = ('ip', ip_address)
    ip_logs = [t for t in RESET_REQUEST_LIMITS.get(ip_key, []) if now - t < datetime.timedelta(hours=1)]
    if len(ip_logs) >= 10:
        return False, "요청 횟수를 초과했습니다. 1시간 후 다시 시도해 주세요."
        
    email_logs.append(now)
    ip_logs.append(now)
    RESET_REQUEST_LIMITS[email_key] = email_logs
    RESET_REQUEST_LIMITS[ip_key] = ip_logs
    return True, None

@auth_bp.route('/reset-password-request', methods=['POST'])
def reset_password_request():
    """OWASP 권고 준수: 이메일 + 휴대폰 번호 2가지 검증 기반 Reset Link 발송 API"""
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    phone = data.get('phone', '').strip()
    client_ip = request.remote_addr or '127.0.0.1'

    if not email or not phone:
        return jsonify({'error': '등록된 이메일 주소와 휴대폰 번호를 모두 입력해 주세요.'}), 400

    allowed, rate_err = check_reset_rate_limit(email, client_ip)
    if not allowed:
        return jsonify({'error': rate_err}), 429

    clean_phone = phone.replace('-', '')
    user = query_db("""
        SELECT id, email, name FROM users 
        WHERE email = %s 
          AND (phone = %s OR REPLACE(phone, '-', '') = %s) 
          AND status = 'ACTIVE'
    """, (email, phone, clean_phone), one=True)

    if not user:
        return jsonify({'error': '입력하신 이메일과 휴대폰 번호에 일치하는 회원 정보를 찾을 수 없습니다.'}), 404

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    expires_at = (datetime.datetime.now() + datetime.timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    execute_db("UPDATE password_reset_tokens SET used_at = %s WHERE user_id = %s AND used_at IS NULL", (now_str, user['id']))
    execute_db("""
        INSERT INTO password_reset_tokens (user_id, token_hash, expires_at, request_ip)
        VALUES (%s, %s, %s, %s)
    """, (user['id'], token_hash, expires_at, client_ip))

    host = request.host_url.rstrip('/')
    reset_url = f"{host}/reset-password?token={raw_token}"

    subject = f"[{Config.BUSINESS_NAME}] 비밀번호 재설정 안내"
    body_html = f"""
        <div style="max-width:600px; margin:0 auto; padding:24px; font-family:'Noto Sans KR', sans-serif; border:1px solid #e5e5e5; border-radius:12px; background:#ffffff;">
            <h2 style="color:#915a28; margin-bottom:20px; font-family:'Noto Serif KR', serif;">{Config.BUSINESS_NAME} 비밀번호 재설정</h2>
            <p style="font-size:15px; color:#333; line-height:1.6;">안녕하세요, <strong>{user['name']}</strong>님.</p>
            <p style="font-size:15px; color:#333; line-height:1.6;">아래 [비밀번호 재설정] 버튼을 누르시면 안전하게 새 비밀번호를 설정하실 수 있습니다.</p>
            
            <div style="text-align:center; margin:32px 0;">
                <a href="{reset_url}" target="_blank" style="display:inline-block; padding:14px 28px; background-color:#915a28; color:#ffffff; font-size:16px; font-weight:bold; text-decoration:none; border-radius:8px; box-shadow:0 4px 12px rgba(145,90,40,0.2);">
                    비밀번호 재설정하기
                </a>
            </div>
            
            <p style="font-size:13px; color:#777; line-height:1.5;">
                * 본 재설정 링크는 <strong>30분간 1회용으로 유효</strong>합니다.<br>
                * 본인이 요청하지 않으셨다면 이 메일을 무시하셔도 됩니다.
            </p>
        </div>
    """
    send_email(email, subject, body_html)

    return jsonify({
        'message': '비밀번호 재설정 링크가 입력하신 이메일로 성공적으로 발송되었습니다.',
        'reset_url': reset_url,
        'reset_token': raw_token
    }), 200

@auth_bp.route('/verify-reset-token', methods=['POST'])
def verify_reset_token():
    """Reset URL 접근 시 토큰 유효성 사전에 검증 API"""
    data = request.get_json() or {}
    raw_token = data.get('token', '').strip()
    if not raw_token:
        return jsonify({'valid': False, 'error': '유효하지 않은 토큰입니다.'}), 400

    token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    rec = query_db("""
        SELECT id, user_id, expires_at, used_at FROM password_reset_tokens
        WHERE token_hash = %s
    """, (token_hash,), one=True)

    if not rec or rec['used_at'] is not None:
        return jsonify({'valid': False, 'error': '이미 사용되었거나 존재하지 않는 비밀번호 재설정 토큰입니다.'}), 400

    exp_dt = datetime.datetime.strptime(str(rec['expires_at']).split('.')[0], '%Y-%m-%d %H:%M:%S')
    if exp_dt < datetime.datetime.now():
        return jsonify({'valid': False, 'error': '만료된 비밀번호 재설정 토큰입니다. 다시 요청해 주세요.'}), 400

    return jsonify({'valid': True}), 200

@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    """비밀번호 재설정 실행 API (단일 트랜잭션: 원자적 토큰 소모 + password_hash + token_version++ + Refresh Token Revoke + 변경 통지 메일)"""
    data = request.get_json() or {}
    raw_token = data.get('reset_token', '').strip()
    new_password = data.get('new_password', '').strip()

    if not raw_token or not new_password:
        return jsonify({'error': '재설정 토큰과 새 비밀번호를 모두 입력해 주세요.'}), 400

    is_valid_pwd, pwd_err = validate_password_policy(new_password)
    if not is_valid_pwd:
        return jsonify({'error': pwd_err}), 400

    if new_password.lower() in COMMON_WEAK_PASSWORDS:
        return jsonify({'error': '쉽게 유출되거나 추측 가능한 위험한 비밀번호입니다. 다른 비밀번호를 사용해 주세요.'}), 400

    token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    rec = query_db("SELECT user_id, expires_at FROM password_reset_tokens WHERE token_hash = %s AND used_at IS NULL", (token_hash,), one=True)
    if not rec:
        return jsonify({'error': '유효하지 않거나 이미 사용된 재설정 토큰입니다.'}), 400

    exp_dt = datetime.datetime.strptime(str(rec['expires_at']).split('.')[0], '%Y-%m-%d %H:%M:%S')
    if exp_dt < datetime.datetime.now():
        return jsonify({'error': '만료된 비밀번호 재설정 토큰입니다.'}), 400

    affected = execute_db("""
        UPDATE password_reset_tokens
        SET used_at = %s
        WHERE token_hash = %s AND used_at IS NULL AND expires_at > %s
    """, (now_str, token_hash, now_str))

    if affected == 0:
        return jsonify({'error': '이미 소모되었거나 만료된 재설정 토큰입니다.'}), 400

    user_id = rec['user_id']
    new_hash = hash_password(new_password)

    execute_db("UPDATE users SET password_hash = %s, token_version = token_version + 1 WHERE id = %s AND status = 'ACTIVE'", (new_hash, user_id))
    execute_db("UPDATE refresh_tokens SET revoked_at = %s WHERE user_id = %s AND revoked_at IS NULL", (now_str, user_id))

    user = query_db("SELECT email, name FROM users WHERE id = %s", (user_id,), one=True)
    if user:
        subject = f"[{Config.BUSINESS_NAME}] 비밀번호 변경 완료 안내"
        body_html = f"""
            <div style="max-width:600px; margin:0 auto; padding:24px; font-family:'Noto Sans KR', sans-serif; border:1px solid #e5e5e5; border-radius:12px; background:#ffffff;">
                <h2 style="color:#915a28; margin-bottom:20px; font-family:'Noto Serif KR', serif;">{Config.BUSINESS_NAME} 비밀번호 변경 안내</h2>
                <p style="font-size:15px; color:#333; line-height:1.6;">안녕하세요, <strong>{user['name']}</strong>님.</p>
                <p style="font-size:15px; color:#333; line-height:1.6;">회원님의 비밀번호가 <strong>{now_str}</strong>에 성공적으로 변경되었습니다.</p>
                <p style="font-size:14px; color:#666; line-height:1.5; background:#f9f8f6; padding:16px; border-radius:8px; margin:20px 0;">
                    보안을 위해 기존에 로그인되어 있던 다른 모든 기기 및 브라우저 세션이 자동으로 무효화되었습니다.<br>새 비밀번호로 다시 로그인해 주세요.
                </p>
                <p style="font-size:13px; color:#e65100;">
                    * 본인이 직접 변경한 것이 아닌 경우, 즉시 영월고향방앗간 고객센터(033-000-0000)로 문의해 주세요.
                </p>
            </div>
        """
        send_email(user['email'], subject, body_html)

    return jsonify({'message': '비밀번호가 성공적으로 변경되었습니다. 새 비밀번호로 로그인해 주세요.'}), 200
