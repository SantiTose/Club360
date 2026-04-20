from flask import render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from website.turnos import turnos_bp
from website import db
from website.models import Turno, Usuario, ListaEspera
from datetime import datetime


@turnos_bp.route('/disponibles', methods=['GET'])
@login_required
def ver_turnos_disponibles():
    """Ver turnos disponibles para reservar."""
    actividad = request.args.get('actividad')
    
    query = Turno.query.filter_by(cancelado=False)
    
    if actividad:
        query = query.filter_by(actividad=actividad)
    
    turnos = query.all()
    
    return render_template('turnos/disponibles.html', turnos=turnos)


@turnos_bp.route('/reservar/<int:turno_id>', methods=['POST'])
@login_required
def reservar_turno(turno_id):
    """Reservar un turno."""
    turno = Turno.query.get_or_404(turno_id)
    
    # Verificar si el usuario ya tiene reservado este turno
    turno_existente = Turno.query.filter_by(
        id=turno_id,
        usuario_id=current_user.id
    ).first()
    
    if turno_existente:
        flash('Ya tienes reservado este turno', 'error')
        return redirect(url_for('turnos.ver_turnos_disponibles'))
    
    if turno.cupos_disponibles > 0:
        turno.usuario_id = current_user.id
        turno.cupos_disponibles -= 1
        db.session.commit()
        flash('Turno reservado exitosamente', 'success')
    else:
        lista_espera = ListaEspera(
            usuario_id=current_user.id,
            turno_id=turno_id,
            tipo_lista='general',
            posicion=ListaEspera.query.filter_by(turno_id=turno_id).count() + 1
        )
        db.session.add(lista_espera)
        db.session.commit()
        flash('Turno lleno. Te agregamos a la lista de espera', 'info')
    
    return redirect(url_for('turnos.ver_turnos_disponibles'))


@turnos_bp.route('/cancelar/<int:turno_id>', methods=['POST'])
@login_required
def cancelar_turno(turno_id):
    """Cancelar una reserva de turno."""
    turno = Turno.query.get_or_404(turno_id)
    
    if turno.usuario_id != current_user.id:
        flash('No tienes permiso para cancelar este turno', 'error')
        return redirect(url_for('turnos.mis_turnos'))
    
    turno.usuario_id = None
    turno.cupos_disponibles += 1
    db.session.commit()
    
    flash('Turno cancelado exitosamente', 'success')
    return redirect(url_for('turnos.mis_turnos'))


@turnos_bp.route('/mis-turnos')
@login_required
def mis_turnos():
    """Ver mis turnos reservados."""
    turnos = Turno.query.filter_by(usuario_id=current_user.id).all()
    return render_template('turnos/mis_turnos.html', turnos=turnos)


@turnos_bp.route('/buscar/<int:turno_id>')
@login_required
def buscar_turno(turno_id):
    """Buscar un turno (para empleados)."""
    turno = Turno.query.get_or_404(turno_id)
    return render_template('turnos/detalle.html', turno=turno)
