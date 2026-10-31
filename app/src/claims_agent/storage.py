"""Almacenamiento de imágenes adjuntas a un siniestro: disco local, no PostgreSQL.

Las fotos no se guardan en la base de datos (evita filas de varios MB y backups
lentos): se escriben en un volumen Docker y solo la ruta relativa, el tipo MIME y el
tamaño quedan en `claim_attachments`. El nombre de archivo es siempre generado por el
servidor (nunca el que mandó el navegador), así que no hay forma de que el nombre del
cliente escape al sistema de archivos.
"""

from __future__ import annotations

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
