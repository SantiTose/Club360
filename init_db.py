"""
Script para inicializar la base de datos con datos y clases demo.
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
    TarjetaCredito,
)
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta, date
import calendar
import secrets


def _fin_de_mes(fecha):
    return fecha.replace(day=calendar.monthrange(fecha.year, fecha.month)[1])


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


def _crear_suspensiones_demo_carlos(cliente):
    ahora = datetime.utcnow()
    inicio_mes = ahora.date().replace(day=1)
    fin_mes = _fin_de_mes(inicio_mes)

    abono = AbonoCliente(
        usuario_id=cliente.id,
        actividad='futbol',
        dia_semana=3,
        hora_inicio=15,
        fecha_desde=inicio_mes,
        fecha_hasta=fin_mes,
        estado=EstadoAbono.SUSPENDIDO,
    )
    db.session.add(abono)
    db.session.flush()

    db.session.add(Pago(
        usuario_id=cliente.id,
        monto=16000.0,
        metodo_pago='tarjeta_credito',
        estado='pendiente',
        tipo_clase=TipoClase.ABONADA,
        fecha_pago=ahora - timedelta(days=18),
        referencia_transaccion=f"abono-total-{abono.id}-{cliente.id}-{int(ahora.timestamp())}",
    ))

    db.session.add(Suspension(
        usuario_id=cliente.id,
        motivo='Suspensión automática por abono pendiente',
        estado='activa',
        fecha_inicio=ahora - timedelta(days=3),
    ))
    db.session.add(Suspension(
        usuario_id=cliente.id,
        motivo='Suspensión automática por 3 deudas no abonadas - futbol jueves 15:00',
        estado='activa',
        fecha_inicio=ahora - timedelta(days=2),
    ))


def _crear_suspensiones_demo_paulina(cliente):
    ahora = datetime.utcnow()
    inicio_mes = ahora.date().replace(day=1)
    fin_mes = _fin_de_mes(inicio_mes)

    abono = AbonoCliente(
        usuario_id=cliente.id,
        actividad='padel',
        dia_semana=2,
        hora_inicio=10,
        fecha_desde=inicio_mes,
        fecha_hasta=fin_mes,
        estado=EstadoAbono.SUSPENDIDO,
    )
    db.session.add(abono)
    db.session.flush()

    db.session.add(Pago(
        usuario_id=cliente.id,
        monto=16000.0,
        metodo_pago='tarjeta_credito',
        estado='pendiente',
        tipo_clase=TipoClase.ABONADA,
        fecha_pago=ahora - timedelta(days=18),
        referencia_transaccion=f"abono-total-{abono.id}-{cliente.id}-{int(ahora.timestamp())}",
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


def _proxima_fecha_en_o_despues(fecha, dia_semana):
    dias_hasta_turno = (dia_semana - fecha.weekday()) % 7
    return fecha + timedelta(days=dias_hasta_turno)


def _crear_clases_demo_recurrentes_hasta_fin_anio():
    hoy = date.today()
    fin_anio = hoy.replace(month=12, day=31)
    clases = [
        # actividad, dia_semana(lunes=0), hora
        ('basquet', 4, 19),
        ('voley', 1, 14),
        ('padel', 2, 10),
        ('futbol', 3, 15),
        ('futbol', 4, 18),
    ]
    creados_por_actividad = {}

    for actividad, dia_semana, hora in clases:
        fecha = _proxima_fecha_en_o_despues(hoy, dia_semana)
        creados_por_actividad[actividad] = 0
        while fecha <= fin_anio:
            inicio = datetime.combine(fecha, datetime.min.time()).replace(hour=hora)
            turno = Turno(
                actividad=actividad,
                hora_inicio=inicio,
                hora_fin=inicio + timedelta(hours=1),
                capacidad_maxima=10,
                cupos_disponibles=10,
                cancelado=False,
            )
            db.session.add(turno)
            creados_por_actividad[actividad] += 1
            fecha += timedelta(days=7)

    return creados_por_actividad


def _crear_reserva_demo(usuario, actividad, tipo_clase=TipoClase.NO_ABONADA):
    turno = (
        Turno.query
        .filter_by(actividad=actividad, cancelado=False)
        .filter(Turno.hora_inicio > datetime.now())
        .filter(Turno.cupos_disponibles > 0)
        .order_by(Turno.hora_inicio.asc())
        .first()
    )
    if not turno:
        return None

    reserva = Reserva(
        usuario_id=usuario.id,
        turno_id=turno.id,
        tipo_clase=tipo_clase,
        qr_token=secrets.token_urlsafe(24),
    )
    turno.cupos_disponibles -= 1
    db.session.add(reserva)
    return reserva


def init_database():
    """Inicializa la base de datos con usuarios, deudas y clases de ejemplo."""
    app = create_app('development')
    
    with app.app_context():
        # Crear todas las tablas
        db.create_all()
        
        # Limpiar datos existentes
        db.session.query(CreditoCliente).delete()
        db.session.query(TarjetaCredito).delete()
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
            tarjeta_credito_vencimiento=date(2030, 12, 31),
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
            tarjeta_credito_vencimiento=date(2024, 12, 31),
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
            tarjeta_credito_saldo=999999999.0
        )

        db.session.add_all([cliente1, cliente2, pedro_sin_fondos, paulina_suspendida])
        db.session.commit()
        for cliente in [cliente1, cliente2, pedro_sin_fondos, paulina_suspendida]:
            db.session.add(TarjetaCredito(
                usuario_id=cliente.id,
                marca=cliente.tarjeta_credito_marca,
                ultimos4=cliente.tarjeta_credito_ultimos4,
                vencimiento=cliente.tarjeta_credito_vencimiento,
                saldo=cliente.tarjeta_credito_saldo,
                es_principal=True,
            ))
        db.session.commit()
        _crear_suspensiones_demo_carlos(cliente1)
        _crear_suspensiones_demo_paulina(paulina_suspendida)
        clases_demo = _crear_clases_demo_recurrentes_hasta_fin_anio()
        db.session.flush()
        _crear_reserva_demo(cliente1, 'futbol')
        _crear_reserva_demo(paulina_suspendida, 'padel')
        _crear_reserva_demo(pedro_sin_fondos, 'basquet')
        db.session.commit()
        print("✓ Clientes creados")
        
        print("Clases demo recurrentes creadas hasta fin de anio:")
        print("  - Basquet: viernes 19:00 con 10 cupos")
        print("  - Voley: martes 14:00 con 10 cupos")
        print("  - Padel: miercoles 10:00 con 10 cupos")
        print("  - Futbol: jueves 15:00 con 10 cupos")
        print("  - Futbol: viernes 18:00 con 10 cupos")
        print(f"  Total por deporte: {clases_demo}")
        
        print("\n✅ Base de datos inicializada correctamente!")
        print("\nCuentas de prueba:")
        print("- Admin: admin@club360.com / admin123")
        print("- Empleado: juan@club360.com / empleado123")
        print("- Todo ok: maria@example.com / cliente123")
        print("- Suspendido abonada/no abonada sin saldo: carlos@example.com / cliente123")
        print("- Suspendida abonada/no abonada con fondos infinitos: paulina@example.com / cliente123")
        print("- Tarjeta vencida y sin fondos: pedro@example.com / cliente123")


if __name__ == '__main__':
    init_database()
