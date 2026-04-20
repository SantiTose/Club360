"""
Script para inicializar la base de datos con datos de ejemplo
Ejecutar: python init_db.py
"""

from website import create_app, db
from website.models import Usuario, Turno, Pago
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta


def init_database():
    """Inicializa la base de datos con datos de ejemplo"""
    app = create_app('development')
    
    with app.app_context():
        # Crear todas las tablas
        db.create_all()
        
        # Limpiar datos existentes
        db.session.query(Pago).delete()
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
            tipo_cliente='abonado',
            estado='activo'
        )
        
        cliente2 = Usuario(
            nombre='María',
            apellido='López',
            dni='45678901',
            email='maria@example.com',
            password=generate_password_hash('cliente123'),
            tipo_usuario='cliente',
            tipo_cliente='no_abonado',
            estado='activo'
        )
        
        db.session.add_all([cliente1, cliente2])
        db.session.commit()
        print("✓ Clientes creados")
        
        # Crear turnos de ejemplo
        now = datetime.utcnow()
        
        for i in range(5):
            fecha = now + timedelta(days=i+1)
            
            # Turnos de Fútbol
            turno_futbol = Turno(
                actividad='futbol',
                hora_inicio=fecha.replace(hour=10, minute=0),
                hora_fin=fecha.replace(hour=11, minute=0),
                capacidad_maxima=5,
                cupos_disponibles=3
            )
            
            # Turnos de Básquet
            turno_basquet = Turno(
                actividad='basquet',
                hora_inicio=fecha.replace(hour=15, minute=0),
                hora_fin=fecha.replace(hour=16, minute=0),
                capacidad_maxima=8,
                cupos_disponibles=5
            )
            
            # Turnos de Vóley
            turno_voley = Turno(
                actividad='voley',
                hora_inicio=fecha.replace(hour=18, minute=0),
                hora_fin=fecha.replace(hour=19, minute=0),
                capacidad_maxima=12,
                cupos_disponibles=8
            )
            
            # Turnos de Pádel
            turno_padel = Turno(
                actividad='padel',
                hora_inicio=fecha.replace(hour=20, minute=0),
                hora_fin=fecha.replace(hour=21, minute=0),
                capacidad_maxima=4,
                cupos_disponibles=2
            )
            
            db.session.add_all([turno_futbol, turno_basquet, turno_voley, turno_padel])
        
        db.session.commit()
        print("✓ Turnos creados (5 días x 4 actividades)")
        
        # Crear pagos de ejemplo
        pago1 = Pago(
            usuario_id=cliente1.id,
            monto=500.00,
            metodo_pago='efectivo',
            estado='completado',
            fecha_pago=now
        )
        
        pago2 = Pago(
            usuario_id=cliente2.id,
            monto=250.00,
            metodo_pago='tarjeta_credito',
            estado='pendiente'
        )
        
        db.session.add_all([pago1, pago2])
        db.session.commit()
        print("✓ Pagos de ejemplo creados")
        
        print("\n✅ Base de datos inicializada correctamente!")
        print("\nCuentas de prueba:")
        print("- Admin: admin@club360.com / admin123")
        print("- Empleado: juan@club360.com / empleado123")
        print("- Cliente (Abonado): carlos@example.com / cliente123")
        print("- Cliente (No Abonado): maria@example.com / cliente123")


if __name__ == '__main__':
    init_database()
