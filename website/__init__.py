from flask import Flask

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'club360_unlp_2026'

    # Importacion de Blueprints
    from website.views import views
    from website.auth.routes import auth
    from website.turnos.routes import turnos
    from website.pagos.routes import pagos
    from website.suspensiones.routes import suspensiones


    # Registro de los Blueprints
    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(auth, url_prefix='/')
    app.register_blueprint(turnos, url_prefix='/turnos')
    app.register_blueprint(pagos, url_prefix='/pagos')
    app.register_blueprint(suspensiones, url_prefix='/suspensiones')

    return app

