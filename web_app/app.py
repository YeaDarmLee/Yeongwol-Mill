import os
from flask import Flask, send_from_directory, jsonify
from flask_cors import CORS
from config import Config
from db.init_db import init_database

# Blueprint Imports
from routes.auth import auth_bp
from routes.products import products_bp
from routes.orders import orders_bp
from routes.payment import payment_bp

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path='')
app.config.from_object(Config)
CORS(app)

# Register Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(products_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(payment_bp)

# Static & HTML Route Handlers
@app.route('/')
def index():
    return send_from_directory(STATIC_DIR, 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    if os.path.exists(os.path.join(STATIC_DIR, filename)):
        return send_from_directory(STATIC_DIR, filename)
    return jsonify({'error': 'Page or resource not found'}), 404

# DB Auto Initialization on Application Startup
try:
    init_database()
except Exception as e:
    print(f"Warning: Database initialization skipped or failed: {e}")

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"영월방앗간 Flask 쇼핑몰 서버가 http://localhost:{port} 에서 실행됩니다.")
    app.run(host='0.0.0.0', port=port, debug=True)
