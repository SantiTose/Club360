# Club 360 - Sistema de Gestión de Turnos Deportivos

## Descripción del Proyecto

Club 360 es un sistema web de gestión de turnos deportivos diseñado para un centro de actividades que ofrece servicios de reserva de clases para fútbol, básquet, vóley y pádel.

## Funcionalidades Principales

### 1. Gestión de Usuarios
- Registro de nuevos usuarios
- Inicio de sesión seguro
- Restablecimiento de contraseña
- Creación de cuentas por empleados
- Creación de cuentas por administradores
- Tipos de usuario: Cliente, Empleado, Administrador
- Estados de cliente: Activo, Suspendido

### 2. Gestión de Turnos
- Visualización de turnos disponibles
- Reserva de turnos con cupo limitado
- Cancelación de reservas
- Listas de espera por tipo (General, Abonados, No Abonados)
- Tipos de clase por turno: Abonada / No Abonada
- Búsqueda de turnos (para empleados)
- Notificación administrativa cuando la lista de espera llega a 10 personas

### 3. Gestión de Pagos
- Visualización de deudas pendientes
- Pago online de clientes con tarjeta de crédito
- Registro presencial por empleados: efectivo o tarjeta de crédito
- Estados: Pendiente, Completado
- Políticas de cobro diferenciadas por tipo de clase (abonada/no abonada) al reservar turnos

### 4. Gestión de Suspensiones
- Solicitud de alta de suspensión por usuarios
- Aprobación de altas por administradores
- Registro de motivos de suspensión
- Estados: Activa, Resuelta

## Estructura del Proyecto

```
Club360/
├── app.py                       # Punto de entrada
├── config.py                    # Configuración por entorno
├── requirements.txt             # Dependencias del proyecto
├── website/                     # Lógica backend Flask
│   ├── __init__.py              # App factory + blueprints
│   ├── models.py                # Modelos SQLAlchemy
│   ├── auth/
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── turnos/
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── pagos/
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── suspensiones/
│   │   ├── __init__.py
│   │   └── routes.py
│   └── services/
│       ├── __init__.py
│       └── notificaciones.py
├── templates/                   # Templates Jinja2
│   ├── base.html
│   ├── index.html
│   ├── auth/
│   ├── turnos/
│   ├── pagos/
│   └── suspensiones/
└── statics/                     # CSS, JS e imágenes
    ├── css/
    │   └── style.css
    ├── js/
    │   └── main.js
    └── images/
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
- estado de cliente (activo, suspendido)
- fecha_creacion, fecha_actualizacion

### Turno
- id, actividad, hora_inicio, hora_fin
- capacidad_maxima, cupos_disponibles
- usuario_id (reservado por), cancelado
- fecha_creacion

### ListaEspera
- id, usuario_id, turno_id
- tipo_lista (general, abonados, no_abonados)
- posicion, fecha_registro

### Pago
- id, usuario_id, monto
- metodo_pago (efectivo, tarjeta_credito)
- tipo_clase (abonada, no_abonada)
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
- Flask-Migrate 4.1.0
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
