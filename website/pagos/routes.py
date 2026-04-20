from flask import render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from website.pagos import pagos_bp
from website import db
from website.models import Pago, Usuario
from datetime import datetime


@pagos_bp.route('/deuda')
@login_required
def ver_deuda():
    """Ver deuda del usuario."""
    deuda = Pago.query.filter_by(
        usuario_id=current_user.id,
        estado='pendiente'
    ).all()
    
    monto_total = sum([pago.monto for pago in deuda])
    
    return render_template('pagos/deuda.html', deuda=deuda, monto_total=monto_total)


@pagos_bp.route('/pagar/<int:pago_id>', methods=['GET', 'POST'])
@login_required
def pagar(pago_id):
    """Realizar pago."""
    pago = Pago.query.get_or_404(pago_id)
    
    if pago.usuario_id != current_user.id:
        flash('No tienes permiso para pagar esta deuda', 'error')
        return redirect(url_for('pagos.ver_deuda'))
    
    if request.method == 'POST':
        metodo_pago = request.form.get('metodo_pago')
        
        if metodo_pago not in ['efectivo', 'tarjeta_credito']:
            flash('Método de pago inválido', 'error')
            return redirect(url_for('pagos.pagar', pago_id=pago_id))
        
        pago.metodo_pago = metodo_pago
        pago.estado = 'completado'
        pago.fecha_pago = datetime.utcnow()
        
        db.session.commit()
        
        flash('Pago completado exitosamente', 'success')
        return redirect(url_for('pagos.ver_deuda'))
    
    return render_template('pagos/pagar.html', pago=pago)


@pagos_bp.route('/registrar-pago', methods=['GET', 'POST'])
@login_required
def registrar_pago():
    """Registrar pago de cliente (para empleados)."""
    if request.method == 'POST':
        usuario_id = request.form.get('usuario_id')
        monto = float(request.form.get('monto'))
        metodo_pago = request.form.get('metodo_pago')
        
        nuevo_pago = Pago(
            usuario_id=usuario_id,
            monto=monto,
            metodo_pago=metodo_pago,
            estado='completado',
            fecha_pago=datetime.utcnow()
        )
        
        db.session.add(nuevo_pago)
        db.session.commit()
        
        flash('Pago registrado exitosamente', 'success')
        return redirect(url_for('pagos.registrar_pago'))
    
    return render_template('pagos/registrar.html')
