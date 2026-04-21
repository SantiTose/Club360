"""
Configuración de la aplicación Club360
"""
import os
from datetime import timedelta


class Config:
    """Configuración base"""
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REMEMBER_COOKIE_DURATION = timedelta(days=7)
    # Fechas opcionales en formato YYYY-MM-DD para contemplar feriados trasladados/no laborables.
    _feriados_env = os.environ.get('FERIADOS_NACIONALES', '')
    FERIADOS_NACIONALES = [d.strip() for d in _feriados_env.split(',') if d.strip()]
    # Información pública del establecimiento (editable por entorno).
    CLUB_DIRECCION_PUBLICA = os.environ.get('CLUB_DIRECCION_PUBLICA', 'A confirmar')
    CLUB_CONTACTO_PUBLICO = os.environ.get('CLUB_CONTACTO_PUBLICO', 'A confirmar')
    CLUB_HORARIOS_PUBLICOS = [
        'Lunes a Sábado: 08:00 a 22:00',
        'Domingos: cerrado',
        'Feriados nacionales: cerrado',
    ]
    CLUB_ACTIVIDADES_PUBLICAS = ['Fútbol', 'Básquet', 'Vóley', 'Pádel']


class DevelopmentConfig(Config):
    """Configuración para desarrollo"""
    DEBUG = True
    TESTING = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///club360.db'
    SECRET_KEY = 'dev-secret-key-change-in-production'
    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    """Configuración para producción"""
    DEBUG = False
    TESTING = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///club360.db')
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True


class TestingConfig(Config):
    """Configuración para pruebas"""
    DEBUG = True
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'testing-key'


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
