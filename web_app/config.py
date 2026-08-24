import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'yeongwol-mill-secret-key-2026')
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'yeongwol-mill-jwt-secret-key-2026')
    JWT_EXPIRATION_HOURS = int(os.getenv('JWT_EXPIRATION_HOURS', 24))
    
    # MySQL Database Config
    MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
    MYSQL_PORT = int(os.getenv('MYSQL_PORT', 3306))
    MYSQL_USER = os.getenv('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
    MYSQL_DB = os.getenv('MYSQL_DB', 'yeongwol_mill')
    
    # Portone PG Config
    PORTONE_API_KEY = os.getenv('PORTONE_API_KEY', '')
    PORTONE_API_SECRET = os.getenv('PORTONE_API_SECRET', '')
    PORTONE_STORE_ID = os.getenv('PORTONE_STORE_ID', 'store-test-id')
    PORTONE_CHANNEL_KEY = os.getenv('PORTONE_CHANNEL_KEY', 'channel-test-key')
