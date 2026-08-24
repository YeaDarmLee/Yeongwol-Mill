import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_nginx_config_syntax():
    """deploy/nginx.conf 파싱 및 SSL/Reverse Proxy 설정 존재 검증"""
    deploy_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'deploy')
    nginx_path = os.path.join(deploy_dir, 'nginx.conf')
    assert os.path.exists(nginx_path)
    with open(nginx_path, 'r', encoding='utf-8') as f:
        content = f.read()
        assert 'proxy_pass http://127.0.0.1:5000' in content
        assert 'ssl_certificate' in content

def test_gunicorn_config_parse():
    """deploy/gunicorn.service Systemd 유닛 파일 존재 및 파싱 검증"""
    deploy_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'deploy')
    gunicorn_path = os.path.join(deploy_dir, 'gunicorn.service')
    assert os.path.exists(gunicorn_path)
    with open(gunicorn_path, 'r', encoding='utf-8') as f:
        content = f.read()
        assert 'gunicorn' in content
        assert 'ExecStart' in content

def test_systemd_unit_syntax():
    """expire_reservations.service & timer 유닛 존재 검증"""
    deploy_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'deploy')
    svc_path = os.path.join(deploy_dir, 'expire_reservations.service')
    timer_path = os.path.join(deploy_dir, 'expire_reservations.timer')
    assert os.path.exists(svc_path)
    assert os.path.exists(timer_path)

def test_health_endpoint(client):
    """/health API 헬스체크 응답 검증"""
    res = client.get('/health')
    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'ok'
    assert 'database' in data

def test_backup_script_execution():
    """deploy/backup_db.sh DB 백업 스크립트 존재 검증"""
    deploy_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'deploy')
    script_path = os.path.join(deploy_dir, 'backup_db.sh')
    assert os.path.exists(script_path)
    with open(script_path, 'r', encoding='utf-8') as f:
        content = f.read()
        assert 'mysqldump' in content
        assert 'gzip' in content

def test_restore_script_execution():
    """deploy/restore_test.sh 격리 DB 복구 스크립트 존재 검증"""
    deploy_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'deploy')
    script_path = os.path.join(deploy_dir, 'restore_test.sh')
    assert os.path.exists(script_path)
    with open(script_path, 'r', encoding='utf-8') as f:
        content = f.read()
        assert 'yeongwol_restore_test_db' in content
