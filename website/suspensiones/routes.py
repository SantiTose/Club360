from flask import render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from website.suspensiones import suspensiones_bp
from website import db
from website.models import Suspension, Usuario, EstadoUsuario, TipoUsuario, Pago, TipoClase, AbonoCliente, EstadoAbono
from datetime import datetime
from website.turnos.routes import _obtener_restricciones_suspension, _pagos_no_abonados_vencidos


def _es_admin(user):
    return user.tipo_usuario == TipoUsuario.ADMINISTRADOR


def _deuda_pendiente_positiva(usuario_id):
    return (
        Pago.query
        .filter_by(usuario_id=usuario_id, estado='pendiente')
        .filter(Pago.monto > 0)
        .all()
    )


def _deudas_abonadas_pendientes(usuario_id):
    return (
        Pago.query
        .filter_by(usuario_id=usuario_id, estado='pendiente', tipo_clase=TipoClase.ABONADA)
        .filter(Pago.monto > 0)
        .all()
    )


def _asegurar_recargo_alta(usuario_id):
    deudas_abonadas = _deudas_abonadas_pendientes(usuario_id)
    deudas_no_abonadas_vencidas = _pagos_no_abonados_vencidos(usuario_id)
    base_abonada = sum(p.monto for p in deudas_abonadas)
    base_no_abonada = sum(p.monto for p in deudas_no_abonadas_vencidas)
    base = base_abonada + base_no_abonada
    if base <= 0:
        return None

    recargo_existente = (
        Pago.query
        .filter_by(usuario_id=usuario_id, estado='pendiente')
        .filter(Pago.referencia_transaccion.like('recargo-alta-%'))
        .first()
    )
    if recargo_existente:
        return recargo_existente

    recargo = round((base_abonada * 0.05) + sum(p.monto * 0.05 for p in deudas_no_abonadas_vencidas), 2)
    if recargo <= 0:
        return None

    nuevo = Pago(
        usuario_id=usuario_id,
        monto=recargo,
        metodo_pago='tarjeta_credito',
        estado='pendiente',
        tipo_clase=TipoClase.NO_ABONADA,
        referencia_transaccion=f"recargo-alta-{usuario_id}-{int(datetime.utcnow().timestamp())}",
    )
    db.session.add(nuevo)
    db.session.commit()
    return nuevo


def _monto_total_alta(usuario_id):
    recargo = _asegurar_recargo_alta(usuario_id)
    deudas = _deuda_pendiente_positiva(usuario_id)
    total = round(sum(p.monto for p in deudas), 2)
    return total, recargo


def _tarjeta_credito_vencida(usuario):
    vencimiento = getattr(usuario, 'tarjeta_credito_vencimiento', None)
    return bool(vencimiento and vencimiento < datetime.utcnow().date())


def _reactivar_cuenta_tras_pago(usuario):
    suspensiones = Suspension.query.filter_by(
        usuario_id=usuario.id,
        estado='activa'
    ).all()
    for suspension in suspensiones:
        suspension.estado = 'resuelta'
        suspension.fecha_resolucion = datetime.utcnow()

    usuario.estado = EstadoUsuario.ACTIVO

    abonos_suspendidos = AbonoCliente.query.filter_by(
        usuario_id=usuario.id,
        estado=EstadoAbono.SUSPENDIDO,
    ).all()
    if not abonos_suspendidos:
        return 0, []

    from website.turnos.routes import _generar_reservas_para_abono

    reservas_restauradas = 0
    conflictos = []
    for abono in abonos_suspendidos:
        abono.estado = EstadoAbono.ACTIVO
        creadas, errores, _ = _generar_reservas_para_abono(abono, crear_pagos=False)
        reservas_restauradas += creadas
        conflictos.extend(errores)

    return reservas_restauradas, conflictos


@suspensiones_bp.route('/solicitar-alta', methods=['GET', 'POST'])
@login_required
def solicitar_alta_suspension():
    """Permite pagar el alta y reactivar automáticamente al cliente."""
    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Esta funcionalidad aplica solo para clientes', 'error')
        return redirect(url_for('index'))

    suspension = Suspension.query.filter_by(
        usuario_id=current_user.id,
        estado='activa'
    ).first()

    if not suspension:
        flash('No tienes suspensiones activas', 'error')
        return redirect(url_for('index'))

    monto_total, recargo = _monto_total_alta(current_user.id)

    if request.method == 'POST':
        if monto_total <= 0:
            reservas_restauradas, conflictos_abonos = _reactivar_cuenta_tras_pago(current_user)
            db.session.commit()

            flash('Tu cuenta fue reactivada. No había deuda pendiente para abonar.', 'success')
            if reservas_restauradas:
                flash(f'Se restauraron {reservas_restauradas} reservas futuras de tus abonos.', 'info')
            for conflicto in conflictos_abonos:
                flash(conflicto, 'warning')
            return redirect(url_for('dashboard'))

        saldo_disponible = float(current_user.tarjeta_credito_saldo or 0.0)
        if _tarjeta_credito_vencida(current_user):
            flash('No se pudo procesar el pago. La tarjeta de credito esta vencida.', 'error')
            return redirect(url_for('suspensiones.solicitar_alta_suspension'))

        if saldo_disponible < monto_total:
            flash(
                f'No se pudo procesar el pago. Saldo insuficiente. Total a abonar: ${monto_total:.2f}.',
                'error',
            )
            return redirect(url_for('suspensiones.solicitar_alta_suspension'))

        deudas = _deuda_pendiente_positiva(current_user.id)
        current_user.tarjeta_credito_saldo = round(saldo_disponible - monto_total, 2)
        for deuda in deudas:
            deuda.estado = 'completado'
            deuda.metodo_pago = 'tarjeta_credito'
            if not deuda.referencia_transaccion:
                deuda.referencia_transaccion = f"alta-online-{current_user.id}-{int(datetime.utcnow().timestamp())}"

        reservas_restauradas, conflictos_abonos = _reactivar_cuenta_tras_pago(current_user)
        db.session.commit()

        flash(
            f'Alta procesada correctamente. Se abonó ${monto_total:.2f} con tarjeta de crédito y tu cuenta volvió a estar activa.',
            'success'
        )
        if reservas_restauradas:
            flash(f'Se restauraron {reservas_restauradas} reservas futuras de tus abonos.', 'info')
        for conflicto in conflictos_abonos:
            flash(conflicto, 'warning')
        return redirect(url_for('dashboard'))
    
    return render_template(
        'suspensiones/solicitar_alta.html',
        suspension=suspension,
        monto_total=monto_total,
        recargo=recargo,
    )


@suspensiones_bp.route('/dar-alta/<int:usuario_id>', methods=['POST'])
@login_required
def dar_alta_suspension(usuario_id):
    """Ruta legacy: el alta ahora la resuelve el propio cliente con pago online."""
    if not _es_admin(current_user):
        flash('No tienes permisos para dar de alta suspensiones', 'error')
        return redirect(url_for('index'))
    flash('El alta de suspensión ya no requiere aprobación administrativa. El cliente debe resolverla pagando online.', 'info')
    return redirect(url_for('index'))


@suspensiones_bp.route('/aplicar-suspension/<int:usuario_id>', methods=['POST'])
@login_required
def aplicar_suspension(usuario_id):
    """Aplicar suspensión a un usuario (para administradores)."""
    if not _es_admin(current_user):
        flash('No tienes permisos para aplicar suspensiones', 'error')
        return redirect(url_for('index'))

    usuario = Usuario.query.get_or_404(usuario_id)
    if usuario.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Solo se puede suspender a usuarios cliente', 'error')
        return redirect(url_for('index'))

    motivo = request.form.get('motivo', 'Suspensión por mora')
    
    nueva_suspension = Suspension(
        usuario_id=usuario_id,
        motivo=motivo,
        estado='activa'
    )
    
    usuario.estado = EstadoUsuario.SUSPENDIDO
    
    db.session.add(nueva_suspension)
    db.session.commit()
    
    flash(f'Usuario {usuario.email} suspendido exitosamente', 'success')
    return redirect(url_for('index'))
