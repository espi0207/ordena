"""Clasificación ampliada (noviembre de 2026): más tipos, capturas de pantalla, archivos
sin extensión reconocidos por su contenido y programas disfrazados de documento."""

import pytest

from ordena.organizer import SCREENSHOTS, SUSPICIOUS, build_plan
from ordena.report import ORDER


def make(folder, files):
    for name, content in files.items():
        (folder / name).write_bytes(content if isinstance(content, bytes) else content.encode())


def plan_for(tmp_path, files, **kw):
    make(tmp_path, files)
    return {m.source: (m.folder, m.note) for m in build_plan(tmp_path, **kw).moves}


@pytest.mark.parametrize(
    "name, folder",
    [
        ("ubuntu-24.04.iso", "Imágenes de disco"),
        ("Windows Server.vmdk", "Imágenes de disco"),
        ("kali.ova", "Imágenes de disco"),
        ("logo.psd", "Diseño"),
        ("cartel.ai", "Diseño"),
        ("pieza.stl", "Modelos 3D"),
        ("plano.dwg", "Modelos 3D"),
        ("peli.es.srt", "Subtítulos"),
        ("debian.torrent", "Torrents"),
        ("cita.ics", "Agenda"),
        ("contacto.vcf", "Agenda"),
        ("aviso del banco.eml", "Correos"),
        ("servidor.crt", "Certificados y claves"),
        ("vpn-clase.ovpn", "Certificados y claves"),
        ("contraseñas.kdbx", "Certificados y claves"),
        ("datos.sqlite", "Bases de datos"),
        ("tráfico.pcapng", "Capturas de red"),
        ("plantilla.dotx", "Documentos"),
        ("macros.xlsm", "Hojas de cálculo"),
        ("audiolibro.m4b", "Música"),
        ("app.msix", "Instaladores"),
        ("main.kt", "Código"),
    ],
)
def test_more_types(tmp_path, name, folder):
    assert plan_for(tmp_path, {name: "x"})[name][0] == folder


@pytest.mark.parametrize(
    "name",
    [
        "Captura de pantalla 2026-11-07 101112.png",  # Windows
        "Captura desde 2026-11-07 10-11-12.png",  # GNOME
        "Captura de pantalla 2026-11-07 a las 10.11.12.png",  # macOS
        "Screenshot_20261107-101112.jpg",  # Android
        "Screen Shot 2020-01-01 at 10.00.00.png",
        "Grabación de pantalla 2026-11-07.mp4",
    ],
)
def test_screenshots_get_their_own_folder(tmp_path, name):
    assert plan_for(tmp_path, {name: "x"})[name][0] == SCREENSHOTS


def test_a_photo_called_captura_is_not_a_screenshot_by_name_alone(tmp_path):
    assert plan_for(tmp_path, {"captura del pez.png": "x"})["captura del pez.png"][0] == "Imágenes"


@pytest.mark.parametrize(
    "content, folder, kind",
    [
        (b"%PDF-1.7\n...", "Documentos", "PDF"),
        (b"\x89PNG\r\n\x1a\n" + b"\0" * 20, "Imágenes", "PNG"),
        (b"\xff\xd8\xff\xe0" + b"\0" * 20, "Imágenes", "JPEG"),
        (b"PK\x03\x04" + b"\0" * 30, "Comprimidos", "ZIP"),
        (b"Rar!\x1a\x07\x01\x00", "Comprimidos", "RAR"),
        (b"ID3\x04\x00" + b"\0" * 20, "Música", "MP3"),
        (b"\0\0\0\x18ftypmp42" + b"\0" * 20, "Vídeos", "MP4"),
        (b"MZ\x90\x00" + b"\0" * 60, "Instaladores", "programa de Windows"),
    ],
)
def test_files_without_extension_are_recognised_by_content(tmp_path, content, folder, kind):
    folder_got, note = plan_for(tmp_path, {"descarga": content})["descarga"]
    assert folder_got == folder and kind in note


def test_unknown_content_stays_in_otros(tmp_path):
    assert plan_for(tmp_path, {"LEEME": "hola"})["LEEME"] == ("Otros", "")


@pytest.mark.parametrize(
    "name, content",
    [
        ("factura.pdf.exe", b"MZ" + b"\0" * 60),
        ("foto_playa.jpg.scr", b"MZ" + b"\0" * 60),
        ("nomina.docx                    .exe", b"MZ" + b"\0" * 60),
        ("pedido.pdf.js", b"var x = 1;"),
        ("invoice‮fdp.exe", b"MZ" + b"\0" * 60),  # el carácter que da la vuelta al texto: se ve "invoiceexe.pdf"
        ("factura.pdf", b"MZ\x90\x00" + b"\0" * 60),  # dice ser un PDF y es un programa
    ],
)
def test_disguised_programs_go_to_suspicious(tmp_path, name, content):
    folder, note = plan_for(tmp_path, {name: content})[name]
    assert folder == SUSPICIOUS and note


def test_normal_programs_and_scripts_are_not_suspicious(tmp_path):
    got = plan_for(
        tmp_path,
        {"setup-7.2.1.exe": b"MZ" + b"\0" * 60, "jquery.min.js": "x", "instalar.ps1": "x", "doc.pdf": b"%PDF-1.4"},
    )
    assert SUSPICIOUS not in {folder for folder, _ in got.values()}


def test_new_folders_have_a_place_in_the_summary():
    assert ORDER[0] == SUSPICIOUS  # lo primero que se ve
    assert ORDER.index(SCREENSHOTS) == ORDER.index("Imágenes") + 1
