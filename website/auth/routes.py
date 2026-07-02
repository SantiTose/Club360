from flask import current_app, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from website.auth import auth_bp
from website import db
from website.models import Usuario, TipoUsuario, EstadoUsuario, TarjetaCredito
from website.services import EmailDeliveryError, enviar_email_simulado
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, date
import calendar
import hashlib
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


def _cancelar_reservas_por_eliminacion_cuenta(cliente):
    from website.models import Reserva, Turno, TipoClase
    from website.turnos.routes import _notificar_siguiente_lista_espera

    reservas = (
        Reserva.query
        .filter_by(usuario_id=cliente.id)
        .all()
    )
    canceladas = 0
    for reserva in reservas:
        turno = reserva.turno
        if turno and not turno.cancelado and turno.hora_fin >= datetime.utcnow():
            tipo_cupo_liberado = TipoClase.ABONADA if reserva.tipo_clase == TipoClase.ABONADA or reserva.abono_id else TipoClase.NO_ABONADA
            turno.cupos_disponibles = min(turno.capacidad_maxima, turno.cupos_disponibles + 1)
            _notificar_siguiente_lista_espera(turno, tipo_cupo_liberado)
            canceladas += 1
        db.session.delete(reserva)
    return canceladas


def _eliminar_cuenta_cliente(cliente):
    from website.models import AbonoCliente, CreditoCliente, ListaEspera, Pago, Suspension, TarjetaCredito, Turno

    reservas_canceladas = _cancelar_reservas_por_eliminacion_cuenta(cliente)

    Turno.query.filter_by(usuario_id=cliente.id).update({'usuario_id': None}, synchronize_session=False)
    ListaEspera.query.filter_by(usuario_id=cliente.id).delete(synchronize_session=False)
    Suspension.query.filter_by(usuario_id=cliente.id).delete(synchronize_session=False)
    CreditoCliente.query.filter_by(usuario_id=cliente.id).delete(synchronize_session=False)
    TarjetaCredito.query.filter_by(usuario_id=cliente.id).delete(synchronize_session=False)
    Pago.query.filter_by(usuario_id=cliente.id).delete(synchronize_session=False)
    AbonoCliente.query.filter_by(usuario_id=cliente.id).delete(synchronize_session=False)

    db.session.delete(cliente)
    return reservas_canceladas


def _validar_password_nueva(password, password_confirm):
    field_errors = {}
    if len(password) < 6:
        field_errors['password'] = 'La contraseña debe tener al menos 6 caracteres'
    if password != password_confirm:
        field_errors['password_confirm'] = 'Las contraseñas no coinciden'
    return field_errors


def _validar_password_distinta_a_actual(usuario, password, field_errors):
    if password and check_password_hash(usuario.password, password):
        field_errors['password'] = 'La nueva contraseña no puede ser igual a la actual'
    return field_errors


def _parsear_fecha_nacimiento(fecha_raw):
    fecha = (fecha_raw or '').strip()
    for formato in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(fecha, formato).date()
        except (TypeError, ValueError):
            continue
    return None


def _edad(fecha_nacimiento):
    hoy = date.today()
    return hoy.year - fecha_nacimiento.year - ((hoy.month, hoy.day) < (fecha_nacimiento.month, fecha_nacimiento.day))


def _validar_nombre_o_apellido(valor, etiqueta):
    if len(valor) < 2 or len(valor) > 20:
        return f'El {etiqueta} debe tener entre 2 y 20 caracteres'
    return None


def _tarjeta_es_valida(numero):
    total = 0
    invertir = numero[::-1]
    for index, caracter in enumerate(invertir):
        digito = int(caracter)
        if index % 2 == 1:
            digito *= 2
            if digito > 9:
                digito -= 9
        total += digito
    return total % 10 == 0


def _marca_tarjeta(numero):
    if numero.startswith('4'):
        return 'Visa'
    if numero[:2] in {'51', '52', '53', '54', '55'} or 2221 <= int(numero[:4]) <= 2720:
        return 'Mastercard'
    if numero[:2] in {'34', '37'}:
        return 'American Express'
    return 'Tarjeta'


def _vencimiento_tarjeta_es_valido(vencimiento_raw):
    return _parsear_vencimiento_tarjeta(vencimiento_raw) is not None


def _parsear_vencimiento_tarjeta(vencimiento_raw):
    vencimiento = (vencimiento_raw or '').strip()

    if re.match(r'^\d{4}-\d{2}$', vencimiento):
        anio_raw, mes_raw = vencimiento.split('-')
        anio = int(anio_raw)
        mes = int(mes_raw)
    else:
        match = re.match(r'^(\d{1,2})\s*/\s*(\d{2}|\d{4})$', vencimiento)
        if not match:
            return None
        mes = int(match.group(1))
        anio = int(match.group(2))
        if anio < 100:
            anio += 2000

    if mes < 1 or mes > 12:
        return None
    if anio > 2032:
        return None

    hoy = date.today()
    if (anio, mes) < (hoy.year, hoy.month):
        return None

    ultimo_dia = calendar.monthrange(anio, mes)[1]
    return date(anio, mes, ultimo_dia)


def _normalizar_tarjeta_credito(tarjeta_raw):
    numero = re.sub(r'\D', '', tarjeta_raw or '')
    if not numero:
        return None, None, 'Debes ingresar una tarjeta de crédito'
    if len(numero) != 16:
        return None, None, 'La tarjeta debe tener 16 dígitos'
    if len(set(numero)) == 1:
        return None, None, 'El numero de tarjeta no es valido'
    if not _tarjeta_es_valida(numero):
        return None, None, 'El número de tarjeta no es válido'
    return _marca_tarjeta(numero), numero[-4:], None


def _hash_numero_tarjeta(numero):
    return hashlib.sha256(numero.encode('utf-8')).hexdigest()


def _normalizar_datos_tarjeta_credito(tarjeta_raw, vencimiento_raw, cvv_raw):
    numero = re.sub(r'\D', '', tarjeta_raw or '')
    cvv = (cvv_raw or '').strip()

    if not numero:
        return None, None, None, 'Debes ingresar una tarjeta de credito'
    if len(numero) != 16:
        return None, None, None, 'La tarjeta debe tener 16 dígitos'
    if len(set(numero)) == 1 or not _tarjeta_es_valida(numero):
        return None, None, None, 'El numero de tarjeta no es valido'
    if not _vencimiento_tarjeta_es_valido(vencimiento_raw):
        return None, None, None, 'La fecha de vencimiento no es valida'
    if not re.match(r'^\d{3}$', cvv):
        return None, None, None, 'El codigo de seguridad debe tener 3 digitos'

    return _marca_tarjeta(numero), numero[-4:], _hash_numero_tarjeta(numero), None


def _tarjeta_duplicada(usuario_id, numero_hash, tarjeta_id_excluida=None):
    if not numero_hash:
        return False

    query = TarjetaCredito.query.filter_by(usuario_id=usuario_id, numero_hash=numero_hash)
    if tarjeta_id_excluida:
        query = query.filter(TarjetaCredito.id != tarjeta_id_excluida)
    return query.first() is not None


def _tarjetas_del_cliente(usuario):
    return (
        TarjetaCredito.query
        .filter_by(usuario_id=usuario.id)
        .order_by(TarjetaCredito.es_principal.desc(), TarjetaCredito.fecha_creacion.asc(), TarjetaCredito.id.asc())
        .all()
    )


def _cliente_tiene_tarjeta(usuario):
    if usuario.tipo_usuario != TipoUsuario.CLIENTE:
        return True

    tiene_tarjeta = TarjetaCredito.query.filter_by(usuario_id=usuario.id).first() is not None
    if tiene_tarjeta:
        return True

    return bool(
        usuario.tarjeta_credito_marca
        and usuario.tarjeta_credito_ultimos4
        and usuario.tarjeta_credito_vencimiento
    )


def _sincronizar_tarjeta_principal(usuario):
    principal = (
        TarjetaCredito.query
        .filter_by(usuario_id=usuario.id, es_principal=True)
        .order_by(TarjetaCredito.fecha_creacion.asc(), TarjetaCredito.id.asc())
        .first()
    )
    if not principal:
        principal = (
            TarjetaCredito.query
            .filter_by(usuario_id=usuario.id)
            .order_by(TarjetaCredito.fecha_creacion.asc(), TarjetaCredito.id.asc())
            .first()
        )

    if not principal:
        usuario.tarjeta_credito_marca = None
        usuario.tarjeta_credito_ultimos4 = None
        usuario.tarjeta_credito_vencimiento = None
        return

    TarjetaCredito.query.filter_by(usuario_id=usuario.id).update({'es_principal': False})
    principal.es_principal = True
    usuario.tarjeta_credito_marca = principal.marca
    usuario.tarjeta_credito_ultimos4 = principal.ultimos4
    usuario.tarjeta_credito_vencimiento = principal.vencimiento
    usuario.tarjeta_credito_saldo = principal.saldo


def _asegurar_tarjeta_legacy(usuario):
    if _tarjetas_del_cliente(usuario):
        return

    if not usuario.tarjeta_credito_marca or not usuario.tarjeta_credito_ultimos4 or not usuario.tarjeta_credito_vencimiento:
        return

    db.session.add(TarjetaCredito(
        usuario_id=usuario.id,
        marca=usuario.tarjeta_credito_marca,
        ultimos4=usuario.tarjeta_credito_ultimos4,
        vencimiento=usuario.tarjeta_credito_vencimiento,
        saldo=usuario.tarjeta_credito_saldo or 100000.0,
        es_principal=True,
    ))
    db.session.commit()


def _render_editar_perfil(field_errors=None, form_data=None):
    fecha_formateada = current_user.fecha_nacimiento.strftime('%d/%m/%Y') if current_user.fecha_nacimiento else ''
    tarjetas = _tarjetas_del_cliente(current_user)
    return render_template(
        'auth/editar_perfil.html',
        field_errors=field_errors or {},
        form_data=form_data or {
            'nombre': current_user.nombre,
            'apellido': current_user.apellido,
            'email': current_user.email,
            'fecha_nacimiento': fecha_formateada,
        },
        tarjetas=tarjetas,
        requiere_tarjeta=not tarjetas,
    )


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Registrar nuevo usuario."""
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        apellido = request.form.get('apellido', '').strip()
        dni = request.form.get('dni', '').strip()
        fecha_nacimiento_raw = request.form.get('fecha_nacimiento', '').strip()
        tarjeta_credito_raw = request.form.get('tarjeta_credito', '').strip()
        tarjeta_vencimiento_raw = request.form.get('tarjeta_vencimiento', '').strip()
        tarjeta_cvv_raw = request.form.get('tarjeta_cvv', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        # Diccionario de errores por campo
        field_errors = {}
        
        # Validaciones
        error_nombre = _validar_nombre_o_apellido(nombre, 'nombre')
        if error_nombre:
            field_errors['nombre'] = error_nombre

        error_apellido = _validar_nombre_o_apellido(apellido, 'apellido')
        if error_apellido:
            field_errors['apellido'] = error_apellido
        
        if not dni or not re.match(r'^\d{8}$', dni):
            field_errors['dni'] = 'El número de documento debe contener 8 caracteres numéricos.'

        fecha_nacimiento = _parsear_fecha_nacimiento(fecha_nacimiento_raw)
        if not fecha_nacimiento:
            field_errors['fecha_nacimiento'] = 'Debes ingresar una fecha de nacimiento válida'
        else:
            if _edad(fecha_nacimiento) < 18:
                field_errors['fecha_nacimiento'] = 'Solo podran registrarse personas de 18 años o mas'

        tarjeta_marca, tarjeta_ultimos4, tarjeta_numero_hash, error_tarjeta = _normalizar_datos_tarjeta_credito(
            tarjeta_credito_raw,
            tarjeta_vencimiento_raw,
            tarjeta_cvv_raw,
        )
        if error_tarjeta:
            field_errors['tarjeta_credito'] = error_tarjeta
        tarjeta_vencimiento = _parsear_vencimiento_tarjeta(tarjeta_vencimiento_raw) if not error_tarjeta else None
        
        if not email or not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
            field_errors['email'] = 'El email no es válido'
        
        if len(password) < 6:
            field_errors['password'] = 'La contraseña debe tener al menos 6 caracteres'
        
        # Verificar duplicados
        if not field_errors.get('email') and Usuario.query.filter_by(email=email).first():
            field_errors['email'] = 'El email ya está registrado'
        
        # Si hay errores, devolver el formulario con los datos
        if field_errors:
            return render_template('auth/register.html', 
                                 field_errors=field_errors,
                                 form_data={
                                     'nombre': nombre,
                                     'apellido': apellido,
                                     'dni': dni,
                                     'fecha_nacimiento': fecha_nacimiento_raw,
                                     'tarjeta_credito': tarjeta_credito_raw,
                                     'tarjeta_vencimiento': tarjeta_vencimiento_raw,
                                     'email': email
                                 })
        
        try:
            nuevo_usuario = Usuario(
                nombre=nombre,
                apellido=apellido,
                dni=dni,
                fecha_nacimiento=fecha_nacimiento,
                autorizacion_menor=False,
                tarjeta_credito_marca=tarjeta_marca,
                tarjeta_credito_ultimos4=tarjeta_ultimos4,
                tarjeta_credito_vencimiento=tarjeta_vencimiento,
                tarjeta_credito_saldo=100000.0,
                email=email,
                password=generate_password_hash(password),
                tipo_usuario=TipoUsuario.CLIENTE,
                estado=EstadoUsuario.ACTIVO
            )
            
            db.session.add(nuevo_usuario)
            db.session.flush()
            db.session.add(TarjetaCredito(
                usuario_id=nuevo_usuario.id,
                marca=tarjeta_marca,
                ultimos4=tarjeta_ultimos4,
                numero_hash=tarjeta_numero_hash,
                vencimiento=tarjeta_vencimiento,
                saldo=100000.0,
                es_principal=True,
            ))
            db.session.commit()
            
            flash('Tu cuenta se creo exitosamente', 'success')
            return redirect(url_for('auth.register'))
        
        except Exception as e:
            db.session.rollback()
            flash('❌ Error al registrar usuario. Por favor, intenta de nuevo.', 'error')
            return render_template('auth/register.html',
                                 field_errors={},
                                 form_data={
                                     'nombre': nombre,
                                     'apellido': apellido,
                                     'dni': dni,
                                     'fecha_nacimiento': fecha_nacimiento_raw,
                                     'tarjeta_credito': tarjeta_credito_raw,
                                     'tarjeta_vencimiento': tarjeta_vencimiento_raw,
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
            if usuario.tipo_usuario == TipoUsuario.CLIENTE and not _cliente_tiene_tarjeta(usuario):
                return redirect(url_for('auth.editar_perfil'))
            if usuario.requiere_cambio_password:
                flash('Debes cambiar tu contraseña temporal para continuar', 'warning')
                return redirect(url_for('auth.cambiar_password_inicial'))
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


@auth_bp.before_app_request
def requerir_perfil_completo_cliente():
    if not current_user.is_authenticated:
        return None

    endpoints_password_temporal = {'auth.cambiar_password_inicial', 'auth.logout', 'static'}
    if current_user.requiere_cambio_password:
        if request.endpoint not in endpoints_password_temporal:
            flash('Debes cambiar tu contraseña temporal para continuar', 'warning')
            return redirect(url_for('auth.cambiar_password_inicial'))
        return None

    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        return None

    endpoints_permitidos = {'auth.editar_perfil', 'auth.logout', 'static'}
    if not _cliente_tiene_tarjeta(current_user):
        if request.endpoint not in endpoints_permitidos:
            return redirect(url_for('auth.editar_perfil'))
        return None

    return None


@auth_bp.route('/perfil/editar', methods=['GET', 'POST'])
@login_required
def editar_perfil():
    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Solo los clientes pueden editar su perfil desde esta pantalla', 'error')
        return redirect(url_for('dashboard'))

    _asegurar_tarjeta_legacy(current_user)

    if request.method == 'POST':
        action = request.form.get('action', 'perfil')
        tarjeta_obligatoria_pendiente = not _cliente_tiene_tarjeta(current_user)

        if action == 'eliminar_cuenta':
            from website.turnos.routes import _total_deudas_pendientes

            total_deuda = _total_deudas_pendientes(current_user.id)
            if total_deuda > 0:
                flash(f'No podés eliminar tu cuenta porque tenés una deuda pendiente de ${total_deuda:.2f}. Primero tenés que pagarla.', 'error')
                return redirect(url_for('turnos.mis_deudas'))

            _eliminar_cuenta_cliente(current_user)
            db.session.commit()
            logout_user()
            flash('Tu cuenta fue eliminada correctamente.', 'success')
            return redirect(url_for('index'))

        if tarjeta_obligatoria_pendiente and action != 'agregar_tarjeta':
            flash('Primero tenes que agregar una tarjeta de credito para continuar.', 'warning')
            return redirect(url_for('auth.editar_perfil'))

        if current_user.requiere_cambio_password and action != 'cambiar_password' and not tarjeta_obligatoria_pendiente:
            flash('Primero tenes que cambiar tu contraseña temporal.', 'warning')
            return redirect(url_for('auth.editar_perfil'))

        if action == 'perfil':
            nombre = request.form.get('nombre', '').strip()
            apellido = request.form.get('apellido', '').strip()
            email = request.form.get('email', '').strip().lower()
            fecha_nacimiento_raw = request.form.get('fecha_nacimiento', '').strip()
            field_errors = {}

            error_nombre = _validar_nombre_o_apellido(nombre, 'nombre')
            if error_nombre:
                field_errors['nombre'] = error_nombre

            error_apellido = _validar_nombre_o_apellido(apellido, 'apellido')
            if error_apellido:
                field_errors['apellido'] = error_apellido

            fecha_nacimiento = _parsear_fecha_nacimiento(fecha_nacimiento_raw)
            if not fecha_nacimiento:
                field_errors['fecha_nacimiento'] = 'Debes ingresar una fecha de nacimiento válida'
            elif _edad(fecha_nacimiento) < 18:
                field_errors['fecha_nacimiento'] = 'La fecha de nacimiento debe corresponder a una persona mayor de edad'

            if not email or not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
                field_errors['email'] = 'El email no es válido'
            elif Usuario.query.filter(Usuario.email == email, Usuario.id != current_user.id).first():
                field_errors['email'] = 'El email ya está registrado'

            if field_errors:
                return render_template(
                    'auth/editar_perfil.html',
                    field_errors=field_errors,
                    form_data={
                        'nombre': nombre,
                        'apellido': apellido,
                        'email': email,
                        'fecha_nacimiento': fecha_nacimiento_raw,
                    },
                    tarjetas=_tarjetas_del_cliente(current_user),
                )

            current_user.nombre = nombre
            current_user.apellido = apellido
            current_user.email = email
            current_user.fecha_nacimiento = fecha_nacimiento
            current_user.autorizacion_menor = False
            db.session.commit()
            flash('Perfil actualizado correctamente', 'success')
            return redirect(url_for('dashboard'))

        if action in {'agregar_tarjeta', 'editar_tarjeta'}:
            tarjeta_credito_raw = request.form.get('tarjeta_credito', '').strip()
            tarjeta_vencimiento_raw = request.form.get('tarjeta_vencimiento', '').strip()
            tarjeta_cvv_raw = request.form.get('tarjeta_cvv', '').strip()
            tarjeta_marca, tarjeta_ultimos4, tarjeta_numero_hash, error_tarjeta = _normalizar_datos_tarjeta_credito(
                tarjeta_credito_raw,
                tarjeta_vencimiento_raw,
                tarjeta_cvv_raw,
            )
            tarjeta_vencimiento = _parsear_vencimiento_tarjeta(tarjeta_vencimiento_raw) if not error_tarjeta else None

            if error_tarjeta:
                flash(error_tarjeta, 'error')
                return redirect(url_for('auth.editar_perfil'))

            if action == 'editar_tarjeta':
                tarjeta = TarjetaCredito.query.filter_by(
                    id=request.form.get('tarjeta_id'),
                    usuario_id=current_user.id,
                ).first_or_404()
                if _tarjeta_duplicada(current_user.id, tarjeta_numero_hash, tarjeta_id_excluida=tarjeta.id):
                    flash('Ya tenés agregada una tarjeta con ese número.', 'error')
                    return redirect(url_for('auth.editar_perfil'))

                tarjeta.marca = tarjeta_marca
                tarjeta.ultimos4 = tarjeta_ultimos4
                tarjeta.numero_hash = tarjeta_numero_hash
                tarjeta.vencimiento = tarjeta_vencimiento
                flash('Tarjeta actualizada correctamente', 'success')
            else:
                if _tarjeta_duplicada(current_user.id, tarjeta_numero_hash):
                    flash('Ya tenés agregada una tarjeta con ese número.', 'error')
                    return redirect(url_for('auth.editar_perfil'))

                es_primera_tarjeta = not TarjetaCredito.query.filter_by(usuario_id=current_user.id).first()
                tarjeta = TarjetaCredito(
                    usuario_id=current_user.id,
                    marca=tarjeta_marca,
                    ultimos4=tarjeta_ultimos4,
                    numero_hash=tarjeta_numero_hash,
                    vencimiento=tarjeta_vencimiento,
                    saldo=100000.0,
                    es_principal=es_primera_tarjeta,
                )
                db.session.add(tarjeta)
                flash('Tarjeta agregada correctamente', 'success')

            db.session.flush()
            _sincronizar_tarjeta_principal(current_user)
            db.session.commit()
            return redirect(url_for('auth.editar_perfil'))

        if action == 'quitar_tarjeta':
            tarjetas = _tarjetas_del_cliente(current_user)
            if len(tarjetas) <= 1:
                flash('Para quitar una tarjeta debe existir otra registrada', 'error')
                return redirect(url_for('auth.editar_perfil'))

            tarjeta = TarjetaCredito.query.filter_by(
                id=request.form.get('tarjeta_id'),
                usuario_id=current_user.id,
            ).first_or_404()
            db.session.delete(tarjeta)
            db.session.flush()
            _sincronizar_tarjeta_principal(current_user)
            db.session.commit()
            flash('Tarjeta quitada correctamente', 'success')
            return redirect(url_for('auth.editar_perfil'))

        if action == 'cambiar_password':
            password_actual = request.form.get('password_actual', '')
            password = request.form.get('password', '')
            password_confirm = request.form.get('password_confirm', '')
            field_errors = _validar_password_nueva(password, password_confirm)

            if not current_user.requiere_cambio_password and not check_password_hash(current_user.password, password_actual):
                field_errors['password_actual'] = 'La contraseña actual no es correcta'

            _validar_password_distinta_a_actual(current_user, password, field_errors)

            if field_errors:
                return _render_editar_perfil(field_errors=field_errors)

            current_user.password = generate_password_hash(password)
            current_user.requiere_cambio_password = False
            db.session.commit()
            flash('Contraseña actualizada correctamente', 'success')
            return redirect(url_for('dashboard'))

        flash('Accion no valida', 'error')
        return redirect(url_for('auth.editar_perfil'))

    return _render_editar_perfil()


@auth_bp.route('/perfil/validar-email')
@login_required
def validar_email_perfil():
    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        return jsonify({'valid': False, 'message': 'No tienes permisos para validar este email.'}), 403

    email = request.args.get('email', '').strip().lower()
    if not email or not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
        return jsonify({'valid': False, 'available': False, 'message': 'El email no es válido'})

    existe = Usuario.query.filter(Usuario.email == email, Usuario.id != current_user.id).first() is not None
    if existe:
        return jsonify({'valid': False, 'available': False, 'message': 'El email ya está registrado'})

    return jsonify({'valid': True, 'available': True, 'message': ''})


@auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    """Recuperar acceso enviando una contraseña temporal por correo."""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        field_errors = {}

        if not email or not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
            field_errors['email'] = 'Ingresa un email valido'
            return render_template('auth/reset_password.html', field_errors=field_errors, form_data={'email': email})

        usuario = Usuario.query.filter_by(email=email).first()

        if not usuario:
            field_errors['email'] = 'No existe una cuenta registrada con ese email'
            return render_template('auth/reset_password.html', field_errors=field_errors, form_data={'email': email})

        if usuario:
            password_temporal = _generar_password_temporal()
            usuario.password = generate_password_hash(password_temporal)
            usuario.requiere_cambio_password = True
            usuario.reset_password_token = None
            usuario.reset_password_expira = None

            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
            asunto = 'Recuperación de contraseña - Club 360'
            cuerpo = (
                f"Hola {usuario.nombre},\n\n"
                "Recibimos una solicitud para recuperar el acceso a tu cuenta.\n"
                f"Tu Contraseña temporal es: {password_temporal}\n\n"
                "Podés iniciar sesión con esa contraseña y luego cambiarla desde tu perfil si lo deseás."
            )
            try:
                enviar_email_simulado(
                    base_dir,
                    usuario.email,
                    asunto,
                    cuerpo,
                    requiere_envio_real=not current_app.config.get('TESTING', False),
                )
            except EmailDeliveryError as exc:
                db.session.rollback()
                current_app.logger.exception('Fallo el envio de email de recuperacion')
                field_errors['email'] = str(exc)
                return render_template('auth/reset_password.html', field_errors=field_errors, form_data={'email': email})

            db.session.commit()

        # Respuesta neutra para no revelar si el email existe o no.
        flash('Si el email está registrado, te enviamos tu contraseña temporal por correo.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', field_errors={}, form_data={})


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
        email = request.form.get('email', '').strip().lower()
        tipo_usuario = request.form.get('tipo_usuario', TipoUsuario.CLIENTE)

        field_errors = {}
        error_nombre = _validar_nombre_o_apellido(nombre, 'nombre')
        if error_nombre:
            field_errors['nombre'] = error_nombre
        error_apellido = _validar_nombre_o_apellido(apellido, 'apellido')
        if error_apellido:
            field_errors['apellido'] = error_apellido
        if not dni or not re.match(r'^\d{8}$', dni):
            field_errors['dni'] = 'El DNI debe tener 8 dígitos'
        fecha_nacimiento = _parsear_fecha_nacimiento(fecha_nacimiento_raw)
        if not fecha_nacimiento:
            field_errors['fecha_nacimiento'] = 'Debes ingresar una fecha de nacimiento válida'
        elif _edad(fecha_nacimiento) < 18:
            field_errors['fecha_nacimiento'] = 'Solo pueden registrarse mayores de edad'
        if not email or not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
            field_errors['email'] = 'El email no es válido'

        tipos_permitidos = {TipoUsuario.CLIENTE}
        if _es_admin(current_user):
            tipos_permitidos.update({TipoUsuario.EMPLEADO, TipoUsuario.ADMINISTRADOR})
        if tipo_usuario not in tipos_permitidos:
            field_errors['tipo_usuario'] = 'No puedes crear este tipo de usuario'

        if Usuario.query.filter_by(email=email).first():
            field_errors['email'] = 'El email ya está registrado'
        if field_errors:
            return render_template(
                'auth/crear_usuario.html',
                field_errors=field_errors,
                form_data={
                    'nombre': nombre,
                    'apellido': apellido,
                    'dni': dni,
                    'fecha_nacimiento': fecha_nacimiento_raw,
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
            autorizacion_menor=False,
            tarjeta_credito_marca=None,
            tarjeta_credito_ultimos4=None,
            tarjeta_credito_vencimiento=None,
            tarjeta_credito_saldo=100000.0 if tipo_usuario == TipoUsuario.CLIENTE else 0.0,
            email=email,
            password=generate_password_hash(password_temporal),
            tipo_usuario=tipo_usuario,
            estado=EstadoUsuario.ACTIVO,
            requiere_cambio_password=tipo_usuario != TipoUsuario.CLIENTE,
        )
        db.session.add(nuevo_usuario)
        db.session.commit()

        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        asunto = 'Alta de cuenta Club 360 - contraseña temporal'
        indicacion_ingreso = (
            "Al iniciar sesión deberás agregar una tarjeta de crédito para continuar."
            if tipo_usuario == TipoUsuario.CLIENTE
            else "Al iniciar sesión deberás cambiar esta contraseña de forma obligatoria."
        )
        cuerpo = (
            f"Hola {nombre},\n\n"
            "Tu cuenta fue creada por el personal de Club 360.\n"
            f"Email de acceso: {email}\n"
            f"Contraseña temporal: {password_temporal}\n\n"
            f"{indicacion_ingreso}"
        )
        enviar_email_simulado(base_dir, 'abonadoexample@gmail.com', asunto, cuerpo)

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
        if password and check_password_hash(current_user.password, password):
            field_errors['password'] = 'La nueva contraseña no puede ser igual a la actual'

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
