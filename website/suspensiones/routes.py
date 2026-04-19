from flask import Blueprint, render_template

suspensiones = Blueprint('suspensiones', __name__)

@suspensiones.route('/')
def pagos_home():
    return "<h1>Sección de Suspensiones</h1>"