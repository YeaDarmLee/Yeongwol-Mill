import os
import time
from collections import defaultdict
from flask import Flask, send_from_directory, jsonify, render_template, request
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from db.init_db import init_database
from cli import register_cli_commands

# Blueprint Imports
from routes.auth import auth_bp
from routes.users import users_bp
from routes.products import products_bp
from routes.orders import orders_bp
from routes.payment import payment_bp
from routes.admin import admin_bp
from routes.health import health_bp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path='/static', template_folder=TEMPLATES_DIR)
app.config.from_object(Config)


# Nginx ProxyFix (trust exactly 1 hop for X-Forwarded-For)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

CORS(app)

# 경량 내장 IP Rate Limiter (Flask-Limiter 모듈 미설치 시 폴백)
REQUEST_LOGS = defaultdict(list)

@app.before_request
def check_rate_limit():
    if app.config.get('TESTING'):
        return
    # 로그인, 비밀번호 변경 및 회원탈퇴 엔드포인트에 대한 IP Rate Limiting (1분 5회 제한)
    if request.path in ['/api/auth/login', '/api/admin/login', '/api/users/me/password', '/api/users/me/withdraw'] and request.method in ['POST', 'PUT']:
        client_ip = request.remote_addr or '127.0.0.1'
        now = time.time()
        REQUEST_LOGS[client_ip] = [t for t in REQUEST_LOGS[client_ip] if now - t < 60]
        if len(REQUEST_LOGS[client_ip]) >= 5:
            return jsonify({'error': '요청 횟수를 초과하였습니다. 잠시 후 다시 시도해 주세요.'}), 429
        REQUEST_LOGS[client_ip].append(now)

# Register Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(users_bp)
app.register_blueprint(products_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(payment_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(health_bp)

# Register Custom CLI Commands (flask create-admin, flask expire-reservations)
register_cli_commands(app)

# Context Processor for Business Information in Jinja2 Templates
@app.context_processor
def inject_config():
    return {'config': Config}

@app.route('/admin')
@app.route('/admin/<path:subpage>')
def admin_page(subpage=None):
    if subpage and any(subpage.endswith(ext) for ext in ['.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.html']):
        return send_from_directory(os.path.join(STATIC_DIR, 'admin'), subpage)
    admin_dir_index = os.path.join(STATIC_DIR, 'admin', 'index.html')
    if os.path.exists(admin_dir_index):
        return send_from_directory(os.path.join(STATIC_DIR, 'admin'), 'index.html')
    if os.path.exists(os.path.join(TEMPLATES_DIR, 'admin.html')):
        return render_template('admin.html')
    return send_from_directory(STATIC_DIR, 'admin.html')



# Favicon Routes
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(STATIC_DIR, 'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/favicon.svg')
def favicon_svg():
    return send_from_directory(STATIC_DIR, 'favicon.svg', mimetype='image/svg+xml')

@app.route('/favicon.png')
def favicon_png():
    return send_from_directory(STATIC_DIR, 'favicon.png', mimetype='image/png')

# Static & Clean URL Route Handlers (확장자 없는 클린 URL 지원)
@app.route('/')
def index():
    if os.path.exists(os.path.join(TEMPLATES_DIR, 'index.html')):
        return render_template('index.html')
    return send_from_directory(STATIC_DIR, 'index.html')

@app.route('/static/<path:filename>')
def serve_static_folder(filename):
    return send_from_directory(STATIC_DIR, filename)

@app.route('/<path:filename>')


def serve_static(filename):
    # 1. 확장자가 없는 경우 .html 붙여서 templates / static 폴더 검색
    target_html = filename if filename.endswith('.html') else f"{filename}.html"
    
    if os.path.exists(os.path.join(TEMPLATES_DIR, target_html)):
        return render_template(target_html)
    if os.path.exists(os.path.join(STATIC_DIR, target_html)):
        return send_from_directory(STATIC_DIR, target_html)

    # 2. CSS, JS, 이미지 등 정적 파일 직접 서비스
    if os.path.exists(os.path.join(STATIC_DIR, filename)):
        return send_from_directory(STATIC_DIR, filename)

    return jsonify({'error': '페이지 또는 리소스를 찾을 수 없습니다.'}), 404

# DB Auto Initialization on Application Startup
try:
    init_database()
except Exception as e:
    print(f"Warning: Database initialization skipped or failed: {e}")

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"영월고향방앗간 Flask 쇼핑몰 서버가 http://localhost:{port} 에서 실행됩니다.")
    app.run(host='0.0.0.0', port=port, debug=True)
