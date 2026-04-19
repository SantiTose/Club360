from flask import Blueprint, render_template

turnos = Blueprint('turnos', __name__)

@turnos.route('/')
def turnos_home():
    return "<h1>Panel de Gestión de Turnos</h1>"

@turnos.route('/reservar')
def reservar():
    return "<h1>Reservar Turno</h1>"