import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app
from db.init_db import init_database
from db.db_connection import query_db, execute_db

@pytest.fixture(autouse=True)
def setup_db():
    app.config['TESTING'] = True
    init_database()
    execute_db("DELETE FROM users WHERE email = 'auth_test@yeongwol.com'")

@pytest.fixture
def client():
    with app.test_client() as client:
        yield client

def test_password_reset_token_flow(client):
    """비밀번호 재설정 토큰 발급 및 변경 테스트"""
    # 1. 회원가입
    client.post('/api/auth/register', json={
        'email': 'auth_test@yeongwol.com',
        'password': 'oldpassword123',
        'name': '보안테스터',
        'phone': '010-1111-2222',
        'terms_agreed': True,
        'privacy_agreed': True
    })

    # 2. 토큰 발급 요청
    res_req = client.post('/api/auth/reset-password-request', json={'email': 'auth_test@yeongwol.com'})
    assert res_req.status_code == 200
    token = res_req.get_json()['reset_token']

    # 3. 비밀번호 변경
    res_reset = client.post('/api/auth/reset-password', json={
        'reset_token': token,
        'new_password': 'newpassword456'
    })
    assert res_reset.status_code == 200

    # 4. 새 비밀번호 로그인 성공 확인
    login_res = client.post('/api/auth/login', json={
        'email': 'auth_test@yeongwol.com',
        'password': 'newpassword456'
    })
    assert login_res.status_code == 200

def test_password_reset_token_single_use(client):
    """비밀번호 재설정 토큰 1회 사용 후 재사용 차단 테스트"""
    client.post('/api/auth/register', json={
        'email': 'auth_test@yeongwol.com',
        'password': 'oldpassword123',
        'name': '보안테스터',
        'phone': '010-1111-2222',
        'terms_agreed': True,
        'privacy_agreed': True
    })
    res_req = client.post('/api/auth/reset-password-request', json={'email': 'auth_test@yeongwol.com'})
    token = res_req.get_json()['reset_token']

    # 1회 사용
    client.post('/api/auth/reset-password', json={'reset_token': token, 'new_password': 'pass1'})
    # 2회 재사용 시도 ➔ 400 실패
    res_reuse = client.post('/api/auth/reset-password', json={'reset_token': token, 'new_password': 'pass2'})
    assert res_reuse.status_code == 400

def test_expired_password_reset_token(client):
    """유효하지 않거나 만료된 재설정 토큰 거부 테스트"""
    res = client.post('/api/auth/reset-password', json={
        'reset_token': 'invalid_token_9999',
        'new_password': 'newpass'
    })
    assert res.status_code == 400

def test_refresh_token_success(client):
    """Refresh Token 기능 구현 여부 감사 (현재 미구현 ➔ FAIL 판정 검증)"""
    res = client.post('/api/auth/refresh', json={'refresh_token': 'dummy_token'})
    # 현재 auth.py에 refresh 라우트가 미구현 상태이므로 404/405/FAIL 반환 (Read-Only 감사 충실)
    assert res.status_code == 200 # 미구현 ➔ FAIL 기대값

def test_expired_refresh_token_rejected(client):
    """만료된 Refresh Token 거부 검증 (미구현 ➔ FAIL)"""
    res = client.post('/api/auth/refresh', json={'refresh_token': 'expired_token'})
    assert res.status_code == 401

def test_logout_blacklisted_token_rejected(client):
    """로그아웃된 토큰 Blacklist 차단 검증 (미구현 ➔ FAIL)"""
    res = client.post('/api/auth/logout', headers={'Authorization': 'Bearer dummy_token'})
    assert res.status_code == 200

def test_admin_login_rate_limit(client):
    """관리자 로그인 연속 실패 시 Rate Limit 차단 검증 (미구현 ➔ FAIL)"""
    for _ in range(10):
        client.post('/api/admin/login', json={'email': 'admin@fail.com', 'password': 'wrong'})
    # 11번째에서 429 Too Many Requests 기대 (현재 미구현으로 401 반환)
    res_11 = client.post('/api/admin/login', json={'email': 'admin@fail.com', 'password': 'wrong'})
    assert res_11.status_code == 429

def test_user_login_rate_limit(client):
    """일반 사용자 로그인 Rate Limit 차단 검증 (미구현 ➔ FAIL)"""
    for _ in range(10):
        client.post('/api/auth/login', json={'email': 'user@fail.com', 'password': 'wrong'})
    res_11 = client.post('/api/auth/login', json={'email': 'user@fail.com', 'password': 'wrong'})
    assert res_11.status_code == 429

def test_jwt_role_enforcement(client):
    """권한 없는 일반 사용자 토큰으로 관리자 API 호출 시 403 거부 검증"""
    # 일반 사용자 회원가입 & 로그인
    client.post('/api/auth/register', json={
        'email': 'auth_test@yeongwol.com',
        'password': 'password123',
        'name': '일반유저',
        'phone': '010-1111-2222',
        'terms_agreed': True,
        'privacy_agreed': True
    })
    login_res = client.post('/api/auth/login', json={'email': 'auth_test@yeongwol.com', 'password': 'password123'})
    user_token = login_res.get_json()['token']

    # 일반 사용자 토큰으로 관리자 대시보드 접근 시도 ➔ 403 거부
    admin_res = client.get('/api/admin/dashboard', headers={'Authorization': f'Bearer {user_token}'})
    assert admin_res.status_code == 403
