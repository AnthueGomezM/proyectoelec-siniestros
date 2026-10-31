"""Guardado de imágenes en disco: valida tipo y tamaño antes de escribir nada."""

from __future__ import annotations

import pytest

from claims_agent.storage import ImageRejected, read_image, save_image


def test_guarda_una_imagen_valida_y_devuelve_su_ruta(tmp_path):
    ruta, mime, tamano = save_image(tmp_path, b"contenido", "image/jpeg", max_bytes=1024)

    assert mime == "image/jpeg"
    assert tamano == len(b"contenido")
    assert (tmp_path / ruta).read_bytes() == b"contenido"
    assert ruta.endswith(".jpg")


def test_acepta_content_type_con_parametros_de_charset(tmp_path):
    _, mime, _ = save_image(tmp_path, b"x", "image/png; charset=binary", max_bytes=1024)
    assert mime == "image/png"


def test_rechaza_tipo_no_soportado(tmp_path):
    with pytest.raises(ImageRejected, match="no soportado"):
        save_image(tmp_path, b"x", "application/pdf", max_bytes=1024)


def test_rechaza_archivo_vacio(tmp_path):
    with pytest.raises(ImageRejected, match="vacío"):
        save_image(tmp_path, b"", "image/png", max_bytes=1024)


def test_rechaza_archivo_demasiado_grande(tmp_path):
    with pytest.raises(ImageRejected, match="supera el máximo"):
        save_image(tmp_path, b"x" * 100, "image/png", max_bytes=50)


def test_read_image_lee_lo_que_save_image_escribio(tmp_path):
    ruta, _, _ = save_image(tmp_path, b"datos", "image/webp", max_bytes=1024)
    assert read_image(tmp_path, ruta) == b"datos"
