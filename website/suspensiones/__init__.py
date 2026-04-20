from flask import Blueprint

suspensiones_bp = Blueprint('suspensiones', __name__, url_prefix='/suspensiones')

from website.suspensiones import routes
