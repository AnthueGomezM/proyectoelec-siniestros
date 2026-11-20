"""Almacenamiento de imágenes adjuntas a un siniestro: disco local, no PostgreSQL.

Las fotos no se guardan en la base de datos (evita filas de varios MB y backups
lentos): se escriben en un volumen Docker y solo la ruta relativa, el tipo MIME y el
tamaño quedan en `claim_attachments`. El nombre de archivo es siempre generado por el
servidor (nunca el que mandó el navegador), así que no hay forma de que el nombre del
cliente escape al sistema de archivos.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

#: Único subconjunto de imágenes que el analizador de visión soporta.
ALLOWED_MIME_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class ImageRejected(ValueError):
    """La imagen no cumple el tipo o el tamaño permitido. Error del cliente, no del sistema."""


def save_image(uploads_dir: Path, data: bytes, content_type: str, max_bytes: int) -> tuple[str, str, int]:
    """Valida y guarda la imagen. Devuelve (ruta_relativa, mime_type, tamaño_bytes)."""
    mime = (content_type or "").split(";")[0].strip().lower()
    extension = ALLOWED_MIME_TYPES.get(mime)
    if extension is None:
        raise ImageRejected(
            f"Tipo de imagen no soportado: {mime or 'desconocido'}. "
            f"Usa uno de: {', '.join(ALLOWED_MIME_TYPES)}."
        )
    if not data:
        raise ImageRejected("El archivo de imagen está vacío.")
    if len(data) > max_bytes:
        raise ImageRejected(f"La imagen supera el máximo de {max_bytes // (1024 * 1024)} MB.")

    nombre = f"{uuid.uuid4().hex}{extension}"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    (uploads_dir / nombre).write_bytes(data)
    return nombre, mime, len(data)


def read_image(uploads_dir: Path, file_path: str) -> bytes:
    """Lee una imagen ya guardada. `file_path` siempre viene de `claim_attachments`."""
    return (uploads_dir / file_path).read_bytes()


def reducir_para_modelo(datos: bytes, mime: str, max_lado: int, calidad: int = 80) -> tuple[bytes, str]:
    """Versión de la foto para el modelo de visión: lado mayor <= `max_lado`, JPEG, sin metadatos.

    El modelo cobra la imagen por teselas, así que una foto de celular de 4000x3000 cuesta varias
    veces lo que una de 1024 px, sin que se vea mejor el daño. El original NO se modifica (el
    ajustador lo ve completo); solo cambia lo que se manda al modelo. Como efecto lateral, el
    reencodificado descarta EXIF (GPS, modelo del equipo) y cualquier dato ajeno a los píxeles.

    Si la imagen ya es pequeña y la versión reducida no pesa menos, se devuelve tal cual.
    Lanza ValueError si el archivo no se puede leer como imagen.
    """
    from PIL import Image, ImageOps  # import tardío: solo se necesita con un modelo de visión

    Image.MAX_IMAGE_PIXELS = 60_000_000   # protege de «bombas de descompresión»
    try:
        with Image.open(io.BytesIO(datos)) as original:
            imagen = ImageOps.exif_transpose(original)       # respeta la orientación del celular
            ya_pequena = max(imagen.size) <= max_lado
            if not ya_pequena:
                imagen.thumbnail((max_lado, max_lado), Image.Resampling.LANCZOS)
            salida = io.BytesIO()
            imagen.convert("RGB").save(salida, "JPEG", quality=calidad, optimize=True)
    except Exception as exc:  # noqa: BLE001 - Pillow lanza varios tipos según el archivo
        raise ValueError("No se pudo leer la imagen adjunta.") from exc
    if ya_pequena and len(salida.getvalue()) >= len(datos):
        return datos, mime
    return salida.getvalue(), "image/jpeg"
