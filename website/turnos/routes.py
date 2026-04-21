import os
import secrets
import calendar
from datetime import datetime, timedelta

from flask import render_template, redirect, url_for, request, flash, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import func

from website.turnos import turnos_bp
from website import db
from website.models import (
    AbonoCliente,
    Turno,
    ListaEspera,
    Reserva,
    Pago,
    Suspension,
    EstadoAbono,
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
DIAS_SEMANA = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
FERIADOS_FIJOS_MM_DD = {
    (1, 1),    # Año Nuevo
    (3, 24),   # Día Nacional de la Memoria por la Verdad y la Justicia
    (4, 2),    # Día del Veterano y de los Caídos en la Guerra de Malvinas
    (5, 1),    # Día del Trabajador
    (5, 25),   # Día de la Revolución de Mayo
    (6, 20),   # Paso a la Inmortalidad del General Manuel Belgrano
    (7, 9),    # Día de la Independencia
    (12, 8),   # Inmaculada Concepción de María
    (12, 25),  # Navidad
}


def _es_empleado_o_admin(user):
    return user.tipo_usuario in {TipoUsuario.EMPLEADO, TipoUsuario.ADMINISTRADOR}


def _es_admin(user):
    return user.tipo_usuario == TipoUsuario.ADMINISTRADOR


def _calcular_monto_reserva(actividad, tipo_clase, usuario=None):
    base_por_actividad = {
        'futbol': 300.0,
        'basquet': 250.0,
        'voley': 220.0,
        'padel': 280.0,
    }
    base = base_por_actividad.get(actividad, 250.0)
    if tipo_clase == TipoClase.ABONADA:
        if usuario and not usuario.beneficio_abonado_activo:
            return round(base, 2)
        return round(base * 0.8, 2)
    return round(base, 2)


def _es_feriado_nacional(fecha_hora):
    fecha = fecha_hora.date() if hasattr(fecha_hora, 'date') else fecha_hora
    if (fecha.month, fecha.day) in FERIADOS_FIJOS_MM_DD:
        return True

    feriados_config = current_app.config.get('FERIADOS_NACIONALES', [])
    return fecha.isoformat() in set(feriados_config)


def _horas_anticipacion(turno):
    return (turno.hora_inicio - datetime.utcnow()).total_seconds() / 3600


def _buscar_pago_reserva(usuario_id, turno_id):
    patrones = [
        f"reserva-{turno_id}-{usuario_id}-%",
        f"espera-{turno_id}-{usuario_id}-%",
        f"abono-%-{turno_id}-{usuario_id}-%",
    ]

    for patron in patrones:
        pago_completado = (
            Pago.query
            .filter_by(usuario_id=usuario_id, estado='completado')
            .filter(Pago.referencia_transaccion.like(patron))
            .order_by(Pago.fecha_pago.desc())
            .first()
        )
        if pago_completado:
            return pago_completado
    return None


def _validar_regla_horaria(inicio, fin):
    if inicio.weekday() == 6:
        return False, 'No se permiten turnos los domingos'
    if _es_feriado_nacional(inicio):
        return False, 'No se permiten turnos en feriados nacionales'

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

    restricciones = _obtener_restricciones_suspension(cliente)
    deudas_abonadas = restricciones['deudas_abonadas']
    deudas_no_abonadas = restricciones['deudas_no_abonadas_vencidas']

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

        abonos_suspendidos = []
        if debe_suspender_abonado:
            abonos_suspendidos = _suspender_abonos_activos(cliente)

        cliente.estado = EstadoUsuario.SUSPENDIDO
        db.session.add(Suspension(
            usuario_id=cliente.id,
            motivo=motivo,
            estado='activa'
        ))
        _notificar_suspension_automatica(
            cliente,
            debe_suspender_abonado,
            debe_suspender_no_abonado,
            abonos_suspendidos,
        )
        cliente.ultimo_recordatorio_mora = datetime.utcnow()
        db.session.commit()


def _notificar_suspension_automatica(cliente, suspendido_abonado, suspendido_no_abonado, abonos_suspendidos):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    deudas_abonadas = (
        Pago.query
        .filter_by(usuario_id=cliente.id, estado='pendiente', tipo_clase=TipoClase.ABONADA)
        .filter(Pago.monto > 0)
        .all()
    )
    deudas_no_abonadas = _pagos_no_abonados_vencidos(cliente.id)
    monto_abonado = round(sum(p.monto for p in deudas_abonadas), 2)
    monto_no_abonado = round(sum(p.monto for p in deudas_no_abonadas), 2)
    monto_total = round(monto_abonado + monto_no_abonado, 2)
    consecuencias = []
    if suspendido_abonado:
        consecuencias.append(
            'tu abono mensual quedó suspendido, se liberaron tus reservas abonadas futuras y no podrás activar nuevos abonos hasta regularizar la deuda'
        )
    if suspendido_no_abonado:
        consecuencias.append(
            'no podrás reservar clases no abonadas hasta regularizar las clases vencidas impagas'
        )
    if suspendido_abonado and not suspendido_no_abonado:
        consecuencias.append('todavía podrás reservar clases no abonadas si tienes cupos disponibles y no presentas deuda de ese tipo')

    asunto = 'Suspensión automática por mora - Club 360'
    detalle_abonos = ''
    if abonos_suspendidos:
        detalle_abonos = (
            "\n\nAbonos mensuales suspendidos:\n"
            + "\n".join(
                f"- {abono.actividad.upper()} | {DIAS_SEMANA[abono.dia_semana].capitalize()} "
                f"{abono.hora_inicio:02d}:00 a {abono.hora_inicio + 1:02d}:00 | vigencia hasta {abono.fecha_hasta.strftime('%d/%m/%Y')}"
                for abono in abonos_suspendidos
            )
        )
    cuerpo = (
        f"Hola {cliente.nombre},\n\n"
        "Tu cuenta fue suspendida automáticamente por registrar deuda vencida.\n\n"
        "Resumen de deuda detectada:\n"
        f"- Deuda abonada pendiente: ${monto_abonado:.2f} ({len(deudas_abonadas)} cargos)\n"
        f"- Deuda no abonada vencida: ${monto_no_abonado:.2f} ({len(deudas_no_abonadas)} cargos)\n"
        f"- Total considerado para la suspensión: ${monto_total:.2f}\n\n"
        "Consecuencias actuales:\n"
        + "\n".join(f"- {item}" for item in consecuencias)
        + detalle_abonos
        + "\n\nIngresá a Club 360 para revisar tu deuda y regularizar tu situación."
    )
    enviar_email_simulado(base_dir, cliente.email, asunto, cuerpo)


def procesar_suspensiones_automaticas_diarias():
    clientes = Usuario.query.filter_by(tipo_usuario=TipoUsuario.CLIENTE).all()
    procesados = 0
    for cliente in clientes:
        estado_previo = cliente.estado
        suspensiones_previas = Suspension.query.filter_by(usuario_id=cliente.id, estado='activa').count()
        _procesar_suspension_automatica(cliente)
        suspensiones_actuales = Suspension.query.filter_by(usuario_id=cliente.id, estado='activa').count()
        if estado_previo != cliente.estado or suspensiones_actuales > suspensiones_previas:
            procesados += 1
    return procesados


def _validar_tipo_clase(valor):
    return valor in {TipoClase.ABONADA, TipoClase.NO_ABONADA}


def _label_tipo_clase(valor):
    return 'Abonada' if valor == TipoClase.ABONADA else 'No abonada'


def _obtener_turno_desde_pago(pago):
    referencia = (pago.referencia_transaccion or '').strip()
    if not referencia:
        return None

    partes = referencia.split('-')
    if len(partes) < 3 or partes[0] not in {'reserva', 'espera'}:
        return None

    try:
        turno_id = int(partes[1])
    except ValueError:
        return None

    return Turno.query.get(turno_id)


def _pagos_no_abonados_vencidos(usuario_id):
    pagos = (
        Pago.query
        .filter_by(usuario_id=usuario_id, estado='pendiente', tipo_clase=TipoClase.NO_ABONADA)
        .filter(Pago.monto > 0)
        .all()
    )
    vencidos = []
    ahora = datetime.utcnow()
    for pago in pagos:
        turno = _obtener_turno_desde_pago(pago)
        if turno and turno.hora_inicio < ahora:
            vencidos.append(pago)
    return vencidos


def _obtener_restricciones_suspension(cliente):
    deudas_abonadas = (
        Pago.query
        .filter_by(usuario_id=cliente.id, estado='pendiente', tipo_clase=TipoClase.ABONADA)
        .filter(Pago.monto > 0)
        .count()
    )
    deudas_no_abonadas_vencidas = len(_pagos_no_abonados_vencidos(cliente.id))

    return {
        'suspendido_abonado': datetime.utcnow().day >= 11 and deudas_abonadas > 0,
        'suspendido_no_abonado': deudas_no_abonadas_vencidas >= 3,
        'deudas_abonadas': deudas_abonadas,
        'deudas_no_abonadas_vencidas': deudas_no_abonadas_vencidas,
    }


def _obtener_siguiente_lista_espera(turno):
    return (
        ListaEspera.query
        .filter_by(turno_id=turno.id)
        .order_by(ListaEspera.posicion.asc(), ListaEspera.fecha_registro.asc())
        .first()
    )


def _recalcular_posiciones_lista(turno_id):
    pendientes = (
        ListaEspera.query
        .filter_by(turno_id=turno_id)
        .order_by(ListaEspera.posicion.asc(), ListaEspera.fecha_registro.asc())
        .all()
    )
    for index, item in enumerate(pendientes, start=1):
        item.posicion = index


def _agregar_a_lista_espera(turno, usuario_id, tipo_clase):
    posicion = ListaEspera.query.filter_by(turno_id=turno.id).count() + 1
    db.session.add(ListaEspera(
        usuario_id=usuario_id,
        turno_id=turno.id,
        tipo_lista=TIPO_LISTA_GENERAL,
        tipo_clase=tipo_clase,
        posicion=posicion,
    ))


def _abono_cubre_turno(abono, turno):
    fecha_turno = turno.hora_inicio.date()
    return (
        abono.estado == EstadoAbono.ACTIVO
        and abono.actividad == turno.actividad
        and abono.dia_semana == turno.hora_inicio.weekday()
        and abono.hora_inicio == turno.hora_inicio.hour
        and abono.fecha_desde <= fecha_turno <= abono.fecha_hasta
    )


def _fin_de_mes(fecha):
    ultimo_dia = calendar.monthrange(fecha.year, fecha.month)[1]
    return fecha.replace(day=ultimo_dia)


def _buscar_abono_activo_para_turno(usuario_id, turno):
    abonos = (
        AbonoCliente.query
        .filter_by(usuario_id=usuario_id, estado=EstadoAbono.ACTIVO, actividad=turno.actividad)
        .all()
    )
    for abono in abonos:
        if _abono_cubre_turno(abono, turno):
            return abono
    return None


def _crear_abono_mensual_para_turno(usuario, turno):
    fecha_desde = turno.hora_inicio.date()
    fecha_hasta = _fin_de_mes(fecha_desde)

    abonos_existentes = (
        AbonoCliente.query
        .filter_by(
            usuario_id=usuario.id,
            actividad=turno.actividad,
            dia_semana=turno.hora_inicio.weekday(),
            hora_inicio=turno.hora_inicio.hour,
            estado=EstadoAbono.ACTIVO,
        )
        .all()
    )
    for existente in abonos_existentes:
        if not (fecha_hasta < existente.fecha_desde or fecha_desde > existente.fecha_hasta):
            return existente, False, []

    abono = AbonoCliente(
        usuario_id=usuario.id,
        actividad=turno.actividad,
        dia_semana=turno.hora_inicio.weekday(),
        hora_inicio=turno.hora_inicio.hour,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        estado=EstadoAbono.ACTIVO,
    )
    db.session.add(abono)
    db.session.flush()
    creadas, conflictos = _generar_reservas_para_abono(abono, crear_pagos=True)
    return abono, True, conflictos


def _crear_pago_pendiente_reserva(usuario, turno, tipo_clase, referencia):
    monto_base = _calcular_monto_reserva(turno.actividad, tipo_clase, usuario)
    credito_aplicado = 0.0
    monto_final = monto_base

    if tipo_clase == TipoClase.ABONADA and usuario.credito_abonado > 0:
        credito_aplicado = min(usuario.credito_abonado, monto_base)
        monto_final = round(monto_base - credito_aplicado, 2)
        usuario.credito_abonado = round(usuario.credito_abonado - credito_aplicado, 2)

    db.session.add(Pago(
        usuario_id=usuario.id,
        monto=monto_final,
        metodo_pago='tarjeta_credito',
        estado='pendiente',
        tipo_clase=tipo_clase,
        referencia_transaccion=referencia,
    ))
    return credito_aplicado, monto_final


def _asegurar_reserva_abono(turno, usuario, abono, crear_pago=True):
    reserva_existente = Reserva.query.filter_by(turno_id=turno.id, usuario_id=usuario.id).first()
    if reserva_existente:
        if reserva_existente.tipo_clase != TipoClase.ABONADA:
            return False, 'El cliente ya tiene una reserva no abonada en esta franja.'
        if not reserva_existente.abono_id:
            reserva_existente.abono_id = abono.id
        return False, None

    if turno.cupos_disponibles <= 0:
        return False, f"El turno {turno.actividad.upper()} del {turno.hora_inicio.strftime('%d/%m/%Y %H:%M')} no tiene cupos disponibles."

    db.session.add(Reserva(
        usuario_id=usuario.id,
        turno_id=turno.id,
        abono_id=abono.id,
        tipo_clase=TipoClase.ABONADA,
        qr_token=secrets.token_urlsafe(24),
    ))
    turno.cupos_disponibles -= 1

    if crear_pago:
        referencia = f"abono-{abono.id}-{turno.id}-{usuario.id}-{int(datetime.utcnow().timestamp())}"
        _crear_pago_pendiente_reserva(usuario, turno, TipoClase.ABONADA, referencia)
    return True, None


def _generar_reservas_para_abono(abono, crear_pagos=True):
    usuario = abono.usuario or Usuario.query.get(abono.usuario_id)
    turnos = (
        Turno.query
        .filter_by(actividad=abono.actividad, cancelado=False)
        .filter(func.date(Turno.hora_inicio) >= abono.fecha_desde.isoformat())
        .filter(func.date(Turno.hora_inicio) <= abono.fecha_hasta.isoformat())
        .order_by(Turno.hora_inicio.asc())
        .all()
    )

    creadas = 0
    conflictos = []
    for turno in turnos:
        if not _abono_cubre_turno(abono, turno):
            continue
        creada, conflicto = _asegurar_reserva_abono(turno, usuario, abono, crear_pago=crear_pagos)
        if conflicto:
            conflictos.append(conflicto)
        elif creada:
            creadas += 1
    return creadas, conflictos


def _cancelar_reservas_futuras_de_abono(abono):
    ahora = datetime.utcnow()
    reservas = (
        Reserva.query
        .join(Turno, Reserva.turno_id == Turno.id)
        .filter(Reserva.abono_id == abono.id)
        .filter(Turno.hora_inicio >= ahora)
        .all()
    )

    for reserva in reservas:
        pagos = (
            Pago.query
            .filter_by(usuario_id=reserva.usuario_id)
            .filter(Pago.referencia_transaccion.like(f"abono-{abono.id}-{reserva.turno_id}-{reserva.usuario_id}-%"))
            .filter(Pago.monto > 0)
            .all()
        )
        for pago in pagos:
            if pago.estado == 'pendiente':
                db.session.delete(pago)
            else:
                db.session.add(Pago(
                    usuario_id=pago.usuario_id,
                    monto=-round(abs(pago.monto), 2),
                    metodo_pago=pago.metodo_pago,
                    estado='completado',
                    tipo_clase=pago.tipo_clase,
                    referencia_transaccion=f"reintegro-abono-{abono.id}-{reserva.turno_id}-{reserva.usuario_id}-{int(datetime.utcnow().timestamp())}",
                ))
        reserva.turno.cupos_disponibles += 1
        db.session.delete(reserva)


def _suspender_abonos_activos(cliente):
    abonos = AbonoCliente.query.filter_by(usuario_id=cliente.id, estado=EstadoAbono.ACTIVO).all()
    afectados = []
    for abono in abonos:
        abono.estado = EstadoAbono.SUSPENDIDO
        _cancelar_reservas_futuras_de_abono(abono)
        afectados.append(abono)
    return afectados


def _aplicar_abonos_a_turno(turno):
    abonos = (
        AbonoCliente.query
        .filter_by(actividad=turno.actividad, estado=EstadoAbono.ACTIVO)
        .all()
    )
    creadas = 0
    conflictos = []
    for abono in abonos:
        if not _abono_cubre_turno(abono, turno):
            continue
        creada, conflicto = _asegurar_reserva_abono(turno, abono.usuario, abono, crear_pago=True)
        if conflicto:
            conflictos.append(f"{abono.usuario.apellido}, {abono.usuario.nombre}: {conflicto}")
        elif creada:
            creadas += 1
    return creadas, conflictos


def _procesar_cancelacion_admin_con_reintegros(turno, motivo):
    """Cancela administrativamente un turno, devuelve pagos y notifica por email."""
    reservas = Reserva.query.filter_by(turno_id=turno.id).all()
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

    for reserva in reservas:
        usuario = reserva.usuario
        pago_reserva = _buscar_pago_reserva(reserva.usuario_id, turno.id)
        if pago_reserva:
            db.session.add(Pago(
                usuario_id=usuario.id,
                monto=-round(abs(pago_reserva.monto), 2),
                metodo_pago=pago_reserva.metodo_pago,
                estado='completado',
                tipo_clase=reserva.tipo_clase,
                referencia_transaccion=f"reintegro-admin-{turno.id}-{usuario.id}-{int(datetime.utcnow().timestamp())}",
            ))

        asunto = 'Cancelación de turno - Club 360'
        cuerpo = (
            f"Hola {usuario.nombre},\n\n"
            f"Tu turno de {turno.actividad} del {turno.hora_inicio.strftime('%d/%m/%Y %H:%M')} "
            "fue cancelado por administración.\n"
            f"Motivo: {motivo}\n\n"
            "Si corresponde, se registró la devolución de tu pago."
        )
        enviar_email_simulado(base_dir, usuario.email, asunto, cuerpo)

    # Limpia listas de espera porque el turno deja de existir operativamente.
    ListaEspera.query.filter_by(turno_id=turno.id).delete(synchronize_session=False)


def _notificar_admin_lista_espera_llena(turno, tipo_lista, cantidad):
    admins = Usuario.query.filter_by(tipo_usuario=TipoUsuario.ADMINISTRADOR).all()
    if not admins:
        return

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    for admin in admins:
        asunto = 'Alerta de lista de espera - Club 360'
        cuerpo = (
            f"Hola {admin.nombre},\n\n"
            f"La lista de espera '{tipo_lista}' del turno {turno.actividad} "
            f"({turno.hora_inicio.strftime('%d/%m/%Y %H:%M')}) alcanzó {cantidad} personas."
        )
        enviar_email_simulado(base_dir, admin.email, asunto, cuerpo)


def _enviar_recordatorios_qr(base_dir, usuario_id=None):
    """Envia recordatorio por email con QR el mismo dia de la clase."""
    hoy = datetime.utcnow().date().isoformat()

    query = (
        Reserva.query
        .join(Turno, Reserva.turno_id == Turno.id)
        .join(Usuario, Reserva.usuario_id == Usuario.id)
        .filter(func.date(Turno.hora_inicio) == hoy)
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
    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Esta vista está disponible solo para clientes', 'error')
        return redirect(url_for('dashboard'))

    if current_user.tipo_usuario == TipoUsuario.CLIENTE:
        _procesar_suspension_automatica(current_user)
        enviados = _enviar_recordatorios_qr(
            os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')),
            usuario_id=current_user.id,
        )
        if enviados:
            flash('Se enviaron recordatorios de clases con QR para hoy', 'info')

    actividad = request.args.get('actividad')
    
    query = Turno.query.filter_by(cancelado=False)
    
    if actividad:
        query = query.filter_by(actividad=actividad)
    
    turnos = [
        t for t in query.order_by(Turno.hora_inicio.asc()).all()
        if not _es_feriado_nacional(t.hora_inicio)
    ]
    
    return render_template(
        'turnos/disponibles.html',
        turnos=turnos,
        filtro_actividad=actividad or '',
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
                'id': str(reserva.id),
                'title': f"{reserva.turno.actividad.upper()} ({_label_tipo_clase(reserva.tipo_clase)})",
                'start': reserva.turno.hora_inicio.isoformat(),
                'end': reserva.turno.hora_fin.isoformat(),
                'backgroundColor': '#2e7d32',
                'borderColor': '#1b5e20',
                'extendedProps': {
                    'cupos': f"{reserva.turno.cupos_disponibles}/{reserva.turno.capacidad_maxima}",
                    'qr_token': reserva.qr_token,
                    'asistencia': 'Validada' if reserva.asistencia_validada else 'Pendiente',
                    'tipo_clase': _label_tipo_clase(reserva.tipo_clase),
                    'origen_reserva': 'Abono mensual' if reserva.abono_id else 'Reserva puntual',
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
                    'editar_url': url_for('turnos.editar_turno', turno_id=turno.id),
                    'cancelar_url': url_for('turnos.cancelar_turno_admin', turno_id=turno.id),
                }
            }
            for turno in turnos
        ]
        return jsonify(eventos)

    actividad = request.args.get('actividad')

    query = Turno.query.filter_by(cancelado=False)
    if actividad:
        query = query.filter_by(actividad=actividad)

    turnos = [
        t for t in query.order_by(Turno.hora_inicio.asc()).all()
        if not _es_feriado_nacional(t.hora_inicio)
    ]
    eventos = [
        {
            'id': str(turno.id),
            'title': f"{turno.actividad.upper()} ({turno.cupos_disponibles}/{turno.capacidad_maxima})",
            'start': turno.hora_inicio.isoformat(),
            'end': turno.hora_fin.isoformat(),
            'backgroundColor': '#2e7d32' if turno.cupos_disponibles > 0 else '#ef6c00',
            'borderColor': '#1b5e20' if turno.cupos_disponibles > 0 else '#e65100',
            'extendedProps': {
                'cupos': f"{turno.cupos_disponibles}/{turno.capacidad_maxima}",
                'reservar_url': url_for('turnos.reservar_turno', turno_id=turno.id),
                'sin_cupos': turno.cupos_disponibles <= 0,
                'tiene_abono': bool(_buscar_abono_activo_para_turno(current_user.id, turno)) if current_user.tipo_usuario == TipoUsuario.CLIENTE else False,
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
    tipo_clase = request.form.get('tipo_clase', TipoClase.NO_ABONADA).strip()

    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Solo los clientes pueden reservar turnos', 'error')
        return redirect(url_for('turnos.ver_turnos_disponibles'))

    if not _validar_tipo_clase(tipo_clase):
        flash('Debes elegir si la reserva es abonada o no abonada', 'error')
        return redirect(url_for('turnos.ver_turnos_disponibles'))

    _procesar_suspension_automatica(current_user)
    restricciones = _obtener_restricciones_suspension(current_user)
    if tipo_clase == TipoClase.ABONADA and restricciones['suspendido_abonado']:
        flash('Tu cuenta está suspendida para reservas abonadas. Debes regularizar tu abono vencido.', 'error')
        return redirect(url_for('pagos.ver_deuda'))
    if tipo_clase == TipoClase.NO_ABONADA and restricciones['suspendido_no_abonado']:
        flash('Tu cuenta está suspendida para clases no abonadas por acumular 3 clases vencidas impagas.', 'error')
        return redirect(url_for('pagos.ver_deuda'))

    if turno.cancelado:
        flash('Este turno ya no está disponible', 'error')
        return redirect(url_for('turnos.ver_turnos_disponibles'))

    if _es_feriado_nacional(turno.hora_inicio):
        flash('No se pueden reservar turnos en feriados nacionales', 'error')
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
        credito_aplicado = 0.0
        monto_final = 0.0
        if tipo_clase == TipoClase.ABONADA:
            abono = _buscar_abono_activo_para_turno(current_user.id, turno)
            if not abono:
                abono, creado_abono, conflictos = _crear_abono_mensual_para_turno(current_user, turno)
                if conflictos:
                    db.session.rollback()
                    flash('No se pudo activar tu abono mensual porque alguna de las clases futuras del mes no tiene cupo disponible.', 'error')
                    for conflicto in conflictos:
                        flash(conflicto, 'warning')
                    return redirect(url_for('turnos.ver_turnos_disponibles'))

                if creado_abono:
                    db.session.commit()
                    flash(
                        f'Se activó tu abono mensual para {turno.actividad.upper()} los '
                        f'{DIAS_SEMANA[turno.hora_inicio.weekday()]} a las {turno.hora_inicio.strftime("%H:%M")} hasta fin de mes.',
                        'success'
                    )
                    return redirect(url_for('turnos.mis_turnos'))

            _, conflicto = _asegurar_reserva_abono(turno, current_user, abono, crear_pago=True)
            if conflicto:
                flash(conflicto, 'error')
                return redirect(url_for('turnos.ver_turnos_disponibles'))

            pago_generado = (
                Pago.query
                .filter_by(usuario_id=current_user.id, estado='pendiente', tipo_clase=TipoClase.ABONADA)
                .filter(Pago.referencia_transaccion.like(f"abono-{abono.id}-{turno_id}-{current_user.id}-%"))
                .order_by(Pago.fecha_pago.desc())
                .first()
            )
            monto_final = pago_generado.monto if pago_generado else 0.0
        else:
            reserva = Reserva(
                usuario_id=current_user.id,
                turno_id=turno_id,
                tipo_clase=tipo_clase,
                qr_token=secrets.token_urlsafe(24),
            )
            db.session.add(reserva)
            turno.cupos_disponibles -= 1
            credito_aplicado, monto_final = _crear_pago_pendiente_reserva(
                current_user,
                turno,
                tipo_clase,
                f"reserva-{turno_id}-{current_user.id}-{int(datetime.utcnow().timestamp())}",
            )

        db.session.commit()
        if credito_aplicado > 0:
            flash(f'Turno reservado. Se aplicó un crédito de ${credito_aplicado:.2f}', 'success')
        if tipo_clase == TipoClase.ABONADA:
            flash(f'Reserva abonada confirmada dentro de tu abono mensual. Se generó una deuda de ${monto_final:.2f}', 'success')
        else:
            flash(f'Turno reservado exitosamente. Se generó una deuda de ${monto_final:.2f}', 'success')
    else:
        if tipo_clase == TipoClase.ABONADA:
            flash('No fue posible activar tu abono mensual porque este turno ya no tiene cupos disponibles.', 'error')
            return redirect(url_for('turnos.ver_turnos_disponibles'))

        existente_espera = ListaEspera.query.filter_by(
            turno_id=turno_id,
            usuario_id=current_user.id
        ).first()
        if existente_espera:
            flash('Ya estás en la lista de espera para este turno', 'info')
            return redirect(url_for('turnos.ver_turnos_disponibles'))

        _agregar_a_lista_espera(turno, current_user.id, tipo_clase)
        db.session.commit()

        personas_en_espera = ListaEspera.query.filter_by(turno_id=turno_id).count()
        if personas_en_espera == 10:
            _notificar_admin_lista_espera_llena(turno, TIPO_LISTA_GENERAL, personas_en_espera)
            flash('La lista de espera de este turno llegó a 10 personas', 'warning')

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

    horas = _horas_anticipacion(turno)
    if reserva.tipo_clase == TipoClase.ABONADA:
        current_user.cancelaciones_abonado += 1
        if horas >= 48:
            credito = _calcular_monto_reserva(turno.actividad, reserva.tipo_clase, current_user)
            current_user.credito_abonado = round(current_user.credito_abonado + credito, 2)
            flash(f'Cancelación abonada con +48h: se generó crédito de ${credito:.2f}', 'info')
        else:
            flash('Cancelación abonada con menos de 48h: no se genera crédito', 'warning')

        if current_user.cancelaciones_abonado >= 3 and current_user.beneficio_abonado_activo:
            current_user.beneficio_abonado_activo = False
            flash('Alcanzaste 3 cancelaciones abonadas: se desactiva el beneficio de abonado', 'warning')
    else:
        if horas >= 24:
            pago_reserva = _buscar_pago_reserva(current_user.id, turno_id)
            if pago_reserva:
                monto_senia = round(_calcular_monto_reserva(turno.actividad, reserva.tipo_clase, current_user) * 0.5, 2)
                monto_reintegro = round(min(abs(pago_reserva.monto), monto_senia), 2)
                db.session.add(Pago(
                    usuario_id=current_user.id,
                    monto=-monto_reintegro,
                    metodo_pago=pago_reserva.metodo_pago,
                    estado='completado',
                    tipo_clase=reserva.tipo_clase,
                    referencia_transaccion=f"reintegro-{turno_id}-{current_user.id}-{int(datetime.utcnow().timestamp())}",
                ))
                flash(f'Cancelación no abonada con +24h: se reintegró la seña (${monto_reintegro:.2f})', 'info')
            else:
                flash('Cancelación no abonada con +24h: no había pago confirmado para reintegrar', 'info')
        else:
            flash('Cancelación no abonada con menos de 24h: seña no reembolsable', 'warning')

    # Si hay lista de espera, asciende automáticamente al primero.
    siguiente = _obtener_siguiente_lista_espera(turno)
    if siguiente and turno.cupos_disponibles > 0:
        db.session.add(Reserva(
            usuario_id=siguiente.usuario_id,
            turno_id=turno_id,
            tipo_clase=siguiente.tipo_clase,
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
        monto = _calcular_monto_reserva(turno.actividad, siguiente.tipo_clase, usuario_promovido)
        db.session.add(Pago(
            usuario_id=siguiente.usuario_id,
            monto=monto,
            metodo_pago='tarjeta_credito',
            estado='pendiente',
            tipo_clase=siguiente.tipo_clase,
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
        _recalcular_posiciones_lista(turno_id)

    db.session.commit()
    
    flash('Turno cancelado exitosamente', 'success')
    return redirect(url_for('turnos.mis_turnos'))


@turnos_bp.route('/mis-turnos')
@login_required
def mis_turnos():
    """Ver mis turnos reservados."""
    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Esta vista está disponible solo para clientes', 'error')
        return redirect(url_for('dashboard'))

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
        flash('Se enviaron recordatorios de clases con QR para hoy', 'info')

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
    """Dispara envío de recordatorios del mismo día con QR."""
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


@turnos_bp.route('/abonos', methods=['GET'])
@login_required
def administrar_abonos():
    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Esta vista está disponible solo para clientes', 'error')
        return redirect(url_for('index'))

    abonos = (
        AbonoCliente.query
        .filter_by(usuario_id=current_user.id)
        .order_by(AbonoCliente.estado.asc(), AbonoCliente.fecha_desde.asc())
        .all()
    )
    return render_template(
        'turnos/abonos.html',
        abonos=abonos,
    )


@turnos_bp.route('/abonos/cancelar/<int:abono_id>', methods=['POST'])
@login_required
def cancelar_abono(abono_id):
    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Solo los clientes pueden gestionar sus abonos mensuales', 'error')
        return redirect(url_for('index'))

    abono = AbonoCliente.query.get_or_404(abono_id)
    if abono.usuario_id != current_user.id:
        flash('No tienes permisos para cancelar este abono', 'error')
        return redirect(url_for('dashboard'))

    if abono.estado == EstadoAbono.CANCELADO:
        flash('El abono ya estaba dado de baja.', 'info')
        return redirect(url_for('turnos.administrar_abonos'))

    _cancelar_reservas_futuras_de_abono(abono)
    abono.estado = EstadoAbono.CANCELADO
    db.session.commit()
    flash('Tu abono mensual fue dado de baja y se liberaron sus reservas futuras.', 'success')
    return redirect(url_for('turnos.administrar_abonos'))


@turnos_bp.route('/crear', methods=['GET', 'POST'])
@login_required
def crear_turno():
    if not _es_admin(current_user):
        flash('Solo administradores pueden crear turnos', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        actividad = request.form.get('actividad', '').strip()
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
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
            capacidad_maxima=capacidad_maxima,
            cupos_disponibles=capacidad_maxima,
            cancelado=False,
        )
        db.session.add(turno)
        db.session.flush()
        creadas_abono, conflictos_abono = _aplicar_abonos_a_turno(turno)
        db.session.commit()
        flash('Turno creado exitosamente', 'success')
        if creadas_abono:
            flash(f'Se generaron {creadas_abono} reservas abonadas fijas en esta nueva franja.', 'info')
        for conflicto in conflictos_abono:
            flash(conflicto, 'warning')
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

        reservas_confirmadas = Reserva.query.filter_by(turno_id=turno.id).count()
        if capacidad_maxima < reservas_confirmadas:
            flash('La capacidad no puede ser menor a reservas confirmadas', 'error')
            return render_template('turnos/form_turno.html', turno=turno, horas_disponibles=HORAS_DISPONIBLES)

        reservas_abono = (
            Reserva.query
            .filter(Reserva.turno_id == turno.id, Reserva.abono_id.isnot(None))
            .all()
        )
        turno_simulado = type('TurnoSimulado', (), {
            'actividad': actividad,
            'hora_inicio': hora_inicio,
            'hora_fin': hora_fin,
        })()
        for reserva_abono in reservas_abono:
            if reserva_abono.abono and not _abono_cubre_turno(reserva_abono.abono, turno_simulado):
                flash('No puedes mover este turno a una franja que rompa abonos fijos ya asignados.', 'error')
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
        turno.hora_inicio = hora_inicio
        turno.hora_fin = hora_fin
        turno.capacidad_maxima = capacidad_maxima
        turno.cupos_disponibles = capacidad_maxima - reservas_confirmadas
        creadas_abono, conflictos_abono = _aplicar_abonos_a_turno(turno)
        db.session.commit()
        flash('Turno actualizado exitosamente', 'success')
        if creadas_abono:
            flash(f'Se generaron {creadas_abono} reservas abonadas fijas por la actualización del turno.', 'info')
        for conflicto in conflictos_abono:
            flash(conflicto, 'warning')
        return redirect(url_for('turnos.administrar_turnos'))

    return render_template('turnos/form_turno.html', turno=turno, horas_disponibles=HORAS_DISPONIBLES)


@turnos_bp.route('/cancelar-admin/<int:turno_id>', methods=['POST'])
@login_required
def cancelar_turno_admin(turno_id):
    if not _es_admin(current_user):
        flash('Solo administradores pueden cancelar turnos', 'error')
        return redirect(url_for('index'))

    turno = Turno.query.get_or_404(turno_id)
    if turno.cancelado:
        flash('El turno ya estaba cancelado', 'info')
        return redirect(url_for('turnos.administrar_turnos'))

    motivo = request.form.get('motivo', '').strip()
    if not motivo:
        flash('Debes indicar el motivo de la cancelación', 'error')
        return redirect(url_for('turnos.administrar_turnos'))

    _procesar_cancelacion_admin_con_reintegros(turno, motivo)
    turno.cancelado = True
    db.session.commit()
    flash('Turno cancelado por administrador, con notificaciones y devoluciones procesadas', 'success')
    return redirect(url_for('turnos.administrar_turnos'))
