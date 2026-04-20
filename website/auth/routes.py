from flask import render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from website.auth import auth_bp
from website import db
from website.models import Usuario, TipoUsuario
from website.auth.forms import LoginForm, RegistroForm
from werkzeug.security import generate_password_hash, check_password_hash
import re


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Registrar nuevo usuario."""
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        apellido = request.form.get('apellido', '').strip()
        dni = request.form.get('dni', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')
        
        # Validaciones
        errors = []
        
        if not nombre or len(nombre) < 2:
            errors.append('El nombre debe tener al menos 2 caracteres')
        
        if not apellido or len(apellido) < 2:
            errors.append('El apellido debe tener al menos 2 caracteres')
        
        if not dni or not re.match(r'^\d{8}$', dni):
            errors.append('El DNI debe tener 8 dígitos')
        
        if not email or not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
            errors.append('El email no es válido')
        
        if len(password) < 6:
            errors.append('La contraseña debe tener al menos 6 caracteres')
        
        if password != password_confirm:
            errors.append('Las contraseñas no coinciden')
        
        # Verificar duplicados
        if Usuario.query.filter_by(email=email).first():
            errors.append('El email ya está registrado')
        
        if Usuario.query.filter_by(dni=dni).first():
            errors.append('El DNI ya está registrado')
        
        if errors:
            for error in errors:
                flash(error, 'error')
            return redirect(url_for('auth.register'))
        
        try:
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
            
            flash('✅ Usuario registrado exitosamente. Por favor, inicia sesión.', 'success')
            return redirect(url_for('auth.login'))
        
        except Exception as e:
            db.session.rollback()
            flash('❌ Error al registrar usuario. Por favor, intenta de nuevo.', 'error')
            return redirect(url_for('auth.register'))
    
    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Iniciar sesión."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember')
        
        if not email or not password:
            flash('❌ Por favor, completa todos los campos', 'error')
            return redirect(url_for('auth.login'))
        
        usuario = Usuario.query.filter_by(email=email).first()
        
        if usuario and check_password_hash(usuario.password, password):
            login_user(usuario, remember=bool(remember))
            flash(f'✅ ¡Bienvenido {usuario.nombre}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('❌ Email o contraseña incorrectos', 'error')
    
    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """Cerrar sesión."""
    logout_user()
    flash('✅ Sesión cerrada exitosamente', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    """Restablecer contraseña."""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        usuario = Usuario.query.filter_by(email=email).first()
        
        if usuario:
            flash('✅ Se ha enviado un enlace de recuperación a tu email', 'success')
        else:
            flash('❌ Email no encontrado', 'error')
        
        return redirect(url_for('auth.login'))
    
    return render_template('auth/reset_password.html')
