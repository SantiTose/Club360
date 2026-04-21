from flask import render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from website.auth import auth_bp
from website import db
from website.models import Usuario, TipoUsuario, EstadoUsuario
from website.services import enviar_email_simulado
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, date
import os
import secrets
import re


def _es_empleado_o_admin(user):
    return user.tipo_usuario in {TipoUsuario.EMPLEADO, TipoUsuario.ADMINISTRADOR}


def _es_admin(user):
    return user.tipo_usuario == TipoUsuario.ADMINISTRADOR


def _generar_password_temporal():
    return secrets.token_urlsafe(8)


def _generar_token_reset():
    return secrets.token_urlsafe(32)


def _parsear_fecha_nacimiento(fecha_raw):
    try:
        return datetime.strptime(fecha_raw, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _edad(fecha_nacimiento):
    hoy = date.today()
    return hoy.year - fecha_nacimiento.year - ((hoy.month, hoy.day) < (fecha_nacimiento.month, fecha_nacimiento.day))


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Registrar nuevo usuario."""
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        apellido = request.form.get('apellido', '').strip()
        dni = request.form.get('dni', '').strip()
        fecha_nacimiento_raw = request.form.get('fecha_nacimiento', '').strip()
        autorizacion_menor = request.form.get('autorizacion_menor') == 'on'
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')
        
        # Diccionario de errores por campo
        field_errors = {}
        
        # Validaciones
        if not nombre or len(nombre) < 2:
            field_errors['nombre'] = 'El nombre debe tener al menos 2 caracteres'
        
        if not apellido or len(apellido) < 2:
            field_errors['apellido'] = 'El apellido debe tener al menos 2 caracteres'
        
        if not dni or not re.match(r'^\d{8}$', dni):
            field_errors['dni'] = 'El DNI debe tener 8 dígitos'

        fecha_nacimiento = _parsear_fecha_nacimiento(fecha_nacimiento_raw)
        if not fecha_nacimiento:
            field_errors['fecha_nacimiento'] = 'Debes ingresar una fecha de nacimiento válida'
        else:
            if _edad(fecha_nacimiento) < 18 and not autorizacion_menor:
                field_errors['autorizacion_menor'] = 'Si eres menor de 18, debes registrar autorización'
        
        if not email or not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
            field_errors['email'] = 'El email no es válido'
        
        if len(password) < 6:
            field_errors['password'] = 'La contraseña debe tener al menos 6 caracteres'
        
        if password != password_confirm:
            field_errors['password_confirm'] = 'Las contraseñas no coinciden'
        
        # Verificar duplicados
        if not field_errors.get('email') and Usuario.query.filter_by(email=email).first():
            field_errors['email'] = 'El email ya está registrado'
        
        if not field_errors.get('dni') and Usuario.query.filter_by(dni=dni).first():
            field_errors['dni'] = 'El DNI ya está registrado'
        
        # Si hay errores, devolver el formulario con los datos
        if field_errors:
            return render_template('auth/register.html', 
                                 field_errors=field_errors,
                                 form_data={
                                     'nombre': nombre,
                                     'apellido': apellido,
                                     'dni': dni,
                                     'fecha_nacimiento': fecha_nacimiento_raw,
                                     'autorizacion_menor': autorizacion_menor,
                                     'email': email
                                 })
        
        try:
            nuevo_usuario = Usuario(
                nombre=nombre,
                apellido=apellido,
                dni=dni,
                fecha_nacimiento=fecha_nacimiento,
                autorizacion_menor=autorizacion_menor,
                email=email,
                password=generate_password_hash(password),
                tipo_usuario=TipoUsuario.CLIENTE,
                estado=EstadoUsuario.ACTIVO
            )
            
            db.session.add(nuevo_usuario)
            db.session.commit()
            
            flash('✅ Usuario registrado exitosamente. Por favor, inicia sesión.', 'success')
            return redirect(url_for('auth.login'))
        
        except Exception as e:
            db.session.rollback()
            flash('❌ Error al registrar usuario. Por favor, intenta de nuevo.', 'error')
            return render_template('auth/register.html', 
                                 form_data={
                                     'nombre': nombre,
                                     'apellido': apellido,
                                     'dni': dni,
                                     'fecha_nacimiento': fecha_nacimiento_raw,
                                     'autorizacion_menor': autorizacion_menor,
                                     'email': email
                                 })
    
    return render_template('auth/register.html', field_errors={}, form_data={})


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Iniciar sesión."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember')
        
        field_errors = {}
        
        if not email:
            field_errors['email'] = 'Por favor, ingresa tu email'
        
        if not password:
            field_errors['password'] = 'Por favor, ingresa tu contraseña'
        
        if field_errors:
            return render_template('auth/login.html', 
                                 field_errors=field_errors,
                                 form_data={'email': email})
        
        usuario = Usuario.query.filter_by(email=email).first()
        
        if usuario and check_password_hash(usuario.password, password):
            login_user(usuario, remember=bool(remember))
            if usuario.requiere_cambio_password:
                flash('Debes cambiar tu contraseña temporal para continuar', 'warning')
                return redirect(url_for('auth.cambiar_password_inicial'))
            flash(f'✅ ¡Bienvenido {usuario.nombre}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            field_errors['email'] = 'Email o contraseña incorrectos'
            return render_template('auth/login.html', 
                                 field_errors=field_errors,
                                 form_data={'email': email})
    
    return render_template('auth/login.html', field_errors={}, form_data={})


@auth_bp.route('/logout')
@login_required
def logout():
    """Cerrar sesión."""
    logout_user()
    flash('✅ Sesión cerrada exitosamente', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    """Restablecer contraseña."""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        usuario = Usuario.query.filter_by(email=email).first()
        
        if usuario:
            token = _generar_token_reset()
            usuario.reset_password_token = token
            usuario.reset_password_expira = datetime.utcnow() + timedelta(hours=1)
            db.session.commit()

            enlace = url_for('auth.reset_password_token', token=token, _external=True)
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
            asunto = 'Recuperación de contraseña - Club 360'
            cuerpo = (
                f"Hola {usuario.nombre},\n\n"
                "Recibimos una solicitud para restablecer tu contraseña.\n"
                f"Usa este enlace (válido por 1 hora): {enlace}\n\n"
                "Si no solicitaste este cambio, puedes ignorar este mensaje."
            )
            enviar_email_simulado(base_dir, usuario.email, asunto, cuerpo)

        # Respuesta neutra para no revelar si el email existe o no.
        flash('Si el email está registrado, te enviamos un enlace de recuperación.', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/reset_password.html')


@auth_bp.route('/crear-usuario', methods=['GET', 'POST'])
@login_required
def crear_usuario():
    """Crear cuentas para clientes/empleados (empleados y administradores)."""
    if not _es_empleado_o_admin(current_user):
        flash('No tienes permisos para crear usuarios', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        apellido = request.form.get('apellido', '').strip()
        dni = request.form.get('dni', '').strip()
        fecha_nacimiento_raw = request.form.get('fecha_nacimiento', '').strip()
        autorizacion_menor = request.form.get('autorizacion_menor') == 'on'
        email = request.form.get('email', '').strip().lower()
        tipo_usuario = request.form.get('tipo_usuario', TipoUsuario.CLIENTE)

        field_errors = {}
        if not nombre or len(nombre) < 2:
            field_errors['nombre'] = 'El nombre debe tener al menos 2 caracteres'
        if not apellido or len(apellido) < 2:
            field_errors['apellido'] = 'El apellido debe tener al menos 2 caracteres'
        if not dni or not re.match(r'^\d{8}$', dni):
            field_errors['dni'] = 'El DNI debe tener 8 dígitos'
        fecha_nacimiento = _parsear_fecha_nacimiento(fecha_nacimiento_raw)
        if not fecha_nacimiento:
            field_errors['fecha_nacimiento'] = 'Debes ingresar una fecha de nacimiento válida'
        if not email or not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
            field_errors['email'] = 'El email no es válido'

        tipos_permitidos = {TipoUsuario.CLIENTE}
        if _es_admin(current_user):
            tipos_permitidos.update({TipoUsuario.EMPLEADO, TipoUsuario.ADMINISTRADOR})
        if tipo_usuario not in tipos_permitidos:
            field_errors['tipo_usuario'] = 'No puedes crear este tipo de usuario'
        if tipo_usuario == TipoUsuario.CLIENTE and fecha_nacimiento and _edad(fecha_nacimiento) < 18 and not autorizacion_menor:
            field_errors['autorizacion_menor'] = 'Para clientes menores de 18 debes registrar autorización'

        if Usuario.query.filter_by(email=email).first():
            field_errors['email'] = 'El email ya está registrado'
        if Usuario.query.filter_by(dni=dni).first():
            field_errors['dni'] = 'El DNI ya está registrado'

        if field_errors:
            return render_template(
                'auth/crear_usuario.html',
                field_errors=field_errors,
                form_data={
                    'nombre': nombre,
                    'apellido': apellido,
                    'dni': dni,
                    'fecha_nacimiento': fecha_nacimiento_raw,
                    'autorizacion_menor': autorizacion_menor,
                    'email': email,
                    'tipo_usuario': tipo_usuario,
                },
                puede_crear_admin=current_user.tipo_usuario == TipoUsuario.ADMINISTRADOR,
                puede_crear_empleado=_es_admin(current_user),
            )

        password_temporal = _generar_password_temporal()
        nuevo_usuario = Usuario(
            nombre=nombre,
            apellido=apellido,
            dni=dni,
            fecha_nacimiento=fecha_nacimiento,
            autorizacion_menor=autorizacion_menor,
            email=email,
            password=generate_password_hash(password_temporal),
            tipo_usuario=tipo_usuario,
            estado=EstadoUsuario.ACTIVO,
            requiere_cambio_password=True,
        )
        db.session.add(nuevo_usuario)
        db.session.commit()

        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        asunto = 'Alta de cuenta Club 360 - contraseña temporal'
        cuerpo = (
            f"Hola {nombre},\n\n"
            "Tu cuenta fue creada por el personal de Club 360.\n"
            f"Email de acceso: {email}\n"
            f"Contraseña temporal: {password_temporal}\n\n"
            "Al iniciar sesión deberás cambiar esta contraseña de forma obligatoria."
        )
        enviar_email_simulado(base_dir, email, asunto, cuerpo)

        flash('Usuario creado exitosamente. Se envió contraseña temporal por email.', 'success')
        return redirect(url_for('dashboard'))

    return render_template(
        'auth/crear_usuario.html',
        field_errors={},
        form_data={},
        puede_crear_admin=current_user.tipo_usuario == TipoUsuario.ADMINISTRADOR,
        puede_crear_empleado=_es_admin(current_user),
    )


@auth_bp.route('/gestionar-empleados', methods=['GET'])
@login_required
def gestionar_empleados():
    if not _es_admin(current_user):
        flash('No tienes permisos para gestionar empleados', 'error')
        return redirect(url_for('index'))

    empleados = (
        Usuario.query
        .filter(Usuario.tipo_usuario.in_([TipoUsuario.EMPLEADO, TipoUsuario.ADMINISTRADOR]))
        .order_by(Usuario.tipo_usuario.desc(), Usuario.apellido.asc(), Usuario.nombre.asc())
        .all()
    )
    return render_template('auth/gestionar_empleados.html', empleados=empleados)


@auth_bp.route('/ascender-empleado/<int:usuario_id>', methods=['POST'])
@login_required
def ascender_empleado(usuario_id):
    if not _es_admin(current_user):
        flash('No tienes permisos para ascender empleados', 'error')
        return redirect(url_for('index'))

    usuario = Usuario.query.get_or_404(usuario_id)
    if usuario.tipo_usuario != TipoUsuario.EMPLEADO:
        flash('Solo se pueden ascender cuentas de empleado', 'error')
        return redirect(url_for('auth.gestionar_empleados'))

    usuario.tipo_usuario = TipoUsuario.ADMINISTRADOR
    db.session.commit()
    flash(f'{usuario.nombre} {usuario.apellido} fue ascendido a administrador', 'success')
    return redirect(url_for('auth.gestionar_empleados'))


@auth_bp.route('/cambiar-password-inicial', methods=['GET', 'POST'])
@login_required
def cambiar_password_inicial():
    if not current_user.requiere_cambio_password:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')
        field_errors = {}

        if len(password) < 6:
            field_errors['password'] = 'La contraseña debe tener al menos 6 caracteres'
        if password != password_confirm:
            field_errors['password_confirm'] = 'Las contraseñas no coinciden'

        if field_errors:
            return render_template('auth/cambiar_password_inicial.html', field_errors=field_errors)

        current_user.password = generate_password_hash(password)
        current_user.requiere_cambio_password = False
        db.session.commit()
        flash('Contraseña actualizada correctamente', 'success')
        return redirect(url_for('dashboard'))

    return render_template('auth/cambiar_password_inicial.html', field_errors={})


@auth_bp.route('/reset-password/<string:token>', methods=['GET', 'POST'])
def reset_password_token(token):
    usuario = (
        Usuario.query
        .filter_by(reset_password_token=token)
        .filter(Usuario.reset_password_expira.isnot(None))
        .first()
    )

    if not usuario or not usuario.reset_password_expira or usuario.reset_password_expira < datetime.utcnow():
        flash('El enlace de recuperación es inválido o expiró', 'error')
        return redirect(url_for('auth.reset_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')
        field_errors = {}

        if len(password) < 6:
            field_errors['password'] = 'La contraseña debe tener al menos 6 caracteres'
        if password != password_confirm:
            field_errors['password_confirm'] = 'Las contraseñas no coinciden'

        if field_errors:
            return render_template('auth/reset_password_token.html', field_errors=field_errors)

        usuario.password = generate_password_hash(password)
        usuario.reset_password_token = None
        usuario.reset_password_expira = None
        usuario.requiere_cambio_password = False
        db.session.commit()
        flash('Contraseña restablecida correctamente. Ya puedes iniciar sesión.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password_token.html', field_errors={})
