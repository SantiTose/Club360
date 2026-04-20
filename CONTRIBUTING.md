# Guía de Contribución - Club 360

## Estructura de Ramas

- `main` - Rama principal de producción
- `develop` - Rama de desarrollo
- `feature/*` - Ramas de nuevas características
- `bugfix/*` - Ramas de corrección de bugs

## Flujo de Trabajo

1. **Crear rama de característica:**
```bash
git checkout develop
git pull origin develop
git checkout -b feature/nombre-caracteristica
```

2. **Desarrollar la característica:**
   - Hacer cambios
   - Commit frecuentes con mensajes descriptivos
   - Seguir las convenciones de código

3. **Crear Pull Request:**
   - Push a la rama remota
   - Crear PR contra `develop`
   - Esperar revisión de código

4. **Merge y Deploy:**
   - Después de aprobación, hacer merge
   - Cuando esté listo, hacer PR de `develop` a `main`

## Convenciones de Commits

```
tipo(módulo): descripción breve

Descripción más detallada si es necesario.
Pueden incluirse múltiples líneas.
```

**Tipos de commits:**
- `feat`: Nueva característica
- `fix`: Corrección de bug
- `docs`: Cambios en documentación
- `style`: Cambios de formato (sin cambios funcionales)
- `refactor`: Refactorización de código
- `test`: Agregar o actualizar pruebas
- `chore`: Cambios en dependencias o configuración

**Ejemplos:**
```
feat(auth): agregar autenticación con email
fix(turnos): corregir cálculo de cupos disponibles
docs(readme): actualizar instrucciones de instalación
```

## Estándares de Código

### Python
- Seguir PEP 8
- Usar nombres descriptivos para variables y funciones
- Documentar funciones con docstrings
- Máximo 100 caracteres por línea

### Templates HTML
- Indentar con 4 espacios
- Usar clases Bootstrap/custom CSS consistentes
- Nombres descriptivos para IDs y clases

### CSS
- Usar clases en lugar de IDs para estilos
- Variables CSS para colores y espaciado
- Mobile-first approach

### JavaScript
- Usar `const` por defecto, `let` si necesita reasignación
- Evitar variables globales
- Comentar código complejo

## Testing

Antes de hacer push, verificar que:
1. La app inicia sin errores
2. Los formularios funcionan correctamente
3. No hay errores en la consola del navegador

## Setup de Desarrollo

1. **Crear entorno virtual:**
```bash
python3 -m venv venv
source venv/bin/activate
```

2. **Instalar dependencias:**
```bash
pip install -r requirements.txt
```

3. **Inicializar base de datos:**
```bash
python init_db.py
```

4. **Ejecutar aplicación:**
```bash
python app.py
```

5. **Acceder a:**
```
http://localhost:5000
```

## Épicas de Desarrollo

### 1. Gestión de Usuarios ✓
- [x] Registro de usuarios
- [x] Login/Logout
- [x] Reset de contraseña
- [ ] Gestión de empleados (admin)
- [ ] Validación de edad

### 2. Gestión de Turnos ✓
- [x] Listar turnos disponibles
- [x] Reservar turno
- [x] Cancelar reserva
- [x] Lista de espera
- [ ] Generación de QR
- [ ] Notificaciones de lista de espera

### 3. Gestión de Pagos ✓
- [x] Ver deudas
- [x] Registrar pagos
- [ ] Integración con pasarela de pago
- [ ] Facturas/Recibos

### 4. Gestión de Suspensiones ✓
- [x] Solicitar alta
- [x] Dar de alta (admin)
- [ ] Notificaciones por email
- [ ] Reporte de suspensiones

## Cambios Recientes

### Base Project Structure
- ✓ Estructura inicial del proyecto
- ✓ Modelos de datos con SQLAlchemy
- ✓ Blueprints para cada módulo
- ✓ Templates básicos con Bootstrap
- ✓ Sistema de autenticación con Flask-Login

## Próximas Prioridades

1. **Panel de Administrador:**
   - Dashboard con estadísticas
   - Gestión de usuarios
   - Gestión de turnos (crear, editar, cancelar)
   - Reportes

2. **Mejoras de UX:**
   - Validación más robusta en formularios
   - Mensajes de error más descriptivos
   - Interfaz responsiva mejorada

3. **Notificaciones:**
   - Email de confirmación de reserva
   - Alerta de deuda
   - Notificación de cambios

4. **Seguridad:**
   - CSRF protection en todos los formularios
   - Rate limiting en login
   - Hashing seguro de contraseñas

## Recursos Útiles

- [Flask Documentation](https://flask.palletsprojects.com/)
- [SQLAlchemy ORM](https://docs.sqlalchemy.org/en/14/orm/)
- [Flask-Login](https://flask-login.readthedocs.io/)
- [WTForms Documentation](https://wtforms.readthedocs.io/)
- [Bootstrap 5](https://getbootstrap.com/docs/5.0/)

## Contacto

Para preguntas o issues, crear un issue en el repositorio o contactar al equipo de desarrollo.
