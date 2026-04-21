from website import db
from flask_login import UserMixin
from datetime import datetime
from enum import Enum


class EstadoUsuario(str, Enum):
    ACTIVO = "activo"
    SUSPENDIDO = "suspendido"


class TipoUsuario(str, Enum):
    CLIENTE = "cliente"
    EMPLEADO = "empleado"
    ADMINISTRADOR = "administrador"


class TipoClase(str, Enum):
    ABONADA = "abonada"
    NO_ABONADA = "no_abonada"


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
    fecha_nacimiento = db.Column(db.Date, nullable=True)
    autorizacion_menor = db.Column(db.Boolean, nullable=False, default=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    tipo_usuario = db.Column(db.String(20), nullable=False, default=TipoUsuario.CLIENTE)
    # Estado operativo del cliente (activo/suspendido). Para empleado/admin no se utiliza.
    estado = db.Column(db.String(20), nullable=False, default=EstadoUsuario.ACTIVO)
    credito_abonado = db.Column(db.Float, nullable=False, default=0.0)
    cancelaciones_abonado = db.Column(db.Integer, nullable=False, default=0)
    beneficio_abonado_activo = db.Column(db.Boolean, nullable=False, default=True)
    requiere_cambio_password = db.Column(db.Boolean, nullable=False, default=False)
    reset_password_token = db.Column(db.String(120), unique=True)
    reset_password_expira = db.Column(db.DateTime)
    ultimo_recordatorio_mora = db.Column(db.DateTime)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_actualizacion = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    # `turnos` se mantiene por compatibilidad con datos antiguos (campo Turno.usuario_id).
    turnos = db.relationship('Turno', backref='usuario', lazy=True)
    reservas = db.relationship('Reserva', backref='usuario', lazy=True, cascade='all, delete-orphan')
    pagos = db.relationship('Pago', backref='usuario', lazy=True)
    listas_espera = db.relationship('ListaEspera', backref='usuario', lazy=True)
    suspensiones = db.relationship('Suspension', backref='usuario', lazy=True)

    def __repr__(self):
        return f'<Usuario {self.email}>'


class Turno(db.Model):
    __tablename__ = 'turnos'
    
    id = db.Column(db.Integer, primary_key=True)
    actividad = db.Column(db.String(20), nullable=False)
    tipo_clase = db.Column(db.String(20), nullable=False, default=TipoClase.NO_ABONADA)
    hora_inicio = db.Column(db.DateTime, nullable=False)
    hora_fin = db.Column(db.DateTime, nullable=False)
    capacidad_maxima = db.Column(db.Integer, nullable=False)
    cupos_disponibles = db.Column(db.Integer, nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    cancelado = db.Column(db.Boolean, default=False)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    reservas = db.relationship('Reserva', backref='turno', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Turno {self.actividad} - {self.hora_inicio}>'


class ListaEspera(db.Model):
    __tablename__ = 'lista_espera'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    turno_id = db.Column(db.Integer, db.ForeignKey('turnos.id'), nullable=False)
    tipo_lista = db.Column(db.String(20), nullable=False)  # general
    posicion = db.Column(db.Integer, nullable=False)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)

    turno = db.relationship('Turno', backref='listas_espera')

    def __repr__(self):
        return f'<ListaEspera {self.usuario_id} - Turno {self.turno_id}>'


class Reserva(db.Model):
    __tablename__ = 'reservas'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    turno_id = db.Column(db.Integer, db.ForeignKey('turnos.id'), nullable=False)
    qr_token = db.Column(db.String(120), unique=True, nullable=False)
    recordatorio_enviado = db.Column(db.Boolean, default=False, nullable=False)
    fecha_recordatorio = db.Column(db.DateTime)
    asistencia_validada = db.Column(db.Boolean, default=False, nullable=False)
    fecha_asistencia = db.Column(db.DateTime)
    fecha_reserva = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('usuario_id', 'turno_id', name='uq_reserva_usuario_turno'),
    )

    def __repr__(self):
        return f'<Reserva usuario={self.usuario_id} turno={self.turno_id}>'


class Pago(db.Model):
    __tablename__ = 'pagos'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    metodo_pago = db.Column(db.String(50), nullable=False)  # efectivo, tarjeta_credito
    estado = db.Column(db.String(20), nullable=False, default='pendiente')  # pendiente, completado
    tipo_clase = db.Column(db.String(20), nullable=False, default=TipoClase.NO_ABONADA)
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
