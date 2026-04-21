import os
from datetime import datetime


def _get_outbox_path(base_dir):
    instance_dir = os.path.join(base_dir, 'instance')
    os.makedirs(instance_dir, exist_ok=True)
    return os.path.join(instance_dir, 'mail_outbox.log')


def enviar_email_simulado(base_dir, destinatario, asunto, cuerpo):
    """Simula el envio de email guardandolo en un log local del proyecto."""
    outbox = _get_outbox_path(base_dir)
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
