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
    PORTONE_WEBHOOK_SECRET = os.getenv('PORTONE_WEBHOOK_SECRET', '')
    ADMIN_SMS_PHONE = os.getenv('ADMIN_SMS_PHONE', '010-0000-0000')

    # Business Information Metadata (From Official Business Registration Certificate)
    BUSINESS_NAME = os.getenv('BUSINESS_NAME', '고향방앗간')
    REPRESENTATIVE_NAME = os.getenv('REPRESENTATIVE_NAME', '권오명')
    BUSINESS_REGISTRATION_NUMBER = os.getenv('BUSINESS_REGISTRATION_NUMBER', '787-04-02840')
    MAIL_ORDER_SALES_NUMBER = os.getenv('MAIL_ORDER_SALES_NUMBER', '제 2026-강원영월-0000 호')
    BUSINESS_ADDRESS = os.getenv('BUSINESS_ADDRESS', '강원특별자치도 영월군 영월읍 절무리골길 16, 제2동 1층')
    CUSTOMER_SERVICE_PHONE = os.getenv('CUSTOMER_SERVICE_PHONE', '010-4422-5267')
    CUSTOMER_SERVICE_EMAIL = os.getenv('CUSTOMER_SERVICE_EMAIL', 'no-reply@yeongwol-gohyangmill.co.kr')
    PRIVACY_OFFICER = os.getenv('PRIVACY_OFFICER', '권오명')
    HOSTING_PROVIDER = os.getenv('HOSTING_PROVIDER', '고향방앗간')


    # Shipping Policy Config
    BASE_SHIPPING_FEE = int(os.getenv('BASE_SHIPPING_FEE', 3000))
    FREE_SHIPPING_THRESHOLD = int(os.getenv('FREE_SHIPPING_THRESHOLD', 50000))
    REMOTE_AREA_SURCHARGE = int(os.getenv('REMOTE_AREA_SURCHARGE', 3000))

    # Refund Reconciliation Config
    REFUND_PROCESSING_STALE_SECONDS = int(os.getenv('REFUND_PROCESSING_STALE_SECONDS', 3600))

    # Aligo API Config
    ALIGO_API_KEY = os.getenv('ALIGO_API_KEY', '')
    ALIGO_USER_ID = os.getenv('ALIGO_USER_ID', '')
    ALIGO_SENDER = os.getenv('ALIGO_SENDER', '033-000-0000')

    # Korea Post Tracking API Config
    EPOST_API_SERVICE_KEY = os.getenv('EPOST_API_SERVICE_KEY', '')
    EPOST_TRACKING_ENABLED = os.getenv('EPOST_TRACKING_ENABLED', 'true').lower() == 'true'
    EPOST_TRACKING_INTERVAL_MINUTES = int(os.getenv('EPOST_TRACKING_INTERVAL_MINUTES', 60))
    EPOST_TRACKING_TIMEOUT_SECONDS = int(os.getenv('EPOST_TRACKING_TIMEOUT_SECONDS', 10))


