import os
import secrets
from datetime import datetime, timedelta

from flask import render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func

from website.turnos import turnos_bp
from website import db
from website.models import (
    Turno,
    ListaEspera,
    Reserva,
    Pago,
    Suspension,
    EstadoUsuario,
    Usuario,
    TipoUsuario,
    TipoClase,
)
from website.services import enviar_email_simulado


HORA_APERTURA = 8
HORA_CIERRE = 22
HORAS_DISPONIBLES = list(range(HORA_APERTURA, HORA_CIERRE))
TIPO_LISTA_GENERAL = 'general'
TIPO_LISTA_ABONADOS = 'abonados'
TIPO_LISTA_NO_ABONADOS = 'no_abonados'


def _es_empleado_o_admin(user):
    return user.tipo_usuario in {TipoUsuario.EMPLEADO, TipoUsuario.ADMINISTRADOR}


def _es_admin(user):
    return user.tipo_usuario == TipoUsuario.ADMINISTRADOR


def _calcular_monto_reserva(actividad, tipo_clase):
    base_por_actividad = {
        'futbol': 300.0,
        'basquet': 250.0,
        'voley': 220.0,
        'padel': 280.0,
    }
    base = base_por_actividad.get(actividad, 250.0)
    if tipo_clase == TipoClase.ABONADA:
        return round(base * 0.6, 2)
    return round(base, 2)


def _validar_regla_horaria(inicio, fin):
    if inicio.weekday() == 6:
        return False, 'No se permiten turnos los domingos'

    if inicio.minute != 0 or inicio.second != 0 or inicio.microsecond != 0:
        return False, 'Los turnos deben comenzar en hora exacta'

    if inicio.hour < HORA_APERTURA or inicio.hour >= HORA_CIERRE:
        return False, 'El horario de inicio debe estar entre 08:00 y 21:00'

    if fin != inicio + timedelta(hours=1):
        return False, 'La duración del turno debe ser exactamente de 1 hora'

    if fin.hour > HORA_CIERRE or (fin.hour == HORA_CIERRE and fin.minute > 0):
        return False, 'Los turnos deben finalizar como máximo a las 22:00'

    return True, None


def _construir_inicio_fin(fecha_raw, hora_raw):
    try:
        fecha = datetime.strptime(fecha_raw, '%Y-%m-%d').date()
        hora = int(hora_raw)
    except (ValueError, TypeError):
        return None, None, 'Fecha u horario inválidos'

    if hora not in HORAS_DISPONIBLES:
        return None, None, 'Horario inválido. Debe estar entre 08 y 21'

    inicio = datetime.combine(fecha, datetime.min.time()).replace(hour=hora, minute=0, second=0, microsecond=0)
    fin = inicio + timedelta(hours=1)
    valido, error = _validar_regla_horaria(inicio, fin)
    if not valido:
        return None, None, error

    return inicio, fin, None


def _procesar_suspension_automatica(cliente):
    """Suspende automaticamente segun reglas de abonados/no abonados."""
    if cliente.tipo_usuario != TipoUsuario.CLIENTE:
        return

    deudas_abonadas = (
        Pago.query
        .filter_by(usuario_id=cliente.id, estado='pendiente', tipo_clase=TipoClase.ABONADA)
        .count()
    )
    deudas_no_abonadas = (
        Pago.query
        .filter_by(usuario_id=cliente.id, estado='pendiente', tipo_clase=TipoClase.NO_ABONADA)
        .count()
    )

    if deudas_abonadas == 0 and deudas_no_abonadas == 0:
        return

    # Regla de entrevistas:
    # - Abonados: se suspenden a partir del dia 11 con deuda pendiente.
    # - No abonados: se suspenden con 3 deudas pendientes.
    debe_suspender_abonado = datetime.utcnow().day >= 11 and deudas_abonadas > 0
    debe_suspender_no_abonado = deudas_no_abonadas >= 3

    if (debe_suspender_abonado or debe_suspender_no_abonado) and cliente.estado != EstadoUsuario.SUSPENDIDO:
        motivo = 'Suspensión automática por mora'
        if debe_suspender_abonado and debe_suspender_no_abonado:
            motivo = 'Suspensión automática por deuda abonada y acumulación de deudas no abonadas'
        elif debe_suspender_abonado:
            motivo = 'Suspensión automática por deuda abonada (día 11 o posterior)'
        elif debe_suspender_no_abonado:
            motivo = 'Suspensión automática por 3 deudas no abonadas'

        cliente.estado = EstadoUsuario.SUSPENDIDO
        db.session.add(Suspension(
            usuario_id=cliente.id,
            motivo=motivo,
            estado='activa'
        ))
        db.session.commit()


def _obtener_siguiente_lista_espera(turno):
    """Aplica prioridad de listas según el tipo de clase del turno liberado."""
    if turno.tipo_clase == TipoClase.ABONADA:
        orden_prioridad = [TIPO_LISTA_ABONADOS, TIPO_LISTA_NO_ABONADOS]
    else:
        orden_prioridad = [TIPO_LISTA_GENERAL]

    for tipo_lista in orden_prioridad:
        candidato = (
            ListaEspera.query
            .filter_by(turno_id=turno.id, tipo_lista=tipo_lista)
            .order_by(ListaEspera.posicion.asc(), ListaEspera.fecha_registro.asc())
            .first()
        )
        if candidato:
            return candidato

    return None


def _recalcular_posiciones_lista(turno_id, tipo_lista):
    pendientes = (
        ListaEspera.query
        .filter_by(turno_id=turno_id, tipo_lista=tipo_lista)
        .order_by(ListaEspera.posicion.asc(), ListaEspera.fecha_registro.asc())
        .all()
    )
    for index, item in enumerate(pendientes, start=1):
        item.posicion = index


def _agregar_a_lista_espera(turno, usuario_id):
    tipos_objetivo = [TIPO_LISTA_GENERAL]
    if turno.tipo_clase == TipoClase.ABONADA:
        tipos_objetivo.append(TIPO_LISTA_ABONADOS)
    else:
        tipos_objetivo.append(TIPO_LISTA_NO_ABONADOS)

    for tipo_lista in tipos_objetivo:
        posicion = ListaEspera.query.filter_by(turno_id=turno.id, tipo_lista=tipo_lista).count() + 1
        db.session.add(ListaEspera(
            usuario_id=usuario_id,
            turno_id=turno.id,
            tipo_lista=tipo_lista,
            posicion=posicion,
        ))

    return tipos_objetivo


def _enviar_recordatorios_qr(base_dir, usuario_id=None):
    """Envia recordatorio por email con QR el dia previo a cada clase."""
    manana = (datetime.utcnow() + timedelta(days=1)).date().isoformat()

    query = (
        Reserva.query
        .join(Turno, Reserva.turno_id == Turno.id)
        .join(Usuario, Reserva.usuario_id == Usuario.id)
        .filter(func.date(Turno.hora_inicio) == manana)
        .filter(Reserva.recordatorio_enviado == False)
    )
    if usuario_id:
        query = query.filter(Reserva.usuario_id == usuario_id)

    reservas = query.all()
    enviados = 0
    for reserva in reservas:
        turno = reserva.turno
        usuario = reserva.usuario
        qr_url = f"QR:{reserva.qr_token}"
        asunto = 'Recordatorio de clase - Club 360'
        cuerpo = (
            f"Hola {usuario.nombre},\n\n"
            f"Te recordamos tu clase de {turno.actividad} el {turno.hora_inicio.strftime('%d/%m/%Y %H:%M')}.\n"
            f"Código QR de asistencia: {qr_url}\n"
            "Presentalo en recepción para validar asistencia."
        )
        enviar_email_simulado(base_dir, usuario.email, asunto, cuerpo)
        reserva.recordatorio_enviado = True
        reserva.fecha_recordatorio = datetime.utcnow()
        enviados += 1

    if enviados:
        db.session.commit()

    return enviados


@turnos_bp.route('/disponibles', methods=['GET'])
@login_required
def ver_turnos_disponibles():
    """Ver turnos disponibles para reservar."""
    if current_user.tipo_usuario == TipoUsuario.CLIENTE:
        _procesar_suspension_automatica(current_user)

    actividad = request.args.get('actividad')
    tipo_clase = request.args.get('tipo_clase')
    
    query = Turno.query.filter_by(cancelado=False)
    
    if actividad:
        query = query.filter_by(actividad=actividad)

    if tipo_clase in [TipoClase.ABONADA, TipoClase.NO_ABONADA]:
        query = query.filter_by(tipo_clase=tipo_clase)
    
    turnos = query.order_by(Turno.hora_inicio.asc()).all()
    
    return render_template(
        'turnos/disponibles.html',
        turnos=turnos,
        filtro_actividad=actividad or '',
        filtro_tipo_clase=tipo_clase or '',
    )


@turnos_bp.route('/eventos')
@login_required
def eventos_turnos():
    scope = request.args.get('scope', 'disponibles').strip().lower()

    if scope == 'mios':
        reservas = (
            Reserva.query
            .join(Turno, Reserva.turno_id == Turno.id)
            .filter(Reserva.usuario_id == current_user.id)
            .filter(Turno.cancelado == False)
            .all()
        )
        eventos = [
            {
                'id': str(reserva.turno.id),
                'title': f"{reserva.turno.actividad.upper()} ({'Abonada' if reserva.turno.tipo_clase == 'abonada' else 'No abonada'})",
                'start': reserva.turno.hora_inicio.isoformat(),
                'end': reserva.turno.hora_fin.isoformat(),
                'backgroundColor': '#2e7d32',
                'borderColor': '#1b5e20',
                'extendedProps': {
                    'cupos': f"{reserva.turno.cupos_disponibles}/{reserva.turno.capacidad_maxima}",
                    'qr_token': reserva.qr_token,
                    'asistencia': 'Validada' if reserva.asistencia_validada else 'Pendiente',
                    'cancelar_url': url_for('turnos.cancelar_turno', turno_id=reserva.turno.id),
                }
            }
            for reserva in reservas
        ]
        return jsonify(eventos)

    if scope == 'admin':
        if not _es_admin(current_user):
            return jsonify([])

        turnos = Turno.query.order_by(Turno.hora_inicio.asc()).all()
        eventos = [
            {
                'id': str(turno.id),
                'title': f"{turno.actividad.upper()} ({turno.cupos_disponibles}/{turno.capacidad_maxima})",
                'start': turno.hora_inicio.isoformat(),
                'end': turno.hora_fin.isoformat(),
                'backgroundColor': '#455a64' if turno.cancelado else '#1565c0',
                'borderColor': '#263238' if turno.cancelado else '#0d47a1',
                'extendedProps': {
                    'cancelado': turno.cancelado,
                    'tipo_clase': 'Abonada' if turno.tipo_clase == 'abonada' else 'No abonada',
                    'editar_url': url_for('turnos.editar_turno', turno_id=turno.id),
                    'cancelar_url': url_for('turnos.cancelar_turno_admin', turno_id=turno.id),
                }
            }
            for turno in turnos
        ]
        return jsonify(eventos)

    actividad = request.args.get('actividad')
    tipo_clase = request.args.get('tipo_clase')

    query = Turno.query.filter_by(cancelado=False)
    if actividad:
        query = query.filter_by(actividad=actividad)
    if tipo_clase in [TipoClase.ABONADA, TipoClase.NO_ABONADA]:
        query = query.filter_by(tipo_clase=tipo_clase)

    turnos = query.order_by(Turno.hora_inicio.asc()).all()
    eventos = [
        {
            'id': str(turno.id),
            'title': f"{turno.actividad.upper()} ({turno.cupos_disponibles}/{turno.capacidad_maxima})",
            'start': turno.hora_inicio.isoformat(),
            'end': turno.hora_fin.isoformat(),
            'backgroundColor': '#2e7d32' if turno.cupos_disponibles > 0 else '#ef6c00',
            'borderColor': '#1b5e20' if turno.cupos_disponibles > 0 else '#e65100',
            'extendedProps': {
                'tipo_clase': 'Abonada' if turno.tipo_clase == 'abonada' else 'No abonada',
                'cupos': f"{turno.cupos_disponibles}/{turno.capacidad_maxima}",
                'reservar_url': url_for('turnos.reservar_turno', turno_id=turno.id),
                'sin_cupos': turno.cupos_disponibles <= 0,
            }
        }
        for turno in turnos
    ]
    return jsonify(eventos)


@turnos_bp.route('/reservar/<int:turno_id>', methods=['POST'])
@login_required
def reservar_turno(turno_id):
    """Reservar un turno."""
    turno = Turno.query.get_or_404(turno_id)

    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Solo los clientes pueden reservar turnos', 'error')
        return redirect(url_for('turnos.ver_turnos_disponibles'))

    _procesar_suspension_automatica(current_user)
    if current_user.estado == EstadoUsuario.SUSPENDIDO:
        flash('Tu cuenta está suspendida por mora. Regulariza pagos para reservar.', 'error')
        return redirect(url_for('pagos.ver_deuda'))

    if turno.cancelado:
        flash('Este turno ya no está disponible', 'error')
        return redirect(url_for('turnos.ver_turnos_disponibles'))

    valido, error = _validar_regla_horaria(turno.hora_inicio, turno.hora_fin)
    if not valido:
        flash(f'El turno no cumple reglas horarias: {error}', 'error')
        return redirect(url_for('turnos.ver_turnos_disponibles'))
    
    # Verificar si el usuario ya tiene reservado este turno
    turno_existente = Reserva.query.filter_by(
        turno_id=turno_id,
        usuario_id=current_user.id
    ).first()
    
    if turno_existente:
        flash('Ya tienes reservado este turno', 'error')
        return redirect(url_for('turnos.ver_turnos_disponibles'))
    
    if turno.cupos_disponibles > 0:
        reserva = Reserva(
            usuario_id=current_user.id,
            turno_id=turno_id,
            qr_token=secrets.token_urlsafe(24),
        )
        db.session.add(reserva)
        turno.cupos_disponibles -= 1

        # Política de cobro por tipo de clase (abonada / no abonada).
        monto = _calcular_monto_reserva(turno.actividad, turno.tipo_clase)
        db.session.add(Pago(
            usuario_id=current_user.id,
            monto=monto,
            metodo_pago='efectivo',
            estado='pendiente',
            tipo_clase=turno.tipo_clase,
            referencia_transaccion=f"reserva-{turno_id}-{current_user.id}-{int(datetime.utcnow().timestamp())}"
        ))

        db.session.commit()
        flash(f'Turno reservado exitosamente. Se generó una deuda de ${monto:.2f}', 'success')
    else:
        existente_espera = ListaEspera.query.filter_by(
            turno_id=turno_id,
            usuario_id=current_user.id
        ).first()
        if existente_espera:
            flash('Ya estás en la lista de espera para este turno', 'info')
            return redirect(url_for('turnos.ver_turnos_disponibles'))

        tipos_registrados = _agregar_a_lista_espera(turno, current_user.id)
        db.session.commit()

        for tipo_lista in tipos_registrados:
            personas_en_espera = ListaEspera.query.filter_by(turno_id=turno_id, tipo_lista=tipo_lista).count()
            if personas_en_espera >= 10:
                flash(f'La lista de espera "{tipo_lista}" de este turno llegó a 10 personas', 'warning')

        flash('Turno lleno. Te agregamos a la lista de espera', 'info')
    
    return redirect(url_for('turnos.ver_turnos_disponibles'))


@turnos_bp.route('/cancelar/<int:turno_id>', methods=['POST'])
@login_required
def cancelar_turno(turno_id):
    """Cancelar una reserva de turno."""
    turno = Turno.query.get_or_404(turno_id)
    reserva = Reserva.query.filter_by(
        turno_id=turno_id,
        usuario_id=current_user.id
    ).first()
    
    if not reserva:
        flash('No tienes permiso para cancelar este turno', 'error')
        return redirect(url_for('turnos.mis_turnos'))
    
    db.session.delete(reserva)
    turno.cupos_disponibles += 1

    # Si hay lista de espera, asciende automáticamente al primero.
    siguiente = _obtener_siguiente_lista_espera(turno)
    if siguiente and turno.cupos_disponibles > 0:
        db.session.add(Reserva(
            usuario_id=siguiente.usuario_id,
            turno_id=turno_id,
            qr_token=secrets.token_urlsafe(24),
        ))
        turno.cupos_disponibles -= 1
        (
            ListaEspera.query
            .filter_by(turno_id=turno_id, usuario_id=siguiente.usuario_id)
            .delete(synchronize_session=False)
        )

        # Genera deuda de la clase al usuario promovido desde lista de espera.
        usuario_promovido = Usuario.query.get(siguiente.usuario_id)
        monto = _calcular_monto_reserva(turno.actividad, turno.tipo_clase)
        db.session.add(Pago(
            usuario_id=siguiente.usuario_id,
            monto=monto,
            metodo_pago='virtual',
            estado='pendiente',
            tipo_clase=turno.tipo_clase,
            referencia_transaccion=f"espera-{turno_id}-{siguiente.usuario_id}-{int(datetime.utcnow().timestamp())}"
        ))

        if usuario_promovido:
            asunto = 'Promoción desde lista de espera - Club 360'
            cuerpo = (
                f"Hola {usuario_promovido.nombre},\n\n"
                f"Se liberó un cupo y quedaste confirmado para {turno.actividad} "
                f"el {turno.hora_inicio.strftime('%d/%m/%Y %H:%M')}."
            )
            enviar_email_simulado(
                os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')),
                usuario_promovido.email,
                asunto,
                cuerpo,
            )

        # Recalcular posiciones restantes por cada tipo de lista.
        for tipo_lista in [TIPO_LISTA_GENERAL, TIPO_LISTA_ABONADOS, TIPO_LISTA_NO_ABONADOS]:
            _recalcular_posiciones_lista(turno_id, tipo_lista)

    db.session.commit()
    
    flash('Turno cancelado exitosamente', 'success')
    return redirect(url_for('turnos.mis_turnos'))


@turnos_bp.route('/mis-turnos')
@login_required
def mis_turnos():
    """Ver mis turnos reservados."""
    if current_user.tipo_usuario == TipoUsuario.CLIENTE:
        _procesar_suspension_automatica(current_user)

    reservas = (
        Reserva.query
        .join(Turno, Reserva.turno_id == Turno.id)
        .filter(Reserva.usuario_id == current_user.id)
        .order_by(Turno.hora_inicio.asc())
        .all()
    )

    enviados = _enviar_recordatorios_qr(
        os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')),
        usuario_id=current_user.id,
    )
    if enviados:
        flash('Se enviaron recordatorios de clases con QR para el día siguiente', 'info')

    return render_template('turnos/mis_turnos.html', reservas=reservas)


@turnos_bp.route('/buscar/<int:turno_id>')
@login_required
def buscar_turno(turno_id):
    """Buscar un turno (para empleados)."""
    if not _es_empleado_o_admin(current_user):
        flash('No tienes permisos para acceder a esta funcionalidad', 'error')
        return redirect(url_for('index'))

    turno = Turno.query.get_or_404(turno_id)
    listas = {
        TIPO_LISTA_GENERAL: (
            ListaEspera.query
            .filter_by(turno_id=turno.id, tipo_lista=TIPO_LISTA_GENERAL)
            .order_by(ListaEspera.posicion.asc(), ListaEspera.fecha_registro.asc())
            .all()
        ),
        TIPO_LISTA_ABONADOS: (
            ListaEspera.query
            .filter_by(turno_id=turno.id, tipo_lista=TIPO_LISTA_ABONADOS)
            .order_by(ListaEspera.posicion.asc(), ListaEspera.fecha_registro.asc())
            .all()
        ),
        TIPO_LISTA_NO_ABONADOS: (
            ListaEspera.query
            .filter_by(turno_id=turno.id, tipo_lista=TIPO_LISTA_NO_ABONADOS)
            .order_by(ListaEspera.posicion.asc(), ListaEspera.fecha_registro.asc())
            .all()
        ),
    }
    return render_template('turnos/detalle.html', turno=turno, listas=listas)


@turnos_bp.route('/validar-asistencia/<string:qr_token>', methods=['GET', 'POST'])
@login_required
def validar_asistencia_qr(qr_token):
    """Validación presencial de asistencia mediante QR."""
    if not _es_empleado_o_admin(current_user):
        flash('No tienes permisos para validar asistencia', 'error')
        return redirect(url_for('index'))

    reserva = Reserva.query.filter_by(qr_token=qr_token).first()
    if not reserva:
        flash('Código QR inválido', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        reserva.asistencia_validada = True
        reserva.fecha_asistencia = datetime.utcnow()
        db.session.commit()
        flash('Asistencia validada correctamente', 'success')
        return redirect(url_for('dashboard'))

    return render_template('turnos/validar_asistencia.html', reserva=reserva)


@turnos_bp.route('/validar-asistencia', methods=['GET', 'POST'])
@login_required
def validar_asistencia_manual():
    """Permite al personal validar asistencia ingresando un token QR manualmente."""
    if not _es_empleado_o_admin(current_user):
        flash('No tienes permisos para validar asistencia', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        qr_token = request.form.get('qr_token', '').strip()
        if not qr_token:
            flash('Debes ingresar un token QR', 'error')
            return redirect(url_for('turnos.validar_asistencia_manual'))
        return redirect(url_for('turnos.validar_asistencia_qr', qr_token=qr_token))

    return render_template('turnos/validar_asistencia_manual.html')


@turnos_bp.route('/procesar-recordatorios', methods=['POST'])
@login_required
def procesar_recordatorios():
    """Dispara envío automático de recordatorios del día siguiente con QR."""
    if not _es_empleado_o_admin(current_user):
        flash('No tienes permisos para enviar recordatorios', 'error')
        return redirect(url_for('index'))

    enviados = _enviar_recordatorios_qr(
        os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    )
    flash(f'Recordatorios enviados: {enviados}', 'success')
    return redirect(url_for('turnos.administrar_turnos'))


@turnos_bp.route('/administrar')
@login_required
def administrar_turnos():
    """Gestión de clases/turnos para administrador."""
    if not _es_admin(current_user):
        flash('Solo administradores pueden gestionar turnos', 'error')
        return redirect(url_for('index'))

    turnos = Turno.query.order_by(Turno.hora_inicio.asc()).all()
    return render_template('turnos/administrar.html', turnos=turnos, horas_disponibles=HORAS_DISPONIBLES)


@turnos_bp.route('/crear', methods=['GET', 'POST'])
@login_required
def crear_turno():
    if not _es_admin(current_user):
        flash('Solo administradores pueden crear turnos', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        actividad = request.form.get('actividad', '').strip()
        tipo_clase = request.form.get('tipo_clase', '').strip()
        capacidad_maxima = request.form.get('capacidad_maxima', type=int)
        fecha_raw = request.form.get('fecha', '').strip()
        hora_slot_raw = request.form.get('hora_inicio_slot', '').strip()

        hora_inicio, hora_fin, error_horario = _construir_inicio_fin(fecha_raw, hora_slot_raw)
        if error_horario:
            flash(error_horario, 'error')
            return render_template('turnos/form_turno.html', turno=None, horas_disponibles=HORAS_DISPONIBLES)

        if capacidad_maxima is None or capacidad_maxima <= 0:
            flash('Capacidad inválida', 'error')
            return render_template('turnos/form_turno.html', turno=None, horas_disponibles=HORAS_DISPONIBLES)

        if actividad not in {'futbol', 'basquet', 'voley', 'padel'}:
            flash('Actividad inválida', 'error')
            return render_template('turnos/form_turno.html', turno=None, horas_disponibles=HORAS_DISPONIBLES)

        if tipo_clase not in {TipoClase.ABONADA, TipoClase.NO_ABONADA}:
            flash('Tipo de clase inválido', 'error')
            return render_template('turnos/form_turno.html', turno=None, horas_disponibles=HORAS_DISPONIBLES)

        existe = Turno.query.filter_by(
            actividad=actividad,
            hora_inicio=hora_inicio,
            cancelado=False,
        ).first()
        if existe:
            flash('Ya existe un turno para ese deporte en ese día y horario', 'error')
            return render_template('turnos/form_turno.html', turno=None, horas_disponibles=HORAS_DISPONIBLES)

        turno = Turno(
            actividad=actividad,
            tipo_clase=tipo_clase,
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
            capacidad_maxima=capacidad_maxima,
            cupos_disponibles=capacidad_maxima,
            cancelado=False,
        )
        db.session.add(turno)
        db.session.commit()
        flash('Turno creado exitosamente', 'success')
        return redirect(url_for('turnos.administrar_turnos'))

    return render_template('turnos/form_turno.html', turno=None, horas_disponibles=HORAS_DISPONIBLES)


@turnos_bp.route('/editar/<int:turno_id>', methods=['GET', 'POST'])
@login_required
def editar_turno(turno_id):
    if not _es_admin(current_user):
        flash('Solo administradores pueden editar turnos', 'error')
        return redirect(url_for('index'))

    turno = Turno.query.get_or_404(turno_id)

    if request.method == 'POST':
        actividad = request.form.get('actividad', '').strip()
        tipo_clase = request.form.get('tipo_clase', '').strip()
        capacidad_maxima = request.form.get('capacidad_maxima', type=int)
        fecha_raw = request.form.get('fecha', '').strip()
        hora_slot_raw = request.form.get('hora_inicio_slot', '').strip()

        hora_inicio, hora_fin, error_horario = _construir_inicio_fin(fecha_raw, hora_slot_raw)
        if error_horario:
            flash(error_horario, 'error')
            return render_template('turnos/form_turno.html', turno=turno, horas_disponibles=HORAS_DISPONIBLES)

        if capacidad_maxima is None or capacidad_maxima <= 0:
            flash('Capacidad inválida', 'error')
            return render_template('turnos/form_turno.html', turno=turno, horas_disponibles=HORAS_DISPONIBLES)

        if actividad not in {'futbol', 'basquet', 'voley', 'padel'}:
            flash('Actividad inválida', 'error')
            return render_template('turnos/form_turno.html', turno=turno, horas_disponibles=HORAS_DISPONIBLES)

        if tipo_clase not in {TipoClase.ABONADA, TipoClase.NO_ABONADA}:
            flash('Tipo de clase inválido', 'error')
            return render_template('turnos/form_turno.html', turno=turno, horas_disponibles=HORAS_DISPONIBLES)

        reservas_confirmadas = Reserva.query.filter_by(turno_id=turno.id).count()
        if capacidad_maxima < reservas_confirmadas:
            flash('La capacidad no puede ser menor a reservas confirmadas', 'error')
            return render_template('turnos/form_turno.html', turno=turno, horas_disponibles=HORAS_DISPONIBLES)

        existe = (
            Turno.query
            .filter_by(actividad=actividad, hora_inicio=hora_inicio, cancelado=False)
            .filter(Turno.id != turno.id)
            .first()
        )
        if existe:
            flash('Ya existe un turno para ese deporte en ese día y horario', 'error')
            return render_template('turnos/form_turno.html', turno=turno, horas_disponibles=HORAS_DISPONIBLES)

        turno.actividad = actividad
        turno.tipo_clase = tipo_clase
        turno.hora_inicio = hora_inicio
        turno.hora_fin = hora_fin
        turno.capacidad_maxima = capacidad_maxima
        turno.cupos_disponibles = capacidad_maxima - reservas_confirmadas
        db.session.commit()
        flash('Turno actualizado exitosamente', 'success')
        return redirect(url_for('turnos.administrar_turnos'))

    return render_template('turnos/form_turno.html', turno=turno, horas_disponibles=HORAS_DISPONIBLES)


@turnos_bp.route('/cancelar-admin/<int:turno_id>', methods=['POST'])
@login_required
def cancelar_turno_admin(turno_id):
    if not _es_admin(current_user):
        flash('Solo administradores pueden cancelar turnos', 'error')
        return redirect(url_for('index'))

    turno = Turno.query.get_or_404(turno_id)
    turno.cancelado = True
    db.session.commit()
    flash('Turno cancelado por administrador', 'success')
    return redirect(url_for('turnos.administrar_turnos'))
