# Consola y demos - Club 360

Guía rápida para preparar escenarios desde consola y mostrar el producto al cliente.

Ejecutar siempre desde la raíz del proyecto:

```bash
cd /home/santi/Desktop/Club/Club360
source venv/bin/activate
```

## Base de datos

La base SQLite está en:

```bash
instance/club360.db
```

Abrir consola SQL:

```bash
sqlite3 instance/club360.db
```

Ver usuarios:

```sql
SELECT id, email, tipo_usuario, estado, tarjeta_credito_saldo
FROM usuarios
ORDER BY tipo_usuario, email;
```

Ver deudas pendientes:

```sql
SELECT p.id, u.email, p.monto, p.tipo_clase, p.metodo_pago, p.estado, p.referencia_transaccion
FROM pagos p
JOIN usuarios u ON u.id = p.usuario_id
WHERE p.estado = 'pendiente'
ORDER BY u.email, p.fecha_pago;
```

Ver suspensiones:

```sql
SELECT s.id, u.email, s.motivo, s.estado, s.fecha_inicio, s.fecha_resolucion
FROM suspensiones s
JOIN usuarios u ON u.id = s.usuario_id
ORDER BY s.fecha_inicio DESC;
```

Salir:

```sql
.exit
```

## Script de demo

Hay un helper para preparar casos y evitar escribir SQL largo:

```bash
python scripts/demo_console.py --help
```

Ver estado general de usuarios:

```bash
python scripts/demo_console.py status
```

Ver suspensiones registradas:

```bash
python scripts/demo_console.py suspensiones
```

## Crear una cuenta desde consola

Cliente:

```bash
python scripts/demo_console.py create-user \
  --email demo@example.com \
  --password cliente123 \
  --nombre Demo \
  --apellido Cliente \
  --tipo cliente \
  --saldo 100000
```

Empleado:

```bash
python scripts/demo_console.py create-user \
  --email empleado.demo@club360.com \
  --password empleado123 \
  --nombre Empleado \
  --apellido Demo \
  --tipo empleado \
  --saldo 0
```

Administrador:

```bash
python scripts/demo_console.py create-user \
  --email admin.demo@club360.com \
  --password admin123 \
  --nombre Admin \
  --apellido Demo \
  --tipo administrador \
  --saldo 0
```

## Modificar fondos de tarjeta ficticia

Poner fondos:

```bash
python scripts/demo_console.py set-saldo --email sinfondos@example.com --saldo 100000
```

Sacar fondos:

```bash
python scripts/demo_console.py set-saldo --email sinfondos@example.com --saldo 0
```

SQL equivalente:

```sql
UPDATE usuarios
SET tarjeta_credito_saldo = 0
WHERE email = 'sinfondos@example.com';
```

## Crear un turno desde consola

```bash
python scripts/demo_console.py create-turno \
  --actividad padel \
  --inicio "2026-05-20 14:00" \
  --capacidad 4
```

SQL para ver turnos:

```sql
SELECT id, actividad, hora_inicio, hora_fin, capacidad_maxima, cupos_disponibles, cancelado
FROM turnos
ORDER BY hora_inicio DESC;
```

## Eliminar una reserva de un usuario

Primero buscar la reserva:

```sql
SELECT r.id, u.email, r.turno_id, t.actividad, t.hora_inicio, r.tipo_clase
FROM reservas r
JOIN usuarios u ON u.id = r.usuario_id
JOIN turnos t ON t.id = r.turno_id
WHERE u.email = 'maria@example.com'
ORDER BY t.hora_inicio;
```

Eliminar por email y turno:

```bash
python scripts/demo_console.py delete-reserva \
  --email maria@example.com \
  --turno-id 12
```

El script devuelve el cupo al turno automáticamente.

## Demo: suspensión por abono impago

Regla: un abono del mes se debe pagar entre el 1 y el 10 inclusive. Desde el día 11, si sigue pendiente, el cliente queda suspendido para reservas abonadas y se liberan sus clases futuras.

Preparar escenario:

```bash
python scripts/demo_console.py demo-suspension-abonada \
  --email maria@example.com \
  --actividad padel \
  --hora 14 \
  --monto 500
```

Luego mostrar:

```bash
python scripts/demo_console.py status
python scripts/demo_console.py suspensiones
```

En la app:

- Iniciar sesión como `maria@example.com / cliente123`.
- Ir a `Mis Deudas`.
- Ver deuda de abono como un único bloque.
- Pagar la deuda para levantar la suspensión.

## Demo: suspensión por 3 deudas no abonadas

Regla: una clase no abonada cobra seña al reservar y deja pendiente el saldo. Si el saldo no se paga antes de la clase, cuenta como strike. Con 3 strikes, el cliente queda suspendido para turnos no abonados.

Preparar escenario:

```bash
python scripts/demo_console.py demo-suspension-no-abonada \
  --email carlos@example.com \
  --actividad padel \
  --hora 14 \
  --monto 120
```

Luego mostrar:

```bash
python scripts/demo_console.py status
python scripts/demo_console.py suspensiones
```

En la app:

- Iniciar sesión como `carlos@example.com / cliente123`.
- Ir a `Mis Deudas`.
- Ver deuda como `Suspensión turnos no abonados`.
- Pagar suspensión.
- Intentar reservar una clase no abonada antes y después del pago.

## Cobrar deuda como empleado

Cuenta:

```text
juan@club360.com / empleado123
```

Flujo:

1. Iniciar sesión como empleado.
2. Ir a `Cobrar Deudas`.
3. Buscar al cliente por email, por ejemplo `maria@example.com`.
4. Cobrar una deuda individual o el total en efectivo.

## QR y asistencia

Ver último mail simulado:

```bash
tail -n 80 instance/mail_outbox.log
```

Los QR generados quedan en:

```bash
ls instance/qrs
```

Validar asistencia manual como empleado:

```text
/turnos/validar-asistencia
```

Se puede pegar el token o el link completo recibido en el mail simulado.

## Reseteo rápido

Volver a datos base:

```bash
python init_db.py
```

Esto limpia usuarios, turnos, reservas, pagos y deja las cuentas de prueba iniciales.
