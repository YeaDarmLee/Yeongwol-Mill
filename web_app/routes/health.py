from flask import Blueprint, jsonify
from db.db_connection import query_db

health_bp = Blueprint('health', __name__)

@health_bp.route('/health', methods=['GET'])
def health_check():
    """시스템 헬스체크 및 DB 연결 점검 API"""
    try:
        res = query_db("SELECT 1 as alive", one=True)
        db_status = "healthy" if res and res.get('alive') == 1 else "unhealthy"
    except Exception as e:
        db_status = f"unhealthy ({e})"

    return jsonify({
        'status': 'ok' if 'healthy' in db_status else 'error',
        'database': db_status,
        'app': '영월고향방앗간 Web Engine v2.2 Gold Master'
    }), 200 if 'healthy' in db_status else 500
