import argparse
import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path

from werkzeug.security import generate_password_hash

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from website import create_app, db
from website.models import (
    AbonoCliente,
    EstadoAbono,
    EstadoUsuario,
    Pago,
    Reserva,
    Suspension,
    TipoClase,
    TipoUsuario,
    Turno,
    Usuario,
)
from website.turnos.routes import _procesar_suspension_automatica


app = create_app('development')


def _parse_datetime(value):
    return datetime.strptime(value, '%Y-%m-%d %H:%M')


def _get_user(email):
    return Usuario.query.filter_by(email=email.lower()).first()


def _next_dni():
    max_id = db.session.query(db.func.max(Usuario.id)).scalar() or 0
    return str(90000000 + max_id + 1)


def _print_user_line(user):
    deuda = (
        db.session.query(db.func.coalesce(db.func.sum(Pago.monto), 0))
        .filter_by(usuario_id=user.id, estado='pendiente')
        .filter(Pago.monto > 0)
        .scalar()
    )
    suspensiones = Suspension.query.filter_by(usuario_id=user.id, estado='activa').count()
    print(f"{user.id:>3} | {user.email:<32} | {user.tipo_usuario:<13} | {user.estado:<10} | deuda ${deuda:.2f} | susp. {suspensiones}")


def create_user(args):
    if _get_user(args.email):
        raise SystemExit(f"Ya existe un usuario con email {args.email}")

    user = Usuario(
        nombre=args.nombre,
        apellido=args.apellido,
        dni=args.dni or _next_dni(),
        email=args.email.lower(),
        password=generate_password_hash(args.password),
        tipo_usuario=args.tipo,
        estado=EstadoUsuario.ACTIVO,
        tarjeta_credito_saldo=args.saldo,
    )
    db.session.add(user)
    db.session.commit()
    print(f"Usuario creado: {user.email} / {args.password}")


def set_saldo(args):
    user = _get_user(args.email)
    if not user:
        raise SystemExit('Usuario no encontrado')
    user.tarjeta_credito_saldo = args.saldo
    db.session.commit()
    print(f"Saldo actualizado: {user.email} -> ${user.tarjeta_credito_saldo:.2f}")


def create_turno(args):
    inicio = _parse_datetime(args.inicio)
    turno = Turno(
        actividad=args.actividad,
        hora_inicio=inicio,
        hora_fin=inicio + timedelta(hours=1),
        capacidad_maxima=args.capacidad,
        cupos_disponibles=args.capacidad,
    )
    db.session.add(turno)
    db.session.commit()
    print(f"Turno creado: id={turno.id} {turno.actividad} {turno.hora_inicio:%d/%m/%Y %H:%M}")


def delete_reserva(args):
    user = _get_user(args.email)
    if not user:
        raise SystemExit('Usuario no encontrado')
    reserva = Reserva.query.filter_by(usuario_id=user.id, turno_id=args.turno_id).first()
    if not reserva:
        raise SystemExit('Reserva no encontrada')
    turno = reserva.turno
    db.session.delete(reserva)
    turno.cupos_disponibles += 1
    db.session.commit()
    print(f"Reserva eliminada: {user.email} -> turno {turno.id}")


def status(_args):
    print("ID  | Email                            | Tipo          | Estado     | Deuda       | Susp.")
    print("-" * 91)
    users = Usuario.query.order_by(Usuario.tipo_usuario.asc(), Usuario.email.asc()).all()
    for user in users:
        _print_user_line(user)


def suspensiones(_args):
    rows = Suspension.query.order_by(Suspension.fecha_inicio.desc()).all()
    if not rows:
        print('No hay suspensiones registradas.')
        return
    for suspension in rows:
        user = Usuario.query.get(suspension.usuario_id)
        print(
            f"{suspension.id:>3} | {suspension.estado:<8} | {user.email if user else 'sin usuario':<30} | "
            f"{suspension.motivo} | {suspension.fecha_inicio:%d/%m/%Y}"
        )


def demo_suspension_abonada(args):
    user = _get_user(args.email)
    if not user:
        raise SystemExit('Usuario no encontrado')

    now = datetime.now()
    actividad = args.actividad
    hora = args.hora
    fecha_base = now.replace(day=1, hour=hora, minute=0, second=0, microsecond=0)
    fecha_desde = fecha_base.date()
    fecha_hasta = (fecha_base.replace(day=28) + timedelta(days=4)).date().replace(day=1) - timedelta(days=1)

    abono = AbonoCliente(
        usuario_id=user.id,
        actividad=actividad,
        dia_semana=fecha_base.weekday(),
        hora_inicio=hora,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        estado=EstadoAbono.PENDIENTE,
    )
    db.session.add(abono)
    db.session.flush()

    for offset in range(1, 4):
        inicio = now + timedelta(days=offset)
        inicio = inicio.replace(hour=hora, minute=0, second=0, microsecond=0)
        turno = Turno(
            actividad=actividad,
            hora_inicio=inicio,
            hora_fin=inicio + timedelta(hours=1),
            capacidad_maxima=4,
            cupos_disponibles=3,
        )
        db.session.add(turno)
        db.session.flush()
        db.session.add(Reserva(
            usuario_id=user.id,
            turno_id=turno.id,
            abono_id=abono.id,
            tipo_clase=TipoClase.ABONADA,
            qr_token=secrets.token_urlsafe(24),
        ))

    db.session.add(Pago(
        usuario_id=user.id,
        monto=args.monto,
        metodo_pago='tarjeta_credito',
        estado='pendiente',
        tipo_clase=TipoClase.ABONADA,
        fecha_pago=datetime.utcnow(),
        referencia_transaccion=f"abono-total-{abono.id}-{user.id}-{int(datetime.utcnow().timestamp())}",
    ))
    db.session.commit()

    _procesar_suspension_automatica(user)
    db.session.commit()
    print(f"Demo abonada lista: {user.email} quedó con abono pendiente/suspensión si la fecha actual ya supera el día 10.")


def demo_suspension_no_abonada(args):
    user = _get_user(args.email)
    if not user:
        raise SystemExit('Usuario no encontrado')

    now = datetime.now()
    for index in range(3):
        inicio = now - timedelta(days=index + 1)
        inicio = inicio.replace(hour=args.hora, minute=0, second=0, microsecond=0)
        turno = Turno(
            actividad=args.actividad,
            hora_inicio=inicio,
            hora_fin=inicio + timedelta(hours=1),
            capacidad_maxima=4,
            cupos_disponibles=3,
        )
        db.session.add(turno)
        db.session.flush()
        db.session.add(Reserva(
            usuario_id=user.id,
            turno_id=turno.id,
            tipo_clase=TipoClase.NO_ABONADA,
            qr_token=secrets.token_urlsafe(24),
        ))
        db.session.add(Pago(
            usuario_id=user.id,
            monto=args.monto,
            metodo_pago='tarjeta_credito',
            estado='pendiente',
            tipo_clase=TipoClase.NO_ABONADA,
            fecha_pago=datetime.utcnow(),
            referencia_transaccion=f"reserva-{turno.id}-{user.id}-{int(datetime.utcnow().timestamp())}-saldo",
        ))

    db.session.commit()
    _procesar_suspension_automatica(user)
    db.session.commit()
    print(f"Demo no abonada lista: {user.email} tiene 3 deudas vencidas y queda suspendido para no abonadas.")


def build_parser():
    parser = argparse.ArgumentParser(description='Herramientas de consola para demos de Club 360')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('status', help='Ver usuarios, estado, deuda y suspensiones activas')
    p.set_defaults(func=status)

    p = sub.add_parser('suspensiones', help='Listar suspensiones registradas')
    p.set_defaults(func=suspensiones)

    p = sub.add_parser('create-user', help='Crear usuario de prueba')
    p.add_argument('--email', required=True)
    p.add_argument('--password', default='cliente123')
    p.add_argument('--nombre', default='Demo')
    p.add_argument('--apellido', default='Cliente')
    p.add_argument('--tipo', choices=[TipoUsuario.CLIENTE, TipoUsuario.EMPLEADO, TipoUsuario.ADMINISTRADOR], default=TipoUsuario.CLIENTE)
    p.add_argument('--saldo', type=float, default=100000.0)
    p.add_argument('--dni')
    p.set_defaults(func=create_user)

    p = sub.add_parser('set-saldo', help='Cambiar saldo ficticio de tarjeta')
    p.add_argument('--email', required=True)
    p.add_argument('--saldo', type=float, required=True)
    p.set_defaults(func=set_saldo)

    p = sub.add_parser('create-turno', help='Crear un turno')
    p.add_argument('--actividad', choices=['futbol', 'basquet', 'voley', 'padel'], required=True)
    p.add_argument('--inicio', required=True, help='Formato: YYYY-MM-DD HH:MM')
    p.add_argument('--capacidad', type=int, default=4)
    p.set_defaults(func=create_turno)

    p = sub.add_parser('delete-reserva', help='Eliminar reserva por email y turno')
    p.add_argument('--email', required=True)
    p.add_argument('--turno-id', type=int, required=True)
    p.set_defaults(func=delete_reserva)

    p = sub.add_parser('demo-suspension-abonada', help='Crear escenario de suspensión por abono impago')
    p.add_argument('--email', default='maria@example.com')
    p.add_argument('--actividad', choices=['futbol', 'basquet', 'voley', 'padel'], default='padel')
    p.add_argument('--hora', type=int, default=14)
    p.add_argument('--monto', type=float, default=500.0)
    p.set_defaults(func=demo_suspension_abonada)

    p = sub.add_parser('demo-suspension-no-abonada', help='Crear escenario de suspensión por 3 deudas no abonadas')
    p.add_argument('--email', default='carlos@example.com')
    p.add_argument('--actividad', choices=['futbol', 'basquet', 'voley', 'padel'], default='padel')
    p.add_argument('--hora', type=int, default=14)
    p.add_argument('--monto', type=float, default=120.0)
    p.set_defaults(func=demo_suspension_no_abonada)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    with app.app_context():
        args.func(args)


if __name__ == '__main__':
    main()
