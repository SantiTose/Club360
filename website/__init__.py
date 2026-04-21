import os
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_required, current_user
from flask_migrate import Migrate
from sqlalchemy import text, inspect
import secrets
from datetime import datetime

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
        from website.models import TipoUsuario, Turno, Reserva, Pago

        turnos_reservados = 0
        deuda_total = 0.0
        actividad_reciente = []

        if current_user.tipo_usuario == TipoUsuario.CLIENTE:
            turnos_reservados = Reserva.query.filter_by(usuario_id=current_user.id).count()
            pagos_pendientes = Pago.query.filter_by(usuario_id=current_user.id, estado='pendiente').all()
            deuda_total = sum(p.monto for p in pagos_pendientes)

            proximo_turno = (
                Turno.query
                .join(Reserva, Reserva.turno_id == Turno.id)
                .filter(Reserva.usuario_id == current_user.id)
                .filter(Turno.hora_inicio >= datetime.utcnow())
                .order_by(Turno.hora_inicio.asc())
                .first()
            )
            if proximo_turno:
                actividad_reciente.append(
                    f"Próximo turno: {proximo_turno.actividad.upper()} el {proximo_turno.hora_inicio.strftime('%d/%m/%Y %H:%M')}"
                )

            ultimo_pago = (
                Pago.query
                .filter_by(usuario_id=current_user.id, estado='completado')
                .order_by(Pago.fecha_pago.desc())
                .first()
            )
            if ultimo_pago:
                actividad_reciente.append(
                    f"Último pago: ${ultimo_pago.monto:.2f} ({ultimo_pago.metodo_pago})"
                )
        else:
            actividad_reciente.append('Cuenta interna habilitada para gestión administrativa y operativa.')

        return render_template(
            'dashboard.html',
            turnos_reservados=turnos_reservados,
            deuda_total=deuda_total,
            actividad_reciente=actividad_reciente,
        )

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
        _ensure_usuario_recordatorio_column()
        _ensure_usuario_cancelaciones_credito_columns()
        _ensure_usuario_requiere_cambio_password_column()
        _ensure_usuario_reset_password_columns()
        _ensure_reserva_qr_columns()
        _ensure_pago_tipo_clase_column()
        _backfill_reserva_qr_tokens()

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


def _ensure_usuario_recordatorio_column():
    inspector = inspect(db.engine)
    if 'usuarios' not in inspector.get_table_names():
        return

    columnas = {c['name'] for c in inspector.get_columns('usuarios')}
    if 'ultimo_recordatorio_mora' not in columnas:
        db.session.execute(text("ALTER TABLE usuarios ADD COLUMN ultimo_recordatorio_mora DATETIME"))
        db.session.commit()


def _ensure_usuario_cancelaciones_credito_columns():
    inspector = inspect(db.engine)
    if 'usuarios' not in inspector.get_table_names():
        return

    columnas = {c['name'] for c in inspector.get_columns('usuarios')}
    updates = []
    if 'credito_abonado' not in columnas:
        updates.append("ALTER TABLE usuarios ADD COLUMN credito_abonado FLOAT NOT NULL DEFAULT 0")
    if 'cancelaciones_abonado' not in columnas:
        updates.append("ALTER TABLE usuarios ADD COLUMN cancelaciones_abonado INTEGER NOT NULL DEFAULT 0")
    if 'beneficio_abonado_activo' not in columnas:
        updates.append("ALTER TABLE usuarios ADD COLUMN beneficio_abonado_activo BOOLEAN NOT NULL DEFAULT 1")

    for sql in updates:
        db.session.execute(text(sql))

    if updates:
        db.session.commit()


def _ensure_usuario_requiere_cambio_password_column():
    inspector = inspect(db.engine)
    if 'usuarios' not in inspector.get_table_names():
        return

    columnas = {c['name'] for c in inspector.get_columns('usuarios')}
    if 'requiere_cambio_password' not in columnas:
        db.session.execute(text("ALTER TABLE usuarios ADD COLUMN requiere_cambio_password BOOLEAN NOT NULL DEFAULT 0"))
        db.session.commit()


def _ensure_usuario_reset_password_columns():
    inspector = inspect(db.engine)
    if 'usuarios' not in inspector.get_table_names():
        return

    columnas = {c['name'] for c in inspector.get_columns('usuarios')}
    updates = []
    if 'reset_password_token' not in columnas:
        updates.append("ALTER TABLE usuarios ADD COLUMN reset_password_token VARCHAR(120)")
    if 'reset_password_expira' not in columnas:
        updates.append("ALTER TABLE usuarios ADD COLUMN reset_password_expira DATETIME")

    for sql in updates:
        db.session.execute(text(sql))

    if updates:
        db.session.commit()


def _ensure_reserva_qr_columns():
    inspector = inspect(db.engine)
    if 'reservas' not in inspector.get_table_names():
        return

    columnas = {c['name'] for c in inspector.get_columns('reservas')}
    updates = []

    if 'qr_token' not in columnas:
        updates.append("ALTER TABLE reservas ADD COLUMN qr_token VARCHAR(120)")
    if 'recordatorio_enviado' not in columnas:
        updates.append("ALTER TABLE reservas ADD COLUMN recordatorio_enviado BOOLEAN NOT NULL DEFAULT 0")
    if 'fecha_recordatorio' not in columnas:
        updates.append("ALTER TABLE reservas ADD COLUMN fecha_recordatorio DATETIME")
    if 'asistencia_validada' not in columnas:
        updates.append("ALTER TABLE reservas ADD COLUMN asistencia_validada BOOLEAN NOT NULL DEFAULT 0")
    if 'fecha_asistencia' not in columnas:
        updates.append("ALTER TABLE reservas ADD COLUMN fecha_asistencia DATETIME")

    for sql in updates:
        db.session.execute(text(sql))

    if updates:
        db.session.commit()


def _ensure_pago_tipo_clase_column():
    inspector = inspect(db.engine)
    if 'pagos' not in inspector.get_table_names():
        return

    columnas = {c['name'] for c in inspector.get_columns('pagos')}
    if 'tipo_clase' not in columnas:
        db.session.execute(text("ALTER TABLE pagos ADD COLUMN tipo_clase VARCHAR(20) NOT NULL DEFAULT 'no_abonada'"))
        db.session.commit()


def _backfill_reserva_qr_tokens():
    from website.models import Reserva

    reservas_sin_qr = Reserva.query.filter((Reserva.qr_token.is_(None)) | (Reserva.qr_token == '')).all()
    for reserva in reservas_sin_qr:
        reserva.qr_token = secrets.token_urlsafe(24)

    if reservas_sin_qr:
        db.session.commit()
