import os
import secrets
from pathlib import Path
from dotenv import load_dotenv
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')
def env_bool(name, default=False):
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {'1', 'true', 'yes', 'on'}
class Config:
    SECRET_KEY = os.getenv('SECRET_KEY') or secrets.token_urlsafe(48)
    DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
    ENVIRONMENT = os.getenv('FLASK_ENV', os.getenv('RENDER', 'development')).lower()
    if ENVIRONMENT not in {'development', 'production', 'testing'}:
        ENVIRONMENT = 'production' if os.getenv('RENDER') else 'development'
    DEBUG = ENVIRONMENT == 'development'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = env_bool('COOKIE_SECURE', ENVIRONMENT == 'production')
    PERMANENT_SESSION_LIFETIME = 28800
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024
    DATABASE_POOL_SIZE = int(os.getenv('DATABASE_POOL_SIZE', '5'))
    DATABASE_MAX_OVERFLOW = int(os.getenv('DATABASE_MAX_OVERFLOW', '5'))
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600
    BOOTSTRAP_ADMIN_USER = os.getenv('BOOTSTRAP_ADMIN_USER', '')
    BOOTSTRAP_ADMIN_PASSWORD = os.getenv('BOOTSTRAP_ADMIN_PASSWORD', '')
    BOOTSTRAP_ADMIN_NAME = os.getenv('BOOTSTRAP_ADMIN_NAME', 'Administrador MAQCONTROL')
    BOOTSTRAP_COMPANY = os.getenv('BOOTSTRAP_COMPANY', 'MAQCONTROL - Administracion')
    @classmethod
    def validate(cls):
        if cls.ENVIRONMENT == 'production' and (not os.getenv('SECRET_KEY') or len(cls.SECRET_KEY) < 32):
            raise RuntimeError('Configura SECRET_KEY con al menos 32 caracteres en las variables de entorno de produccion')
        if not cls.DATABASE_URL:
            raise RuntimeError('DATABASE_URL no esta configurada en .env')
        if cls.ENVIRONMENT == 'production' and not cls.SESSION_COOKIE_SECURE:
            raise RuntimeError('COOKIE_SECURE=true es obligatorio en produccion HTTPS')
def get_config():
    return Config
