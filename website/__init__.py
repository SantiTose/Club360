import os
from flask import Flask, render_template, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_required, current_user
from flask_migrate import Migrate
from sqlalchemy import text, inspect, func
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
        from website.models import TipoUsuario, Turno, Reserva, Pago, Usuario, CreditoCliente, EstadoCredito

        turnos_reservados = 0
        actividad_reciente = []
        dashboard_context = {
            'mode': 'cliente',
            'eyebrow': 'Panel personal',
            'hero_title': f'Hola, {current_user.nombre}',
            'hero_text': 'Gestioná tus turnos con cobro automático al confirmar cada reserva.',
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
            hoy = datetime.utcnow().date()
            CreditoCliente.query.filter(
                CreditoCliente.usuario_id == current_user.id,
                CreditoCliente.estado == EstadoCredito.DISPONIBLE,
                CreditoCliente.fecha_vencimiento < hoy,
            ).update({'estado': EstadoCredito.VENCIDO}, synchronize_session=False)
            db.session.commit()

            turnos_reservados = Reserva.query.filter_by(usuario_id=current_user.id).count()

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
                    f"Último pago: ${ultimo_pago.monto:.2f}"
                )

            dashboard_context['stats'] = [
                {
                    'label': 'Turnos reservados',
                    'value': turnos_reservados,
                    'description': 'Reservas activas listas para asistir o gestionar.',
                    'accent': False,
                },
                {
                    'label': 'Cobro automático',
                    'value': 'Activo',
                    'description': 'Las reservas se cobran al confirmar con tarjeta de crédito.',
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
            reservas_activas = (
                Reserva.query
                .join(Turno, Reserva.turno_id == Turno.id)
                .filter(Turno.cancelado.is_(False))
                .filter(Turno.hora_inicio >= datetime.utcnow())
                .count()
            )

            dashboard_context['stats'] = [
                {
                    'label': 'Reservas activas',
                    'value': reservas_activas,
                    'description': 'Cupos ya tomados sobre turnos todavía vigentes.',
                    'accent': True,
                },
                {
                    'label': 'Clientes registrados',
                    'value': clientes_registrados,
                    'description': 'Base total de clientes para operar desde el panel.',
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
            actividad_reciente=actividad_reciente,
            dashboard_context=dashboard_context,
        )

    @app.route('/mis-creditos')
    @login_required
    def mis_creditos():
        from website.models import TipoUsuario, CreditoCliente, EstadoCredito

        if current_user.tipo_usuario != TipoUsuario.CLIENTE:
            return redirect(url_for('dashboard'))

        hoy = datetime.utcnow().date()
        CreditoCliente.query.filter(
            CreditoCliente.usuario_id == current_user.id,
            CreditoCliente.estado == EstadoCredito.DISPONIBLE,
            CreditoCliente.fecha_vencimiento < hoy,
        ).update({'estado': EstadoCredito.VENCIDO}, synchronize_session=False)
        db.session.commit()

        creditos = (
            db.session.query(
                CreditoCliente.actividad,
                func.count(CreditoCliente.id).label('cantidad'),
                func.coalesce(func.sum(CreditoCliente.monto), 0).label('monto_total'),
                func.min(CreditoCliente.fecha_vencimiento).label('vence_primero'),
            )
            .filter(
                CreditoCliente.usuario_id == current_user.id,
                CreditoCliente.estado == EstadoCredito.DISPONIBLE,
            )
            .filter(CreditoCliente.fecha_vencimiento >= hoy)
            .group_by(CreditoCliente.actividad)
            .order_by(CreditoCliente.actividad.asc())
            .all()
        )

        return render_template('mis_creditos.html', creditos=creditos)

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
    from website.suspensiones import suspensiones_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(turnos_bp)
    app.register_blueprint(suspensiones_bp)

    # Create tables
    with app.app_context():
        db.create_all()
        _drop_legacy_turno_tipo_clase_column()
        _repair_legacy_turno_foreign_keys()
        _ensure_turno_motivo_cancelacion_column()
        _drop_legacy_usuario_tipo_cliente_column()
        _ensure_usuario_recordatorio_column()
        _ensure_usuario_cancelaciones_credito_columns()
        _ensure_abono_descuento_column()
        _ensure_usuario_requiere_cambio_password_column()
        _ensure_usuario_reset_password_columns()
        _ensure_usuario_edad_columns()
        _ensure_usuario_tarjeta_columns()
        _drop_usuario_dni_unique_constraint()
        _ensure_reserva_qr_columns()
        _ensure_reserva_tipo_clase_column()
        _ensure_reserva_abono_column()
        _ensure_lista_espera_tipo_clase_column()
        _ensure_pago_tipo_clase_column()
        _ensure_creditos_clientes_table()
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


def _ensure_turno_motivo_cancelacion_column():
    inspector = inspect(db.engine)
    if 'turnos' not in inspector.get_table_names():
        return

    columnas = {c['name'] for c in inspector.get_columns('turnos')}
    if 'motivo_cancelacion' not in columnas:
        db.session.execute(text("ALTER TABLE turnos ADD COLUMN motivo_cancelacion VARCHAR(255)"))
        db.session.commit()


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
    if 'cupon_abono_mes' not in columnas:
        updates.append("ALTER TABLE usuarios ADD COLUMN cupon_abono_mes VARCHAR(7)")
    if 'cupon_abono_actividad' not in columnas:
        updates.append("ALTER TABLE usuarios ADD COLUMN cupon_abono_actividad VARCHAR(20)")
    if 'cupon_abono_dia_semana' not in columnas:
        updates.append("ALTER TABLE usuarios ADD COLUMN cupon_abono_dia_semana INTEGER")
    if 'cupon_abono_hora_inicio' not in columnas:
        updates.append("ALTER TABLE usuarios ADD COLUMN cupon_abono_hora_inicio INTEGER")
    if 'cupon_abono_porcentaje' not in columnas:
        updates.append("ALTER TABLE usuarios ADD COLUMN cupon_abono_porcentaje FLOAT NOT NULL DEFAULT 0")

    for sql in updates:
        db.session.execute(text(sql))

    if updates:
        db.session.commit()


def _ensure_abono_descuento_column():
    inspector = inspect(db.engine)
    if 'abonos_clientes' not in inspector.get_table_names():
        return

    columnas = {c['name'] for c in inspector.get_columns('abonos_clientes')}
    if 'descuento_porcentaje' not in columnas:
        db.session.execute(text("ALTER TABLE abonos_clientes ADD COLUMN descuento_porcentaje FLOAT NOT NULL DEFAULT 0"))
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


def _ensure_usuario_tarjeta_columns():
    inspector = inspect(db.engine)
    if 'usuarios' not in inspector.get_table_names():
        return

    columnas = {c['name'] for c in inspector.get_columns('usuarios')}
    updates = []
    if 'tarjeta_credito_marca' not in columnas:
        updates.append("ALTER TABLE usuarios ADD COLUMN tarjeta_credito_marca VARCHAR(20)")
    if 'tarjeta_credito_ultimos4' not in columnas:
        updates.append("ALTER TABLE usuarios ADD COLUMN tarjeta_credito_ultimos4 VARCHAR(4)")
    if 'tarjeta_credito_vencimiento' not in columnas:
        updates.append("ALTER TABLE usuarios ADD COLUMN tarjeta_credito_vencimiento DATE")
    agregar_saldo = 'tarjeta_credito_saldo' not in columnas
    if agregar_saldo:
        updates.append("ALTER TABLE usuarios ADD COLUMN tarjeta_credito_saldo FLOAT NOT NULL DEFAULT 100000")

    for sql in updates:
        db.session.execute(text(sql))

    if updates:
        db.session.commit()
        if agregar_saldo:
            db.session.execute(text("UPDATE usuarios SET tarjeta_credito_saldo = 100000 WHERE tipo_usuario = 'cliente'"))
            db.session.commit()


def _drop_usuario_dni_unique_constraint():
    inspector = inspect(db.engine)
    if 'usuarios' not in inspector.get_table_names():
        return

    unique_dni_index = False
    for index in db.session.execute(text("PRAGMA index_list('usuarios')")).mappings():
        if not index['unique']:
            continue
        columns = [
            row['name']
            for row in db.session.execute(text(f"PRAGMA index_info('{index['name']}')")).mappings()
        ]
        if columns == ['dni']:
            unique_dni_index = True
            break

    if not unique_dni_index:
        return

    columns = [
        'id',
        'nombre',
        'apellido',
        'dni',
        'fecha_nacimiento',
        'autorizacion_menor',
        'tarjeta_credito_marca',
        'tarjeta_credito_ultimos4',
        'tarjeta_credito_vencimiento',
        'tarjeta_credito_saldo',
        'email',
        'password',
        'tipo_usuario',
        'estado',
        'credito_abonado',
        'cancelaciones_abonado',
        'beneficio_abonado_activo',
        'cupon_abono_mes',
        'cupon_abono_actividad',
        'cupon_abono_dia_semana',
        'cupon_abono_hora_inicio',
        'cupon_abono_porcentaje',
        'requiere_cambio_password',
        'reset_password_token',
        'reset_password_expira',
        'ultimo_recordatorio_mora',
        'fecha_creacion',
        'fecha_actualizacion',
    ]
    column_sql = ', '.join(columns)

    try:
        db.session.execute(text("PRAGMA foreign_keys=OFF"))
        db.session.execute(text("""
            CREATE TABLE usuarios_new (
                id INTEGER NOT NULL PRIMARY KEY,
                nombre VARCHAR(100) NOT NULL,
                apellido VARCHAR(100) NOT NULL,
                dni VARCHAR(20) NOT NULL,
                fecha_nacimiento DATE,
                autorizacion_menor BOOLEAN NOT NULL,
                tarjeta_credito_marca VARCHAR(20),
                tarjeta_credito_ultimos4 VARCHAR(4),
                tarjeta_credito_vencimiento DATE,
                tarjeta_credito_saldo FLOAT NOT NULL DEFAULT 100000,
                email VARCHAR(120) NOT NULL UNIQUE,
                password VARCHAR(255) NOT NULL,
                tipo_usuario VARCHAR(20) NOT NULL,
                estado VARCHAR(20) NOT NULL,
                credito_abonado FLOAT NOT NULL DEFAULT 0,
                cancelaciones_abonado INTEGER NOT NULL DEFAULT 0,
                beneficio_abonado_activo BOOLEAN NOT NULL DEFAULT 1,
                cupon_abono_mes VARCHAR(7),
                cupon_abono_actividad VARCHAR(20),
                cupon_abono_dia_semana INTEGER,
                cupon_abono_hora_inicio INTEGER,
                cupon_abono_porcentaje FLOAT NOT NULL DEFAULT 0,
                requiere_cambio_password BOOLEAN NOT NULL DEFAULT 0,
                reset_password_token VARCHAR(120) UNIQUE,
                reset_password_expira DATETIME,
                ultimo_recordatorio_mora DATETIME,
                fecha_creacion DATETIME,
                fecha_actualizacion DATETIME
            )
        """))
        db.session.execute(text(f"""
            INSERT INTO usuarios_new ({column_sql})
            SELECT {column_sql}
            FROM usuarios
        """))
        db.session.execute(text("DROP TABLE usuarios"))
        db.session.execute(text("ALTER TABLE usuarios_new RENAME TO usuarios"))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    finally:
        db.session.execute(text("PRAGMA foreign_keys=ON"))


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


def _ensure_creditos_clientes_table():
    inspector = inspect(db.engine)
    if 'creditos_clientes' in inspector.get_table_names():
        return

    db.session.execute(text("""
        CREATE TABLE creditos_clientes (
            id INTEGER NOT NULL PRIMARY KEY,
            usuario_id INTEGER NOT NULL,
            actividad VARCHAR(20) NOT NULL,
            monto FLOAT NOT NULL,
            estado VARCHAR(20) NOT NULL DEFAULT 'disponible',
            fecha_vencimiento DATE NOT NULL,
            reserva_origen_id INTEGER,
            reserva_uso_id INTEGER,
            fecha_creacion DATETIME NOT NULL,
            fecha_uso DATETIME,
            FOREIGN KEY(usuario_id) REFERENCES usuarios (id),
            FOREIGN KEY(reserva_origen_id) REFERENCES reservas (id),
            FOREIGN KEY(reserva_uso_id) REFERENCES reservas (id)
        )
    """))
    db.session.commit()


def _clear_pending_client_debts():
    """Legacy: se conserva para instalaciones antiguas, pero ya no se ejecuta al iniciar."""
    inspector = inspect(db.engine)
    if 'pagos' not in inspector.get_table_names():
        return

    db.session.execute(text(
        """
        UPDATE pagos
        SET estado = 'completado',
            monto = 0,
            metodo_pago = 'tarjeta_credito',
            referencia_transaccion = COALESCE(referencia_transaccion, 'deuda-removida')
        WHERE estado = 'pendiente'
        """
    ))
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
