import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'change-me')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'mysql+pymysql://root:@127.0.0.1:3306/pasar_remboken')
    SQLALCHEMY_TRACK_MODIFICATIONS = True
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    MIDTRANS_SERVER_KEY = os.getenv('MIDTRANS_SERVER_KEY', '')
    MIDTRANS_CLIENT_KEY = os.getenv('MIDTRANS_CLIENT_KEY', '')
    MIDTRANS_IS_PRODUCTION = os.getenv('MIDTRANS_IS_PRODUCTION', 'False').lower() == 'true'
    FONNTE_TOKEN = os.getenv('FONNTE_TOKEN', '')
    SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
    SMTP_USER = os.getenv('SMTP_USER', '')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
    MARKET_LAT = float(os.getenv('MARKET_LAT', '0') or 0)
    MARKET_LNG = float(os.getenv('MARKET_LNG', '0') or 0)
    DELIVERY_BASE_FEE = int(os.getenv('DELIVERY_BASE_FEE', '5000'))
    DELIVERY_PER_KM = int(os.getenv('DELIVERY_PER_KM', '2000'))
