#!/bin/bash

# Script para iniciar Club360
# Uso: ./run.sh

echo "🚀 Iniciando Club 360..."
echo ""

# Activar entorno virtual
source venv/bin/activate

# Verificar que Flask está disponible
if ! python3 -c "import flask" 2>/dev/null; then
    echo "❌ Error: Flask no está instalado"
    echo "Instala las dependencias primero:"
    echo "  pip install -r requirements.txt"
    exit 1
fi

echo "✅ Entorno virtual activado"
echo "✅ Dependencias verificadas"
echo ""
echo "🌐 Iniciando servidor..."
echo "📍 Accede a: http://localhost:5000"
echo ""
echo "Presiona Ctrl+C para detener el servidor"
echo ""

# Ejecutar la aplicación
python3 app.py
