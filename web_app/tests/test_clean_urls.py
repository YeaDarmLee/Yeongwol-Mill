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

def test_clean_urls_without_html_extension(client):
    """.html 확장자 없는 Clean URL 접속 200 OK 정상 반환 검증"""
    clean_routes = [
        '/',
        '/brand',
        '/category',
        '/process',
        '/cart',
        '/checkout',
        '/order-history',
        '/order-complete',
        '/login',
        '/register',
        '/admin',
        '/terms',
        '/privacy'
    ]
    for route in clean_routes:
        res = client.get(route)
        assert res.status_code == 200, f"Route '{route}' must return 200 OK, got {res.status_code}"
