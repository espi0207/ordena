import os
import random
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ordena import media
from ordena.media import heic_exif_location, taken_date

FIXTURES = Path(__file__).parent / "fixtures"
# Los archivos de fixtures/ son de verdad: las fotos las hizo Pillow (el HEIC con pillow-heif) y los
# vídeos ffmpeg, cada uno con su fecha puesta a propósito.
VIDEO_UTC = datetime(2024, 5, 6, 7, 8, 9, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "name, expected",
    [
        # Lleva DateTimeOriginal (el 15) y DateTime (el 16, como si se hubiera editado): manda la primera.
        ("camara.jpg", datetime(2024, 8, 15, 18, 30, 2)),
        ("solo_datetime.jpg", datetime(2023, 1, 2, 3, 4, 5)),
        ("sin_exif.jpg", None),
        ("iphone.heic", datetime(2025, 7, 4, 21, 15, 30)),
        ("sin_exif.heic", None),
        ("sin_fecha.mp4", None),
    ],
)
def test_fecha_de_fotos(name, expected):
    assert taken_date(FIXTURES / name) == expected


@pytest.mark.parametrize("name", ["video.mp4", "video_faststart.mp4", "video.mov"])
def test_fecha_de_videos_en_hora_local(name):
    # La caja moov va al final en video.mp4 y al principio en video_faststart.mp4.
    assert taken_date(FIXTURES / name) == VIDEO_UTC.astimezone().replace(tzinfo=None)


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="cambiar la zona horaria así solo va en Linux y macOS")
def test_video_grabado_en_espana(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Madrid")
    time.tzset()
    try:
        # 07:08 UTC en mayo son las 09:08 en la península (horario de verano).
        assert taken_date(FIXTURES / "video.mp4") == datetime(2024, 5, 6, 9, 8, 9)
    finally:
        monkeypatch.undo()
        time.tzset()


def test_la_extension_manda(tmp_path):
    # Un JPEG con otro nombre no se mira: ordena solo abre lo que dice ser foto o vídeo.
    other = tmp_path / "camara.txt"
    other.write_bytes((FIXTURES / "camara.jpg").read_bytes())
    assert taken_date(other) is None
    upper = tmp_path / "CAMARA.JPG"
    upper.write_bytes((FIXTURES / "camara.jpg").read_bytes())
    assert taken_date(upper) == datetime(2024, 8, 15, 18, 30, 2)


def test_heic_con_el_exif_al_final(monkeypatch):
    # libheif guarda el EXIF al final, detrás de la imagen: en una foto de 13 MB, a 13 MB del
    # principio. Aquí se hace lo mismo en pequeño: solo se deja leer hasta el final de la caja
    # meta, así que al EXIF (en el byte 544) hay que saltar.
    assert heic_exif_location((FIXTURES / "iphone.heic").read_bytes()) == (544, 92)
    monkeypatch.setattr(media, "MAX_READ", 443)
    assert taken_date(FIXTURES / "iphone.heic") == datetime(2025, 7, 4, 21, 15, 30)


def box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", 8 + len(body)) + kind + body


def test_heic_con_tablas_vacias():
    # Casos que encontró el fuzzing: la tabla de elementos o la de posiciones, vacías.
    infe = box(b"infe", bytes([2, 0, 0, 0]) + struct.pack(">HH", 1, 0) + b"Exif\x00")
    iinf = box(b"iinf", bytes(4) + struct.pack(">H", 1) + infe)
    ftyp = box(b"ftyp", b"heic\x00\x00\x00\x00")
    assert heic_exif_location(ftyp + box(b"meta", bytes(4) + iinf + box(b"iloc", b""))) is None
    # (la tabla vacía al final del archivo, sin nada detrás que leer por error)
    assert heic_exif_location(ftyp + box(b"meta", bytes(4) + box(b"iloc", bytes(8)) + box(b"iinf", b""))) is None


def test_archivos_rotos_no_rompen_nada(tmp_path):
    """Miles de versiones estropeadas de los archivos de prueba: cortados, con bytes
    cambiados o con basura en medio. Da igual lo que devuelva, pero no puede fallar."""
    rng = random.Random(2026)
    for fixture in sorted(FIXTURES.iterdir()):
        data = fixture.read_bytes()
        target = tmp_path / f"roto{fixture.suffix}"
        for _ in range(400):
            mutated = bytearray(data)
            how = rng.random()
            if how < 0.3:
                del mutated[rng.randrange(len(mutated)) :]
            elif how < 0.8:
                for _ in range(rng.randint(1, 8)):
                    # Sobre todo al principio, que es donde están las cabeceras.
                    mutated[min(int(rng.expovariate(1 / 300)), len(mutated) - 1)] = rng.randrange(256)
            else:
                pos = rng.randrange(len(mutated))
                mutated[pos:pos] = os.urandom(rng.randint(1, 64))
            target.write_bytes(mutated)
            result = taken_date(target)
            assert result is None or isinstance(result, datetime)
