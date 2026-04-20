# 🚀 INSTRUCCIONES DE CONFIGURACIÓN - Club 360

## ⚠️ Problema Resuelto: pip: command not found

Si recibes el error `pip: command not found`, es porque necesitas activar el entorno virtual primero.

---

## ✅ SOLUCIÓN RÁPIDA (30 segundos)

Ejecuta estos 3 comandos en la terminal:

```bash
# 1. Ir al directorio del proyecto
cd /Users/nicobasaj/Desktop/Club360/Club360

# 2. Activar el entorno virtual
source venv/bin/activate

# 3. Ejecutar la aplicación
python3 app.py
```

Luego abre: **http://localhost:5000**

---

## 📋 INSTRUCCIONES PASO A PASO

### Paso 1️⃣: Abrir Terminal

```bash
cd /Users/nicobasaj/Desktop/Club360/Club360
```

### Paso 2️⃣: Activar Entorno Virtual

**En macOS/Linux:**
```bash
source venv/bin/activate
```

**En Windows:**
```bash
venv\Scripts\activate
```

✅ Sabrás que funciona cuando veas `(venv)` al inicio de tu línea de comando

### Paso 3️⃣: Instalar Dependencias (Solo primera vez)

```bash
pip install -r requirements.txt
```

Espera a que termine. Verás:
```
Successfully installed Flask-3.1.3 Flask-Login-0.6.3 ...
```

### Paso 4️⃣: Ejecutar la Aplicación

```bash
python3 app.py
```

Verás algo como:
```
 * Serving Flask app 'website'
 * Debug mode: on
 * Running on http://127.0.0.1:5000
```

### Paso 5️⃣: Acceder al Proyecto

Abre tu navegador y ve a:
```
http://localhost:5000
```

---

## 🎯 FORMA MÁS FÁCIL: Usar el Script

Ya hemos creado un script para ti. Solo ejecuta:

```bash
./run.sh
```

Esto hace todo automáticamente.

---

## 🔧 TROUBLESHOOTING

### ❌ Error: `venv: command not found`

**Solución**: Crea el entorno virtual:
```bash
python3 -m venv venv
source venv/bin/activate
```

### ❌ Error: `pip: command not found` después de `source venv/bin/activate`

**Soluciones**:
1. Verifica que estés en el directorio correcto:
   ```bash
   pwd
   # Debe mostrar: /Users/nicobasaj/Desktop/Club360/Club360
   ```

2. Intenta de nuevo:
   ```bash
   source venv/bin/activate
   pip --version
   ```

3. Si aún no funciona, recrea el venv:
   ```bash
   rm -rf venv
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

### ❌ Error: `ModuleNotFoundError: No module named 'flask'`

**Solución**: Instala las dependencias:
```bash
pip install -r requirements.txt
```

### ❌ Puerto 5000 ya está en uso

**Solución**: Usa otro puerto:
```bash
python3 app.py --port 5001
```

Luego accede a: `http://localhost:5001`

### ❌ "Address already in use"

**Solución**: Mata el proceso:
```bash
# macOS/Linux
lsof -ti:5000 | xargs kill -9

# O cambia de puerto
python3 app.py --port 5001
```

---

## ✅ VERIFICACIÓN

Una vez que ejecutes `python3 app.py`, deberías ver:

```
 * Serving Flask app 'website'
 * Debug mode: on
 * Running on http://127.0.0.1:5000
 * Press CTRL+C to quit
```

Si ves esto: ✅ **¡El proyecto funciona!**

---

## 📝 COMANDOS ÚTILES

### Activar el venv (siempre lo primero)
```bash
source venv/bin/activate
```

### Desactivar el venv
```bash
deactivate
```

### Ver dependencias instaladas
```bash
pip list
```

### Actualizar una dependencia
```bash
pip install --upgrade Flask
```

### Instalar nuevo paquete
```bash
pip install nombre-paquete
pip freeze > requirements.txt  # Actualizar requirements.txt
```

---

## 🎓 ESTRUCTURA DE CARPETAS

```
Club360/
├── venv/              ← Entorno virtual (virtual environment)
├── website/           ← Código principal
├── templates/         ← Páginas HTML
├── statics/           ← CSS, JS, imágenes
├── app.py             ← Punto de entrada
├── requirements.txt   ← Lista de dependencias
├── run.sh            ← Script para iniciar (NUEVO)
└── README.md         ← Documentación
```

---

## 🚀 PRÓXIMAS VECES

Cuando vuelvas a trabajar en el proyecto:

```bash
# 1. Navega al proyecto
cd /Users/nicobasaj/Desktop/Club360/Club360

# 2. Activa venv
source venv/bin/activate

# 3. Ejecuta
python3 app.py

# 4. Abre navegador
# http://localhost:5000
```

O simplemente:
```bash
cd /Users/nicobasaj/Desktop/Club360/Club360
./run.sh
```

---

## 💡 TIPS

✨ El entorno virtual (`venv/`) NO se comparte en git. Es local a tu computadora.

✨ Cada vez que abras una nueva terminal, debes activar el venv.

✨ Si alguien nuevo clona el proyecto, solo necesita:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

✨ `requirements.txt` contiene todas las dependencias. Es lo que se comparte.

---

## ✅ CHECKLIST

- [ ] Terminal abierta en `/Users/nicobasaj/Desktop/Club360/Club360`
- [ ] Entorno virtual activado (`source venv/bin/activate`)
- [ ] Dependencias instaladas (`pip install -r requirements.txt`)
- [ ] Aplicación corriendo (`python3 app.py`)
- [ ] Navegador abierto en `http://localhost:5000`
- [ ] ¡Funciona! ✅

---

¿Tienes más preguntas? Revisa:
- `README.md` - Documentación principal
- `QUICKSTART.md` - Guía rápida
- `CONTRIBUTING.md` - Cómo contribuir
