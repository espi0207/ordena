"""Una carpeta de Descargas de ejemplo para probar ordena sin miedo.

Los archivos son de relleno (un .docx que es texto, no se abrirá en Word), salvo lo que
ordena mira de verdad: las fotos llevan su fecha en el EXIF y el vídeo en su cabecera.
"""

from __future__ import annotations

import base64
import os
import struct
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from .media import MP4_EPOCH

# Una foto JPEG de 16x16 píxeles gris, sin metadatos. Se le añade la fecha al crearla.
GRAY_JPEG = base64.b64decode(
    "/9j/2wBDABsSFBcUERsXFhceHBsgKEIrKCUlKFE6PTBCYFVlZF9VXVtqeJmBanGQc1tdhbWGkJ6jq62rZ4C8ybqmx5moq6T/wAAL"
    "CAAQABABAREA/8QAFQABAQAAAAAAAAAAAAAAAAAAAAP/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAA/ALgP/9k="
)


def jpeg_with_date(date: datetime) -> bytes:
    """La foto gris con un segmento EXIF que dice cuándo se hizo (DateTimeOriginal)."""
    text = date.strftime("%Y:%m:%d %H:%M:%S").encode() + b"\x00"
    tiff = b"II*\x00" + struct.pack("<I", 8)
    # IFD0 (en el byte 8): una sola entrada, dónde está el IFD de EXIF (en el 26).
    tiff += struct.pack("<HHHII", 1, 0x8769, 4, 1, 26) + struct.pack("<I", 0)
    # IFD de EXIF: DateTimeOriginal, texto de 20 bytes que va justo detrás (en el 44).
    tiff += struct.pack("<HHHII", 1, 0x9003, 2, len(text), 44) + struct.pack("<I", 0)
    tiff += text
    app1 = b"Exif\x00\x00" + tiff
    return GRAY_JPEG[:2] + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + GRAY_JPEG[2:]


def mp4_with_date(date: datetime) -> bytes:
    """Un MP4 sin imagen: solo las cajas ftyp y moov/mvhd con la fecha, que es lo único que
    mira ordena. No se puede reproducir."""
    seconds = int((date.astimezone() - MP4_EPOCH).total_seconds())
    matrix = struct.pack(">9I", 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)
    mvhd = struct.pack(">B3xIIII", 0, seconds, seconds, 1000, 0) + struct.pack(">IH10x", 0x10000, 0x100)
    mvhd += matrix + bytes(24) + struct.pack(">I", 1)
    ftyp = b"isom" + struct.pack(">I", 512) + b"isomiso2mp41"
    return _box(b"ftyp", ftyp) + _box(b"moov", _box(b"mvhd", mvhd))


def _box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", 8 + len(body)) + kind + body


def filler(name: str) -> bytes:
    return f"Archivo de ejemplo de ordena: {name}\n".encode()


# (nombre, contenido, hace cuántos días se descargó)
PHOTO_1 = jpeg_with_date(datetime(2024, 8, 15, 18, 30, 2))
CV = filler("CV Marta López 2026.docx")
FILES = [
    ("Factura luz agosto 2026.pdf", filler("factura"), 30),
    ("Contrato alquiler piso.pdf", filler("contrato"), 200),
    ("CV Marta López 2026.docx", CV, 60),
    ("CV Marta López 2026 (1).docx", CV, 12),
    ("apuntes tema 4.txt", filler("apuntes"), 90),
    ("Presupuesto reforma cocina.xlsx", filler("presupuesto"), 45),
    ("gastos-septiembre.csv", b"fecha;concepto;importe\n2026-09-02;super;54,20\n", 3),
    ("Presentación proyecto final.pptx", filler("presentación"), 150),
    ("IMG_20240815_183002.jpg", PHOTO_1, 300),
    ("IMG_20240815_183002 (1).jpg", PHOTO_1, 20),
    ("IMG_20251224_213011.jpg", jpeg_with_date(datetime(2025, 12, 24, 21, 30, 11)), 250),
    ("PXL_20260702_101512.jpg", jpeg_with_date(datetime(2026, 7, 2, 10, 15, 12)), 80),
    ("Captura de pantalla 2026-09-20 114207.png", filler("captura"), 7),
    ("meme-lunes.webp", filler("meme"), 5),
    ("VID_20250614_120501.mp4", mp4_with_date(datetime(2025, 6, 14, 12, 5, 1)), 100),
    ("tutorial excel tablas dinámicas.mkv", filler("tutorial"), 40),
    ("podcast episodio 112.mp3", filler("podcast"), 25),
    ("fotos-boda-ana-y-luis.zip", filler("zip"), 70),
    ("vlc-3.0.21-win64.exe", filler("vlc"), 120),
    ("zoom_amd64.deb", filler("zoom"), 110),
    ("El Quijote.epub", filler("quijote"), 400),
    ("entradas-concierto.pkpass", filler("entradas"), 15),
    ("temporada 2 capítulo 3.mkv.crdownload", filler("a medias"), 0),
    ("desktop.ini", b"[.ShellClassInfo]\n", 500),
]


def create(base: Path | None = None) -> Path:
    """Crea la carpeta de ejemplo (en la carpeta temporal si no se dice dónde)."""
    folder = Path(tempfile.mkdtemp(prefix="ordena-demo-", dir=base))
    now = datetime.now()
    for name, data, days_ago in FILES:
        path = folder / name
        path.write_bytes(data)
        when = (now - timedelta(days=days_ago)).timestamp()
        os.utime(path, (when, when))
    return folder
