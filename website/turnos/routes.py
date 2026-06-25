import os
import secrets
import calendar
import re
from datetime import datetime, timedelta, time

from flask import render_template, redirect, url_for, request, flash, jsonify, current_app, send_file
from flask_login import login_required, current_user
from sqlalchemy import func, or_

from website.turnos import turnos_bp
from website import db
from website.models import (
    AbonoCliente,
    CreditoCliente,
    Turno,
    ListaEspera,
    Reserva,
    Pago,
    Suspension,
    EstadoAbono,
    EstadoCredito,
    EstadoUsuario,
    Usuario,
    TipoUsuario,
    TipoClase,
)
from website.services import enviar_email_simulado, generar_qr_asistencia


HORA_APERTURA = 8
HORA_CIERRE = 22
HORAS_DISPONIBLES = list(range(HORA_APERTURA, HORA_CIERRE))
TIPO_LISTA_GENERAL = 'general'
ESTADO_ESPERA_ESPERANDO = 'esperando'
ESTADO_ESPERA_NOTIFICADO = 'notificado'
DIAS_SEMANA = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
DIAS_SEMANA_CREACION = list(enumerate(DIAS_SEMANA[:6]))
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


def _calcular_monto_reserva(actividad, tipo_clase, usuario=None, descuento_porcentaje=0.0):
    base_por_actividad = {
        'futbol': 8000.0,
        'basquet': 8000.0,
        'voley': 8000.0,
        'padel': 8000.0,
    }
    base = base_por_actividad.get(actividad, 8000.0)
    if tipo_clase == TipoClase.ABONADA:
        descuento = max(0.0, min(float(descuento_porcentaje or 0.0), 100.0))
        return round(base * (1 - descuento / 100), 2)
    return round(base, 2)


def _es_feriado_nacional(fecha_hora):
    fecha = fecha_hora.date() if hasattr(fecha_hora, 'date') else fecha_hora
    if (fecha.month, fecha.day) in FERIADOS_FIJOS_MM_DD:
        return True

    feriados_config = current_app.config.get('FERIADOS_NACIONALES', [])
    return fecha.isoformat() in set(feriados_config)


def _ahora_local():
    return datetime.now()


def _horas_anticipacion(turno):
    return (turno.hora_inicio - _ahora_local()).total_seconds() / 3600


def _cancelacion_con_mas_de_48h(turno):
    return _horas_anticipacion(turno) > 48


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


def _buscar_pago_pendiente_reserva(usuario_id, turno_id):
    patrones = [
        f"reserva-{turno_id}-{usuario_id}-%",
        f"espera-{turno_id}-{usuario_id}-%",
        f"abono-%-{turno_id}-{usuario_id}-%",
    ]
    for patron in patrones:
        pago = (
            Pago.query
            .filter_by(usuario_id=usuario_id, estado='pendiente')
            .filter(Pago.referencia_transaccion.like(patron))
            .order_by(Pago.fecha_pago.desc())
            .first()
        )
        if pago:
            return pago
    return None


def _buscar_pago_abono_completado(usuario_id, abono_id):
    if not abono_id:
        return None

    patrones = [
        f"abono-{abono_id}-%-{usuario_id}-%",
        f"abono-total-{abono_id}-{usuario_id}-%",
        f"abono-inmediato-{abono_id}-{usuario_id}-%",
    ]
    for patron in patrones:
        pago = (
            Pago.query
            .filter_by(usuario_id=usuario_id, estado='completado', tipo_clase=TipoClase.ABONADA)
            .filter(Pago.referencia_transaccion.like(patron))
            .filter(Pago.monto > 0)
            .order_by(Pago.fecha_pago.desc())
            .first()
        )
        if pago:
            return pago
    return None


def _obtener_cliente_objetivo_para_reserva():
    if current_user.tipo_usuario == TipoUsuario.CLIENTE:
        return current_user, None

    if not _es_empleado_o_admin(current_user):
        return None, 'No tienes permisos para reservar turnos'

    email_cliente = request.form.get('cliente_email', '').strip().lower()
    if not email_cliente:
        return None, 'Debes ingresar el mail del cliente'

    cliente = Usuario.query.filter(func.lower(Usuario.email) == email_cliente).first()
    if not cliente or cliente.tipo_usuario != TipoUsuario.CLIENTE:
        return None, 'No existe un cliente registrado con ese mail'

    return cliente, None


def _obtener_metodo_pago_reserva(reserva_interna):
    if not reserva_interna:
        return 'tarjeta_credito', None

    if current_user.tipo_usuario == TipoUsuario.EMPLEADO:
        return 'pendiente', None

    metodo_pago = request.form.get('metodo_pago_reserva', 'tarjeta_credito').strip()
    if metodo_pago not in {'efectivo', 'tarjeta_credito'}:
        return None, 'Debes elegir una forma de pago válida'
    return metodo_pago, None


def _resolver_redirect_reserva():
    if request.form.get('redirect_to') == 'administrar_turnos' and _es_admin(current_user):
        return redirect(url_for('turnos.administrar_turnos'))
    if request.form.get('redirect_to') == 'mis_turnos':
        return redirect(url_for('turnos.mis_turnos'))
    return redirect(url_for('turnos.ver_turnos_disponibles'))


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

    if fin <= datetime.utcnow():
        return None, None, 'No se pueden crear o editar turnos en fechas u horarios ya finalizados'

    valido, error = _validar_regla_horaria(inicio, fin)
    if not valido:
        return None, None, error

    return inicio, fin, None


def _proxima_fecha_para_dia(dia_semana, hora):
    hoy = datetime.utcnow().date()
    dias_hasta_turno = (dia_semana - hoy.weekday()) % 7
    fecha = hoy + timedelta(days=dias_hasta_turno)
    inicio = datetime.combine(fecha, datetime.min.time()).replace(hour=hora, minute=0, second=0, microsecond=0)

    if inicio <= datetime.utcnow():
        fecha += timedelta(days=7)

    return fecha


def _construir_turnos_recurrentes_hasta_fin_anio(dia_semana_raw, hora_raw):
    try:
        dia_semana = int(dia_semana_raw)
        hora = int(hora_raw)
    except (ValueError, TypeError):
        return [], 'Día u horario inválidos'

    if dia_semana < 0 or dia_semana > 5:
        return [], 'Día inválido. No se permiten clases los domingos'

    if hora not in HORAS_DISPONIBLES:
        return [], 'Horario inválido. Debe estar entre 08 y 21'

    fecha = _proxima_fecha_para_dia(dia_semana, hora)
    fin_anio = datetime.utcnow().date().replace(month=12, day=31)
    turnos = []

    while fecha <= fin_anio:
        inicio = datetime.combine(fecha, datetime.min.time()).replace(hour=hora, minute=0, second=0, microsecond=0)
        fin = inicio + timedelta(hours=1)
        valido, error = _validar_regla_horaria(inicio, fin)
        if valido:
            turnos.append((inicio, fin))
        elif error != 'No se permiten turnos en feriados nacionales':
            return [], error
        fecha += timedelta(days=7)

    if not turnos:
        return [], 'No hay fechas disponibles para crear esa clase hasta fin de año'

    return turnos, None


def _procesar_suspension_automatica(cliente):
    """Suspende automaticamente segun reglas de abonados/no abonados."""
    if cliente.tipo_usuario != TipoUsuario.CLIENTE:
        return

    restricciones = _obtener_restricciones_suspension(cliente)
    deudas_no_abonadas = restricciones['deudas_no_abonadas_vencidas']
    abonos_vencidos = _abonos_pendientes_vencidos(cliente.id)

    if deudas_no_abonadas == 0 and not abonos_vencidos:
        return

    debe_suspender_abonado = bool(abonos_vencidos)
    debe_suspender_no_abonado = deudas_no_abonadas >= 3

    if (debe_suspender_abonado or debe_suspender_no_abonado) and cliente.estado != EstadoUsuario.SUSPENDIDO:
        motivo = 'Suspensión automática por mora'
        if debe_suspender_abonado:
            motivo = 'Suspensión automática por abono pendiente'
        if debe_suspender_no_abonado:
            motivo = 'Suspensión automática por 3 deudas no abonadas'

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
            abonos_vencidos,
        )
        cliente.ultimo_recordatorio_mora = datetime.utcnow()

    if debe_suspender_abonado:
        for abono in abonos_vencidos:
            _cancelar_reservas_futuras_de_abono(abono, generar_creditos=False, eliminar_pagos_pendientes=False)
            abono.estado = EstadoAbono.SUSPENDIDO

    if debe_suspender_abonado or debe_suspender_no_abonado:
        db.session.commit()


def _notificar_suspension_automatica(cliente, suspendido_abonado, suspendido_no_abonado, abonos_suspendidos):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    deudas_no_abonadas = _pagos_no_abonados_vencidos(cliente.id)
    monto_no_abonado = round(sum(p.monto for p in deudas_no_abonadas), 2)
    monto_abonado = round(sum(p.monto for abono in abonos_suspendidos for p in _pagos_pendientes_de_abono(abono)), 2)
    monto_total = round(monto_no_abonado + monto_abonado, 2)
    consecuencias = []
    if suspendido_abonado:
        consecuencias.append(
            'no podrás reservar nuevos abonos hasta regularizar el abono pendiente'
        )
    if suspendido_no_abonado:
        consecuencias.append(
            'no podrás reservar clases no abonadas hasta regularizar las clases vencidas impagas'
        )

    asunto = 'Suspensión automática por mora - Club 360'
    cuerpo = (
        f"Hola {cliente.nombre},\n\n"
        "Tu cuenta fue suspendida automáticamente por registrar deuda vencida.\n\n"
        "Resumen de deuda detectada:\n"
        f"- Deuda abonada pendiente: ${monto_abonado:.2f} ({len(abonos_suspendidos)} abono/s)\n"
        f"- Deuda no abonada vencida: ${monto_no_abonado:.2f} ({len(deudas_no_abonadas)} cargos)\n"
        f"- Total considerado para la suspensión: ${monto_total:.2f}\n\n"
        "Consecuencias actuales:\n"
        + "\n".join(f"- {item}" for item in consecuencias)
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


def _es_reserva_abonada(reserva):
    return reserva.tipo_clase == TipoClase.ABONADA or reserva.abono_id is not None


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


def _fecha_limite_pago_abono(abono):
    limite_mensual = abono.fecha_desde.replace(day=11)
    fecha_creacion = (abono.fecha_creacion or datetime.utcnow()).date()
    limite_desde_alta = fecha_creacion + timedelta(days=7)
    return max(limite_mensual, limite_desde_alta)


def _cantidad_reservas_de_abono(abono):
    return Reserva.query.filter_by(abono_id=abono.id).count()


def _abono_pendiente_puede_suspender(abono):
    return _cantidad_reservas_de_abono(abono) > 1


def _monto_pendiente_de_abono(abono):
    return round(sum(pago.monto for pago in _pagos_pendientes_de_abono(abono)), 2)


def _abono_suspendido_debe_bloquear(abono):
    monto_una_clase = _calcular_monto_reserva(
        abono.actividad,
        TipoClase.ABONADA,
        abono.usuario,
        descuento_porcentaje=abono.descuento_porcentaje,
    )
    return _monto_pendiente_de_abono(abono) > monto_una_clase


def _abonos_pendientes_vencidos(usuario_id):
    hoy = _ahora_local().date()
    abonos = (
        AbonoCliente.query
        .filter_by(usuario_id=usuario_id, estado=EstadoAbono.PENDIENTE)
        .all()
    )
    return [
        abono
        for abono in abonos
        if _abono_pendiente_puede_suspender(abono) and hoy >= _fecha_limite_pago_abono(abono)
    ]


def _tiene_suspension_abonada_activa(usuario_id):
    return (
        Suspension.query
        .filter_by(usuario_id=usuario_id, estado='activa')
        .filter(Suspension.motivo.like('%abono%'))
        .count()
        > 0
    )


def _tiene_suspension_no_abonada_activa(usuario_id):
    return (
        Suspension.query
        .filter_by(usuario_id=usuario_id, estado='activa')
        .filter(or_(Suspension.motivo.like('%no abonad%'), Suspension.motivo.like('%3 deudas%')))
        .count()
        > 0
    )


def _obtener_restricciones_suspension(cliente):
    deudas_no_abonadas_vencidas = len(_pagos_no_abonados_vencidos(cliente.id))
    abonos_pendientes_vencidos = len(_abonos_pendientes_vencidos(cliente.id))
    abonos_suspendidos_bloqueantes = [
        abono
        for abono in AbonoCliente.query.filter_by(
            usuario_id=cliente.id,
            estado=EstadoAbono.SUSPENDIDO,
        ).all()
        if _abono_suspendido_debe_bloquear(abono)
    ]
    suspension_abonada_activa = (
        _tiene_suspension_abonada_activa(cliente.id)
        and (abonos_pendientes_vencidos > 0 or bool(abonos_suspendidos_bloqueantes))
    )

    return {
        'suspendido_abonado': (
            abonos_pendientes_vencidos > 0
            or bool(abonos_suspendidos_bloqueantes)
            or suspension_abonada_activa
        ),
        'suspendido_no_abonado': deudas_no_abonadas_vencidas >= 3 or _tiene_suspension_no_abonada_activa(cliente.id),
        'deudas_abonadas': abonos_pendientes_vencidos,
        'deudas_no_abonadas_vencidas': deudas_no_abonadas_vencidas,
    }


def _obtener_siguiente_lista_espera(turno, tipo_clase=None):
    query = ListaEspera.query.filter_by(turno_id=turno.id, estado=ESTADO_ESPERA_ESPERANDO)
    if tipo_clase:
        query = query.filter_by(tipo_clase=tipo_clase)
    return query.order_by(ListaEspera.posicion.asc(), ListaEspera.fecha_registro.asc()).first()


def _obtener_siguiente_lista_espera_para_cupo(turno, tipo_cupo_liberado):
    if ListaEspera.query.filter_by(turno_id=turno.id, estado=ESTADO_ESPERA_NOTIFICADO).first():
        return None

    if tipo_cupo_liberado == TipoClase.ABONADA:
        siguiente = _obtener_siguiente_lista_espera(turno, tipo_clase=TipoClase.ABONADA)
        if siguiente:
            return siguiente
        return _obtener_siguiente_lista_espera(turno, tipo_clase=TipoClase.NO_ABONADA)

    return (
        ListaEspera.query
        .filter_by(turno_id=turno.id, estado=ESTADO_ESPERA_ESPERANDO)
        .order_by(ListaEspera.fecha_registro.asc(), ListaEspera.posicion.asc())
        .first()
    )


def _obtener_invitacion_activa_turno(turno_id):
    return (
        ListaEspera.query
        .filter_by(turno_id=turno_id, estado=ESTADO_ESPERA_NOTIFICADO)
        .order_by(ListaEspera.fecha_notificacion.asc(), ListaEspera.fecha_registro.asc())
        .first()
    )


def _enviar_email_cupo_lista_espera(item):
    turno = item.turno
    usuario = item.usuario
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    asunto = 'Se libero un cupo - Club 360'
    cuerpo = (
        f"Hola {usuario.nombre},\n\n"
        f"Se libero {turno.actividad.upper()} el {turno.hora_inicio.strftime('%d/%m/%Y')} "
        f"a las {turno.hora_inicio.strftime('%H:%M')}.\n"
        "Inicia sesion en la pagina para confirmar la reserva.\n\n"
        "El cupo no queda reservado hasta que confirmes desde el sistema."
    )
    enviar_email_simulado(base_dir, usuario.email, asunto, cuerpo)


def _notificar_siguiente_lista_espera(turno, tipo_cupo_liberado):
    if turno.cupos_disponibles <= 0:
        return None

    siguiente = _obtener_siguiente_lista_espera_para_cupo(turno, tipo_cupo_liberado)
    if not siguiente:
        return None

    siguiente.estado = ESTADO_ESPERA_NOTIFICADO
    siguiente.fecha_notificacion = datetime.utcnow()
    siguiente.tipo_cupo_liberado = tipo_cupo_liberado
    _enviar_email_cupo_lista_espera(siguiente)
    return siguiente


def _recalcular_posiciones_lista(turno_id):
    for tipo_clase in (TipoClase.ABONADA, TipoClase.NO_ABONADA):
        pendientes = (
            ListaEspera.query
            .filter_by(turno_id=turno_id, tipo_clase=tipo_clase)
            .order_by(ListaEspera.fecha_registro.asc(), ListaEspera.id.asc())
            .all()
        )
        for index, item in enumerate(pendientes, start=1):
            item.posicion = index


def _agregar_a_lista_espera(turno, usuario_id, tipo_clase):
    posicion = ListaEspera.query.filter_by(turno_id=turno.id, tipo_clase=tipo_clase).count() + 1
    db.session.add(ListaEspera(
        usuario_id=usuario_id,
        turno_id=turno.id,
        tipo_lista=TIPO_LISTA_GENERAL,
        tipo_clase=tipo_clase,
        posicion=posicion,
        estado=ESTADO_ESPERA_ESPERANDO,
    ))


def _agregar_a_lista_espera_si_no_existe(turno, usuario_id, tipo_clase):
    existente = ListaEspera.query.filter_by(
        turno_id=turno.id,
        usuario_id=usuario_id,
    ).first()
    if existente:
        return False

    _agregar_a_lista_espera(turno, usuario_id, tipo_clase)
    return True


def _eliminar_espera_usuario_turno(turno_id, usuario_id):
    eliminadas = (
        ListaEspera.query
        .filter_by(turno_id=turno_id, usuario_id=usuario_id)
        .delete(synchronize_session=False)
    )
    if eliminadas:
        _recalcular_posiciones_lista(turno_id)
    return eliminadas


def _limpiar_esperas_de_abono(usuario_id, abono):
    turnos_ids = [turno.id for turno in _obtener_turnos_para_abono(abono)]
    if not turnos_ids:
        return
    ListaEspera.query.filter(
        ListaEspera.usuario_id == usuario_id,
        ListaEspera.tipo_clase == TipoClase.ABONADA,
        ListaEspera.turno_id.in_(turnos_ids),
    ).delete(synchronize_session=False)
    for turno_id in turnos_ids:
        _recalcular_posiciones_lista(turno_id)


def _crear_abono_desde_lista_espera(usuario, turno):
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
            return existente, 0, []

    abono = AbonoCliente(
        usuario_id=usuario.id,
        actividad=turno.actividad,
        dia_semana=turno.hora_inicio.weekday(),
        hora_inicio=turno.hora_inicio.hour,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        estado=EstadoAbono.ACTIVO,
        descuento_porcentaje=0.0,
    )
    turnos_abono = _obtener_turnos_para_abono(abono)
    abono.descuento_porcentaje = _calcular_descuento_abono(turnos_abono)

    _, conflictos = _validar_cupos_turnos_abono(turnos_abono, usuario)
    if conflictos:
        return None, 0, conflictos

    db.session.add(abono)
    db.session.flush()
    creadas, conflictos, _ = _generar_reservas_para_abono(abono, crear_pagos=True)
    return abono, creadas, conflictos


def _promover_siguiente_lista_espera(turno, tipo_clase=None):
    tipo_cupo_liberado = tipo_clase or TipoClase.NO_ABONADA
    return _notificar_siguiente_lista_espera(turno, tipo_cupo_liberado)


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


def _mes_siguiente(fecha):
    if fecha.month == 12:
        return fecha.replace(year=fecha.year + 1, month=1, day=1)
    return fecha.replace(month=fecha.month + 1, day=1)


def _fecha_limite_busqueda_turnos():
    return _fin_de_mes(_mes_siguiente(datetime.utcnow().date()))


def _datetime_limite_busqueda_turnos():
    return datetime.combine(_fecha_limite_busqueda_turnos(), time.max)


def _clave_mes(fecha):
    return fecha.strftime('%Y-%m')


def _vencimiento_credito(fecha_cancelacion):
    return _fin_de_mes(_mes_siguiente(fecha_cancelacion))


def _vencer_creditos_expirados(usuario_id=None):
    query = CreditoCliente.query.filter(
        CreditoCliente.estado == EstadoCredito.DISPONIBLE,
        CreditoCliente.fecha_vencimiento < datetime.utcnow().date(),
    )
    if usuario_id:
        query = query.filter(CreditoCliente.usuario_id == usuario_id)
    query.update({'estado': EstadoCredito.VENCIDO}, synchronize_session=False)


def _obtener_credito_disponible(usuario_id, actividad):
    _vencer_creditos_expirados(usuario_id)
    return (
        CreditoCliente.query
        .filter_by(usuario_id=usuario_id, actividad=actividad, estado=EstadoCredito.DISPONIBLE)
        .filter(CreditoCliente.fecha_vencimiento >= datetime.utcnow().date())
        .order_by(CreditoCliente.fecha_vencimiento.asc(), CreditoCliente.fecha_creacion.asc())
        .first()
    )


def _marcar_credito_usado(credito, reserva):
    credito.estado = EstadoCredito.USADO
    credito.reserva_uso_id = reserva.id
    credito.fecha_uso = datetime.utcnow()


def _crear_credito_por_cancelacion_abonada(reserva, turno, pago):
    if not pago or pago.estado != 'completado' or pago.monto <= 0:
        return None

    credito = CreditoCliente(
        usuario_id=reserva.usuario_id,
        actividad=turno.actividad,
        monto=round(abs(pago.monto), 2),
        fecha_vencimiento=_vencimiento_credito(datetime.utcnow().date()),
    )
    db.session.add(credito)
    return credito


def _crear_credito_por_cancelacion_admin(reserva, turno, monto, fecha_vencimiento=None):
    monto = round(float(monto or 0), 2)
    if monto <= 0:
        return None

    credito = CreditoCliente(
        usuario_id=reserva.usuario_id,
        actividad=turno.actividad,
        monto=monto,
        estado=EstadoCredito.DISPONIBLE,
        fecha_vencimiento=fecha_vencimiento or _vencimiento_credito(datetime.utcnow().date()),
    )
    db.session.add(credito)
    return credito


def _restaurar_credito_usado_por_reserva(reserva):
    credito = (
        CreditoCliente.query
        .filter_by(reserva_uso_id=reserva.id, estado=EstadoCredito.USADO)
        .first()
    )
    if not credito:
        return None

    credito.estado = EstadoCredito.DISPONIBLE
    credito.reserva_uso_id = None
    credito.fecha_uso = None
    return credito


def _pagos_de_reserva_por_estado(usuario_id, turno_id, tipo_clase, estados=None):
    patrones = [
        f"reserva-{turno_id}-{usuario_id}-%",
        f"espera-{turno_id}-{usuario_id}-%",
    ]
    if tipo_clase == TipoClase.ABONADA:
        patrones.append(f"abono-%-{turno_id}-{usuario_id}-%")

    query = Pago.query.filter_by(usuario_id=usuario_id, tipo_clase=tipo_clase)
    if estados:
        query = query.filter(Pago.estado.in_(estados))

    filtros = [Pago.referencia_transaccion.like(patron) for patron in patrones]
    return (
        query
        .filter(or_(*filtros))
        .order_by(Pago.fecha_pago.asc(), Pago.id.asc())
        .all()
    )


def _pagos_pendientes_de_reserva(reserva):
    return _pagos_de_reserva_por_estado(
        reserva.usuario_id,
        reserva.turno_id,
        reserva.tipo_clase,
        estados=['pendiente'],
    )


def _monto_pendiente_de_reserva(reserva):
    if _es_reserva_abonada(reserva) and reserva.abono:
        return round(sum(pago.monto for pago in _pagos_pendientes_de_abono(reserva.abono)), 2)
    return round(sum(pago.monto for pago in _pagos_pendientes_de_reserva(reserva)), 2)


def _estado_cliente_de_reserva(reserva):
    if reserva.asistencia_validada:
        return 'Confirmado'
    if _monto_pendiente_de_reserva(reserva) > 0:
        return 'Pendiente'
    return 'Pagado'


def _registrar_reintegro_admin(usuario, reserva, turno, monto, metodo_pago):
    monto = round(float(monto or 0), 2)
    if monto <= 0:
        return None

    reintegro = Pago(
        usuario_id=usuario.id,
        monto=-monto,
        metodo_pago=metodo_pago,
        estado='completado',
        tipo_clase=reserva.tipo_clase,
        fecha_pago=datetime.utcnow(),
        referencia_transaccion=f"reintegro-admin-{turno.id}-{usuario.id}-{int(datetime.utcnow().timestamp())}",
    )
    db.session.add(reintegro)
    return reintegro


def _descontar_monto_de_pagos_pendientes(pagos, monto):
    restante = round(float(monto or 0), 2)
    descontado = 0.0

    for pago in pagos:
        if restante <= 0:
            break

        monto_pago = round(float(pago.monto or 0), 2)
        descuento = min(monto_pago, restante)
        pago.monto = round(monto_pago - descuento, 2)
        restante = round(restante - descuento, 2)
        descontado = round(descontado + descuento, 2)
        if pago.monto <= 0:
            db.session.delete(pago)

    return descontado


def _obtener_descuento_cupon_abono(usuario, turno):
    fecha_turno = turno.hora_inicio.date()
    if (
        (usuario.cupon_abono_porcentaje or 0) > 0
        and usuario.cupon_abono_mes == _clave_mes(fecha_turno)
        and usuario.cupon_abono_actividad == turno.actividad
        and usuario.cupon_abono_dia_semana == turno.hora_inicio.weekday()
        and usuario.cupon_abono_hora_inicio == turno.hora_inicio.hour
    ):
        return usuario.cupon_abono_porcentaje
    return 0.0


def _limpiar_cupon_abono(usuario):
    usuario.cupon_abono_mes = None
    usuario.cupon_abono_actividad = None
    usuario.cupon_abono_dia_semana = None
    usuario.cupon_abono_hora_inicio = None
    usuario.cupon_abono_porcentaje = 0.0


def _generar_cupon_abono_proximo_mes(usuario, turno):
    proximo_mes = _mes_siguiente(turno.hora_inicio.date())
    usuario.cupon_abono_mes = _clave_mes(proximo_mes)
    usuario.cupon_abono_actividad = turno.actividad
    usuario.cupon_abono_dia_semana = turno.hora_inicio.weekday()
    usuario.cupon_abono_hora_inicio = turno.hora_inicio.hour
    usuario.cupon_abono_porcentaje = 20.0


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


def _obtener_turnos_para_abono(abono):
    turnos = (
        Turno.query
        .filter_by(actividad=abono.actividad, cancelado=False)
        .filter(func.date(Turno.hora_inicio) >= abono.fecha_desde.isoformat())
        .filter(func.date(Turno.hora_inicio) <= abono.fecha_hasta.isoformat())
        .filter(Turno.hora_inicio > _ahora_local())
        .order_by(Turno.hora_inicio.asc())
        .all()
    )
    return [turno for turno in turnos if _abono_cubre_turno(abono, turno)]


def _calcular_descuento_abono(turnos_abono):
    cantidad_clases = len(turnos_abono)
    if 1 < cantidad_clases <= 3:
        return 20.0
    return 0.0


def _validar_cupos_turnos_abono(turnos, usuario, permitir_sin_cupo=False):
    conflictos = []
    disponibles = []

    for turno in turnos:
        reserva_existente = Reserva.query.filter_by(turno_id=turno.id, usuario_id=usuario.id).first()
        if reserva_existente:
            if reserva_existente.tipo_clase != TipoClase.ABONADA:
                conflictos.append(f"El cliente ya tiene una reserva no abonada el {turno.hora_inicio.strftime('%d/%m/%Y %H:%M')}.")
                continue
            disponibles.append(turno)
            continue

        if turno.cupos_disponibles <= 0:
            if permitir_sin_cupo:
                continue
            conflictos.append(f"El turno {turno.actividad.upper()} del {turno.hora_inicio.strftime('%d/%m/%Y %H:%M')} no tiene cupos disponibles.")
            continue

        disponibles.append(turno)

    return disponibles, conflictos


def _crear_pago_abono_inmediato(usuario, abono, turnos):
    monto_total = sum(
        _calcular_monto_reserva(
            turno.actividad,
            TipoClase.ABONADA,
            usuario,
            descuento_porcentaje=abono.descuento_porcentaje,
        )
        for turno in turnos
    )
    pago = Pago(
        usuario_id=usuario.id,
        monto=round(monto_total, 2),
        metodo_pago='tarjeta_credito',
        estado='completado',
        tipo_clase=TipoClase.ABONADA,
        fecha_pago=datetime.utcnow(),
        referencia_transaccion=f"abono-inmediato-{abono.id}-{usuario.id}-{int(datetime.utcnow().timestamp())}",
    )
    db.session.add(pago)
    return pago


def _crear_abono_mensual_para_turno(usuario, turno, credito=None, metodo_pago='tarjeta_credito'):
    fecha_desde = turno.hora_inicio.date()
    fecha_hasta = _fin_de_mes(fecha_desde)

    abonos_existentes = (
        AbonoCliente.query
        .filter_by(
            usuario_id=usuario.id,
            actividad=turno.actividad,
            dia_semana=turno.hora_inicio.weekday(),
            hora_inicio=turno.hora_inicio.hour,
        )
        .filter(AbonoCliente.estado.in_([EstadoAbono.ACTIVO, EstadoAbono.PENDIENTE, EstadoAbono.SUSPENDIDO]))
        .all()
    )
    for existente in abonos_existentes:
        if not (fecha_hasta < existente.fecha_desde or fecha_desde > existente.fecha_hasta):
            return existente, False, [], 0, [], False, False

    abono = AbonoCliente(
        usuario_id=usuario.id,
        actividad=turno.actividad,
        dia_semana=turno.hora_inicio.weekday(),
        hora_inicio=turno.hora_inicio.hour,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        estado=EstadoAbono.ACTIVO,
        descuento_porcentaje=0.0,
    )
    db.session.add(abono)
    db.session.flush()

    turnos_abono = _obtener_turnos_para_abono(abono)
    abono.descuento_porcentaje = _calcular_descuento_abono(turnos_abono)

    _, conflictos = _validar_cupos_turnos_abono(turnos_abono, usuario, permitir_sin_cupo=True)
    if conflictos:
        return abono, True, conflictos, 0, [], False, False

    creadas, conflictos, turnos_en_espera = _generar_reservas_para_abono(
        abono,
        crear_pagos=True,
        agregar_espera_sin_cupo=True,
        credito=credito,
        metodo_pago=metodo_pago,
    )
    if creadas > 0:
        turnos_cobrables = (
            Turno.query
            .join(Reserva, Reserva.turno_id == Turno.id)
            .filter(Reserva.abono_id == abono.id)
            .filter(Reserva.usuario_id == usuario.id)
            .order_by(Turno.hora_inicio.asc())
            .all()
        )
        _crear_pago_abono_mensual(usuario, abono, turnos_cobrables, metodo_pago=metodo_pago, credito=credito)
    return abono, True, conflictos, creadas, turnos_en_espera, False, False


def _crear_pago_pendiente_reserva(
    usuario,
    turno,
    tipo_clase,
    referencia,
    descuento_porcentaje=0.0,
    credito=None,
    metodo_pago='tarjeta_credito',
):
    monto_base = _calcular_monto_reserva(turno.actividad, tipo_clase, usuario, descuento_porcentaje=descuento_porcentaje)
    credito_aplicado = round(min(float(credito.monto), monto_base), 2) if credito else 0.0
    monto_final = round(max(monto_base - credito_aplicado, 0), 2)
    estado_pago = 'completado'
    monto_senia = round(monto_final * 0.5, 2) if tipo_clase == TipoClase.NO_ABONADA else monto_final
    monto_deuda = round(monto_final - monto_senia, 2) if tipo_clase == TipoClase.NO_ABONADA else 0.0

    if metodo_pago == 'pendiente':
        estado_pago = 'pendiente'
    elif metodo_pago == 'tarjeta_credito' and monto_senia > 0:
        saldo = float(usuario.tarjeta_credito_saldo or 0.0)
        if _tarjeta_credito_vencida(usuario):
            estado_pago = 'pendiente'
        elif saldo >= monto_senia:
            usuario.tarjeta_credito_saldo = round(saldo - monto_senia, 2)
        else:
            estado_pago = 'pendiente'

    db.session.add(Pago(
        usuario_id=usuario.id,
        monto=monto_senia,
        metodo_pago=metodo_pago,
        estado=estado_pago,
        tipo_clase=tipo_clase,
        fecha_pago=datetime.utcnow(),
        referencia_transaccion=f"{referencia}-senia" if tipo_clase == TipoClase.NO_ABONADA else referencia,
    ))
    if monto_deuda > 0:
        db.session.add(Pago(
            usuario_id=usuario.id,
            monto=monto_deuda,
            metodo_pago='pendiente' if metodo_pago == 'pendiente' else 'tarjeta_credito',
            estado='pendiente',
            tipo_clase=tipo_clase,
            fecha_pago=datetime.utcnow(),
            referencia_transaccion=f"{referencia}-saldo",
        ))
    return credito_aplicado, monto_senia, estado_pago


def _crear_pago_abono_mensual(usuario, abono, turnos, metodo_pago='tarjeta_credito', credito=None):
    monto_base = round(sum(
        _calcular_monto_reserva(
            turno.actividad,
            TipoClase.ABONADA,
            usuario,
            descuento_porcentaje=abono.descuento_porcentaje,
        )
        for turno in turnos
    ), 2)
    credito_aplicado = round(min(float(credito.monto), monto_base), 2) if credito else 0.0
    monto_final = round(max(monto_base - credito_aplicado, 0), 2)

    db.session.add(Pago(
        usuario_id=usuario.id,
        monto=monto_final,
        metodo_pago='tarjeta_credito',
        estado='pendiente',
        tipo_clase=TipoClase.ABONADA,
        fecha_pago=datetime.utcnow(),
        referencia_transaccion=f"abono-total-{abono.id}-{usuario.id}-{int(datetime.utcnow().timestamp())}",
    ))
    return credito_aplicado, monto_final, 'pendiente'


def _asegurar_reserva_abono(turno, usuario, abono, crear_pago=True, credito=None, metodo_pago='tarjeta_credito'):
    reserva_existente = Reserva.query.filter_by(turno_id=turno.id, usuario_id=usuario.id).first()
    if reserva_existente:
        if reserva_existente.tipo_clase != TipoClase.ABONADA:
            return False, 'El cliente ya tiene una reserva no abonada en esta franja.'
        if not reserva_existente.abono_id:
            reserva_existente.abono_id = abono.id
        return False, None

    if turno.cupos_disponibles <= 0:
        return False, f"El turno {turno.actividad.upper()} del {turno.hora_inicio.strftime('%d/%m/%Y %H:%M')} no tiene cupos disponibles."

    reserva = Reserva(
        usuario_id=usuario.id,
        turno_id=turno.id,
        abono_id=abono.id,
        tipo_clase=TipoClase.ABONADA,
        qr_token=secrets.token_urlsafe(24),
    )
    db.session.add(reserva)
    turno.cupos_disponibles -= 1

    if crear_pago and credito:
        db.session.flush()
        _marcar_credito_usado(credito, reserva)
    return True, None


def _generar_reservas_para_abono(abono, crear_pagos=True, agregar_espera_sin_cupo=False, credito=None, metodo_pago='tarjeta_credito'):
    usuario = abono.usuario or Usuario.query.get(abono.usuario_id)
    turnos = _obtener_turnos_para_abono(abono)

    creadas = 0
    conflictos = []
    turnos_en_espera = []
    for turno in turnos:
        reserva_existente = Reserva.query.filter_by(turno_id=turno.id, usuario_id=usuario.id).first()
        if reserva_existente:
            if reserva_existente.tipo_clase != TipoClase.ABONADA:
                conflictos.append('El cliente ya tiene una reserva no abonada en esta franja.')
            elif not reserva_existente.abono_id:
                reserva_existente.abono_id = abono.id
            continue

        if turno.cupos_disponibles <= 0 and agregar_espera_sin_cupo:
            _agregar_a_lista_espera_si_no_existe(turno, usuario.id, TipoClase.ABONADA)
            turnos_en_espera.append(turno)
            continue

        credito_turno = credito if credito and credito.estado == EstadoCredito.DISPONIBLE else None
        creada, conflicto = _asegurar_reserva_abono(
            turno,
            usuario,
            abono,
            crear_pago=crear_pagos,
            credito=credito_turno,
            metodo_pago=metodo_pago,
        )
        if conflicto:
            conflictos.append(conflicto)
        elif creada:
            creadas += 1
    return creadas, conflictos, turnos_en_espera


def _abono_tiene_pagos_pendientes(abono):
    return (
        Pago.query
        .filter_by(usuario_id=abono.usuario_id, estado='pendiente', tipo_clase=TipoClase.ABONADA)
        .filter(
            or_(
                Pago.referencia_transaccion.like(f"abono-{abono.id}-%-{abono.usuario_id}-%"),
                Pago.referencia_transaccion.like(f"abono-total-{abono.id}-{abono.usuario_id}-%"),
            )
        )
        .filter(Pago.monto > 0)
        .count()
        > 0
    )


def _pagos_pendientes_de_abono(abono):
    return (
        Pago.query
        .filter_by(usuario_id=abono.usuario_id, estado='pendiente', tipo_clase=TipoClase.ABONADA)
        .filter(
            or_(
                Pago.referencia_transaccion.like(f"abono-{abono.id}-%-{abono.usuario_id}-%"),
                Pago.referencia_transaccion.like(f"abono-total-{abono.id}-{abono.usuario_id}-%"),
            )
        )
        .filter(Pago.monto > 0)
        .order_by(Pago.fecha_pago.asc())
        .all()
    )


def _intentar_cobrar_abono(abono):
    usuario = abono.usuario or Usuario.query.get(abono.usuario_id)
    pagos = _pagos_pendientes_de_abono(abono)
    if not pagos:
        abono.estado = EstadoAbono.ACTIVO
        return 0.0, True

    total = round(sum(pago.monto for pago in pagos), 2)
    if _tarjeta_credito_vencida(usuario):
        abono.estado = EstadoAbono.PENDIENTE
        return total, False

    saldo = float(usuario.tarjeta_credito_saldo or 0.0)
    if saldo < total:
        abono.estado = EstadoAbono.PENDIENTE
        return total, False

    usuario.tarjeta_credito_saldo = round(saldo - total, 2)
    for pago in pagos:
        pago.estado = 'completado'
        pago.metodo_pago = 'tarjeta_credito'
        pago.fecha_pago = datetime.utcnow()
    abono.estado = EstadoAbono.ACTIVO
    return total, True


def _obtener_deudas_pendientes(usuario_id):
    return (
        Pago.query
        .filter_by(usuario_id=usuario_id, estado='pendiente')
        .filter(Pago.monto > 0)
        .order_by(Pago.fecha_pago.asc(), Pago.id.asc())
        .all()
    )


def _total_deudas_pendientes(usuario_id):
    return round(sum(deuda.monto for deuda in _obtener_deudas_pendientes(usuario_id)), 2)


def _tarjeta_credito_vencida(usuario):
    vencimiento = getattr(usuario, 'tarjeta_credito_vencimiento', None)
    return bool(vencimiento and vencimiento < datetime.utcnow().date())


def _rechazar_pago_tarjeta_vencida(usuario):
    if not _tarjeta_credito_vencida(usuario):
        return False
    flash('No se pudo procesar el pago. La tarjeta de credito esta vencida.', 'error')
    return True


def _descripcion_deuda(deuda):
    if deuda.referencia_transaccion and deuda.referencia_transaccion.startswith('recargo-alta-'):
        return 'Recargo de alta'

    turno = _obtener_turno_desde_pago(deuda)
    if turno:
        return f"{turno.actividad.upper()} - {turno.hora_inicio.strftime('%d/%m/%Y %H:%M')}"

    if deuda.tipo_clase == TipoClase.ABONADA:
        return 'Abono pendiente'
    return 'Clase pendiente'


def _abono_id_desde_pago(pago):
    referencia = (pago.referencia_transaccion or '').strip()
    partes = referencia.split('-')
    if len(partes) >= 3 and partes[0] == 'abono' and partes[1] == 'total':
        try:
            return int(partes[2])
        except ValueError:
            return None
    if len(partes) >= 2 and partes[0] == 'abono':
        try:
            return int(partes[1])
        except ValueError:
            return None
    return None


def _items_deuda_pendientes(usuario_id):
    deudas = _obtener_deudas_pendientes(usuario_id)
    items = []
    grupos_abono = {}
    deudas_suspension_no_abonada = []
    tiene_suspension_no_abonada = _tiene_suspension_no_abonada_activa(usuario_id)

    for deuda in deudas:
        abono_id = _abono_id_desde_pago(deuda) if deuda.tipo_clase == TipoClase.ABONADA else None
        if abono_id:
            grupos_abono.setdefault(abono_id, []).append(deuda)
            continue
        if tiene_suspension_no_abonada and deuda.tipo_clase == TipoClase.NO_ABONADA:
            deudas_suspension_no_abonada.append(deuda)
            continue

        items.append({
            'tipo': 'pago',
            'pago': deuda,
            'id': deuda.id,
            'concepto': _descripcion_deuda(deuda),
            'categoria': 'No abonada' if deuda.tipo_clase == TipoClase.NO_ABONADA else 'Suspensión',
            'fecha': deuda.fecha_pago,
            'monto': round(deuda.monto, 2),
            'pagable_individual': True,
            'accion_cliente': 'Pagar',
            'accion_empleado': 'Cobrar',
        })

    if deudas_suspension_no_abonada:
        deportes = []
        for deuda in deudas_suspension_no_abonada:
            turno = _obtener_turno_desde_pago(deuda)
            if turno and turno.actividad.upper() not in deportes:
                deportes.append(turno.actividad.upper())
        deportes_texto = ', '.join(deportes) if deportes else 'varios deportes'
        items.append({
            'tipo': 'suspension_no_abonada',
            'id': 'no_abonada',
            'concepto': f"Suspensión - {deportes_texto}",
            'categoria': 'Suspensión',
            'fecha': min((p.fecha_pago for p in deudas_suspension_no_abonada if p.fecha_pago), default=None),
            'monto': round(sum(p.monto for p in deudas_suspension_no_abonada), 2),
            'pagable_individual': True,
            'accion_cliente': 'Pagar suspensión',
            'accion_empleado': 'Cobrar suspensión',
        })

    for abono_id, pagos in grupos_abono.items():
        abono = AbonoCliente.query.get(abono_id)
        concepto = 'Abono pendiente'
        if abono:
            dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
            concepto = f"Abono {abono.actividad.upper()} - {dias[abono.dia_semana]} {abono.hora_inicio:02d}:00"
            if abono.estado == EstadoAbono.SUSPENDIDO:
                concepto = f"Suspensión - {abono.actividad.upper()} - {dias[abono.dia_semana]} {abono.hora_inicio:02d}:00"
        items.append({
            'tipo': 'abono',
            'abono': abono,
            'id': abono_id,
            'concepto': concepto,
            'categoria': 'Abonada',
            'fecha': min((p.fecha_pago for p in pagos if p.fecha_pago), default=None),
            'monto': round(sum(p.monto for p in pagos), 2),
            'pagable_individual': True,
            'accion_cliente': 'Pagar',
            'accion_empleado': 'Cobrar suspensión' if abono and abono.estado == EstadoAbono.SUSPENDIDO else 'Cobrar abono',
        })

    return sorted(items, key=lambda item: (item['fecha'] or datetime.utcnow(), item['concepto']))


def _reactivar_si_sin_deudas(usuario):
    deudas_no_abonadas = (
        Pago.query
        .filter_by(usuario_id=usuario.id, estado='pendiente', tipo_clase=TipoClase.NO_ABONADA)
        .filter(Pago.monto > 0)
        .count()
    )
    deudas_abonadas = (
        Pago.query
        .filter_by(usuario_id=usuario.id, estado='pendiente', tipo_clase=TipoClase.ABONADA)
        .filter(Pago.monto > 0)
        .count()
    )
    suspensiones = Suspension.query.filter_by(usuario_id=usuario.id, estado='activa').all()
    for suspension in suspensiones:
        motivo = (suspension.motivo or '').lower()
        resolver_no_abonada = ('no abonad' in motivo or '3 deudas' in motivo) and deudas_no_abonadas == 0
        resolver_abonada = 'abono' in motivo and deudas_abonadas == 0
        resolver_generica = 'mora' in motivo and deudas_no_abonadas == 0 and deudas_abonadas == 0
        if resolver_no_abonada or resolver_abonada or resolver_generica:
            suspension.estado = 'resuelta'
            suspension.fecha_resolucion = datetime.utcnow()

    if Suspension.query.filter_by(usuario_id=usuario.id, estado='activa').count() == 0:
        usuario.estado = EstadoUsuario.ACTIVO

    if deudas_abonadas > 0:
        return 0, []

    abonos_suspendidos = AbonoCliente.query.filter_by(
        usuario_id=usuario.id,
        estado=EstadoAbono.SUSPENDIDO,
    ).all()
    for abono in abonos_suspendidos:
        abono.estado = EstadoAbono.ACTIVO

    return 0, []


def _activar_abonos_pendientes_sin_deuda(usuario):
    abonos = AbonoCliente.query.filter_by(usuario_id=usuario.id, estado=EstadoAbono.PENDIENTE).all()
    for abono in abonos:
        if not _abono_tiene_pagos_pendientes(abono):
            abono.estado = EstadoAbono.ACTIVO


def _marcar_deudas_como_pagadas(usuario, metodo_pago):
    deudas = _obtener_deudas_pendientes(usuario.id)
    total = round(sum(deuda.monto for deuda in deudas), 2)
    for deuda in deudas:
        deuda.estado = 'completado'
        deuda.metodo_pago = metodo_pago
        deuda.fecha_pago = datetime.utcnow()
        if not deuda.referencia_transaccion:
            deuda.referencia_transaccion = f"deuda-{metodo_pago}-{usuario.id}-{int(datetime.utcnow().timestamp())}"

    _activar_abonos_pendientes_sin_deuda(usuario)
    reservas_restauradas, conflictos = _reactivar_si_sin_deudas(usuario)
    return total, reservas_restauradas, conflictos


def _marcar_deuda_como_pagada(usuario, deuda, metodo_pago):
    if deuda.usuario_id != usuario.id or deuda.estado != 'pendiente' or deuda.monto <= 0:
        return 0.0, 0, []

    total = round(deuda.monto, 2)
    deuda.estado = 'completado'
    deuda.metodo_pago = metodo_pago
    deuda.fecha_pago = datetime.utcnow()
    if not deuda.referencia_transaccion:
        deuda.referencia_transaccion = f"deuda-{metodo_pago}-{usuario.id}-{int(datetime.utcnow().timestamp())}"

    _activar_abonos_pendientes_sin_deuda(usuario)
    reservas_restauradas, conflictos = _reactivar_si_sin_deudas(usuario)
    return total, reservas_restauradas, conflictos


def _marcar_deuda_abono_como_pagada(usuario, abono, metodo_pago):
    if not abono or abono.usuario_id != usuario.id:
        return 0.0, 0, []

    pagos = _pagos_pendientes_de_abono(abono)
    total = round(sum(pago.monto for pago in pagos), 2)
    for pago in pagos:
        pago.estado = 'completado'
        pago.metodo_pago = metodo_pago
        pago.fecha_pago = datetime.utcnow()

    if pagos and abono.estado == EstadoAbono.PENDIENTE:
        abono.estado = EstadoAbono.ACTIVO

    _activar_abonos_pendientes_sin_deuda(usuario)
    reservas_restauradas, conflictos = _reactivar_si_sin_deudas(usuario)
    return total, reservas_restauradas, conflictos


def _marcar_deudas_no_abonadas_como_pagadas(usuario, metodo_pago):
    deudas = (
        Pago.query
        .filter_by(usuario_id=usuario.id, estado='pendiente', tipo_clase=TipoClase.NO_ABONADA)
        .filter(Pago.monto > 0)
        .all()
    )
    total = round(sum(deuda.monto for deuda in deudas), 2)
    for deuda in deudas:
        deuda.estado = 'completado'
        deuda.metodo_pago = metodo_pago
        deuda.fecha_pago = datetime.utcnow()
        if not deuda.referencia_transaccion:
            deuda.referencia_transaccion = f"suspension-no-abonada-{metodo_pago}-{usuario.id}-{int(datetime.utcnow().timestamp())}"

    _activar_abonos_pendientes_sin_deuda(usuario)
    reservas_restauradas, conflictos = _reactivar_si_sin_deudas(usuario)
    return total, reservas_restauradas, conflictos


def _cancelar_abono_si_sin_reservas_futuras(abono_id):
    if not abono_id:
        return False

    abono = AbonoCliente.query.get(abono_id)
    if not abono or abono.estado != EstadoAbono.ACTIVO:
        return False

    reservas_futuras = (
        Reserva.query
        .join(Turno, Reserva.turno_id == Turno.id)
        .filter(Reserva.abono_id == abono.id)
        .filter(Turno.hora_inicio >= _ahora_local())
        .count()
    )
    if reservas_futuras > 0:
        return False

    abono.estado = EstadoAbono.CANCELADO
    return True


def _cancelar_reservas_futuras_de_abono(abono, generar_creditos=False, eliminar_pagos_pendientes=True):
    ahora = datetime.utcnow()
    reservas = (
        Reserva.query
        .join(Turno, Reserva.turno_id == Turno.id)
        .filter(Reserva.abono_id == abono.id)
        .filter(Turno.hora_inicio >= ahora)
        .all()
    )

    turnos_liberados = []
    creditos_generados = []
    reservas_sin_credito_por_pago = 0
    reservas_sin_credito_por_tiempo = 0
    credito_de_abono_generado = False
    if eliminar_pagos_pendientes:
        for pago in _pagos_pendientes_de_abono(abono):
            db.session.delete(pago)

    for reserva in reservas:
        turno = reserva.turno
        pago_completado = _buscar_pago_abono_completado(reserva.usuario_id, abono.id)

        if generar_creditos and not credito_de_abono_generado:
            if _cancelacion_con_mas_de_48h(turno):
                credito = _crear_credito_por_cancelacion_abonada(reserva, turno, pago_completado)
                if credito:
                    creditos_generados.append(credito)
                    credito_de_abono_generado = True
                else:
                    reservas_sin_credito_por_pago += 1
            else:
                reservas_sin_credito_por_tiempo += 1

        turno.cupos_disponibles += 1
        db.session.delete(reserva)
        turnos_liberados.append(turno)

    for turno in turnos_liberados:
        _promover_siguiente_lista_espera(turno, tipo_clase=TipoClase.ABONADA)

    return {
        'creditos_generados': creditos_generados,
        'reservas_sin_credito_por_pago': reservas_sin_credito_por_pago,
        'reservas_sin_credito_por_tiempo': reservas_sin_credito_por_tiempo,
        'reservas_canceladas': len(reservas),
    }


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
    """Cancela administrativamente un turno puntual, ajusta pagos/créditos y notifica."""
    reservas = Reserva.query.filter_by(turno_id=turno.id).all()
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    resumen = {
        'reservas_canceladas': len(reservas),
        'creditos_generados': 0,
        'creditos_restaurados': 0,
        'reintegros_generados': 0,
        'monto_reintegrado': 0.0,
        'monto_descontado_pendiente': 0.0,
        'abonos_cancelados': 0,
    }
    abonos_afectados = set()

    for reserva in reservas:
        usuario = reserva.usuario
        credito_restaurado = _restaurar_credito_usado_por_reserva(reserva)
        if credito_restaurado:
            resumen['creditos_restaurados'] += 1

        if _es_reserva_abonada(reserva):
            abono = reserva.abono
            if abono:
                abonos_afectados.add(abono.id)

            monto_clase = _calcular_monto_reserva(
                turno.actividad,
                TipoClase.ABONADA,
                usuario,
                descuento_porcentaje=abono.descuento_porcentaje if abono else 0.0,
            )

            if not credito_restaurado:
                pagos_pendientes = _pagos_pendientes_de_abono(abono) if abono else []
                if pagos_pendientes:
                    descontado = _descontar_monto_de_pagos_pendientes(pagos_pendientes, monto_clase)
                    resumen['monto_descontado_pendiente'] = round(resumen['monto_descontado_pendiente'] + descontado, 2)
                else:
                    credito = _crear_credito_por_cancelacion_admin(reserva, turno, monto_clase)
                    if credito:
                        resumen['creditos_generados'] += 1
        else:
            pagos_completados = _pagos_de_reserva_por_estado(
                reserva.usuario_id,
                turno.id,
                TipoClase.NO_ABONADA,
                estados=['completado'],
            )
            pagos_pendientes = _pagos_de_reserva_por_estado(
                reserva.usuario_id,
                turno.id,
                TipoClase.NO_ABONADA,
                estados=['pendiente'],
            )

            for pago_pendiente in pagos_pendientes:
                db.session.delete(pago_pendiente)

            if not credito_restaurado:
                monto_pagado = round(sum(max(float(pago.monto or 0), 0.0) for pago in pagos_completados), 2)
                monto_clase = _calcular_monto_reserva(turno.actividad, TipoClase.NO_ABONADA, usuario)
                clase_totalmente_paga = monto_pagado >= monto_clase and not pagos_pendientes

                if clase_totalmente_paga:
                    credito = _crear_credito_por_cancelacion_admin(reserva, turno, monto_clase)
                    if credito:
                        resumen['creditos_generados'] += 1
                elif monto_pagado > 0:
                    metodo_pago = pagos_completados[-1].metodo_pago if pagos_completados else 'tarjeta_credito'
                    if _registrar_reintegro_admin(usuario, reserva, turno, monto_pagado, metodo_pago):
                        resumen['reintegros_generados'] += 1
                        resumen['monto_reintegrado'] = round(resumen['monto_reintegrado'] + monto_pagado, 2)

        asunto = 'Cancelación de turno - Club 360'
        cuerpo = (
            f"Hola {usuario.nombre},\n\n"
            f"Tu turno de {turno.actividad} del {turno.hora_inicio.strftime('%d/%m/%Y %H:%M')} "
            "fue cancelado por administración.\n"
            f"Motivo: {motivo}\n\n"
            "Si correspondía, se ajustó tu pago pendiente, reintegro o crédito."
        )
        enviar_email_simulado(base_dir, usuario.email, asunto, cuerpo)

        db.session.delete(reserva)

    for abono_id in abonos_afectados:
        if _cancelar_abono_si_sin_reservas_futuras(abono_id):
            resumen['abonos_cancelados'] += 1

    turno.cupos_disponibles = turno.capacidad_maxima
    # Limpia listas de espera porque el turno deja de existir operativamente.
    ListaEspera.query.filter_by(turno_id=turno.id).delete(synchronize_session=False)
    return resumen


def _obtener_turnos_recurrentes_activos(turno):
    inicio = turno.hora_inicio.time()
    fin = turno.hora_fin.time()
    dia_semana = turno.hora_inicio.weekday()

    turnos_misma_actividad = (
        Turno.query
        .filter_by(actividad=turno.actividad, cancelado=False)
        .filter(Turno.hora_fin >= _ahora_local())
        .order_by(Turno.hora_inicio.asc())
        .all()
    )
    return [
        turno_recurrente for turno_recurrente in turnos_misma_actividad
        if turno_recurrente.hora_inicio.weekday() == dia_semana
        and turno_recurrente.hora_inicio.time() == inicio
        and turno_recurrente.hora_fin.time() == fin
    ]


def _sumar_resumen_cancelacion_admin(total, parcial):
    for clave in (
        'reservas_canceladas',
        'creditos_generados',
        'creditos_restaurados',
        'reintegros_generados',
        'abonos_cancelados',
    ):
        total[clave] += parcial.get(clave, 0)

    for clave in ('monto_reintegrado', 'monto_descontado_pendiente'):
        total[clave] = round(total[clave] + parcial.get(clave, 0.0), 2)

    return total


def _notificar_admin_lista_espera_llena(turno, tipo_lista, cantidad):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    asunto = 'Alerta de lista de espera - Club 360'
    cuerpo = (
        "Hola Admin,\n\n"
        f"La lista de espera '{tipo_lista}' del turno {turno.actividad} "
        f"({turno.hora_inicio.strftime('%d/%m/%Y %H:%M')}) alcanzó {cantidad} personas."
    )
    enviar_email_simulado(base_dir, 'abonadoexample@gmail.com', asunto, cuerpo)


def _enviar_email_qr_reserva(reserva, asunto='Reserva confirmada - Club 360'):
    # El QR se consulta desde "Mis Turnos"; no se envía por mail al reservar.
    return False


def _enviar_emails_qr_reservas(reservas, asunto='Reserva confirmada - Club 360'):
    return 0


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
        validation_url = url_for('turnos.validar_asistencia_qr', qr_token=reserva.qr_token, _external=True)
        try:
            qr_path = generar_qr_asistencia(base_dir, reserva, validation_url)
        except RuntimeError as exc:
            qr_path = f"No generado: {exc}"
        asunto = 'Recordatorio de clase - Club 360'
        cuerpo = (
            f"Hola {usuario.nombre},\n\n"
            f"Te recordamos tu clase de {turno.actividad} el {turno.hora_inicio.strftime('%d/%m/%Y %H:%M')}.\n"
            f"Código de asistencia: {reserva.qr_token}\n"
            f"QR generado: {qr_path}\n"
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
    if current_user.tipo_usuario not in {TipoUsuario.CLIENTE, TipoUsuario.EMPLEADO}:
        flash('Esta vista está disponible solo para clientes y empleados', 'error')
        return redirect(url_for('dashboard'))

    if current_user.tipo_usuario == TipoUsuario.CLIENTE:
        _procesar_suspension_automatica(current_user)
        _enviar_recordatorios_qr(
            os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')),
            usuario_id=current_user.id,
        )
    
    query = (
        Turno.query
        .filter_by(cancelado=False)
        .filter(Turno.hora_inicio > _ahora_local())
        .filter(Turno.hora_inicio <= _datetime_limite_busqueda_turnos())
    )
    credito_actividad = request.args.get('credito', '').strip().lower()
    credito_disponible = None
    if current_user.tipo_usuario == TipoUsuario.CLIENTE and credito_actividad:
        credito_disponible = _obtener_credito_disponible(current_user.id, credito_actividad)

    turnos = [
        t for t in query.order_by(Turno.hora_inicio.asc()).all()
        if not _es_feriado_nacional(t.hora_inicio)
    ]

    reservas_usuario = set()
    if current_user.tipo_usuario == TipoUsuario.CLIENTE:
        reservas_usuario = {
            reserva.turno_id
            for reserva in Reserva.query.filter_by(usuario_id=current_user.id).all()
        }
    
    return render_template(
        'turnos/disponibles.html',
        turnos=turnos,
        reservas_usuario=reservas_usuario,
        permite_asignar_cliente=_es_empleado_o_admin(current_user),
        fecha_limite_busqueda=_fecha_limite_busqueda_turnos().isoformat(),
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

        turnos = (
            Turno.query
            .filter(Turno.hora_fin >= datetime.utcnow())
            .filter(Turno.cancelado == False)
            .order_by(Turno.hora_inicio.asc())
            .all()
        )
        eventos = []
        for turno in turnos:
            espera_abonados = ListaEspera.query.filter_by(turno_id=turno.id, tipo_clase=TipoClase.ABONADA).count()
            espera_no_abonados = ListaEspera.query.filter_by(turno_id=turno.id, tipo_clase=TipoClase.NO_ABONADA).count()
            invitacion_pendiente = bool(_obtener_invitacion_activa_turno(turno.id))
            eventos.append({
                'id': str(turno.id),
                'title': f"{turno.actividad.upper()} ({turno.cupos_disponibles}/{turno.capacidad_maxima})",
                'start': turno.hora_inicio.isoformat(),
                'end': turno.hora_fin.isoformat(),
                'backgroundColor': '#1565c0',
                'borderColor': '#0d47a1',
                'extendedProps': {
                    'cancelado': False,
                    'motivo_cancelacion': '',
                    'cupos': f"{turno.cupos_disponibles}/{turno.capacidad_maxima}",
                    'editar_url': url_for('turnos.editar_turno', turno_id=turno.id),
                    'cancelar_url': url_for('turnos.cancelar_turno_admin', turno_id=turno.id),
                    'eliminar_clase_url': url_for('turnos.eliminar_clase_admin', turno_id=turno.id),
                    'reservar_url': url_for('turnos.reservar_turno', turno_id=turno.id),
                    'detalle_url': url_for('turnos.buscar_turno', turno_id=turno.id),
                    'sin_cupos': turno.cupos_disponibles <= 0 or invitacion_pendiente,
                    'invitacion_pendiente': invitacion_pendiente,
                    'espera_abonados': espera_abonados,
                    'espera_no_abonados': espera_no_abonados,
                    'espera_total': espera_abonados + espera_no_abonados,
                }
            })
        return jsonify(eventos)

    query = (
        Turno.query
        .filter_by(cancelado=False)
        .filter(Turno.hora_inicio > _ahora_local())
        .filter(Turno.hora_inicio <= _datetime_limite_busqueda_turnos())
    )
    credito_actividad = request.args.get('credito', '').strip().lower()
    credito_disponible = None
    if current_user.tipo_usuario == TipoUsuario.CLIENTE and credito_actividad:
        credito_disponible = _obtener_credito_disponible(current_user.id, credito_actividad)

    turnos = [
        t for t in query.order_by(Turno.hora_inicio.asc()).all()
        if not _es_feriado_nacional(t.hora_inicio)
    ]
    reservas_usuario = set()
    if current_user.tipo_usuario == TipoUsuario.CLIENTE:
        reservas_usuario = {
            reserva.turno_id
            for reserva in Reserva.query.filter_by(usuario_id=current_user.id).all()
        }
    eventos = []
    for turno in turnos:
        invitacion_pendiente = bool(_obtener_invitacion_activa_turno(turno.id))
        cupos_disponibles_visibles = 0 if invitacion_pendiente else turno.cupos_disponibles
        espera_usuario = None
        if current_user.tipo_usuario == TipoUsuario.CLIENTE:
            espera_usuario = ListaEspera.query.filter_by(
                turno_id=turno.id,
                usuario_id=current_user.id,
            ).first()
        eventos.append({
            'id': str(turno.id),
            'title': f"{turno.actividad.upper()} ({turno.cupos_disponibles}/{turno.capacidad_maxima})",
            'start': turno.hora_inicio.isoformat(),
            'end': turno.hora_fin.isoformat(),
            'backgroundColor': '#2e7d32' if cupos_disponibles_visibles > 0 else '#ef6c00',
            'borderColor': '#1b5e20' if cupos_disponibles_visibles > 0 else '#e65100',
            'extendedProps': {
                'actividad': turno.actividad,
                'cupos': f"{turno.cupos_disponibles}/{turno.capacidad_maxima}",
                'cupos_disponibles': cupos_disponibles_visibles,
                'capacidad_maxima': turno.capacidad_maxima,
                'precio': _calcular_monto_reserva(turno.actividad, TipoClase.NO_ABONADA, current_user),
                'duracion_minutos': int((turno.hora_fin - turno.hora_inicio).total_seconds() // 60),
                'reservar_url': url_for('turnos.reservar_turno', turno_id=turno.id),
                'cancelar_url': url_for('turnos.cancelar_turno', turno_id=turno.id),
                'salir_lista_espera_url': url_for('turnos.salir_lista_espera_turno', turno_id=turno.id),
                'sin_cupos': cupos_disponibles_visibles <= 0,
                'ya_reservado': turno.id in reservas_usuario,
                'en_lista_espera': bool(espera_usuario),
                'tiene_abono': bool(_buscar_abono_activo_para_turno(current_user.id, turno)) if current_user.tipo_usuario == TipoUsuario.CLIENTE else False,
                'credito_disponible': bool(credito_disponible and credito_disponible.actividad == turno.actividad),
            }
        })
    return jsonify(eventos)


@turnos_bp.route('/reservar/<int:turno_id>', methods=['POST'])
@login_required
def reservar_turno(turno_id):
    """Reservar un turno."""
    turno = Turno.query.get_or_404(turno_id)
    tipo_clase = request.form.get('tipo_clase', TipoClase.NO_ABONADA).strip()
    usar_credito = request.form.get('usar_credito') == '1'

    if not _validar_tipo_clase(tipo_clase):
        flash('Debes elegir si la reserva es abonada o no abonada', 'error')
        return _resolver_redirect_reserva()

    cliente_objetivo, error_cliente = _obtener_cliente_objetivo_para_reserva()
    if error_cliente:
        flash(error_cliente, 'error')
        return _resolver_redirect_reserva()
    reserva_interna = cliente_objetivo.id != current_user.id
    metodo_pago_reserva, error_metodo_pago = _obtener_metodo_pago_reserva(reserva_interna)
    if error_metodo_pago:
        flash(error_metodo_pago, 'error')
        return _resolver_redirect_reserva()

    if not usar_credito:
        _procesar_suspension_automatica(cliente_objetivo)
    restricciones = _obtener_restricciones_suspension(cliente_objetivo)
    if not usar_credito and tipo_clase == TipoClase.ABONADA and restricciones['suspendido_abonado']:
        flash('La cuenta del cliente está suspendida para reservas abonadas. Debe regularizar su abono vencido.', 'error')
        return _resolver_redirect_reserva()
    if not usar_credito and tipo_clase == TipoClase.NO_ABONADA and restricciones['suspendido_no_abonado']:
        flash('La cuenta del cliente está suspendida para clases no abonadas por acumular 3 clases vencidas impagas.', 'error')
        return _resolver_redirect_reserva()

    if turno.cancelado:
        flash('Este turno ya no está disponible', 'error')
        return _resolver_redirect_reserva()

    if turno.hora_inicio <= _ahora_local():
        flash('Este turno ya comenzo y no se puede reservar', 'error')
        return _resolver_redirect_reserva()

    if current_user.tipo_usuario in {TipoUsuario.CLIENTE, TipoUsuario.EMPLEADO} and turno.hora_inicio > _datetime_limite_busqueda_turnos():
        flash('Solo se pueden reservar turnos del mes actual y el proximo.', 'error')
        return _resolver_redirect_reserva()

    if _es_feriado_nacional(turno.hora_inicio):
        flash('No se pueden reservar turnos en feriados nacionales', 'error')
        return _resolver_redirect_reserva()

    valido, error = _validar_regla_horaria(turno.hora_inicio, turno.hora_fin)
    if not valido:
        flash(f'El turno no cumple reglas horarias: {error}', 'error')
        return _resolver_redirect_reserva()
    
    # Verificar si el usuario ya tiene reservado este turno
    turno_existente = Reserva.query.filter_by(
        turno_id=turno_id,
        usuario_id=cliente_objetivo.id
    ).first()
    
    if turno_existente:
        flash('El cliente ya tiene reservado este turno' if reserva_interna else 'Ya tienes reservado este turno', 'error')
        return _resolver_redirect_reserva()

    invitacion_activa = _obtener_invitacion_activa_turno(turno_id)
    if invitacion_activa and invitacion_activa.usuario_id != cliente_objetivo.id:
        existente_espera = ListaEspera.query.filter_by(
            turno_id=turno_id,
            usuario_id=cliente_objetivo.id
        ).first()
        if existente_espera:
            flash('El cliente ya está en la lista de espera para este turno' if reserva_interna else 'Ya estás en la lista de espera para este turno', 'info')
        else:
            _agregar_a_lista_espera(turno, cliente_objetivo.id, tipo_clase)
            db.session.commit()
            flash(f'El cupo liberado está pendiente de confirmación. {cliente_objetivo.nombre} {cliente_objetivo.apellido} fue agregado a la lista de espera.', 'info')
        return _resolver_redirect_reserva()

    if invitacion_activa and invitacion_activa.usuario_id == cliente_objetivo.id:
        tipo_clase = invitacion_activa.tipo_clase

    if turno.cupos_disponibles > 0:
        credito_aplicado = 0.0
        monto_final = 0.0
        estado_pago = 'completado'
        reserva_para_qr = None
        credito = _obtener_credito_disponible(cliente_objetivo.id, turno.actividad) if usar_credito else None
        if usar_credito and not credito:
            flash('No hay créditos disponibles para esta actividad.', 'error')
            return _resolver_redirect_reserva()

        if usar_credito:
            if restricciones['suspendido_no_abonado']:
                flash('La reserva falló debido a que el usuario se encuentra suspendido para turnos no abonados.', 'error')
                return _resolver_redirect_reserva()

            reserva = Reserva(
                usuario_id=cliente_objetivo.id,
                turno_id=turno_id,
                tipo_clase=TipoClase.NO_ABONADA,
                qr_token=secrets.token_urlsafe(24),
            )
            db.session.add(reserva)
            turno.cupos_disponibles -= 1
            db.session.flush()
            _marcar_credito_usado(credito, reserva)
            _eliminar_espera_usuario_turno(turno_id, cliente_objetivo.id)
            db.session.commit()
            _enviar_email_qr_reserva(reserva)
            flash('Ha utilizado su credito y se reservo el turno exitosamente.', 'success')
            return _resolver_redirect_reserva()

        if tipo_clase == TipoClase.ABONADA:
            abono = _buscar_abono_activo_para_turno(cliente_objetivo.id, turno)
            if not abono:
                abono, creado_abono, conflictos, reservas_creadas, turnos_en_espera, _, pago_inmediato = _crear_abono_mensual_para_turno(
                    cliente_objetivo,
                    turno,
                    credito=credito,
                    metodo_pago=metodo_pago_reserva,
                )
                if conflictos:
                    db.session.rollback()
                    flash(
                        'No se pudo reservar el turno abonado para el cliente.'
                        if reserva_interna else
                        'No se pudo reservar tu turno abonado.',
                        'error'
                    )
                    for conflicto in conflictos:
                        flash(conflicto, 'warning')
                    return _resolver_redirect_reserva()

                if creado_abono:
                    if _abono_tiene_pagos_pendientes(abono):
                        abono.estado = EstadoAbono.PENDIENTE
                    _eliminar_espera_usuario_turno(turno_id, cliente_objetivo.id)
                    db.session.commit()
                    reservas_qr = (
                        Reserva.query
                        .filter_by(usuario_id=cliente_objetivo.id, abono_id=abono.id)
                        .join(Turno, Reserva.turno_id == Turno.id)
                        .filter(Turno.hora_inicio >= _ahora_local())
                        .order_by(Turno.hora_inicio.asc())
                        .all()
                    )
                    _enviar_emails_qr_reservas(reservas_qr)
                    pago_abono = _buscar_pago_abono_completado(cliente_objetivo.id, abono.id)
                    monto_cobrado = pago_abono.monto if pago_abono else 0.0
                    if abono.estado == EstadoAbono.PENDIENTE:
                        mensaje = (
                            f'Se reservaron {reservas_creadas} clase(s) del abono para {cliente_objetivo.nombre} {cliente_objetivo.apellido}, '
                            'y se generó la deuda del abono para pagar desde Mis Deudas.'
                        )
                    elif metodo_pago_reserva == 'efectivo':
                        mensaje = (
                            f'Se confirmaron {reservas_creadas} reserva(s) abonadas para {cliente_objetivo.nombre} {cliente_objetivo.apellido}. '
                            f'Se registró pago en efectivo por ${monto_cobrado:.2f}.'
                        )
                    else:
                        mensaje = (
                            f'Se confirmaron {reservas_creadas} reserva(s) abonadas para {cliente_objetivo.nombre} {cliente_objetivo.apellido}. '
                            f'Se cobró automáticamente ${monto_cobrado:.2f} con tarjeta de crédito.'
                        )
                    if credito and credito.estado == EstadoCredito.USADO:
                        mensaje += ' Se aplicó un crédito a una clase del abono.'
                    flash(mensaje, 'success')
                    if turnos_en_espera:
                        flash('Alguno de los turnos del abono no tenía cupo y fue agregado a la lista de espera.', 'info')
                    for turno_espera in turnos_en_espera:
                        personas_en_espera = ListaEspera.query.filter_by(turno_id=turno_espera.id).count()
                        if personas_en_espera == 10:
                            _notificar_admin_lista_espera_llena(turno_espera, TIPO_LISTA_GENERAL, personas_en_espera)
                        flash(
                            f'{cliente_objetivo.nombre} {cliente_objetivo.apellido} fue agregado a la lista de espera de '
                            f'{turno_espera.actividad.upper()} del {turno_espera.hora_inicio.strftime("%d/%m/%Y %H:%M")} '
                            'porque ya no tenía cupo.',
                            'info'
                        )
                    return _resolver_redirect_reserva()

            _, conflicto = _asegurar_reserva_abono(
                turno,
                cliente_objetivo,
                abono,
                crear_pago=True,
                credito=credito,
                metodo_pago=metodo_pago_reserva,
            )
            if conflicto:
                flash(conflicto, 'error')
                return _resolver_redirect_reserva()

            reserva_para_qr = (
                Reserva.query
                .filter_by(turno_id=turno_id, usuario_id=cliente_objetivo.id)
                .first()
            )
            pago_generado = _buscar_pago_abono_completado(cliente_objetivo.id, abono.id)
            if _abono_tiene_pagos_pendientes(abono):
                abono.estado = EstadoAbono.PENDIENTE
            monto_final = pago_generado.monto if pago_generado else 0.0
            estado_pago = pago_generado.estado if pago_generado else 'completado'
            if credito and credito.estado == EstadoCredito.USADO:
                credito_aplicado = round(credito.monto, 2)
        else:
            reserva = Reserva(
                usuario_id=cliente_objetivo.id,
                turno_id=turno_id,
                tipo_clase=tipo_clase,
                qr_token=secrets.token_urlsafe(24),
            )
            db.session.add(reserva)
            turno.cupos_disponibles -= 1
            db.session.flush()
            if credito:
                _marcar_credito_usado(credito, reserva)
            credito_aplicado, monto_final, estado_pago = _crear_pago_pendiente_reserva(
                cliente_objetivo,
                turno,
                tipo_clase,
                f"reserva-{turno_id}-{cliente_objetivo.id}-{int(datetime.utcnow().timestamp())}",
                credito=credito,
                metodo_pago=metodo_pago_reserva,
            )
            if metodo_pago_reserva == 'tarjeta_credito' and estado_pago == 'pendiente':
                db.session.rollback()
                flash('No se pudo cobrar la seña con tarjeta de crédito. No se pudo reservar el turno.', 'error')
                return _resolver_redirect_reserva()

        _eliminar_espera_usuario_turno(turno_id, cliente_objetivo.id)
        db.session.commit()
        if tipo_clase == TipoClase.ABONADA and reserva_para_qr:
            _enviar_email_qr_reserva(reserva_para_qr)
        elif tipo_clase == TipoClase.NO_ABONADA:
            _enviar_email_qr_reserva(reserva)
        if credito_aplicado > 0:
            flash(f'Turno reservado. Se aplicó un crédito de ${credito_aplicado:.2f}', 'success')
        if tipo_clase == TipoClase.ABONADA:
            extra_credito = ' Se aplicó un crédito.' if credito_aplicado > 0 else ''
            if abono.estado == EstadoAbono.PENDIENTE:
                flash('Reserva abonada pendiente de pago. Podés abonar la deuda desde Mis Deudas.', 'warning')
            elif metodo_pago_reserva == 'efectivo':
                flash(f'Reserva abonada confirmada para {cliente_objetivo.nombre} {cliente_objetivo.apellido}.{extra_credito}', 'success')
            else:
                flash(f'Reserva abonada confirmada para {cliente_objetivo.nombre} {cliente_objetivo.apellido}.{extra_credito}', 'success')
        else:
            if estado_pago == 'pendiente':
                if metodo_pago_reserva == 'pendiente':
                    flash(
                        f'Turno reservado para {cliente_objetivo.nombre} {cliente_objetivo.apellido}. '
                        'Se generó la deuda pendiente para este turno.',
                        'warning',
                    )
                else:
                    flash(
                        f'Turno reservado para {cliente_objetivo.nombre} {cliente_objetivo.apellido}, '
                        'pero el pago quedó pendiente por saldo insuficiente en la tarjeta.',
                        'warning',
                    )
            elif metodo_pago_reserva == 'efectivo':
                flash(f'Turno reservado exitosamente para {cliente_objetivo.nombre} {cliente_objetivo.apellido}. Se registró una seña en efectivo por ${monto_final:.2f}.', 'success')
            else:
                flash(f'Turno reservado exitosamente para {cliente_objetivo.nombre} {cliente_objetivo.apellido}. Se cobró una seña de ${monto_final:.2f} con tarjeta de crédito.', 'success')
    else:
        existente_espera = ListaEspera.query.filter_by(
            turno_id=turno_id,
            usuario_id=cliente_objetivo.id
        ).first()
        if existente_espera:
            flash('El cliente ya está en la lista de espera para este turno' if reserva_interna else 'Ya estás en la lista de espera para este turno', 'info')
            return _resolver_redirect_reserva()

        _agregar_a_lista_espera(turno, cliente_objetivo.id, tipo_clase)
        db.session.commit()

        personas_en_espera = ListaEspera.query.filter_by(turno_id=turno_id).count()
        if personas_en_espera == 10:
            _notificar_admin_lista_espera_llena(turno, TIPO_LISTA_GENERAL, personas_en_espera)

        flash(f'Turno lleno. {cliente_objetivo.nombre} {cliente_objetivo.apellido} fue agregado a la lista de espera', 'info')
    
    return _resolver_redirect_reserva()


@turnos_bp.route('/lista-espera/<int:item_id>/rechazar', methods=['POST'])
@login_required
def rechazar_cupo_lista_espera(item_id):
    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Esta acción está disponible solo para clientes', 'error')
        return redirect(url_for('dashboard'))

    item = ListaEspera.query.get_or_404(item_id)
    if item.usuario_id != current_user.id or item.estado != ESTADO_ESPERA_NOTIFICADO:
        flash('No tienes una invitación activa para este cupo', 'error')
        return redirect(url_for('dashboard'))

    turno = item.turno
    tipo_cupo_liberado = item.tipo_cupo_liberado or item.tipo_clase
    db.session.delete(item)
    db.session.flush()
    _recalcular_posiciones_lista(turno.id)
    _notificar_siguiente_lista_espera(turno, tipo_cupo_liberado)
    db.session.commit()

    flash('Te quitamos de la lista de espera de ese turno.', 'info')
    return redirect(url_for('turnos.ver_turnos_disponibles'))


@turnos_bp.route('/lista-espera/turno/<int:turno_id>/salir', methods=['POST'])
@login_required
def salir_lista_espera_turno(turno_id):
    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Esta acción está disponible solo para clientes', 'error')
        return redirect(url_for('turnos.ver_turnos_disponibles'))

    item = ListaEspera.query.filter_by(
        turno_id=turno_id,
        usuario_id=current_user.id,
    ).first()
    if not item:
        flash('No estás en la lista de espera de ese turno.', 'info')
        return redirect(url_for('turnos.ver_turnos_disponibles'))

    turno = item.turno
    estaba_notificado = item.estado == ESTADO_ESPERA_NOTIFICADO
    tipo_cupo_liberado = item.tipo_cupo_liberado or item.tipo_clase
    db.session.delete(item)
    db.session.flush()
    _recalcular_posiciones_lista(turno.id)
    if estaba_notificado:
        _notificar_siguiente_lista_espera(turno, tipo_cupo_liberado)
    db.session.commit()

    flash('Saliste de la lista de espera de ese turno.', 'info')
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
    
    es_reserva_abonada = _es_reserva_abonada(reserva)
    tipo_cupo_liberado = TipoClase.ABONADA if es_reserva_abonada else TipoClase.NO_ABONADA
    credito_generado = None
    pago_reserva = _buscar_pago_abono_completado(current_user.id, reserva.abono_id) if es_reserva_abonada else None
    abono_id_cancelado = reserva.abono_id if es_reserva_abonada else None
    db.session.delete(reserva)
    turno.cupos_disponibles += 1

    horas = _horas_anticipacion(turno)
    if es_reserva_abonada:
        current_user.cancelaciones_abonado += 1
        if _cancelacion_con_mas_de_48h(turno):
            credito_generado = _crear_credito_por_cancelacion_abonada(reserva, turno, pago_reserva)
            if not credito_generado:
                flash('Cancelación abonada con +48h: no se genera crédito porque no había pago confirmado.', 'info')
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

    abono_cancelado_por_vacio = _cancelar_abono_si_sin_reservas_futuras(abono_id_cancelado)
    _notificar_siguiente_lista_espera(turno, tipo_cupo_liberado)

    db.session.commit()
    
    if credito_generado:
        flash(
            f'Turno cancelado exitosamente. Se generó un crédito de {turno.actividad.upper()} por ${credito_generado.monto:.2f}, válido hasta {credito_generado.fecha_vencimiento.strftime("%d/%m/%Y")}.',
            'success',
        )
    else:
        flash('Turno cancelado exitosamente', 'success')
    if abono_cancelado_por_vacio:
        flash('El abono quedó sin clases futuras y fue dado de baja automáticamente.', 'info')
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
        .filter(Turno.hora_fin >= datetime.utcnow())
        .order_by(Turno.hora_inicio.asc())
        .all()
    )

    enviados = _enviar_recordatorios_qr(
        os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')),
        usuario_id=current_user.id,
    )
    if enviados:
        flash('Se enviaron recordatorios de clases con QR para hoy', 'info')

    reservas_info = []
    reservas_confirmadas_info = []
    for reserva in reservas:
        item = {
            'reserva': reserva,
            'estado_pago': _estado_cliente_de_reserva(reserva),
        }
        if reserva.asistencia_validada:
            reservas_confirmadas_info.append(item)
        else:
            reservas_info.append(item)

    return render_template(
        'turnos/mis_turnos.html',
        reservas_info=reservas_info,
        reservas_confirmadas_info=reservas_confirmadas_info,
    )


@turnos_bp.route('/mis-turnos/<int:reserva_id>/qr')
@login_required
def ver_qr_reserva(reserva_id):
    """Muestra el QR de asistencia de una reserva del cliente."""
    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Esta vista está disponible solo para clientes', 'error')
        return redirect(url_for('dashboard'))

    reserva = Reserva.query.get_or_404(reserva_id)
    if reserva.usuario_id != current_user.id:
        flash('No tienes permisos para ver este QR', 'error')
        return redirect(url_for('turnos.mis_turnos'))

    return render_template(
        'turnos/ver_qr.html',
        reserva=reserva,
    )


@turnos_bp.route('/mis-turnos/<int:reserva_id>/qr/imagen')
@login_required
def imagen_qr_reserva(reserva_id):
    """Devuelve la imagen PNG del QR de asistencia de una reserva del cliente."""
    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Esta vista está disponible solo para clientes', 'error')
        return redirect(url_for('dashboard'))

    reserva = Reserva.query.get_or_404(reserva_id)
    if reserva.usuario_id != current_user.id:
        flash('No tienes permisos para ver este QR', 'error')
        return redirect(url_for('turnos.mis_turnos'))

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    validation_url = url_for('turnos.validar_asistencia_qr', qr_token=reserva.qr_token, _external=True)
    try:
        qr_path = generar_qr_asistencia(base_dir, reserva, validation_url)
    except RuntimeError:
        return '', 503

    return send_file(qr_path, mimetype='image/png', max_age=0)


@turnos_bp.route('/buscar-turnos-cliente')
@login_required
def buscar_turnos_cliente_empleado():
    if current_user.tipo_usuario != TipoUsuario.EMPLEADO:
        flash('Esta sección está disponible solo para empleados', 'error')
        return redirect(url_for('dashboard'))

    dni = request.args.get('dni', '').strip()
    cliente = None
    reservas_info = []

    if dni:
        if not re.match(r'^\d{8}$', dni):
            flash('El DNI debe tener 8 dígitos sin puntos', 'error')
        else:
            cliente = Usuario.query.filter_by(dni=dni, tipo_usuario=TipoUsuario.CLIENTE).first()
            if not cliente:
                flash('No existe un cliente registrado con ese DNI', 'error')
            else:
                reservas = (
                    Reserva.query
                    .join(Turno, Reserva.turno_id == Turno.id)
                    .filter(Reserva.usuario_id == cliente.id)
                    .filter(Turno.hora_fin >= _ahora_local())
                    .order_by(Turno.hora_inicio.asc())
                    .all()
                )
                for reserva in reservas:
                    pagos_pendientes = _pagos_pendientes_de_reserva(reserva)
                    deuda = round(sum(pago.monto for pago in pagos_pendientes), 2)
                    reservas_info.append({
                        'reserva': reserva,
                        'deuda': deuda,
                        'pagos_pendientes': pagos_pendientes,
                    })

    return render_template(
        'turnos/buscar_turnos_cliente.html',
        dni=dni,
        cliente=cliente,
        reservas_info=reservas_info,
    )


@turnos_bp.route('/buscar-turnos-cliente/<int:usuario_id>/<int:reserva_id>/pagar-efectivo', methods=['POST'])
@login_required
def registrar_pago_efectivo_turno_cliente(usuario_id, reserva_id):
    if current_user.tipo_usuario != TipoUsuario.EMPLEADO:
        flash('Esta acción está disponible solo para empleados', 'error')
        return redirect(url_for('dashboard'))

    cliente = Usuario.query.get_or_404(usuario_id)
    reserva = Reserva.query.get_or_404(reserva_id)
    if cliente.tipo_usuario != TipoUsuario.CLIENTE or reserva.usuario_id != cliente.id:
        flash('La reserva indicada no corresponde al cliente.', 'error')
        return redirect(url_for('turnos.buscar_turnos_cliente_empleado'))

    pagos_pendientes = _pagos_pendientes_de_reserva(reserva)
    total = round(sum(pago.monto for pago in pagos_pendientes), 2)
    if total <= 0:
        flash('Ese turno no tiene deuda pendiente.', 'info')
        return redirect(url_for('turnos.buscar_turnos_cliente_empleado', dni=cliente.dni))

    for pago in pagos_pendientes:
        pago.estado = 'completado'
        pago.metodo_pago = 'efectivo'
        pago.fecha_pago = datetime.utcnow()
        if not pago.referencia_transaccion:
            pago.referencia_transaccion = f"efectivo-turno-{reserva.turno_id}-{cliente.id}-{int(datetime.utcnow().timestamp())}"

    _activar_abonos_pendientes_sin_deuda(cliente)
    _reactivar_si_sin_deudas(cliente)
    db.session.commit()

    flash(
        f'Se registró pago en efectivo por ${total:.2f} para el turno de '
        f'{reserva.turno.actividad.upper()} del {reserva.turno.hora_inicio.strftime("%d/%m/%Y %H:%M")}.',
        'success',
    )
    return redirect(url_for('turnos.buscar_turnos_cliente_empleado', dni=cliente.dni))


@turnos_bp.route('/buscar/<int:turno_id>')
@login_required
def buscar_turno(turno_id):
    """Ver detalle de un turno para administradores."""
    if not _es_admin(current_user):
        flash('No tienes permisos para acceder a esta funcionalidad', 'error')
        return redirect(url_for('index'))

    turno = Turno.query.get_or_404(turno_id)
    listas = {
        TipoClase.ABONADA.value: (
            ListaEspera.query
            .filter_by(turno_id=turno.id, tipo_clase=TipoClase.ABONADA)
            .order_by(ListaEspera.posicion.asc(), ListaEspera.fecha_registro.asc())
            .all()
        ),
        TipoClase.NO_ABONADA.value: (
            ListaEspera.query
            .filter_by(turno_id=turno.id, tipo_clase=TipoClase.NO_ABONADA)
            .order_by(ListaEspera.posicion.asc(), ListaEspera.fecha_registro.asc())
            .all()
        ),
    }
    return render_template('turnos/detalle.html', turno=turno, listas=listas)


@turnos_bp.route('/validar-asistencia/<string:qr_token>', methods=['GET', 'POST'])
def validar_asistencia_qr(qr_token):
    """Validación presencial de asistencia mediante QR."""
    if not current_user.is_authenticated or not _es_empleado_o_admin(current_user):
        flash('No tienes permisos para escanear un QR de asistencia, intenta iniciar sesion con una cuenta de empleado valida', 'error')
        return redirect(url_for('auth.login'))

    reserva = Reserva.query.filter_by(qr_token=qr_token).first()
    if not reserva:
        flash('Ese QR no contiene datos válidos.', 'error')
        return redirect(url_for('dashboard'))

    if reserva.asistencia_validada:
        flash('El qr provisto ya fue registrado escaneado previamente, intente con otro', 'error')
        return redirect(url_for('dashboard'))

    monto_pendiente = _monto_pendiente_de_reserva(reserva)
    if request.method == 'POST':
        if monto_pendiente > 0:
            flash('No se puede validar la asistencia hasta que no se termine de pagar el turno', 'error')
            return redirect(url_for('turnos.validar_asistencia_qr', qr_token=qr_token))

        reserva.asistencia_validada = True
        reserva.fecha_asistencia = datetime.utcnow()
        db.session.commit()
        flash('Asistencia validada correctamente', 'success')
        return redirect(url_for('dashboard'))

    return render_template(
        'turnos/validar_asistencia.html',
        reserva=reserva,
        monto_pendiente=monto_pendiente,
    )


@turnos_bp.route('/validar-asistencia', methods=['GET', 'POST'])
@login_required
def validar_asistencia_manual():
    """Permite al personal validar asistencia ingresando un token QR manualmente."""
    if not _es_empleado_o_admin(current_user):
        flash('No tienes permisos para escanear un QR de asistencia, intenta iniciar sesion con una cuenta de empleado valida', 'error')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        qr_token = request.form.get('qr_token', '').strip()
        if qr_token.startswith('QR:'):
            qr_token = qr_token[3:].strip()
        if '/validar-asistencia/' in qr_token:
            qr_token = qr_token.rstrip('/').rsplit('/', 1)[-1]
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
    return render_template(
        'turnos/administrar.html',
        turnos=turnos,
        horas_disponibles=HORAS_DISPONIBLES,
        fecha_limite_busqueda=_fecha_limite_busqueda_turnos().isoformat(),
    )


@turnos_bp.route('/mis-deudas')
@login_required
def mis_deudas():
    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Esta sección está disponible solo para clientes', 'error')
        return redirect(url_for('dashboard'))

    _procesar_suspension_automatica(current_user)
    items_deuda = _items_deuda_pendientes(current_user.id)
    total = round(sum(item['monto'] for item in items_deuda), 2)
    return render_template(
        'turnos/mis_deudas.html',
        items_deuda=items_deuda,
        total=total,
    )


@turnos_bp.route('/mis-deudas/pagar', methods=['POST'])
@login_required
def pagar_mis_deudas():
    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Esta sección está disponible solo para clientes', 'error')
        return redirect(url_for('dashboard'))

    total = _total_deudas_pendientes(current_user.id)
    if total <= 0:
        flash('No tenés deudas pendientes.', 'info')
        return redirect(url_for('turnos.mis_deudas'))

    if _rechazar_pago_tarjeta_vencida(current_user):
        return redirect(url_for('turnos.mis_deudas'))

    saldo = float(current_user.tarjeta_credito_saldo or 0.0)
    if saldo < total:
        flash(f'No se pudo procesar el pago. Saldo insuficiente. Total a abonar: ${total:.2f}.', 'error')
        return redirect(url_for('turnos.mis_deudas'))

    current_user.tarjeta_credito_saldo = round(saldo - total, 2)
    total_pagado, _, _ = _marcar_deudas_como_pagadas(current_user, 'tarjeta_credito')
    db.session.commit()

    flash(f'Se abonó ${total_pagado:.2f} con tarjeta de crédito.', 'success')
    return redirect(url_for('turnos.mis_deudas'))


@turnos_bp.route('/mis-deudas/pagar/<int:pago_id>', methods=['POST'])
@login_required
def pagar_mi_deuda(pago_id):
    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Esta sección está disponible solo para clientes', 'error')
        return redirect(url_for('dashboard'))

    deuda = Pago.query.get_or_404(pago_id)
    if deuda.usuario_id != current_user.id or deuda.estado != 'pendiente' or deuda.monto <= 0:
        flash('La deuda indicada no está disponible para pago.', 'error')
        return redirect(url_for('turnos.mis_deudas'))
    if deuda.tipo_clase == TipoClase.ABONADA and _abono_id_desde_pago(deuda):
        flash('Las deudas de abono se pagan completas, no clase por clase.', 'warning')
        return redirect(url_for('turnos.mis_deudas'))

    if _rechazar_pago_tarjeta_vencida(current_user):
        return redirect(url_for('turnos.mis_deudas'))

    monto = round(deuda.monto, 2)
    saldo = float(current_user.tarjeta_credito_saldo or 0.0)
    if saldo < monto:
        flash(f'No se pudo procesar el pago. Saldo insuficiente. Total a abonar: ${monto:.2f}.', 'error')
        return redirect(url_for('turnos.mis_deudas'))

    current_user.tarjeta_credito_saldo = round(saldo - monto, 2)
    total_pagado, _, _ = _marcar_deuda_como_pagada(current_user, deuda, 'tarjeta_credito')
    db.session.commit()

    flash(f'Se abonó ${total_pagado:.2f} con tarjeta de crédito.', 'success')
    return redirect(url_for('turnos.mis_deudas'))


@turnos_bp.route('/mis-deudas/pagar-abono/<int:abono_id>', methods=['POST'])
@login_required
def pagar_mi_deuda_abono(abono_id):
    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Esta sección está disponible solo para clientes', 'error')
        return redirect(url_for('dashboard'))

    abono = AbonoCliente.query.get_or_404(abono_id)
    if abono.usuario_id != current_user.id:
        flash('No tienes permisos para pagar este abono', 'error')
        return redirect(url_for('turnos.mis_deudas'))

    total = round(sum(pago.monto for pago in _pagos_pendientes_de_abono(abono)), 2)
    if total <= 0:
        flash('Este abono no tiene deuda pendiente.', 'info')
        return redirect(url_for('turnos.mis_deudas'))

    if _rechazar_pago_tarjeta_vencida(current_user):
        return redirect(url_for('turnos.mis_deudas'))

    saldo = float(current_user.tarjeta_credito_saldo or 0.0)
    if saldo < total:
        flash(f'No se pudo procesar el pago. Saldo insuficiente. Total a abonar: ${total:.2f}.', 'error')
        return redirect(url_for('turnos.mis_deudas'))

    current_user.tarjeta_credito_saldo = round(saldo - total, 2)
    total_pagado, _, _ = _marcar_deuda_abono_como_pagada(current_user, abono, 'tarjeta_credito')
    db.session.commit()

    flash(f'Se abonó ${total_pagado:.2f} con tarjeta de crédito.', 'success')
    return redirect(url_for('turnos.mis_deudas'))


@turnos_bp.route('/mis-deudas/pagar-suspension-no-abonada', methods=['POST'])
@login_required
def pagar_mi_suspension_no_abonada():
    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Esta sección está disponible solo para clientes', 'error')
        return redirect(url_for('dashboard'))

    total = round(sum(
        deuda.monto for deuda in Pago.query
        .filter_by(usuario_id=current_user.id, estado='pendiente', tipo_clase=TipoClase.NO_ABONADA)
        .filter(Pago.monto > 0)
        .all()
    ), 2)
    if total <= 0:
        flash('No tenés deuda de suspensión pendiente.', 'info')
        return redirect(url_for('turnos.mis_deudas'))

    if _rechazar_pago_tarjeta_vencida(current_user):
        return redirect(url_for('turnos.mis_deudas'))

    saldo = float(current_user.tarjeta_credito_saldo or 0.0)
    if saldo < total:
        flash(f'No se pudo procesar el pago. Saldo insuficiente. Total a abonar: ${total:.2f}.', 'error')
        return redirect(url_for('turnos.mis_deudas'))

    current_user.tarjeta_credito_saldo = round(saldo - total, 2)
    total_pagado, _, _ = _marcar_deudas_no_abonadas_como_pagadas(current_user, 'tarjeta_credito')
    db.session.commit()

    flash(f'Se abonó ${total_pagado:.2f} con tarjeta de crédito.', 'success')
    return redirect(url_for('turnos.mis_deudas'))


@turnos_bp.route('/cobrar-deudas')
@login_required
def cobrar_deudas():
    if not _es_admin(current_user):
        flash('No tienes permisos para cobrar deudas', 'error')
        return redirect(url_for('dashboard'))

    email = request.args.get('email', '').strip().lower()
    cliente = None
    deudas = []
    total = 0.0
    if email:
        cliente = Usuario.query.filter(func.lower(Usuario.email) == email).first()
        if not cliente or cliente.tipo_usuario != TipoUsuario.CLIENTE:
            flash('No existe un cliente registrado con ese mail', 'error')
            cliente = None
        else:
            _procesar_suspension_automatica(cliente)
            deudas = _items_deuda_pendientes(cliente.id)
            total = round(sum(item['monto'] for item in deudas), 2)

    return render_template(
        'turnos/cobrar_deudas.html',
        email=email,
        cliente=cliente,
        deudas=deudas,
        total=total,
    )


@turnos_bp.route('/cobrar-deudas/<int:usuario_id>', methods=['POST'])
@login_required
def cobrar_deudas_cliente(usuario_id):
    if not _es_admin(current_user):
        flash('No tienes permisos para cobrar deudas', 'error')
        return redirect(url_for('dashboard'))

    cliente = Usuario.query.get_or_404(usuario_id)
    if cliente.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Solo se pueden cobrar deudas de clientes.', 'error')
        return redirect(url_for('turnos.cobrar_deudas'))

    total = _total_deudas_pendientes(cliente.id)
    if total <= 0:
        flash('El cliente no tiene deudas pendientes.', 'info')
        return redirect(url_for('turnos.cobrar_deudas', email=cliente.email))

    total_pagado, _, _ = _marcar_deudas_como_pagadas(cliente, 'efectivo')
    db.session.commit()

    flash(f'Se cobró ${total_pagado:.2f} en efectivo y se saldó la deuda de {cliente.nombre} {cliente.apellido}.', 'success')
    return redirect(url_for('turnos.cobrar_deudas', email=cliente.email))


@turnos_bp.route('/cobrar-deudas/<int:usuario_id>/<int:pago_id>', methods=['POST'])
@login_required
def cobrar_deuda_cliente(usuario_id, pago_id):
    if not _es_admin(current_user):
        flash('No tienes permisos para cobrar deudas', 'error')
        return redirect(url_for('dashboard'))

    cliente = Usuario.query.get_or_404(usuario_id)
    if cliente.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Solo se pueden cobrar deudas de clientes.', 'error')
        return redirect(url_for('turnos.cobrar_deudas'))

    deuda = Pago.query.get_or_404(pago_id)
    if deuda.usuario_id != cliente.id or deuda.estado != 'pendiente' or deuda.monto <= 0:
        flash('La deuda indicada no está disponible para cobro.', 'error')
        return redirect(url_for('turnos.cobrar_deudas', email=cliente.email))
    if deuda.tipo_clase == TipoClase.ABONADA and _abono_id_desde_pago(deuda):
        flash('Las deudas de abono se cobran completas, no clase por clase.', 'warning')
        return redirect(url_for('turnos.cobrar_deudas', email=cliente.email))

    total_pagado, _, _ = _marcar_deuda_como_pagada(cliente, deuda, 'efectivo')
    db.session.commit()

    flash(f'Se cobró ${total_pagado:.2f} en efectivo a {cliente.nombre} {cliente.apellido}.', 'success')
    return redirect(url_for('turnos.cobrar_deudas', email=cliente.email))


@turnos_bp.route('/cobrar-deudas/<int:usuario_id>/abono/<int:abono_id>', methods=['POST'])
@login_required
def cobrar_deuda_abono_cliente(usuario_id, abono_id):
    if not _es_admin(current_user):
        flash('No tienes permisos para cobrar deudas', 'error')
        return redirect(url_for('dashboard'))

    cliente = Usuario.query.get_or_404(usuario_id)
    abono = AbonoCliente.query.get_or_404(abono_id)
    if cliente.tipo_usuario != TipoUsuario.CLIENTE or abono.usuario_id != cliente.id:
        flash('La deuda indicada no está disponible para cobro.', 'error')
        return redirect(url_for('turnos.cobrar_deudas'))

    total = round(sum(pago.monto for pago in _pagos_pendientes_de_abono(abono)), 2)
    if total <= 0:
        flash('Este abono no tiene deuda pendiente.', 'info')
        return redirect(url_for('turnos.cobrar_deudas', email=cliente.email))

    total_pagado, _, _ = _marcar_deuda_abono_como_pagada(cliente, abono, 'efectivo')
    db.session.commit()

    flash(f'Se cobró el abono pendiente completo por ${total_pagado:.2f} en efectivo a {cliente.nombre} {cliente.apellido}.', 'success')
    return redirect(url_for('turnos.cobrar_deudas', email=cliente.email))


@turnos_bp.route('/cobrar-deudas/<int:usuario_id>/suspension-no-abonada', methods=['POST'])
@login_required
def cobrar_suspension_no_abonada_cliente(usuario_id):
    if not _es_admin(current_user):
        flash('No tienes permisos para cobrar deudas', 'error')
        return redirect(url_for('dashboard'))

    cliente = Usuario.query.get_or_404(usuario_id)
    if cliente.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Solo se pueden cobrar deudas de clientes.', 'error')
        return redirect(url_for('turnos.cobrar_deudas'))

    total = round(sum(
        deuda.monto for deuda in Pago.query
        .filter_by(usuario_id=cliente.id, estado='pendiente', tipo_clase=TipoClase.NO_ABONADA)
        .filter(Pago.monto > 0)
        .all()
    ), 2)
    if total <= 0:
        flash('El cliente no tiene deuda de suspensión pendiente.', 'info')
        return redirect(url_for('turnos.cobrar_deudas', email=cliente.email))

    total_pagado, _, _ = _marcar_deudas_no_abonadas_como_pagadas(cliente, 'efectivo')
    db.session.commit()

    flash(f'Se cobró la suspensión por ${total_pagado:.2f} en efectivo a {cliente.nombre} {cliente.apellido}.', 'success')
    return redirect(url_for('turnos.cobrar_deudas', email=cliente.email))


@turnos_bp.route('/crear', methods=['GET', 'POST'])
@login_required
def crear_turno():
    if not _es_admin(current_user):
        flash('Solo administradores pueden crear turnos', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        actividad = request.form.get('actividad', '').strip()
        capacidad_maxima = request.form.get('capacidad_maxima', type=int)
        dia_semana_raw = request.form.get('dia_semana', '').strip()
        hora_slot_raw = request.form.get('hora_inicio_slot', '').strip()

        turnos_recurrentes, error_horario = _construir_turnos_recurrentes_hasta_fin_anio(dia_semana_raw, hora_slot_raw)
        if error_horario:
            flash(error_horario, 'error')
            return render_template(
                'turnos/form_turno.html',
                turno=None,
                horas_disponibles=HORAS_DISPONIBLES,
                dias_semana=DIAS_SEMANA_CREACION,
            )

        if capacidad_maxima is None or capacidad_maxima <= 0:
            flash('Capacidad inválida', 'error')
            return render_template(
                'turnos/form_turno.html',
                turno=None,
                horas_disponibles=HORAS_DISPONIBLES,
                dias_semana=DIAS_SEMANA_CREACION,
            )

        if actividad not in {'futbol', 'basquet', 'voley', 'padel'}:
            flash('Actividad inválida', 'error')
            return render_template(
                'turnos/form_turno.html',
                turno=None,
                horas_disponibles=HORAS_DISPONIBLES,
                dias_semana=DIAS_SEMANA_CREACION,
            )

        turnos_creados = []
        conflictos_existentes = 0
        creadas_abono = 0
        conflictos_abono = []

        for hora_inicio, hora_fin in turnos_recurrentes:
            existe = Turno.query.filter_by(
                actividad=actividad,
                hora_inicio=hora_inicio,
                cancelado=False,
            ).first()
            if existe:
                conflictos_existentes += 1
                continue

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
            turnos_creados.append(turno)
            creadas_turno, conflictos_turno = _aplicar_abonos_a_turno(turno)
            creadas_abono += creadas_turno
            conflictos_abono.extend(conflictos_turno)

        if not turnos_creados:
            flash('Ya existen clases para ese deporte, día y horario hasta fin de año', 'error')
            return render_template(
                'turnos/form_turno.html',
                turno=None,
                horas_disponibles=HORAS_DISPONIBLES,
                dias_semana=DIAS_SEMANA_CREACION,
            )

        db.session.commit()
        dia_semana = DIAS_SEMANA[int(dia_semana_raw)]
        flash(
            f"Se crearon {len(turnos_creados)} clases semanales de {actividad.capitalize()} "
            f"los {dia_semana} a las {int(hora_slot_raw):02d}:00 con capacidad para {capacidad_maxima} personas.",
            'success',
        )
        if conflictos_existentes:
            flash(f'Se omitieron {conflictos_existentes} fechas porque ya existía esa clase.', 'info')
        if creadas_abono:
            flash(f'Se generaron {creadas_abono} reservas abonadas fijas en esta nueva franja.', 'info')
        for conflicto in conflictos_abono:
            flash(conflicto, 'warning')
        return redirect(url_for('turnos.crear_turno'))

    return render_template(
        'turnos/form_turno.html',
        turno=None,
        horas_disponibles=HORAS_DISPONIBLES,
        dias_semana=DIAS_SEMANA_CREACION,
    )


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

    if turno.hora_fin < _ahora_local():
        flash('No se puede cancelar administrativamente un turno ya finalizado', 'error')
        return redirect(url_for('turnos.administrar_turnos'))

    actividad = turno.actividad.upper()
    fecha = turno.hora_inicio.strftime("%d/%m/%Y")
    hora_inicio = turno.hora_inicio.strftime("%H:%M")
    hora_fin = turno.hora_fin.strftime("%H:%M")
    resumen = _procesar_cancelacion_admin_con_reintegros(turno, motivo)
    db.session.delete(turno)
    db.session.commit()

    flash(
        f'Se canceló y eliminó el turno de {actividad} del {fecha} '
        f'de {hora_inicio} a {hora_fin}. '
        f'Reservas canceladas: {resumen["reservas_canceladas"]}. '
        f'Créditos generados: {resumen["creditos_generados"]}. '
        f'Créditos restaurados: {resumen["creditos_restaurados"]}. '
        f'Reintegros: ${resumen["monto_reintegrado"]:.2f}. '
        f'Descontado de pagos pendientes: ${resumen["monto_descontado_pendiente"]:.2f}.',
        'success',
    )
    if resumen['abonos_cancelados']:
        flash(f'Se dieron de baja {resumen["abonos_cancelados"]} abono(s) que quedaron sin clases futuras.', 'info')
    return redirect(url_for('turnos.administrar_turnos'))


@turnos_bp.route('/eliminar-clase-admin/<int:turno_id>', methods=['POST'])
@login_required
def eliminar_clase_admin(turno_id):
    if not _es_admin(current_user):
        flash('Solo administradores pueden eliminar clases', 'error')
        return redirect(url_for('index'))

    turno = Turno.query.get_or_404(turno_id)
    if turno.cancelado:
        flash('El turno ya no está activo', 'info')
        return redirect(url_for('turnos.administrar_turnos'))

    modo_eliminacion = request.form.get('modo_eliminacion', 'todas').strip()
    motivo = request.form.get('motivo', '').strip()
    if modo_eliminacion != 'sin_reservas' and not motivo:
        flash('Debes indicar el motivo de la eliminación de la clase', 'error')
        return redirect(url_for('turnos.administrar_turnos'))

    turnos_a_eliminar = _obtener_turnos_recurrentes_activos(turno)
    if not turnos_a_eliminar:
        flash('No hay turnos activos para eliminar en esa clase.', 'info')
        return redirect(url_for('turnos.administrar_turnos'))

    actividad = turno.actividad.upper()
    dia_semana = DIAS_SEMANA[turno.hora_inicio.weekday()]
    hora_inicio = turno.hora_inicio.strftime("%H:%M")
    hora_fin = turno.hora_fin.strftime("%H:%M")

    if modo_eliminacion == 'sin_reservas':
        turnos_sin_reservas = [
            turno_recurrente for turno_recurrente in turnos_a_eliminar
            if turno_recurrente.cupos_disponibles == turno_recurrente.capacidad_maxima
            and Reserva.query.filter_by(turno_id=turno_recurrente.id).count() == 0
        ]
        if not turnos_sin_reservas:
            flash('No hay instancias sin reservas para eliminar en esta clase.', 'info')
            return redirect(url_for('turnos.administrar_turnos'))

        for turno_recurrente in turnos_sin_reservas:
            ListaEspera.query.filter_by(turno_id=turno_recurrente.id).delete(synchronize_session=False)
            db.session.delete(turno_recurrente)

        db.session.commit()
        turnos_con_reserva = len(turnos_a_eliminar) - len(turnos_sin_reservas)
        flash(
            f'Se eliminaron {len(turnos_sin_reservas)} instancia(s) sin reservas de la clase '
            f'{actividad} de los {dia_semana} de {hora_inicio} a {hora_fin}. '
            f'Se dejaron {turnos_con_reserva} instancia(s) con reservas.',
            'success',
        )
        return redirect(url_for('turnos.administrar_turnos'))

    resumen_total = {
        'reservas_canceladas': 0,
        'creditos_generados': 0,
        'creditos_restaurados': 0,
        'reintegros_generados': 0,
        'monto_reintegrado': 0.0,
        'monto_descontado_pendiente': 0.0,
        'abonos_cancelados': 0,
    }

    for turno_recurrente in turnos_a_eliminar:
        resumen = _procesar_cancelacion_admin_con_reintegros(turno_recurrente, motivo)
        _sumar_resumen_cancelacion_admin(resumen_total, resumen)
        db.session.delete(turno_recurrente)

    db.session.commit()

    flash(
        f'Se eliminó la clase {actividad} de los {dia_semana} '
        f'de {hora_inicio} a {hora_fin}. '
        f'Turnos eliminados: {len(turnos_a_eliminar)}. '
        f'Reservas canceladas: {resumen_total["reservas_canceladas"]}. '
        f'Créditos generados: {resumen_total["creditos_generados"]}. '
        f'Créditos restaurados: {resumen_total["creditos_restaurados"]}. '
        f'Reintegros: ${resumen_total["monto_reintegrado"]:.2f}. '
        f'Descontado de pagos pendientes: ${resumen_total["monto_descontado_pendiente"]:.2f}.',
        'success',
    )
    if resumen_total['abonos_cancelados']:
        flash(f'Se dieron de baja {resumen_total["abonos_cancelados"]} abono(s) que quedaron sin clases futuras.', 'info')
    return redirect(url_for('turnos.administrar_turnos'))


@turnos_bp.route('/reanudar-admin/<int:turno_id>', methods=['POST'])
@login_required
def reanudar_turno_admin(turno_id):
    if not _es_admin(current_user):
        flash('Solo administradores pueden reanudar turnos', 'error')
        return redirect(url_for('index'))

    flash('Los turnos cancelados por administración se eliminan. Para reanudarlo, creá un turno nuevo.', 'warning')
    return redirect(url_for('turnos.administrar_turnos'))
