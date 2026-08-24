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

    # Business Information Metadata (Placeholder from Environment Variables)
    BUSINESS_NAME = os.getenv('BUSINESS_NAME', '영월고향방앗간')
    REPRESENTATIVE_NAME = os.getenv('REPRESENTATIVE_NAME', '이예닮')
    BUSINESS_REGISTRATION_NUMBER = os.getenv('BUSINESS_REGISTRATION_NUMBER', '000-00-00000')
    MAIL_ORDER_SALES_NUMBER = os.getenv('MAIL_ORDER_SALES_NUMBER', '2026-강원영월-0000호')
    BUSINESS_ADDRESS = os.getenv('BUSINESS_ADDRESS', '강원특별자치도 영월군 영월읍 방앗간길 12')
    CUSTOMER_SERVICE_PHONE = os.getenv('CUSTOMER_SERVICE_PHONE', '033-000-0000')
    CUSTOMER_SERVICE_EMAIL = os.getenv('CUSTOMER_SERVICE_EMAIL', 'support@yeongwol-mill.com')
    PRIVACY_OFFICER = os.getenv('PRIVACY_OFFICER', '이예닮')
    HOSTING_PROVIDER = os.getenv('HOSTING_PROVIDER', '영월고향방앗간')

    # Shipping Policy Config
    BASE_SHIPPING_FEE = int(os.getenv('BASE_SHIPPING_FEE', 3000))
    FREE_SHIPPING_THRESHOLD = int(os.getenv('FREE_SHIPPING_THRESHOLD', 50000))
    REMOTE_AREA_SURCHARGE = int(os.getenv('REMOTE_AREA_SURCHARGE', 3000))
