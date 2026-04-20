from website import db
from flask_login import UserMixin
from datetime import datetime
from enum import Enum


class EstadoUsuario(str, Enum):
    ACTIVO = "activo"
    SUSPENDIDO = "suspendido"
    INACTIVO = "inactivo"


class TipoUsuario(str, Enum):
    CLIENTE = "cliente"
    EMPLEADO = "empleado"
    ADMINISTRADOR = "administrador"


class TipoCliente(str, Enum):
    ABONADO = "abonado"
    NO_ABONADO = "no_abonado"


class Actividad(str, Enum):
    FUTBOL = "futbol"
    BASQUET = "basquet"
    VOLEY = "voley"
    PADEL = "padel"


class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    apellido = db.Column(db.String(100), nullable=False)
    dni = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    tipo_usuario = db.Column(db.String(20), nullable=False, default=TipoUsuario.CLIENTE)
    estado = db.Column(db.String(20), nullable=False, default=EstadoUsuario.ACTIVO)
    tipo_cliente = db.Column(db.String(20))  # Solo para clientes
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_actualizacion = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    turnos = db.relationship('Turno', backref='usuario', lazy=True)
    pagos = db.relationship('Pago', backref='usuario', lazy=True)
    listas_espera = db.relationship('ListaEspera', backref='usuario', lazy=True)
    suspensiones = db.relationship('Suspension', backref='usuario', lazy=True)

    def __repr__(self):
        return f'<Usuario {self.email}>'


class Turno(db.Model):
    __tablename__ = 'turnos'
    
    id = db.Column(db.Integer, primary_key=True)
    actividad = db.Column(db.String(20), nullable=False)
    hora_inicio = db.Column(db.DateTime, nullable=False)
    hora_fin = db.Column(db.DateTime, nullable=False)
    capacidad_maxima = db.Column(db.Integer, nullable=False)
    cupos_disponibles = db.Column(db.Integer, nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    cancelado = db.Column(db.Boolean, default=False)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Turno {self.actividad} - {self.hora_inicio}>'


class ListaEspera(db.Model):
    __tablename__ = 'lista_espera'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    turno_id = db.Column(db.Integer, db.ForeignKey('turnos.id'), nullable=False)
    tipo_lista = db.Column(db.String(20), nullable=False)  # general, abonado, no_abonado
    posicion = db.Column(db.Integer, nullable=False)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)

    turno = db.relationship('Turno', backref='listas_espera')

    def __repr__(self):
        return f'<ListaEspera {self.usuario_id} - Turno {self.turno_id}>'


class Pago(db.Model):
    __tablename__ = 'pagos'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    metodo_pago = db.Column(db.String(50), nullable=False)  # efectivo, tarjeta_credito
    estado = db.Column(db.String(20), nullable=False, default='pendiente')  # pendiente, completado
    fecha_pago = db.Column(db.DateTime, default=datetime.utcnow)
    referencia_transaccion = db.Column(db.String(100))

    def __repr__(self):
        return f'<Pago {self.usuario_id} - ${self.monto}>'


class Suspension(db.Model):
    __tablename__ = 'suspensiones'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    motivo = db.Column(db.String(255), nullable=False)
    estado = db.Column(db.String(20), nullable=False, default='activa')  # activa, resuelta
    fecha_inicio = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_resolucion = db.Column(db.DateTime)
    
    def __repr__(self):
        return f'<Suspension {self.usuario_id}>'
