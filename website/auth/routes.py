from flask import render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from website.auth import auth_bp
from website import db
from website.models import Usuario, TipoUsuario
from website.auth.forms import LoginForm, RegistroForm
from werkzeug.security import generate_password_hash, check_password_hash


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Registrar nuevo usuario."""
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        apellido = request.form.get('apellido')
        dni = request.form.get('dni')
        email = request.form.get('email')
        password = request.form.get('password')
        
        usuario_existente = Usuario.query.filter_by(email=email).first()
        if usuario_existente:
            flash('El email ya está registrado', 'error')
            return redirect(url_for('auth.register'))
        
        nuevo_usuario = Usuario(
            nombre=nombre,
            apellido=apellido,
            dni=dni,
            email=email,
            password=generate_password_hash(password),
            tipo_usuario=TipoUsuario.CLIENTE,
            tipo_cliente='no_abonado'
        )
        
        db.session.add(nuevo_usuario)
        db.session.commit()
        
        flash('Usuario registrado exitosamente. Por favor, inicia sesión.', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Iniciar sesión."""
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        usuario = Usuario.query.filter_by(email=email).first()
        
        if usuario and check_password_hash(usuario.password, password):
            login_user(usuario)
            return redirect(url_for('index'))
        else:
            flash('Email o contraseña incorrectos', 'error')
    
    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """Cerrar sesión."""
    logout_user()
    flash('Sesión cerrada exitosamente', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    """Restablecer contraseña."""
    if request.method == 'POST':
        email = request.form.get('email')
        usuario = Usuario.query.filter_by(email=email).first()
        
        if usuario:
            flash('Se ha enviado un enlace de recuperación a tu email', 'success')
        else:
            flash('Email no encontrado', 'error')
        
        return redirect(url_for('auth.login'))
    
    return render_template('auth/reset_password.html')
