import os
from datetime import date
from unittest.mock import patch

from werkzeug.security import check_password_hash, generate_password_hash

from website import create_app, db
from website.models import TarjetaCredito, Usuario


def test_reset_password_envia_contraseña_y_no_pide_segundo_paso(tmp_path):
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
        assert response.headers['Location'].endswith('/auth/cambiar-password-inicial')

        response = client.post(
            '/auth/cambiar-password-inicial',
            data={
                'password': 'temporal123',
                'password_confirm': 'temporal123',
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert 'La nueva contraseña no puede ser igual a la actual'.encode() in response.data

        response = client.post(
            '/auth/cambiar-password-inicial',
            data={
                'password': 'cliente456',
                'password_confirm': 'cliente456',
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers['Location'].endswith('/dashboard')

        usuario_actualizado = Usuario.query.get(usuario.id)
        assert usuario_actualizado.requiere_cambio_password is False

        response = client.post(
            '/auth/perfil/editar',
            data={
                'action': 'agregar_tarjeta',
                'tarjeta_credito': '4111111111111111',
                'tarjeta_vencimiento': '2030-12',
                'tarjeta_cvv': '123',
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers['Location'].endswith('/auth/perfil/editar')
        assert TarjetaCredito.query.filter_by(usuario_id=usuario.id).count() == 1


def test_cliente_no_puede_reutilizar_password_actual_desde_editar_perfil():
    app = create_app('testing')
    app.config['TESTING'] = True
    app.config['SERVER_NAME'] = 'localhost'

    with app.app_context():
        db.drop_all()
        db.create_all()

        usuario = Usuario(
            nombre='Maria',
            apellido='Lopez',
            dni='45678901',
            email='maria@example.com',
            password=generate_password_hash('cliente123'),
            tipo_usuario='cliente',
            estado='activo',
            tarjeta_credito_marca='Visa',
            tarjeta_credito_ultimos4='1111',
        )
        db.session.add(usuario)
        db.session.flush()
        db.session.add(TarjetaCredito(
            usuario_id=usuario.id,
            marca='Visa',
            ultimos4='1111',
            vencimiento=date(2030, 12, 31),
            saldo=100000.0,
            es_principal=True,
        ))
        db.session.commit()

        client = app.test_client()
        response = client.post(
            '/auth/login',
            data={'email': usuario.email, 'password': 'cliente123'},
            follow_redirects=False,
        )
        assert response.status_code == 302

        response = client.post(
            '/auth/perfil/editar',
            data={
                'action': 'cambiar_password',
                'password_actual': 'cliente123',
                'password': 'cliente123',
                'password_confirm': 'cliente123',
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert 'La nueva contraseña no puede ser igual a la actual'.encode() in response.data

        usuario_actualizado = Usuario.query.get(usuario.id)
        assert check_password_hash(usuario_actualizado.password, 'cliente123')


def test_crear_cliente_desde_personal_no_pide_ni_guarda_tarjeta():
    app = create_app('testing')
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SERVER_NAME'] = 'localhost'

    with app.app_context():
        db.drop_all()
        db.create_all()

        empleado = Usuario(
            nombre='Eva',
            apellido='Staff',
            dni='87654321',
            email='empleado@example.com',
            password=generate_password_hash('empleado123'),
            tipo_usuario='empleado',
        )
        db.session.add(empleado)
        db.session.commit()

        client = app.test_client()
        response = client.post(
            '/auth/login',
            data={'email': empleado.email, 'password': 'empleado123'},
            follow_redirects=False,
        )
        assert response.status_code == 302

        with patch('website.auth.routes._generar_password_temporal', return_value='temporal123'):
            response = client.post(
                '/auth/crear-usuario',
                data={
                    'nombre': 'Cliente',
                    'apellido': 'SinTarjeta',
                    'dni': '11223344',
                    'fecha_nacimiento': '1990-01-01',
                    'email': 'cliente-sin-tarjeta@example.com',
                    'tipo_usuario': 'cliente',
                },
                follow_redirects=False,
            )
        assert response.status_code == 302

        cliente = Usuario.query.filter_by(email='cliente-sin-tarjeta@example.com').one()
        assert cliente.tarjeta_credito_marca is None
        assert cliente.tarjeta_credito_ultimos4 is None
        assert cliente.tarjeta_credito_vencimiento is None
        assert cliente.requiere_cambio_password is False
        assert TarjetaCredito.query.filter_by(usuario_id=cliente.id).count() == 0

        client.get('/auth/logout')
        response = client.post(
            '/auth/login',
            data={'email': cliente.email, 'password': 'temporal123'},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers['Location'].endswith('/auth/perfil/editar')
