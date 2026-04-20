import os
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()


def create_app(config_name='development'):
    """Application factory function."""
    # Get base directory
    basedir = os.path.abspath(os.path.dirname(__file__))
    
    app = Flask(__name__,
                template_folder=os.path.join(os.path.dirname(basedir), 'templates'),
                static_folder=os.path.join(os.path.dirname(basedir), 'statics'),
                static_url_path='/static')

    # Configuration
    if config_name == 'development':
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///club360.db'
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
    
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    # Setup user loader
    @login_manager.user_loader
    def load_user(user_id):
        from website.models import Usuario
        if user_id:
            try:
                return Usuario.query.get(int(user_id))
            except:
                return None
        return None

    # Main routes
    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/dashboard')
    def dashboard():
        return render_template('dashboard.html')

    # Register blueprints
    from website.auth import auth_bp
    from website.turnos import turnos_bp
    from website.pagos import pagos_bp
    from website.suspensiones import suspensiones_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(turnos_bp)
    app.register_blueprint(pagos_bp)
    app.register_blueprint(suspensiones_bp)

    # Create tables
    with app.app_context():
        db.create_all()

    return app
