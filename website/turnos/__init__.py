from flask import Blueprint

turnos_bp = Blueprint('turnos', __name__, url_prefix='/turnos')

from website.turnos import routes
