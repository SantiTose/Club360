# Club 360 - Sistema de Gestión de Turnos Deportivos

## Descripción del Proyecto

Club 360 es un sistema web de gestión de turnos deportivos diseñado para un centro de actividades que ofrece servicios de reserva de clases para fútbol, básquet, vóley y pádel.

## Funcionalidades Principales

### 1. Gestión de Usuarios
- Registro de nuevos usuarios
- Inicio de sesión seguro
- Restablecimiento de contraseña
- Creación de cuentas por empleados
- Tipos de usuario: Cliente, Empleado, Administrador
- Estados: Activo, Suspendido, Inactivo

### 2. Gestión de Turnos
- Visualización de turnos disponibles
- Reserva de turnos con cupo limitado
- Cancelación de reservas
- Lista de espera (General, Abonados, No Abonados)
- Búsqueda de turnos (para empleados)
- Notificaciones cuando la lista de espera llega a 10 personas

### 3. Gestión de Pagos
- Visualización de deudas pendientes
- Registro de pagos en efectivo o tarjeta de crédito
- Métodos de pago: Efectivo, Tarjeta de Crédito
- Estados: Pendiente, Completado
- Políticas de cobro diferenciadas para abonados y no abonados

### 4. Gestión de Suspensiones
- Solicitud de alta de suspensión por usuarios
- Aprobación de altas por administradores
- Registro de motivos de suspensión
- Estados: Activa, Resuelta

## Estructura del Proyecto

```
Club360/
├── website/                      # Directorio principal de la aplicación
│   ├── __init__.py              # Configuración de Flask y registración de Blueprints
│   ├── models.py                # Modelos de base de datos (SQLAlchemy)
│   ├── auth/                    # Épica: Gestión de Usuarios
│   │   ├── __init__.py
│   │   ├── routes.py            # Rutas de login, registro, logout
│   │   └── forms.py             # Formularios de Flask-WTF
│   ├── turnos/                  # Épica: Gestión de Turnos
│   │   ├── __init__.py
│   │   └── routes.py            # Rutas de reservar, cancelar, verificar
│   ├── pagos/                   # Épica: Gestión de Pagos
│   │   ├── __init__.py
│   │   └── routes.py            # Rutas de pago y registro
│   ├── suspensiones/            # Épica: Gestión de Suspensiones
│   │   ├── __init__.py
│   │   └── routes.py            # Rutas de suspensiones
│   ├── static/                  # Archivos estáticos
│   │   ├── css/
│   │   │   └── style.css
│   │   ├── js/
│   │   │   └── main.js
│   │   └── images/
│   └── templates/               # Archivos HTML
│       ├── base.html            # Navbar y Footer principal
│       ├── index.html           # Página de inicio
│       ├── auth/                # Templates de usuarios
│       │   ├── login.html
│       │   ├── register.html
│       │   └── reset_password.html
│       ├── turnos/              # Templates de turnos
│       │   ├── disponibles.html
│       │   └── mis_turnos.html
│       ├── pagos/               # Templates de pagos
│       │   ├── deuda.html
│       │   └── pagar.html
│       └── suspensiones/        # Templates de suspensiones
│           └── solicitar_alta.html
├── app.py                       # Punto de entrada (solo arranca la app)
├── requirements.txt             # Dependencias del proyecto
├── .gitignore                   # Archivos a ignorar en git
└── README.md                    # Este archivo
```

## Instalación

1. **Clonar el repositorio:**
```bash
git clone <repository-url>
cd Club360
```

2. **Crear un entorno virtual:**
```bash
python3 -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate
```

3. **Instalar dependencias:**
```bash
pip install -r requirements.txt
```

4. **Ejecutar la aplicación:**
```bash
python app.py
```

La aplicación estará disponible en `http://localhost:5000`

## Modelos de Datos

### Usuario
- id, nombre, apellido, dni, email, password
- tipo_usuario (cliente, empleado, administrador)
- estado (activo, suspendido, inactivo)
- tipo_cliente (abonado, no_abonado)
- fecha_creacion, fecha_actualizacion

### Turno
- id, actividad, hora_inicio, hora_fin
- capacidad_maxima, cupos_disponibles
- usuario_id (reservado por), cancelado
- fecha_creacion

### ListaEspera
- id, usuario_id, turno_id
- tipo_lista (general, abonado, no_abonado)
- posicion, fecha_registro

### Pago
- id, usuario_id, monto
- metodo_pago (efectivo, tarjeta_credito)
- estado (pendiente, completado)
- fecha_pago, referencia_transaccion

### Suspension
- id, usuario_id, motivo
- estado (activa, resuelta)
- fecha_inicio, fecha_resolucion

## Dependencias

- Flask 3.1.3
- Flask-SQLAlchemy 3.1.1
- Flask-Login 0.6.3
- Flask-Migrate 4.0.5
- Flask-WTF 1.2.1
- WTForms 3.1.1
- Werkzeug 3.1.8

## Próximos Pasos para Desarrollo

1. Implementar autenticación mejorada (JWT, OAuth)
2. Agregar generación de códigos QR para asistencia
3. Envío de notificaciones por email
4. Panel de administrador con estadísticas
5. Integración con pasarelas de pago
6. Pruebas unitarias y de integración
7. Documentación API (Swagger/OpenAPI)
8. Despliegue en producción

## Autores

- Agustin Gonzalez
- Santino Tosetti
- Nicolas Basaj
- Gianella Graneros
- Juan Pablo Agnusdei

## Licencia

Este proyecto es parte de la materia Ingeniería de Software 2 - Facultad de Informática UNLP
