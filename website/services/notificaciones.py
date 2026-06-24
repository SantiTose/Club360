import os
import smtplib
from datetime import datetime
from email.message import EmailMessage


def _get_outbox_path(base_dir):
    instance_dir = os.path.join(base_dir, 'instance')
    os.makedirs(instance_dir, exist_ok=True)
    return os.path.join(instance_dir, 'mail_outbox.log')


def _get_smtp_config():
    server = os.environ.get('MAIL_SERVER', '').strip()
    if not server:
        return None

    return {
        'server': server,
        'port': int(os.environ.get('MAIL_PORT', '587')),
        'username': os.environ.get('MAIL_USERNAME', '').strip(),
        'password': os.environ.get('MAIL_PASSWORD', '').strip(),
        'use_tls': os.environ.get('MAIL_USE_TLS', 'true').strip().lower() in {'1', 'true', 'yes', 'on'},
        'sender': os.environ.get('MAIL_DEFAULT_SENDER', os.environ.get('MAIL_USERNAME', 'club360@example.com')).strip(),
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


def enviar_email_simulado(base_dir, destinatario, asunto, cuerpo):
    """Envía un email real si hay SMTP configurado; si no, lo guarda en el outbox local."""
    outbox = _get_outbox_path(base_dir)
    smtp_config = _get_smtp_config()

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
            return
        except Exception:
            pass

    _log_email(outbox, destinatario, asunto, cuerpo)
