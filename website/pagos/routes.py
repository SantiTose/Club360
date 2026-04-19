from flask import Blueprint, render_template

pagos = Blueprint('pagos', __name__)

@pagos.route('/')
def pagos_home():
    return "<h1>Sección de Pagos</h1>"