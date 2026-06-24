import os

from werkzeug.security import generate_password_hash

from website import create_app, db
from website.models import Usuario


def test_reset_password_envia_contrasena_y_no_pide_segundo_paso(tmp_path):
    app = create_app('testing')
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SERVER_NAME'] = 'localhost'

    with app.app_context():
        db.drop_all()
        db.create_all()

        usuario = Usuario(
            nombre='Ana',
            apellido='García',
            dni='12345678',
            email='ana@example.com',
            password=generate_password_hash('password-vieja'),
            tipo_usuario='cliente',
        )
        db.session.add(usuario)
        db.session.commit()

        old_hash = usuario.password

        client = app.test_client()
        response = client.post('/auth/reset-password', data={'email': usuario.email}, follow_redirects=True)

        assert response.status_code == 200
        usuario_actualizado = Usuario.query.get(usuario.id)
        assert usuario_actualizado.password != old_hash

        outbox_path = os.path.join(app.root_path, '..', 'instance', 'mail_outbox.log')
        assert os.path.exists(outbox_path)
        with open(outbox_path, 'r', encoding='utf-8') as handle:
            contenido = handle.read()
        assert usuario.email in contenido
        assert 'Contraseña' in contenido
