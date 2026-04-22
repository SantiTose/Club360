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
        return render_template(
            'index.html',
            club_direccion=app.config.get('CLUB_DIRECCION_PUBLICA', ''),
            club_contacto=app.config.get('CLUB_CONTACTO_PUBLICO', ''),
            club_horarios=app.config.get('CLUB_HORARIOS_PUBLICOS', []),
            club_actividades=app.config.get('CLUB_ACTIVIDADES_PUBLICAS', []),
        )

    @app.route('/dashboard')
    @login_required
    def dashboard():
        from website.models import TipoUsuario, Turno, Reserva, Pago, Usuario

        turnos_reservados = 0
        deuda_total = 0.0
        actividad_reciente = []
        dashboard_context = {
            'mode': 'cliente',
            'eyebrow': 'Panel personal',
            'hero_title': f'Hola, {current_user.nombre}',
            'hero_text': 'Gestioná tus turnos, controlá tu estado y resolvé pagos desde un mismo lugar, con accesos claros y datos relevantes a primera vista.',
            'hero_tags': [
                current_user.tipo_usuario.capitalize(),
                current_user.estado.capitalize() if current_user.estado else 'Sin estado',
            ],
            'stats': [],
            'actions_intro': 'Las tareas que más usás, organizadas con mejor prioridad visual.',
            'activity_heading': 'Actividad reciente',
            'activity_intro': 'Lo último que pasó en tu cuenta.',
        }

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

            dashboard_context['stats'] = [
                {
                    'label': 'Estado de la cuenta',
                    'value': current_user.estado.capitalize() if current_user.estado else 'N/A',
                    'description': 'Tu membresía y acceso actual dentro de Club 360.',
                    'accent': False,
                },
                {
                    'label': 'Turnos reservados',
                    'value': turnos_reservados,
                    'description': 'Reservas activas listas para asistir o gestionar.',
                    'accent': False,
                },
                {
                    'label': 'Deuda pendiente',
                    'value': f"${deuda_total:.2f}",
                    'description': 'Controlá pagos y mantené tu cuenta al día.',
                    'accent': True,
                },
            ]
        else:
            dashboard_context.update({
                'mode': 'interno',
                'eyebrow': 'Panel operativo',
                'hero_title': 'Centro de gestión',
                'hero_text': 'Centralizá altas, agenda y administración interna desde un tablero orientado a operación, sin métricas de cliente que no aplican a tu cuenta.',
                'hero_tags': [
                    current_user.tipo_usuario.capitalize(),
                    'Acceso interno',
                ],
                'actions_intro': 'Atajos de trabajo para las tareas administrativas del día.',
                'activity_heading': 'Seguimiento operativo',
                'activity_intro': 'Resumen breve de lo más reciente en la administración del club.',
            })

            clientes_registrados = Usuario.query.filter_by(tipo_usuario=TipoUsuario.CLIENTE).count()
            empleados_registrados = Usuario.query.filter_by(tipo_usuario=TipoUsuario.EMPLEADO).count()
            reservas_activas = (
                Reserva.query
                .join(Turno, Reserva.turno_id == Turno.id)
                .filter(Turno.cancelado.is_(False))
                .filter(Turno.hora_inicio >= datetime.utcnow())
                .count()
            )

            dashboard_context['stats'] = [
                {
                    'label': 'Clientes registrados',
                    'value': clientes_registrados,
                    'description': 'Base total de clientes para operar desde el panel.',
                    'accent': False,
                },
                {
                    'label': 'Reservas activas',
                    'value': reservas_activas,
                    'description': 'Cupos ya tomados sobre turnos todavía vigentes.',
                    'accent': True,
                },
                {
                    'label': 'Equipo interno',
                    'value': empleados_registrados,
                    'description': 'Empleados operativos cargados en el sistema.',
                    'accent': False,
                },
            ]

            ultimo_turno = (
                Turno.query
                .filter(Turno.cancelado.is_(False))
                .order_by(Turno.fecha_creacion.desc())
                .first()
            )
            if ultimo_turno:
                actividad_reciente.append(
                    f"Último turno cargado: {ultimo_turno.actividad.upper()} el {ultimo_turno.hora_inicio.strftime('%d/%m/%Y %H:%M')}"
                )

            ultimo_cliente = (
                Usuario.query
                .filter_by(tipo_usuario=TipoUsuario.CLIENTE)
                .order_by(Usuario.fecha_creacion.desc())
                .first()
            )
            if ultimo_cliente:
                actividad_reciente.append(
                    f"Último cliente registrado: {ultimo_cliente.nombre} {ultimo_cliente.apellido}"
                )

            actividad_reciente.append('Cuenta interna habilitada para gestión administrativa y operativa.')

        return render_template(
            'dashboard.html',
            turnos_reservados=turnos_reservados,
            deuda_total=deuda_total,
            actividad_reciente=actividad_reciente,
            dashboard_context=dashboard_context,
        )

    @app.before_request
    def _run_daily_automatic_suspension_audit():
        today_key = datetime.utcnow().date().isoformat()
        last_run = app.extensions.get('club360_last_daily_suspension_audit')
        if last_run == today_key:
            return

        from website.turnos.routes import procesar_suspensiones_automaticas_diarias

        procesar_suspensiones_automaticas_diarias()
        app.extensions['club360_last_daily_suspension_audit'] = today_key

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
        _drop_legacy_turno_tipo_clase_column()
        _repair_legacy_turno_foreign_keys()
        _drop_legacy_usuario_tipo_cliente_column()
        _ensure_usuario_recordatorio_column()
        _ensure_usuario_cancelaciones_credito_columns()
        _ensure_usuario_requiere_cambio_password_column()
        _ensure_usuario_reset_password_columns()
        _ensure_usuario_edad_columns()
        _ensure_reserva_qr_columns()
        _ensure_reserva_tipo_clase_column()
        _ensure_reserva_abono_column()
        _ensure_lista_espera_tipo_clase_column()
        _ensure_pago_tipo_clase_column()
        _backfill_reserva_qr_tokens()

    return app


def _drop_legacy_turno_tipo_clase_column():
    """Elimina `tipo_clase` de `turnos` en instalaciones donde quedó como columna legacy."""
    inspector = inspect(db.engine)
    if 'turnos' not in inspector.get_table_names():
        return

    columnas = {c['name'] for c in inspector.get_columns('turnos')}
    if 'tipo_clase' not in columnas:
        return

    try:
        db.session.execute(text("PRAGMA foreign_keys=OFF"))
        db.session.execute(text("ALTER TABLE turnos RENAME TO turnos_legacy"))
        db.session.execute(text("""
            CREATE TABLE turnos (
                id INTEGER NOT NULL PRIMARY KEY,
                actividad VARCHAR(20) NOT NULL,
                hora_inicio DATETIME NOT NULL,
                hora_fin DATETIME NOT NULL,
                capacidad_maxima INTEGER NOT NULL,
                cupos_disponibles INTEGER NOT NULL,
                usuario_id INTEGER,
                cancelado BOOLEAN,
                fecha_creacion DATETIME,
                FOREIGN KEY(usuario_id) REFERENCES usuarios (id)
            )
        """))
        db.session.execute(text("""
            INSERT INTO turnos (
                id,
                actividad,
                hora_inicio,
                hora_fin,
                capacidad_maxima,
                cupos_disponibles,
                usuario_id,
                cancelado,
                fecha_creacion
            )
            SELECT
                id,
                actividad,
                hora_inicio,
                hora_fin,
                capacidad_maxima,
                cupos_disponibles,
                usuario_id,
                cancelado,
                fecha_creacion
            FROM turnos_legacy
        """))
        db.session.execute(text("DROP TABLE turnos_legacy"))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    finally:
        db.session.execute(text("PRAGMA foreign_keys=ON"))


def _repair_legacy_turno_foreign_keys():
    """Repara FKs SQLite que hayan quedado apuntando a `turnos_legacy`."""
    if db.engine.dialect.name != 'sqlite':
        return

    inspector = inspect(db.engine)
    tablas = set(inspector.get_table_names())
    if 'turnos' not in tablas:
        return

    _rebuild_reservas_if_needed()
    _rebuild_lista_espera_if_needed()


def _rebuild_reservas_if_needed():
    foreign_keys = db.session.execute(text("PRAGMA foreign_key_list('reservas')")).mappings().all()
    if not any(fk['table'] == 'turnos_legacy' for fk in foreign_keys):
        return

    try:
        db.session.execute(text("PRAGMA foreign_keys=OFF"))
        db.session.execute(text("ALTER TABLE reservas RENAME TO reservas_legacy"))
        db.session.execute(text("""
            CREATE TABLE reservas (
                id INTEGER NOT NULL PRIMARY KEY,
                usuario_id INTEGER NOT NULL,
                turno_id INTEGER NOT NULL,
                fecha_reserva DATETIME NOT NULL,
                qr_token VARCHAR(120),
                recordatorio_enviado BOOLEAN NOT NULL DEFAULT 0,
                fecha_recordatorio DATETIME,
                asistencia_validada BOOLEAN NOT NULL DEFAULT 0,
                fecha_asistencia DATETIME,
                tipo_clase VARCHAR(20) NOT NULL DEFAULT 'no_abonada',
                abono_id INTEGER,
                CONSTRAINT uq_reserva_usuario_turno UNIQUE (usuario_id, turno_id),
                FOREIGN KEY(usuario_id) REFERENCES usuarios (id),
                FOREIGN KEY(turno_id) REFERENCES turnos (id),
                FOREIGN KEY(abono_id) REFERENCES abonos_clientes (id)
            )
        """))
        db.session.execute(text("""
            INSERT INTO reservas (
                id,
                usuario_id,
                turno_id,
                fecha_reserva,
                qr_token,
                recordatorio_enviado,
                fecha_recordatorio,
                asistencia_validada,
                fecha_asistencia,
                tipo_clase,
                abono_id
            )
            SELECT
                id,
                usuario_id,
                turno_id,
                fecha_reserva,
                qr_token,
                recordatorio_enviado,
                fecha_recordatorio,
                asistencia_validada,
                fecha_asistencia,
                tipo_clase,
                abono_id
            FROM reservas_legacy
        """))
        db.session.execute(text("DROP TABLE reservas_legacy"))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    finally:
        db.session.execute(text("PRAGMA foreign_keys=ON"))


def _rebuild_lista_espera_if_needed():
    foreign_keys = db.session.execute(text("PRAGMA foreign_key_list('lista_espera')")).mappings().all()
    if not any(fk['table'] == 'turnos_legacy' for fk in foreign_keys):
        return

    try:
        db.session.execute(text("PRAGMA foreign_keys=OFF"))
        db.session.execute(text("ALTER TABLE lista_espera RENAME TO lista_espera_legacy"))
        db.session.execute(text("""
            CREATE TABLE lista_espera (
                id INTEGER NOT NULL PRIMARY KEY,
                usuario_id INTEGER NOT NULL,
                turno_id INTEGER NOT NULL,
                tipo_lista VARCHAR(20) NOT NULL,
                tipo_clase VARCHAR(20) NOT NULL DEFAULT 'no_abonada',
                posicion INTEGER NOT NULL,
                fecha_registro DATETIME,
                FOREIGN KEY(usuario_id) REFERENCES usuarios (id),
                FOREIGN KEY(turno_id) REFERENCES turnos (id)
            )
        """))
        db.session.execute(text("""
            INSERT INTO lista_espera (
                id,
                usuario_id,
                turno_id,
                tipo_lista,
                tipo_clase,
                posicion,
                fecha_registro
            )
            SELECT
                id,
                usuario_id,
                turno_id,
                tipo_lista,
                tipo_clase,
                posicion,
                fecha_registro
            FROM lista_espera_legacy
        """))
        db.session.execute(text("DROP TABLE lista_espera_legacy"))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    finally:
        db.session.execute(text("PRAGMA foreign_keys=ON"))


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


def _ensure_usuario_edad_columns():
    inspector = inspect(db.engine)
    if 'usuarios' not in inspector.get_table_names():
        return

    columnas = {c['name'] for c in inspector.get_columns('usuarios')}
    updates = []
    if 'fecha_nacimiento' not in columnas:
        updates.append("ALTER TABLE usuarios ADD COLUMN fecha_nacimiento DATE")
    if 'autorizacion_menor' not in columnas:
        updates.append("ALTER TABLE usuarios ADD COLUMN autorizacion_menor BOOLEAN NOT NULL DEFAULT 0")

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


def _ensure_reserva_tipo_clase_column():
    inspector = inspect(db.engine)
    if 'reservas' not in inspector.get_table_names():
        return

    columnas = {c['name'] for c in inspector.get_columns('reservas')}
    if 'tipo_clase' not in columnas:
        db.session.execute(text("ALTER TABLE reservas ADD COLUMN tipo_clase VARCHAR(20) NOT NULL DEFAULT 'no_abonada'"))
        db.session.commit()


def _ensure_reserva_abono_column():
    inspector = inspect(db.engine)
    if 'reservas' not in inspector.get_table_names():
        return

    columnas = {c['name'] for c in inspector.get_columns('reservas')}
    if 'abono_id' not in columnas:
        db.session.execute(text("ALTER TABLE reservas ADD COLUMN abono_id INTEGER"))
        db.session.commit()

    columnas_turno = {c['name'] for c in inspector.get_columns('turnos')} if 'turnos' in inspector.get_table_names() else set()
    if 'tipo_clase' in columnas_turno:
        db.session.execute(text("""
            UPDATE reservas
            SET tipo_clase = (
                SELECT COALESCE(turnos.tipo_clase, 'no_abonada')
                FROM turnos
                WHERE turnos.id = reservas.turno_id
            )
            WHERE tipo_clase IS NULL OR tipo_clase = '' OR tipo_clase = 'no_abonada'
        """))
        db.session.commit()


def _ensure_lista_espera_tipo_clase_column():
    inspector = inspect(db.engine)
    if 'lista_espera' not in inspector.get_table_names():
        return

    columnas = {c['name'] for c in inspector.get_columns('lista_espera')}
    if 'tipo_clase' not in columnas:
        db.session.execute(text("ALTER TABLE lista_espera ADD COLUMN tipo_clase VARCHAR(20) NOT NULL DEFAULT 'no_abonada'"))
        db.session.commit()


def _backfill_reserva_qr_tokens():
    from website.models import Reserva

    reservas_sin_qr = Reserva.query.filter((Reserva.qr_token.is_(None)) | (Reserva.qr_token == '')).all()
    for reserva in reservas_sin_qr:
        reserva.qr_token = secrets.token_urlsafe(24)

    if reservas_sin_qr:
        db.session.commit()
