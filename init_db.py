"""
Script para inicializar la base de datos sin turnos precargados.
Ejecutar: python init_db.py
"""

from website import create_app, db
from website.models import (
    Usuario,
    Turno,
    Pago,
    Reserva,
    EstadoUsuario,
    TipoClase,
    AbonoCliente,
    EstadoAbono,
    ListaEspera,
    Suspension,
    CreditoCliente,
)
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta, date
import calendar
import secrets


def _fin_de_mes(fecha):
    return fecha.replace(day=calendar.monthrange(fecha.year, fecha.month)[1])


def _inicio_mes_siguiente(fecha):
    if fecha.month == 12:
        return fecha.replace(year=fecha.year + 1, month=1, day=1)
    return fecha.replace(month=fecha.month + 1, day=1)


def _crear_turno_demo(actividad, inicio, capacidad=8):
    turno = Turno(
        actividad=actividad,
        hora_inicio=inicio,
        hora_fin=inicio + timedelta(hours=1),
        capacidad_maxima=capacidad,
        cupos_disponibles=max(capacidad - 1, 0),
        cancelado=False,
    )
    db.session.add(turno)
    db.session.flush()
    return turno


def _crear_deudas_demo_carlos(cliente):
    ahora = datetime.utcnow()
    inicio_mes = ahora.date().replace(day=1)
    fin_mes = _fin_de_mes(inicio_mes)

    abonos_demo = [
        ('basquet', 0, 19, 24000.0),
        ('voley', 2, 20, 21000.0),
    ]

    for actividad, dia_semana, hora, monto in abonos_demo:
        abono = AbonoCliente(
            usuario_id=cliente.id,
            actividad=actividad,
            dia_semana=dia_semana,
            hora_inicio=hora,
            fecha_desde=inicio_mes,
            fecha_hasta=fin_mes,
            estado=EstadoAbono.SUSPENDIDO,
        )
        db.session.add(abono)
        db.session.flush()

        fecha_turno = inicio_mes
        while fecha_turno.weekday() != dia_semana:
            fecha_turno += timedelta(days=1)

        for _ in range(4):
            inicio = datetime.combine(fecha_turno, datetime.min.time()).replace(hour=hora)
            turno = _crear_turno_demo(actividad, inicio)
            db.session.add(Reserva(
                usuario_id=cliente.id,
                turno_id=turno.id,
                abono_id=abono.id,
                tipo_clase=TipoClase.ABONADA,
                qr_token=secrets.token_urlsafe(24),
            ))
            fecha_turno += timedelta(days=7)
            if fecha_turno > fin_mes:
                break

        db.session.add(Pago(
            usuario_id=cliente.id,
            monto=monto,
            metodo_pago='tarjeta_credito',
            estado='pendiente',
            tipo_clase=TipoClase.ABONADA,
            fecha_pago=ahora - timedelta(days=18),
            referencia_transaccion=f"abono-total-{abono.id}-{cliente.id}-{int(ahora.timestamp())}",
        ))

    deudas_no_abonadas = [
        ('futbol', 12, 5000.0),
        ('padel', 10, 6000.0),
        ('basquet', 8, 4500.0),
        ('voley', 6, 4000.0),
        ('futbol', 4, 5000.0),
    ]

    for actividad, dias_atras, monto in deudas_no_abonadas:
        inicio = (ahora - timedelta(days=dias_atras)).replace(hour=18, minute=0, second=0, microsecond=0)
        turno = _crear_turno_demo(actividad, inicio)
        db.session.add(Reserva(
            usuario_id=cliente.id,
            turno_id=turno.id,
            tipo_clase=TipoClase.NO_ABONADA,
            qr_token=secrets.token_urlsafe(24),
        ))
        db.session.add(Pago(
            usuario_id=cliente.id,
            monto=monto,
            metodo_pago='tarjeta_credito',
            estado='pendiente',
            tipo_clase=TipoClase.NO_ABONADA,
            fecha_pago=inicio,
            referencia_transaccion=f"reserva-{turno.id}-{cliente.id}-{int(inicio.timestamp())}-saldo",
        ))

    db.session.add(Suspension(
        usuario_id=cliente.id,
        motivo='Suspensión automática por abono pendiente',
        estado='activa',
        fecha_inicio=ahora - timedelta(days=3),
    ))
    db.session.add(Suspension(
        usuario_id=cliente.id,
        motivo='Suspensión automática por 3 deudas no abonadas',
        estado='activa',
        fecha_inicio=ahora - timedelta(days=2),
    ))


def _crear_suspensiones_demo_paulina(cliente):
    ahora = datetime.utcnow()
    db.session.add(Suspension(
        usuario_id=cliente.id,
        motivo='Suspensión automática por abono pendiente',
        estado='activa',
        fecha_inicio=ahora - timedelta(days=3),
    ))
    db.session.add(Suspension(
        usuario_id=cliente.id,
        motivo='Suspensión automática por 3 deudas no abonadas',
        estado='activa',
        fecha_inicio=ahora - timedelta(days=2),
    ))


def _proxima_fecha_en_o_despues(fecha, dia_semana):
    dias_hasta_turno = (dia_semana - fecha.weekday()) % 7
    return fecha + timedelta(days=dias_hasta_turno)


def _crear_clases_demo_recurrentes_desde_mes_siguiente():
    primer_dia = _inicio_mes_siguiente(datetime.utcnow().date().replace(day=1))
    fin_anio = primer_dia.replace(month=12, day=31)
    clases = [
        # actividad, dia_semana(lunes=0), hora, capacidad, cupos_disponibles
        ('futbol', 1, 14, 10, 10),
        ('basquet', 3, 16, 10, 10),
        ('voley', 2, 20, 10, 0),
        ('padel', 4, 18, 10, 0),
    ]
    creados_por_actividad = {}

    for actividad, dia_semana, hora, capacidad, cupos in clases:
        fecha = _proxima_fecha_en_o_despues(primer_dia, dia_semana)
        creados_por_actividad[actividad] = 0
        while fecha <= fin_anio:
            inicio = datetime.combine(fecha, datetime.min.time()).replace(hour=hora)
            turno = Turno(
                actividad=actividad,
                hora_inicio=inicio,
                hora_fin=inicio + timedelta(hours=1),
                capacidad_maxima=capacidad,
                cupos_disponibles=cupos,
                cancelado=False,
            )
            db.session.add(turno)
            creados_por_actividad[actividad] += 1
            fecha += timedelta(days=7)

    return creados_por_actividad

def init_database():
    """Inicializa la base de datos sin turnos de ejemplo."""
    app = create_app('development')
    
    with app.app_context():
        # Crear todas las tablas
        db.create_all()
        
        # Limpiar datos existentes
        db.session.query(CreditoCliente).delete()
        db.session.query(ListaEspera).delete()
        db.session.query(Suspension).delete()
        db.session.query(Reserva).delete()
        db.session.query(Pago).delete()
        db.session.query(AbonoCliente).delete()
        db.session.query(Turno).delete()
        db.session.query(Usuario).delete()
        db.session.commit()
        
        print("✓ Base de datos limpiada")
        
        # Crear administrador
        admin = Usuario(
            nombre='Admin',
            apellido='Sistema',
            dni='12345678',
            email='admin@club360.com',
            password=generate_password_hash('admin123'),
            tipo_usuario='administrador',
            estado='activo'
        )
        db.session.add(admin)
        print("✓ Administrador creado: admin@club360.com")
        
        # Crear empleados
        empleado1 = Usuario(
            nombre='Juan',
            apellido='Pérez',
            dni='23456789',
            email='juan@club360.com',
            password=generate_password_hash('empleado123'),
            tipo_usuario='empleado',
            estado='activo'
        )
        db.session.add(empleado1)
        print("✓ Empleado creado: juan@club360.com")
        
        # Crear clientes de prueba
        cliente1 = Usuario(
            nombre='Carlos',
            apellido='García',
            dni='34567890',
            email='carlos@example.com',
            password=generate_password_hash('cliente123'),
            tipo_usuario='cliente',
            estado=EstadoUsuario.SUSPENDIDO,
            tarjeta_credito_marca='Visa',
            tarjeta_credito_ultimos4='1111',
            tarjeta_credito_vencimiento=date(2024, 12, 31),
            tarjeta_credito_saldo=0.0
        )
        
        cliente2 = Usuario(
            nombre='María',
            apellido='López',
            dni='45678901',
            email='maria@example.com',
            password=generate_password_hash('cliente123'),
            tipo_usuario='cliente',
            estado='activo',
            tarjeta_credito_marca='Visa',
            tarjeta_credito_ultimos4='1111',
            tarjeta_credito_vencimiento=date(2030, 12, 31),
            tarjeta_credito_saldo=100000.0
        )

        cliente_sin_fondos = Usuario(
            nombre='Sin Fondos',
            apellido='Prueba',
            dni='67890123',
            email='sinfondos@example.com',
            password=generate_password_hash('cliente123'),
            tipo_usuario='cliente',
            estado='activo',
            tarjeta_credito_marca='Visa',
            tarjeta_credito_ultimos4='1111',
            tarjeta_credito_vencimiento=date(2030, 12, 31),
            tarjeta_credito_saldo=0.0
        )

        pedro_sin_fondos = Usuario(
            nombre='Pedro',
            apellido='Sin Fondos',
            dni='78901234',
            email='pedro@example.com',
            password=generate_password_hash('cliente123'),
            tipo_usuario='cliente',
            estado='activo',
            tarjeta_credito_marca='Visa',
            tarjeta_credito_ultimos4='1111',
            tarjeta_credito_vencimiento=date(2030, 12, 31),
            tarjeta_credito_saldo=0.0
        )

        paulina_suspendida = Usuario(
            nombre='Paulina',
            apellido='Suspendida',
            dni='89012345',
            email='paulina@example.com',
            password=generate_password_hash('cliente123'),
            tipo_usuario='cliente',
            estado=EstadoUsuario.SUSPENDIDO,
            tarjeta_credito_marca='Visa',
            tarjeta_credito_ultimos4='1111',
            tarjeta_credito_vencimiento=date(2030, 12, 31),
            tarjeta_credito_saldo=100000.0
        )

        cliente_suspendido = Usuario(
            nombre='Suspendido',
            apellido='Prueba',
            dni='56789012',
            email='suspendido@example.com',
            password=generate_password_hash('suspendido123'),
            tipo_usuario='cliente',
            estado=EstadoUsuario.SUSPENDIDO,
            tarjeta_credito_marca='Visa',
            tarjeta_credito_ultimos4='1111',
            tarjeta_credito_vencimiento=date(2030, 12, 31),
            tarjeta_credito_saldo=0.0
        )
        
        db.session.add_all([cliente1, cliente2, cliente_sin_fondos, pedro_sin_fondos, paulina_suspendida, cliente_suspendido])
        db.session.commit()
        _crear_deudas_demo_carlos(cliente1)
        _crear_suspensiones_demo_paulina(paulina_suspendida)
        clases_demo = _crear_clases_demo_recurrentes_desde_mes_siguiente()
        db.session.commit()
        print("✓ Clientes creados")
        
        print("✓ Deudas demo creadas para carlos@example.com")
        print("✓ Carlos queda suspendido, con tarjeta vencida y sin fondos")
        print("✓ Clases demo recurrentes creadas desde el mes siguiente hasta fin de año:")
        print("  - Fútbol: martes 14:00 con cupos")
        print("  - Básquet: jueves 16:00 con cupos")
        print("  - Vóley: miércoles 20:00 sin cupos")
        print("  - Pádel: viernes 18:00 sin cupos")
        print(f"  Total por deporte: {clases_demo}")
        
        print("\n✅ Base de datos inicializada correctamente!")
        print("\nCuentas de prueba:")
        print("- Admin: admin@club360.com / admin123")
        print("- Empleado: juan@club360.com / empleado123")
        print("- Cliente 1: carlos@example.com / cliente123")
        print("- Cliente 2: maria@example.com / cliente123")
        print("- Cliente sin fondos: sinfondos@example.com / cliente123")
        print("- Pedro sin fondos: pedro@example.com / cliente123")
        print("- Paulina suspendida: paulina@example.com / cliente123")
        print("- Cliente suspendido: suspendido@example.com / suspendido123")


if __name__ == '__main__':
    init_database()
