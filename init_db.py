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
import hashlib
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


def _crear_cliente_seed(nombre, apellido, dni, email, password='cliente123', saldo=100000.0):
    return Usuario(
        nombre=nombre,
        apellido=apellido,
        dni=dni,
        email=email,
        password=generate_password_hash(password),
        tipo_usuario='cliente',
        estado='activo',
        fecha_nacimiento=date(1990, 1, 1),
        autorizacion_menor=False,
        tarjeta_credito_marca='Visa',
        tarjeta_credito_ultimos4='1111',
        tarjeta_credito_vencimiento=date(2030, 12, 31),
        tarjeta_credito_saldo=saldo,
    )


def _hash_numero_tarjeta(numero):
    return hashlib.sha256(numero.encode('utf-8')).hexdigest()


def _crear_reserva_en_turno(usuario, turno, tipo_clase=TipoClase.NO_ABONADA, abono=None):
    reserva = Reserva(
        usuario_id=usuario.id,
        turno_id=turno.id,
        abono_id=abono.id if abono else None,
        tipo_clase=tipo_clase,
        qr_token=secrets.token_urlsafe(24),
    )
    db.session.add(reserva)
    turno.cupos_disponibles = max(turno.cupos_disponibles - 1, 0)
    db.session.flush()
    return reserva


def _crear_pago_no_abonado_con_deuda(usuario, turno):
    referencia = f"reserva-{turno.id}-{usuario.id}-{int(datetime.utcnow().timestamp())}"
    db.session.add(Pago(
        usuario_id=usuario.id,
        monto=4000.0,
        metodo_pago='tarjeta_credito',
        estado='completado',
        tipo_clase=TipoClase.NO_ABONADA,
        fecha_pago=turno.hora_inicio,
        referencia_transaccion=f'{referencia}-senia',
    ))
    db.session.add(Pago(
        usuario_id=usuario.id,
        monto=4000.0,
        metodo_pago='tarjeta_credito',
        estado='pendiente',
        tipo_clase=TipoClase.NO_ABONADA,
        fecha_pago=turno.hora_inicio,
        referencia_transaccion=f'{referencia}-saldo',
    ))


def _crear_pago_no_abonado_completo(usuario, turno):
    referencia = f"reserva-{turno.id}-{usuario.id}-{int(datetime.utcnow().timestamp())}"
    db.session.add(Pago(
        usuario_id=usuario.id,
        monto=8000.0,
        metodo_pago='tarjeta_credito',
        estado='completado',
        tipo_clase=TipoClase.NO_ABONADA,
        fecha_pago=turno.hora_inicio,
        referencia_transaccion=f'{referencia}-total',
    ))


def _crear_pago_abonado_completo(usuario, turno, abono):
    db.session.add(Pago(
        usuario_id=usuario.id,
        monto=8000.0,
        metodo_pago='tarjeta_credito',
        estado='completado',
        tipo_clase=TipoClase.ABONADA,
        fecha_pago=turno.hora_inicio,
        referencia_transaccion=f'abono-total-{abono.id}-{usuario.id}-{int(datetime.utcnow().timestamp())}',
    ))


def _crear_entrada_lista_espera(usuario, turno, tipo_clase, posicion):
    db.session.add(ListaEspera(
        usuario_id=usuario.id,
        turno_id=turno.id,
        tipo_lista='general',
        tipo_clase=tipo_clase,
        posicion=posicion,
        estado='esperando',
        fecha_registro=datetime.utcnow() + timedelta(seconds=posicion),
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
        ('basquet', 0, 14),
        ('basquet', 2, 10),
        ('padel', 4, 16),
        ('padel', 4, 19),
        ('futbol', 5, 13),
    ]
    creados_por_actividad = {}

    for actividad, dia_semana, hora in clases:
        fecha = _proxima_fecha_en_o_despues(hoy, dia_semana)
        creados_por_actividad[actividad] = 0
        while fecha <= fin_anio:
            inicio = datetime.combine(fecha, datetime.min.time()).replace(hour=hora)
            capacidad = 5 if (actividad, dia_semana, hora) == ('basquet', 0, 14) else 10
            turno = Turno(
                actividad=actividad,
                hora_inicio=inicio,
                hora_fin=inicio + timedelta(hours=1),
                capacidad_maxima=capacidad,
                cupos_disponibles=capacidad,
                cancelado=False,
            )
            db.session.add(turno)
            creados_por_actividad[actividad] += 1
            fecha += timedelta(days=7)

    return creados_por_actividad


def _buscar_turno(actividad, fecha, hora):
    inicio = datetime.combine(fecha, datetime.min.time()).replace(hour=hora)
    return Turno.query.filter_by(
        actividad=actividad,
        hora_inicio=inicio,
        cancelado=False,
    ).first()


def _crear_escenarios_turnos_demo(felipe, maria, pepe, carlos, mati, usuarios_espera_basquet):
    # En 2026, los equivalentes viernes/sabado de esa semana son 10/07 y 11/07.
    viernes_padel = _buscar_turno('padel', date(2026, 7, 10), 19)
    sabado_futbol = _buscar_turno('futbol', date(2026, 7, 11), 13)
    miercoles_basquet = _buscar_turno('basquet', date(2026, 7, 8), 10)
    miercoles_basquet_deuda = _buscar_turno('basquet', date(2026, 7, 15), 10)
    lunes_basquet_lleno = _buscar_turno('basquet', date(2026, 7, 13), 14)
    martes_basquet_lleno = _buscar_turno('basquet', date(2026, 7, 14), 14)
    viernes_padel_mati = _buscar_turno('padel', date(2026, 7, 17), 16)
    sabado_futbol_mati = _buscar_turno('futbol', date(2026, 7, 18), 13)
    viernes_futbol_abonada = _buscar_turno('futbol', date(2026, 7, 3), 18)

    if viernes_padel:
        viernes_padel.capacidad_maxima = 2
        viernes_padel.cupos_disponibles = 2
        abono_maria_padel = AbonoCliente(
            usuario_id=maria.id,
            actividad='padel',
            dia_semana=4,
            hora_inicio=19,
            fecha_desde=date(2026, 7, 1),
            fecha_hasta=date(2026, 7, 31),
            estado=EstadoAbono.ACTIVO,
        )
        db.session.add(abono_maria_padel)
        db.session.flush()
        _crear_reserva_en_turno(maria, viernes_padel, TipoClase.ABONADA, abono_maria_padel)
        db.session.add(Pago(
            usuario_id=maria.id,
            monto=8000.0,
            metodo_pago='pendiente',
            estado='pendiente',
            tipo_clase=TipoClase.ABONADA,
            fecha_pago=viernes_padel.hora_inicio,
            referencia_transaccion=f'abono-total-{abono_maria_padel.id}-{maria.id}-{int(datetime.utcnow().timestamp())}',
        ))
        abono_felipe_padel = AbonoCliente(
            usuario_id=felipe.id,
            actividad='padel',
            dia_semana=4,
            hora_inicio=19,
            fecha_desde=date(2026, 7, 1),
            fecha_hasta=date(2026, 7, 31),
            estado=EstadoAbono.ACTIVO,
        )
        db.session.add(abono_felipe_padel)
        db.session.flush()
        _crear_reserva_en_turno(felipe, viernes_padel, TipoClase.ABONADA, abono_felipe_padel)
        db.session.add(Pago(
            usuario_id=felipe.id,
            monto=8000.0,
            metodo_pago='pendiente',
            estado='pendiente',
            tipo_clase=TipoClase.ABONADA,
            fecha_pago=viernes_padel.hora_inicio,
            referencia_transaccion=f'abono-total-{abono_felipe_padel.id}-{felipe.id}-{int(datetime.utcnow().timestamp())}',
        ))
        _crear_entrada_lista_espera(pepe, viernes_padel, TipoClase.ABONADA, 1)
        _crear_entrada_lista_espera(carlos, viernes_padel, TipoClase.NO_ABONADA, 1)

    if sabado_futbol:
        sabado_futbol.capacidad_maxima = 2
        sabado_futbol.cupos_disponibles = 2
        _crear_reserva_en_turno(maria, sabado_futbol, TipoClase.NO_ABONADA)
        _crear_pago_no_abonado_con_deuda(maria, sabado_futbol)
        _crear_reserva_en_turno(felipe, sabado_futbol, TipoClase.NO_ABONADA)
        _crear_pago_no_abonado_con_deuda(felipe, sabado_futbol)
        _crear_entrada_lista_espera(carlos, sabado_futbol, TipoClase.NO_ABONADA, 1)
        _crear_entrada_lista_espera(pepe, sabado_futbol, TipoClase.NO_ABONADA, 2)

    if lunes_basquet_lleno:
        lunes_basquet_lleno.capacidad_maxima = 5
        lunes_basquet_lleno.cupos_disponibles = 5
        for usuario in usuarios_espera_basquet[:5]:
            _crear_reserva_en_turno(usuario, lunes_basquet_lleno, TipoClase.NO_ABONADA)
        for posicion, usuario in enumerate(usuarios_espera_basquet[5:14], start=1):
            _crear_entrada_lista_espera(usuario, lunes_basquet_lleno, TipoClase.NO_ABONADA, posicion)

    if not martes_basquet_lleno:
        martes_basquet_lleno = Turno(
            actividad='basquet',
            hora_inicio=datetime(2026, 7, 14, 14, 0),
            hora_fin=datetime(2026, 7, 14, 15, 0),
            capacidad_maxima=1,
            cupos_disponibles=1,
            cancelado=False,
        )
        db.session.add(martes_basquet_lleno)
        db.session.flush()
    else:
        martes_basquet_lleno.capacidad_maxima = 1
        martes_basquet_lleno.cupos_disponibles = 1

    _crear_reserva_en_turno(usuarios_espera_basquet[0], martes_basquet_lleno, TipoClase.NO_ABONADA)
    _crear_pago_no_abonado_completo(usuarios_espera_basquet[0], martes_basquet_lleno)

    viernes_padel_deuda = _buscar_turno('padel', date(2026, 7, 3), 16)
    if viernes_padel_deuda:
        _crear_reserva_en_turno(maria, viernes_padel_deuda, TipoClase.NO_ABONADA)
        _crear_pago_no_abonado_con_deuda(maria, viernes_padel_deuda)

    if not viernes_futbol_abonada:
        viernes_futbol_abonada = Turno(
            actividad='futbol',
            hora_inicio=datetime(2026, 7, 3, 18, 0),
            hora_fin=datetime(2026, 7, 3, 19, 0),
            capacidad_maxima=10,
            cupos_disponibles=10,
            cancelado=False,
        )
        db.session.add(viernes_futbol_abonada)
        db.session.flush()

    abono_maria_futbol = AbonoCliente(
        usuario_id=maria.id,
        actividad='futbol',
        dia_semana=4,
        hora_inicio=18,
        fecha_desde=date(2026, 7, 1),
        fecha_hasta=date(2026, 7, 31),
        estado=EstadoAbono.ACTIVO,
    )
    db.session.add(abono_maria_futbol)
    db.session.flush()
    _crear_reserva_en_turno(maria, viernes_futbol_abonada, TipoClase.ABONADA, abono_maria_futbol)

    if miercoles_basquet:
        _crear_reserva_en_turno(maria, miercoles_basquet, TipoClase.NO_ABONADA)
        _crear_pago_no_abonado_con_deuda(maria, miercoles_basquet)

    if miercoles_basquet_deuda:
        _crear_reserva_en_turno(maria, miercoles_basquet_deuda, TipoClase.NO_ABONADA)
        _crear_pago_no_abonado_con_deuda(maria, miercoles_basquet_deuda)

    if viernes_padel_mati:
        _crear_reserva_en_turno(mati, viernes_padel_mati, TipoClase.NO_ABONADA)
        _crear_pago_no_abonado_completo(mati, viernes_padel_mati)

    if sabado_futbol_mati:
        abono_mati_futbol = AbonoCliente(
            usuario_id=mati.id,
            actividad='futbol',
            dia_semana=5,
            hora_inicio=13,
            fecha_desde=date(2026, 7, 1),
            fecha_hasta=date(2026, 7, 31),
            estado=EstadoAbono.ACTIVO,
        )
        db.session.add(abono_mati_futbol)
        db.session.flush()
        _crear_reserva_en_turno(mati, sabado_futbol_mati, TipoClase.ABONADA, abono_mati_futbol)
        _crear_pago_abonado_completo(mati, sabado_futbol_mati, abono_mati_futbol)


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
            nombre='Felipe',
            apellido='Martinez',
            dni='34567890',
            email='felipe@example.com',
            password=generate_password_hash('cliente123'),
            tipo_usuario='cliente',
            estado='activo',
            fecha_nacimiento=date(1990, 1, 1),
            autorizacion_menor=False,
            tarjeta_credito_marca='Visa',
            tarjeta_credito_ultimos4='1111',
            tarjeta_credito_vencimiento=date(2030, 12, 31),
            tarjeta_credito_saldo=100000.0
        )
        
        cliente2 = Usuario(
            nombre='María',
            apellido='López',
            dni='45678901',
            email='maria@example.com',
            password=generate_password_hash('cliente123'),
            tipo_usuario='cliente',
            estado='activo',
            fecha_nacimiento=date(1990, 3, 3),
            autorizacion_menor=False,
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
            fecha_nacimiento=date(1990, 1, 1),
            autorizacion_menor=False,
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
            fecha_nacimiento=date(1990, 1, 1),
            autorizacion_menor=False,
            tarjeta_credito_marca='Visa',
            tarjeta_credito_ultimos4='1111',
            tarjeta_credito_vencimiento=date(2030, 12, 31),
            tarjeta_credito_saldo=999999999.0
        )

        pepe_gonzalez = Usuario(
            nombre='Pepe',
            apellido='Gonzalez',
            dni='56789123',
            email='abonadoexample@gmail.com',
            password=generate_password_hash('cliente123'),
            tipo_usuario='cliente',
            estado='activo',
            fecha_nacimiento=date(1990, 1, 1),
            autorizacion_menor=False,
            tarjeta_credito_marca='Visa',
            tarjeta_credito_ultimos4='1111',
            tarjeta_credito_vencimiento=date(2030, 12, 31),
            tarjeta_credito_saldo=100000.0
        )

        carlos_cordero = Usuario(
            nombre='Carlos',
            apellido='Cordero',
            dni='90123456',
            email='noabonadoexample@gmail.com',
            password=generate_password_hash('cliente123'),
            tipo_usuario='cliente',
            estado='activo',
            fecha_nacimiento=date(1990, 1, 1),
            autorizacion_menor=False,
            tarjeta_credito_marca='Visa',
            tarjeta_credito_ultimos4='1111',
            tarjeta_credito_vencimiento=date(2030, 12, 31),
            tarjeta_credito_saldo=100000.0
        )

        mati_cliente = Usuario(
            nombre='Mati',
            apellido='Demo',
            dni='90123457',
            email='mati@example.com',
            password=generate_password_hash('cliente123'),
            tipo_usuario='cliente',
            estado='activo',
            fecha_nacimiento=date(1990, 1, 1),
            autorizacion_menor=False,
            tarjeta_credito_marca='Visa',
            tarjeta_credito_ultimos4='2222',
            tarjeta_credito_vencimiento=date(2030, 12, 31),
            tarjeta_credito_saldo=100000.0
        )

        usuarios_espera_basquet = [
            _crear_cliente_seed('Lucia', 'Ramos', '91000001', 'lucia.ramos@example.com'),
            _crear_cliente_seed('Tomas', 'Silva', '91000002', 'tomas.silva@example.com'),
            _crear_cliente_seed('Valentina', 'Molina', '91000003', 'valentina.molina@example.com'),
            _crear_cliente_seed('Mateo', 'Herrera', '91000004', 'mateo.herrera@example.com'),
            _crear_cliente_seed('Sofia', 'Nuñez', '91000005', 'sofia.nunez@example.com'),
            _crear_cliente_seed('Agustin', 'Paz', '91000006', 'agustin.paz@example.com'),
            _crear_cliente_seed('Camila', 'Ortiz', '91000007', 'camila.ortiz@example.com'),
            _crear_cliente_seed('Bruno', 'Vega', '91000008', 'bruno.vega@example.com'),
            _crear_cliente_seed('Martina', 'Suarez', '91000009', 'martina.suarez@example.com'),
            _crear_cliente_seed('Nicolas', 'Castro', '91000010', 'nicolas.castro@example.com'),
            _crear_cliente_seed('Julieta', 'Medina', '91000011', 'julieta.medina@example.com'),
            _crear_cliente_seed('Santino', 'Acosta', '91000012', 'santino.acosta@example.com'),
            _crear_cliente_seed('Renata', 'Flores', '91000013', 'renata.flores@example.com'),
            _crear_cliente_seed('Bautista', 'Rios', '91000014', 'bautista.rios@example.com'),
        ]

        clientes = [
            cliente1,
            cliente2,
            pedro_sin_fondos,
            paulina_suspendida,
            pepe_gonzalez,
            carlos_cordero,
            mati_cliente,
            *usuarios_espera_basquet,
        ]

        db.session.add_all(clientes)
        db.session.commit()
        for cliente in clientes:
            db.session.add(TarjetaCredito(
                usuario_id=cliente.id,
                marca=cliente.tarjeta_credito_marca,
                ultimos4=cliente.tarjeta_credito_ultimos4,
                numero_hash=_hash_numero_tarjeta(f'411111111111{cliente.tarjeta_credito_ultimos4}'),
                vencimiento=cliente.tarjeta_credito_vencimiento,
                saldo=cliente.tarjeta_credito_saldo,
                es_principal=True,
            ))
        db.session.commit()
        _crear_suspensiones_demo_paulina(paulina_suspendida)
        clases_demo = _crear_clases_demo_recurrentes_hasta_fin_anio()
        db.session.flush()
        _crear_escenarios_turnos_demo(cliente1, cliente2, pepe_gonzalez, carlos_cordero, mati_cliente, usuarios_espera_basquet)
        db.session.commit()
        print("✓ Clientes creados")
        
        print("Clases demo recurrentes creadas hasta fin de anio:")
        print("  - Basquet: lunes 14:00 con 5 cupos")
        print("  - Basquet: martes 14/07/2026 14:00 con 1 cupo, lleno y sin lista de espera")
        print("  - Basquet: miercoles 10:00 con 10 cupos")
        print("  - Padel: viernes 16:00 con 10 cupos")
        print("  - Padel: viernes 19:00 con 10 cupos")
        print("  - Futbol: sabado 13:00 con 10 cupos")
        print("  - Futbol: viernes 03/07/2026 18:00 puntual con Maria abonada")
        print(f"  Total por deporte: {clases_demo}")
        print("Escenarios demo creados para 03/07/2026, 08/07/2026, 10/07/2026, 11/07/2026, 13/07/2026, 14/07/2026, 15/07/2026, 17/07/2026 y 18/07/2026.")
        
        print("\n✅ Base de datos inicializada correctamente!")
        print("\nCuentas de prueba:")
        print("- Admin: admin@club360.com / admin123")
        print("- Empleado: juan@club360.com / empleado123")
        print("- Todo ok: felipe@example.com / cliente123")
        print("- Todo ok: maria@example.com / cliente123")
        print("- Suspendida abonada/no abonada con fondos infinitos: paulina@example.com / cliente123")
        print("- Tarjeta vencida y sin fondos: pedro@example.com / cliente123")
        print("- Pepe Gonzalez: abonadoexample@gmail.com / cliente123")
        print("- Carlos Cordero: noabonadoexample@gmail.com / cliente123")
        print("- Mati Demo: mati@example.com / cliente123")


if __name__ == '__main__':
    init_database()
