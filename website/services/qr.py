import os


def generar_qr_asistencia(base_dir, reserva, validation_url):
    """Genera un PNG con el QR de asistencia y devuelve su ruta local."""
    try:
        import qrcode
    except ImportError as exc:
        raise RuntimeError('Falta instalar la dependencia qrcode para generar QR.') from exc

    qr_dir = os.path.join(base_dir, 'instance', 'qrs')
    os.makedirs(qr_dir, exist_ok=True)

    filename = f"reserva-{reserva.id}-{reserva.qr_token}.png"
    qr_path = os.path.join(qr_dir, filename)
    img = qrcode.make(validation_url)
    img.save(qr_path)
    return qr_path
