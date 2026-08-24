import os
from flask import Flask, send_from_directory, jsonify, render_template
from flask_cors import CORS
from config import Config
from db.init_db import init_database
from cli import register_cli_commands

# Blueprint Imports
from routes.auth import auth_bp
from routes.products import products_bp
from routes.orders import orders_bp
from routes.payment import payment_bp
from routes.admin import admin_bp
from routes.health import health_bp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')

app = Flask(__name__, static_folder=STATIC_DIR, template_folder=TEMPLATES_DIR, static_url_path='')
app.config.from_object(Config)
CORS(app)

# Register Blueprints
app.register_blueprint(auth_bp)
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

# Static & HTML Route Handlers
@app.route('/')
def index():
    if os.path.exists(os.path.join(TEMPLATES_DIR, 'index.html')):
        return render_template('index.html')
    return send_from_directory(STATIC_DIR, 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    # 1. Templates 폴더 내 HTML 검색 및 렌더링
    if filename.endswith('.html'):
        template_name = filename
        if os.path.exists(os.path.join(TEMPLATES_DIR, template_name)):
            return render_template(template_name)
    # 2. Static 파일 처리
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
