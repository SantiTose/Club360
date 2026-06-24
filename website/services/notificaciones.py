import os
import smtplib
from datetime import datetime
from email.message import EmailMessage


class EmailDeliveryError(Exception):
    pass


def _get_outbox_path(base_dir):
    instance_dir = os.path.join(base_dir, 'instance')
    os.makedirs(instance_dir, exist_ok=True)
    return os.path.join(instance_dir, 'mail_outbox.log')


def _cargar_env_local(base_dir):
    env_path = os.path.join(base_dir, '.env')
    if not os.path.exists(env_path):
        return

    with open(env_path, 'r', encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def _get_mail_env(cuenta_mail, suffix, default=''):
    if cuenta_mail == 'default':
        return os.environ.get(f'MAIL_{suffix}', default).strip()
    return os.environ.get(f'{cuenta_mail.upper()}_MAIL_{suffix}', default).strip()


def _get_smtp_config(base_dir, cuenta_mail='default'):
    _cargar_env_local(base_dir)
    server = _get_mail_env(cuenta_mail, 'SERVER', os.environ.get('MAIL_SERVER', ''))
    if not server:
        return None

    return {
        'server': server,
        'port': int(_get_mail_env(cuenta_mail, 'PORT', os.environ.get('MAIL_PORT', '587'))),
        'username': _get_mail_env(cuenta_mail, 'USERNAME'),
        'password': _get_mail_env(cuenta_mail, 'PASSWORD'),
        'use_tls': _get_mail_env(cuenta_mail, 'USE_TLS', os.environ.get('MAIL_USE_TLS', 'true')).lower() in {'1', 'true', 'yes', 'on'},
        'sender': _get_mail_env(
            cuenta_mail,
            'DEFAULT_SENDER',
            _get_mail_env(cuenta_mail, 'USERNAME', os.environ.get('MAIL_USERNAME', 'club360@example.com')),
        ),
    }


def _log_email(outbox, destinatario, asunto, cuerpo):
    timestamp = datetime.utcnow().isoformat()
    contenido = (
        f"\n=== EMAIL {timestamp} ===\n"
        f"TO: {destinatario}\n"
        f"SUBJECT: {asunto}\n"
        f"BODY:\n{cuerpo}\n"
        f"=== FIN EMAIL ===\n"
    )
    with open(outbox, 'a', encoding='utf-8') as f:
        f.write(contenido)


def enviar_email_simulado(base_dir, destinatario, asunto, cuerpo, requiere_envio_real=False, cuenta_mail='default'):
    """Envía un email real si hay SMTP configurado; si no, lo guarda en el outbox local."""
    outbox = _get_outbox_path(base_dir)
    smtp_config = _get_smtp_config(base_dir, cuenta_mail)

    if smtp_config:
        try:
            msg = EmailMessage()
            msg['Subject'] = asunto
            msg['From'] = smtp_config['sender']
            msg['To'] = destinatario
            msg.set_content(cuerpo)

            with smtplib.SMTP(smtp_config['server'], smtp_config['port']) as server:
                if smtp_config['use_tls']:
                    server.starttls()
                if smtp_config['username'] and smtp_config['password']:
                    server.login(smtp_config['username'], smtp_config['password'])
                server.send_message(msg)
            return True
        except Exception as exc:
            if requiere_envio_real:
                raise EmailDeliveryError(f'No se pudo enviar el email real: {exc}') from exc

    if requiere_envio_real:
        raise EmailDeliveryError('No hay SMTP real configurado. Completa MAIL_SERVER, MAIL_USERNAME y MAIL_PASSWORD.')

    _log_email(outbox, destinatario, asunto, cuerpo)
    return False
