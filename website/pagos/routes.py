from flask import render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from website.pagos import pagos_bp
from website import db
from website.models import Pago, Usuario, TipoUsuario
from website.services import enviar_email_simulado
from datetime import datetime
import os
import secrets


def _es_cliente(user):
    return user.tipo_usuario == TipoUsuario.CLIENTE


def _es_empleado_o_admin(user):
    return user.tipo_usuario in {TipoUsuario.EMPLEADO, TipoUsuario.ADMINISTRADOR}


def _enviar_alerta_moroso_si_corresponde(usuario):
    deuda = Pago.query.filter_by(usuario_id=usuario.id, estado='pendiente').count()
    if deuda == 0:
        return

    ahora = datetime.utcnow()
    if usuario.ultimo_recordatorio_mora and (ahora - usuario.ultimo_recordatorio_mora).total_seconds() < 86400:
        return

    asunto = 'Recordatorio de deuda pendiente - Club 360'
    cuerpo = (
        f"Hola {usuario.nombre},\n\n"
        f"Detectamos {deuda} pago(s) pendiente(s) en tu cuenta.\n"
        "Por favor regulariza tu situación para evitar restricciones de nuevas reservas."
    )
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    enviar_email_simulado(base_dir, usuario.email, asunto, cuerpo)
    usuario.ultimo_recordatorio_mora = ahora
    db.session.commit()


def _reconciliar_estado_cliente(usuario):
    # El alta de suspensión debe ser un proceso manual por administrador.
    # Se mantiene la función por compatibilidad del flujo actual.
    return


@pagos_bp.route('/deuda')
@login_required
def ver_deuda():
    """Ver deuda del usuario."""
    if not _es_cliente(current_user):
        flash('Esta sección de deuda aplica solo para clientes', 'error')
        return redirect(url_for('index'))

    deuda = Pago.query.filter_by(
        usuario_id=current_user.id,
        estado='pendiente'
    ).all()

    _enviar_alerta_moroso_si_corresponde(current_user)
    
    monto_total = sum([pago.monto for pago in deuda])
    
    return render_template('pagos/deuda.html', deuda=deuda, monto_total=monto_total)


@pagos_bp.route('/pagar/<int:pago_id>', methods=['GET', 'POST'])
@login_required
def pagar(pago_id):
    """Realizar pago de cliente en web (solo tarjeta de credito)."""
    if not _es_cliente(current_user):
        flash('Esta funcionalidad de pago online aplica solo para clientes', 'error')
        return redirect(url_for('index'))

    pago = Pago.query.get_or_404(pago_id)
    
    if pago.usuario_id != current_user.id:
        flash('No tienes permiso para pagar esta deuda', 'error')
        return redirect(url_for('pagos.ver_deuda'))
    
    if request.method == 'POST':
        pago.metodo_pago = 'tarjeta_credito'
        pago.estado = 'completado'
        pago.fecha_pago = datetime.utcnow()
        pago.referencia_transaccion = f"TC-{secrets.token_hex(8).upper()}"
        
        db.session.commit()
        _reconciliar_estado_cliente(current_user)

        flash(f'Pago con tarjeta completado. Referencia: {pago.referencia_transaccion}', 'success')
        return redirect(url_for('pagos.ver_deuda'))
    
    return render_template('pagos/pagar.html', pago=pago)


@pagos_bp.route('/registrar-pago', methods=['GET', 'POST'])
@login_required
def registrar_pago():
    """Registrar pago de cliente (para empleados)."""
    if not _es_empleado_o_admin(current_user):
        flash('No tienes permisos para registrar pagos', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        usuario_id = request.form.get('usuario_id', type=int)
        monto_raw = request.form.get('monto', '').strip()
        metodo_pago = request.form.get('metodo_pago', '').strip()

        if not usuario_id or not Usuario.query.get(usuario_id):
            flash('Usuario inválido', 'error')
            return redirect(url_for('pagos.registrar_pago'))

        try:
            monto = float(monto_raw)
        except ValueError:
            flash('Monto inválido', 'error')
            return redirect(url_for('pagos.registrar_pago'))

        if monto <= 0:
            flash('El monto debe ser mayor a cero', 'error')
            return redirect(url_for('pagos.registrar_pago'))

        if metodo_pago not in ['efectivo', 'tarjeta_credito']:
            flash('Método de pago inválido', 'error')
            return redirect(url_for('pagos.registrar_pago'))
        
        nuevo_pago = Pago(
            usuario_id=usuario_id,
            monto=monto,
            metodo_pago=metodo_pago,
            estado='completado',
            fecha_pago=datetime.utcnow(),
            referencia_transaccion=(f"TC-{secrets.token_hex(8).upper()}" if metodo_pago == 'tarjeta_credito' else None)
        )
        
        db.session.add(nuevo_pago)
        db.session.commit()
        
        flash('Pago registrado exitosamente', 'success')
        return redirect(url_for('pagos.registrar_pago'))
    
    usuarios = Usuario.query.order_by(Usuario.apellido.asc(), Usuario.nombre.asc()).all()
    return render_template('pagos/registrar.html', usuarios=usuarios)
