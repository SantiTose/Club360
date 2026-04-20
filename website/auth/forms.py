from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, ValidationError, Length
from website.models import Usuario


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Contraseña', validators=[DataRequired()])
    submit = SubmitField('Iniciar Sesión')


class RegistroForm(FlaskForm):
    nombre = StringField('Nombre', validators=[DataRequired(), Length(min=2, max=100)])
    apellido = StringField('Apellido', validators=[DataRequired(), Length(min=2, max=100)])
    dni = StringField('DNI', validators=[DataRequired(), Length(min=7, max=10)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Contraseña', validators=[DataRequired(), Length(min=6)])
    password_confirm = PasswordField('Confirmar Contraseña', 
                                     validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Registrarse')

    def validate_email(self, field):
        if Usuario.query.filter_by(email=field.data).first():
            raise ValidationError('Email ya registrado')

    def validate_dni(self, field):
        if Usuario.query.filter_by(dni=field.data).first():
            raise ValidationError('DNI ya registrado')
