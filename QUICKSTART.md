# Guía Rápida de Inicio - Club 360

## 1. Primer Inicio

```bash
# Activar entorno virtual
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Inicializar base de datos (sin turnos precargados)
python init_db.py

# Ejecutar aplicación
python app.py
```

La aplicación estará en: **http://localhost:5000**

## 2. Cuentas de Prueba

Después de ejecutar `init_db.py`, tendrás:

| Rol | Email | Contraseña |
|-----|-------|-----------|
| Administrador | admin@club360.com | admin123 |
| Empleado | juan@club360.com | empleado123 |
| Cliente 1 | carlos@example.com | cliente123 |
| Cliente 2 | maria@example.com | cliente123 |

## 3. Características Disponibles

### Para Clientes
- ✓ Registrarse e iniciar sesión
- ✓ Ver turnos disponibles
- ✓ Reservar un turno
- ✓ Cancelar reservas
- ✓ Ver deudas pendientes
- ✓ Pagar deudas online con tarjeta de crédito
- ✓ Solicitar alta de suspensión

### Para Empleados
- ✓ Buscar turnos
- ✓ Registrar pagos de clientes

### Para Administradores
- ✓ Acceso a todas las funcionalidades
- ✓ Gestión de suspensiones
- ✓ Crear y editar turnos desde calendario real

## Reglas de Turnos

- Solo de lunes a sábado
- Franja horaria de 08:00 a 22:00
- Duración fija de 1 hora (08-09, 09-10, etc.)
- Los domingos y feriados nacionales no se pueden crear ni reservar turnos

## 4. Estructura de Módulos

```
website/
├── auth/          → Gestión de Usuarios (login, registro)
├── turnos/        → Gestión de Turnos (reservar, cancelar)
├── pagos/         → Gestión de Pagos
├── suspensiones/  → Gestión de Suspensiones
└── models.py      → Modelos de base de datos
```

## 5. Rutas Principales

| Ruta | Descripción |
|------|------------|
| `/` | Página de inicio |
| `/auth/register` | Registrar nuevo usuario |
| `/auth/login` | Iniciar sesión |
| `/auth/crear-usuario` | Crear cuentas (empleado/admin) |
| `/turnos/disponibles` | Ver turnos disponibles |
| `/turnos/mis-turnos` | Mis turnos reservados |
| `/pagos/deuda` | Ver deudas |
| `/suspensiones/solicitar-alta` | Solicitar alta |

## 6. Stack Tecnológico

- **Backend:** Flask 3.1.3
- **Base de Datos:** SQLite (desarrollo)
- **ORM:** SQLAlchemy
- **Autenticación:** Flask-Login
- **Validación de Formularios:** Validaciones HTML + backend (Flask)
- **Frontend:** HTML5 + CSS + Vanilla JavaScript

## 7. Desarrollo Local

### Agregar una nueva ruta

1. Ir al módulo correspondiente (ej: `website/turnos/`)
2. Editar `routes.py`:

```python
@turnos_bp.route('/nueva-ruta', methods=['GET', 'POST'])
@login_required
def nueva_funcion():
    return render_template('turnos/template.html')
```

3. Crear template en `templates/turnos/template.html`

### Modificar modelos de datos

1. Editar `website/models.py`
2. Generar migración (si está configurado):
```bash
flask db migrate -m "Descripción del cambio"
flask db upgrade
```
3. O simplemente eliminar `club360.db` y ejecutar `init_db.py` nuevamente

## 8. Archivos Importantes

- `app.py` - Punto de entrada
- `config.py` - Configuración (dev, prod, testing)
- `init_db.py` - Script para inicializar BD
- `requirements.txt` - Dependencias
- `website/__init__.py` - Configuración de Flask
- `website/models.py` - Modelos de datos

## 9. Tips de Desarrollo

### Ver logs en tiempo real
```bash
tail -f debug.log
```

### Reiniciar BD
```bash
rm club360.db
python init_db.py
```

### Instalar nuevo paquete
```bash
pip install nombre-paquete
pip freeze > requirements.txt
```

### Testing de rutas
Usar Postman, Insomnia o curl

## 10. Próximos Pasos

1. **Implementar panel de administrador**
2. **Agregar notificaciones por email**
3. **Integración con pasarela de pago**
4. **Generación de códigos QR**
5. **Pruebas unitarias**
6. **Despliegue en producción**

## 11. Troubleshooting

### ❌ "ModuleNotFoundError: No module named 'flask'"
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### ❌ "Address already in use"
```bash
# Cambiar puerto
python app.py --port 5001
```

### ❌ Base de datos corrupta
```bash
rm club360.db
python init_db.py
```

### ❌ Cambios en código no aparecen
- Reiniciar la aplicación
- Limpiar caché del navegador (Ctrl+Shift+Delete)
- Verificar que `DEBUG = True` en `config.py`

## 12. Contacto y Soporte

- 📧 Email del equipo de desarrollo
- 💬 Canal de Slack/Discord
- 📋 Issues en el repositorio
- 📚 Documentación en README.md

---

¡Bienvenido al desarrollo de Club 360! 🚀
