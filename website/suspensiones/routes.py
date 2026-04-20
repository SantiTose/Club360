from flask import render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from website.suspensiones import suspensiones_bp
from website import db
from website.models import Suspension, Usuario, EstadoUsuario, TipoUsuario
from datetime import datetime


def _es_admin(user):
    return user.tipo_usuario == TipoUsuario.ADMINISTRADOR


@suspensiones_bp.route('/solicitar-alta', methods=['GET', 'POST'])
@login_required
def solicitar_alta_suspension():
    """Solicitar el alta de suspensión."""
    if current_user.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Esta funcionalidad aplica solo para clientes', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        suspension = Suspension.query.filter_by(
            usuario_id=current_user.id,
            estado='activa'
        ).first()
        
        if not suspension:
            flash('No tienes suspensiones activas', 'error')
            return redirect(url_for('index'))
        
        suspension.estado = 'solicitud_alta'
        
        db.session.commit()
        
        flash('Solicitud de alta enviada. Pendiente de aprobación del administrador', 'success')
        return redirect(url_for('index'))
    
    suspension = Suspension.query.filter_by(
        usuario_id=current_user.id,
        estado='activa'
    ).first()
    
    return render_template('suspensiones/solicitar_alta.html', suspension=suspension)


@suspensiones_bp.route('/dar-alta/<int:usuario_id>', methods=['POST'])
@login_required
def dar_alta_suspension(usuario_id):
    """Dar de alta a un usuario suspendido (para administradores)."""
    if not _es_admin(current_user):
        flash('No tienes permisos para dar de alta suspensiones', 'error')
        return redirect(url_for('index'))

    usuario = Usuario.query.get_or_404(usuario_id)
    if usuario.tipo_usuario != TipoUsuario.CLIENTE:
        flash('Solo se puede dar de alta suspensiones de clientes', 'error')
        return redirect(url_for('index'))
    
    suspension = Suspension.query.filter_by(
        usuario_id=usuario_id,
        estado='solicitud_alta'
    ).first()

    if not suspension:
        suspension = Suspension.query.filter_by(
            usuario_id=usuario_id,
            estado='activa'
        ).first()
    
    if suspension:
        suspension.estado = 'resuelta'
        suspension.fecha_resolucion = datetime.utcnow()
    
    usuario.estado = EstadoUsuario.ACTIVO
    
    db.session.commit()
    
    flash(f'Usuario {usuario.email} dado de alta exitosamente', 'success')
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
