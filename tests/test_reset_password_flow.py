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
        assert usuario_actualizado.requiere_cambio_password is True

        outbox_path = os.path.join(app.root_path, '..', 'instance', 'mail_outbox.log')
        assert os.path.exists(outbox_path)
        with open(outbox_path, 'r', encoding='utf-8') as handle:
            contenido = handle.read()
        assert usuario.email in contenido
        assert 'Contraseña' in contenido


def test_cliente_con_password_temporal_cambia_desde_editar_perfil():
    app = create_app('testing')
    app.config['TESTING'] = True
    app.config['SERVER_NAME'] = 'localhost'

    with app.app_context():
        db.drop_all()
        db.create_all()

        usuario = Usuario(
            nombre='Pepe',
            apellido='Gonzalez',
            dni='56789123',
            email='abonadoexample@gmail.com',
            password=generate_password_hash('temporal123'),
            tipo_usuario='cliente',
            estado='activo',
            requiere_cambio_password=True,
        )
        db.session.add(usuario)
        db.session.commit()

        client = app.test_client()
        response = client.post(
            '/auth/login',
            data={'email': usuario.email, 'password': 'temporal123'},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers['Location'].endswith('/auth/perfil/editar')

        response = client.get('/dashboard', follow_redirects=False)
        assert response.status_code == 302
        assert response.headers['Location'].endswith('/auth/perfil/editar')

        response = client.post(
            '/auth/perfil/editar',
            data={
                'action': 'cambiar_password',
                'password': 'cliente456',
                'password_confirm': 'cliente456',
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers['Location'].endswith('/dashboard')

        usuario_actualizado = Usuario.query.get(usuario.id)
        assert usuario_actualizado.requiere_cambio_password is False
