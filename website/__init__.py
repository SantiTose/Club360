import os
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_required
from flask_migrate import Migrate
from sqlalchemy import text, inspect

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()


def create_app(config_name='development'):
    """Application factory function."""
    # Get base directory
    basedir = os.path.abspath(os.path.dirname(__file__))
    
    app = Flask(__name__,
                template_folder=os.path.join(os.path.dirname(basedir), 'templates'),
                static_folder=os.path.join(os.path.dirname(basedir), 'statics'),
                static_url_path='/static')

    # Configuration
    try:
        from config import config as app_config
        app.config.from_object(app_config.get(config_name, app_config['default']))
    except Exception:
        # Fallback seguro para entornos donde no se pueda cargar config.py
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///club360.db'
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        app.config['SECRET_KEY'] = 'dev-secret-key-change-in-production'
    
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'warning'

    # Setup user loader
    @login_manager.user_loader
    def load_user(user_id):
        from website.models import Usuario
        if user_id:
            try:
                return Usuario.query.get(int(user_id))
            except:
                return None
        return None

    # Main routes
    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/dashboard')
    @login_required
    def dashboard():
        return render_template('dashboard.html')

    # Register blueprints
    from website.auth import auth_bp
    from website.turnos import turnos_bp
    from website.pagos import pagos_bp
    from website.suspensiones import suspensiones_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(turnos_bp)
    app.register_blueprint(pagos_bp)
    app.register_blueprint(suspensiones_bp)

    # Create tables
    with app.app_context():
        db.create_all()
        _ensure_turno_tipo_clase_column()
        _drop_legacy_usuario_tipo_cliente_column()

    return app


def _ensure_turno_tipo_clase_column():
    """Agrega `tipo_clase` a `turnos` en instalaciones existentes sin migraciones."""
    inspector = inspect(db.engine)
    if 'turnos' not in inspector.get_table_names():
        return

    columnas = {c['name'] for c in inspector.get_columns('turnos')}
    if 'tipo_clase' in columnas:
        return

    db.session.execute(text("ALTER TABLE turnos ADD COLUMN tipo_clase VARCHAR(20) NOT NULL DEFAULT 'no_abonada'"))
    db.session.commit()


def _drop_legacy_usuario_tipo_cliente_column():
    """Elimina `tipo_cliente` de `usuarios` en instalaciones existentes cuando sea posible."""
    inspector = inspect(db.engine)
    if 'usuarios' not in inspector.get_table_names():
        return

    columnas = {c['name'] for c in inspector.get_columns('usuarios')}
    if 'tipo_cliente' not in columnas:
        return

    try:
        db.session.execute(text("ALTER TABLE usuarios DROP COLUMN tipo_cliente"))
        db.session.commit()
    except Exception:
        # Si la versión de SQLite no soporta DROP COLUMN, se mantiene compatibilidad sin romper arranque.
        db.session.rollback()
