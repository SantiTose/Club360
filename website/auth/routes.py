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
        
        # Diccionario de errores por campo
        field_errors = {}
        
        # Validaciones
        if not nombre or len(nombre) < 2:
            field_errors['nombre'] = 'El nombre debe tener al menos 2 caracteres'
        
        if not apellido or len(apellido) < 2:
            field_errors['apellido'] = 'El apellido debe tener al menos 2 caracteres'
        
        if not dni or not re.match(r'^\d{8}$', dni):
            field_errors['dni'] = 'El DNI debe tener 8 dígitos'
        
        if not email or not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
            field_errors['email'] = 'El email no es válido'
        
        if len(password) < 6:
            field_errors['password'] = 'La contraseña debe tener al menos 6 caracteres'
        
        if password != password_confirm:
            field_errors['password_confirm'] = 'Las contraseñas no coinciden'
        
        # Verificar duplicados
        if not field_errors.get('email') and Usuario.query.filter_by(email=email).first():
            field_errors['email'] = 'El email ya está registrado'
        
        if not field_errors.get('dni') and Usuario.query.filter_by(dni=dni).first():
            field_errors['dni'] = 'El DNI ya está registrado'
        
        # Si hay errores, devolver el formulario con los datos
        if field_errors:
            return render_template('auth/register.html', 
                                 field_errors=field_errors,
                                 form_data={
                                     'nombre': nombre,
                                     'apellido': apellido,
                                     'dni': dni,
                                     'email': email
                                 })
        
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
            return render_template('auth/register.html', 
                                 form_data={
                                     'nombre': nombre,
                                     'apellido': apellido,
                                     'dni': dni,
                                     'email': email
                                 })
    
    return render_template('auth/register.html', field_errors={}, form_data={})


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Iniciar sesión."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember')
        
        field_errors = {}
        
        if not email:
            field_errors['email'] = 'Por favor, ingresa tu email'
        
        if not password:
            field_errors['password'] = 'Por favor, ingresa tu contraseña'
        
        if field_errors:
            return render_template('auth/login.html', 
                                 field_errors=field_errors,
                                 form_data={'email': email})
        
        usuario = Usuario.query.filter_by(email=email).first()
        
        if usuario and check_password_hash(usuario.password, password):
            login_user(usuario, remember=bool(remember))
            flash(f'✅ ¡Bienvenido {usuario.nombre}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            field_errors['email'] = 'Email o contraseña incorrectos'
            return render_template('auth/login.html', 
                                 field_errors=field_errors,
                                 form_data={'email': email})
    
    return render_template('auth/login.html', field_errors={}, form_data={})


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
