from flask import Blueprint

pagos_bp = Blueprint('pagos', __name__, url_prefix='/pagos')

from website.pagos import routes
