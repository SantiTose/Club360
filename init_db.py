"""
Script para inicializar la base de datos sin turnos precargados.
Ejecutar: python init_db.py
"""

from website import create_app, db
from website.models import Usuario, Turno, Pago, Reserva
from werkzeug.security import generate_password_hash


def init_database():
    """Inicializa la base de datos sin turnos de ejemplo."""
    app = create_app('development')
    
    with app.app_context():
        # Crear todas las tablas
        db.create_all()
        
        # Limpiar datos existentes
        db.session.query(Reserva).delete()
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
            estado='activo'
        )
        
        cliente2 = Usuario(
            nombre='María',
            apellido='López',
            dni='45678901',
            email='maria@example.com',
            password=generate_password_hash('cliente123'),
            tipo_usuario='cliente',
            estado='activo'
        )
        
        db.session.add_all([cliente1, cliente2])
        db.session.commit()
        print("✓ Clientes creados")
        
        print("✓ Sin turnos de ejemplo (calendario inicia vacío)")
        print("✓ Sin pagos de ejemplo")
        
        print("\n✅ Base de datos inicializada correctamente!")
        print("\nCuentas de prueba:")
        print("- Admin: admin@club360.com / admin123")
        print("- Empleado: juan@club360.com / empleado123")
        print("- Cliente 1: carlos@example.com / cliente123")
        print("- Cliente 2: maria@example.com / cliente123")


if __name__ == '__main__':
    init_database()
