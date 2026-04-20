from flask import render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from website.turnos import turnos_bp
from website import db
from website.models import Turno, ListaEspera, Reserva, Pago, TipoUsuario, TipoClase
from datetime import datetime


def _es_empleado_o_admin(user):
    return user.tipo_usuario in {TipoUsuario.EMPLEADO, TipoUsuario.ADMINISTRADOR}


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


@turnos_bp.route('/disponibles', methods=['GET'])
@login_required
def ver_turnos_disponibles():
    """Ver turnos disponibles para reservar."""
    actividad = request.args.get('actividad')
    tipo_clase = request.args.get('tipo_clase')
    
    query = Turno.query.filter_by(cancelado=False)
    
    if actividad:
        query = query.filter_by(actividad=actividad)

    if tipo_clase in [TipoClase.ABONADA, TipoClase.NO_ABONADA]:
        query = query.filter_by(tipo_clase=tipo_clase)
    
    turnos = query.all()
    
    return render_template('turnos/disponibles.html', turnos=turnos, filtro_actividad=actividad or '', filtro_tipo_clase=tipo_clase or '')


@turnos_bp.route('/reservar/<int:turno_id>', methods=['POST'])
@login_required
def reservar_turno(turno_id):
    """Reservar un turno."""
    turno = Turno.query.get_or_404(turno_id)

    if turno.cancelado:
        flash('Este turno ya no está disponible', 'error')
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
        reserva = Reserva(usuario_id=current_user.id, turno_id=turno_id)
        db.session.add(reserva)
        turno.cupos_disponibles -= 1

        # Política de cobro por tipo de clase (abonada / no abonada).
        monto = _calcular_monto_reserva(turno.actividad, turno.tipo_clase)
        db.session.add(Pago(
            usuario_id=current_user.id,
            monto=monto,
            metodo_pago='efectivo',
            estado='pendiente',
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

        lista_espera = ListaEspera(
            usuario_id=current_user.id,
            turno_id=turno_id,
            tipo_lista='general',
            posicion=ListaEspera.query.filter_by(turno_id=turno_id).count() + 1
        )
        db.session.add(lista_espera)
        db.session.commit()

        personas_en_espera = ListaEspera.query.filter_by(turno_id=turno_id).count()
        if personas_en_espera >= 10:
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

    # Si hay lista de espera, asciende automáticamente al primero.
    siguiente = ListaEspera.query.filter_by(turno_id=turno_id).order_by(ListaEspera.posicion.asc()).first()
    if siguiente and turno.cupos_disponibles > 0:
        db.session.add(Reserva(usuario_id=siguiente.usuario_id, turno_id=turno_id))
        turno.cupos_disponibles -= 1
        db.session.delete(siguiente)

        # Recalcular posiciones restantes.
        pendientes = ListaEspera.query.filter_by(turno_id=turno_id).order_by(ListaEspera.posicion.asc()).all()
        for index, item in enumerate(pendientes, start=1):
            item.posicion = index

    db.session.commit()
    
    flash('Turno cancelado exitosamente', 'success')
    return redirect(url_for('turnos.mis_turnos'))


@turnos_bp.route('/mis-turnos')
@login_required
def mis_turnos():
    """Ver mis turnos reservados."""
    turnos = (
        Turno.query
        .join(Reserva, Reserva.turno_id == Turno.id)
        .filter(Reserva.usuario_id == current_user.id)
        .order_by(Turno.hora_inicio.asc())
        .all()
    )
    return render_template('turnos/mis_turnos.html', turnos=turnos)


@turnos_bp.route('/buscar/<int:turno_id>')
@login_required
def buscar_turno(turno_id):
    """Buscar un turno (para empleados)."""
    if not _es_empleado_o_admin(current_user):
        flash('No tienes permisos para acceder a esta funcionalidad', 'error')
        return redirect(url_for('index'))

    turno = Turno.query.get_or_404(turno_id)
    return render_template('turnos/detalle.html', turno=turno)
