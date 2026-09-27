"""La fecha en que se hizo una foto o un vídeo, leída del propio archivo.

La fecha de modificación no sirve: al descargar una foto de WhatsApp o copiarla del
móvil, pasa a ser la de hoy. La de verdad está dentro del archivo:

- JPEG: en los metadatos EXIF, la etiqueta DateTimeOriginal (la pone la cámara).
- HEIC (las fotos del iPhone): el mismo EXIF, pero guardado como un "elemento" dentro
  de un contenedor como el de los MP4. Hay que buscar en la tabla de elementos (iinf)
  cuál es el EXIF y en la de posiciones (iloc) dónde está.
- MP4 y MOV: en la caja "mvhd", la fecha de creación en segundos desde 1904.

Se lee a mano, con struct, sin Pillow ni nada. Todo con comprobaciones de límites: un
archivo roto o hecho a propósito no puede hacer que el programa se caiga.
"""

from __future__ import annotations

import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_READ = 256 * 1024  # los metadatos van al principio: no hace falta leer la foto entera
EXIF_DATE_ORIGINAL, EXIF_DATE = 0x9003, 0x0132
EXIF_IFD_POINTER = 0x8769
MP4_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)


def _exif_date(tiff: bytes) -> datetime | None:
    """Busca la fecha dentro del bloque TIFF que va en el segmento EXIF."""
    if len(tiff) < 8 or tiff[:2] not in (b"II", b"MM"):
        return None
    endian = "<" if tiff[:2] == b"II" else ">"

    def read_ifd(offset: int) -> dict[int, tuple[int, int, int]]:
        # Cada entrada: etiqueta, tipo, cuántos valores y el valor (o dónde está).
        if offset + 2 > len(tiff):
            return {}
        (count,) = struct.unpack_from(endian + "H", tiff, offset)
        entries = {}
        for i in range(min(count, 500)):
            pos = offset + 2 + i * 12
            if pos + 12 > len(tiff):
                break
            tag, kind, n, value = struct.unpack_from(endian + "HHII", tiff, pos)
            entries[tag] = (kind, n, value)
        return entries

    def text(entry) -> str | None:
        kind, n, offset = entry
        if kind != 2 or not 19 <= n <= 64 or offset + n > len(tiff):  # tipo 2 = texto ASCII
            return None
        return tiff[offset : offset + 19].decode("ascii", errors="replace")

    ifd0 = read_ifd(struct.unpack_from(endian + "I", tiff, 4)[0])
    candidates = []
    if EXIF_IFD_POINTER in ifd0:
        exif = read_ifd(ifd0[EXIF_IFD_POINTER][2])
        if EXIF_DATE_ORIGINAL in exif:
            candidates.append(text(exif[EXIF_DATE_ORIGINAL]))
    if EXIF_DATE in ifd0:
        candidates.append(text(ifd0[EXIF_DATE]))
    for value in candidates:
        try:
            # "2024:08:15 18:30:02". Hay cámaras que ponen "0000:00:00 00:00:00" si no saben la hora.
            return datetime.strptime(value or "", "%Y:%m:%d %H:%M:%S")
        except ValueError:
            continue
    return None


def jpeg_date(data: bytes) -> datetime | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            return None
        marker = data[pos + 1]
        if marker == 0xFF:  # relleno entre segmentos
            pos += 1
            continue
        if marker in (0xD9, 0xDA):  # fin de imagen o empieza la imagen en sí: ya no hay metadatos
            return None
        (length,) = struct.unpack_from(">H", data, pos + 2)
        segment = data[pos + 4 : pos + 2 + length]
        if marker == 0xE1 and segment.startswith(b"Exif\x00\x00"):  # APP1 con EXIF
            return _exif_date(segment[6:])
        pos += 2 + length
    return None


def _boxes(data: bytes, start: int, end: int):
    """Las "cajas" de un MP4/MOV: tamaño (4 bytes), tipo (4 letras) y contenido."""
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack_from(">I4s", data, pos)
        header = 8
        if size == 1 and pos + 16 <= end:  # tamaño de 64 bits
            size = struct.unpack_from(">Q", data, pos + 8)[0]
            header = 16
        elif size == 0:  # hasta el final del archivo
            size = end - pos
        if size < header:
            return
        yield kind, pos + header, min(pos + size, end)
        pos += size


def _read_uint(data: bytes, pos: int, size: int) -> tuple[int, int]:
    """Entero sin signo de `size` bytes (0, 4 u 8, como los de iloc)."""
    if size == 0:
        return 0, pos
    if pos + size > len(data):
        raise ValueError("iloc cortado")
    return int.from_bytes(data[pos : pos + size], "big"), pos + size


def heic_exif_location(data: bytes) -> tuple[int, int] | None:
    """Dónde está el EXIF dentro de un HEIC: (posición, tamaño). Las tablas que lo dicen
    van en la caja meta, al principio del archivo; el EXIF en sí puede estar en cualquier sitio."""
    meta = next(((s, e) for kind, s, e in _boxes(data, 0, len(data)) if kind == b"meta"), None)
    if not meta:
        return None
    start, end = meta[0] + 4, meta[1]  # meta es una "full box": 4 bytes de versión y flags
    boxes = {kind: (s, e) for kind, s, e in _boxes(data, start, end)}
    if b"iinf" not in boxes or b"iloc" not in boxes:
        return None

    # iinf: la lista de elementos. Se busca el que es de tipo "Exif".
    s, e = boxes[b"iinf"]
    if e - s < 6:
        return None
    version = data[s]
    exif_id = None
    first = s + 4 + (2 if version == 0 else 4)
    for kind, bs, be in _boxes(data, first, e):
        if kind != b"infe" or be - bs < 12:
            continue
        infe_version = data[bs]
        if infe_version < 2:
            continue
        id_size = 2 if infe_version == 2 else 4
        item_id = int.from_bytes(data[bs + 4 : bs + 4 + id_size], "big")
        item_type = data[bs + 4 + id_size + 2 : bs + 4 + id_size + 6]
        if item_type == b"Exif":
            exif_id = item_id
            break
    if exif_id is None:
        return None

    # iloc: dónde empieza y cuánto mide cada elemento dentro del archivo.
    s, e = boxes[b"iloc"]
    iloc = data[s:e]
    if len(iloc) < 8:
        return None
    version = iloc[0]
    offset_size, length_size = iloc[4] >> 4, iloc[4] & 0x0F
    base_offset_size, index_size = iloc[5] >> 4, (iloc[5] & 0x0F) if version in (1, 2) else 0
    pos = 6
    count, pos = _read_uint(iloc, pos, 2 if version < 2 else 4)
    for _ in range(min(count, 10000)):
        item_id, pos = _read_uint(iloc, pos, 2 if version < 2 else 4)
        method = 0
        if version in (1, 2):
            method, pos = _read_uint(iloc, pos, 2)
        pos += 2  # data_reference_index
        base, pos = _read_uint(iloc, pos, base_offset_size)
        extents, pos = _read_uint(iloc, pos, 2)
        first_extent = None
        for _ in range(min(extents, 1000)):
            _, pos = _read_uint(iloc, pos, index_size)
            offset, pos = _read_uint(iloc, pos, offset_size)
            length, pos = _read_uint(iloc, pos, length_size)
            if first_extent is None:
                first_extent = (base + offset, length)
        if item_id == exif_id:
            # Con método 0 la posición es dentro del archivo, que es lo que hacen los móviles.
            # Los otros (dentro de otra caja) no se usan para el EXIF en la práctica.
            return first_extent if method & 0x0F == 0 else None
    return None


def heic_date(path: Path) -> datetime | None:
    with open(path, "rb") as fh:
        where = heic_exif_location(fh.read(MAX_READ))
        if not where:
            return None
        offset, length = where
        fh.seek(offset)
        item = fh.read(min(length, MAX_READ))
    # El elemento empieza con 4 bytes que dicen dónde está la cabecera TIFF.
    if len(item) < 4:
        return None
    tiff_start = 4 + int.from_bytes(item[:4], "big")
    return _exif_date(item[tiff_start:])


def mp4_date(path: Path) -> datetime | None:
    """Fecha de creación del vídeo. La caja moov puede estar al principio o al final del
    archivo (depende del programa que lo grabó), así que se recorren las cajas de primer
    nivel saltando por encima de los datos, sin leerlos."""
    with open(path, "rb") as fh:
        size = fh.seek(0, 2)
        pos = 0
        for _ in range(1000):
            if pos + 8 > size:
                return None
            fh.seek(pos)
            head = fh.read(16)
            box_size, kind = struct.unpack_from(">I4s", head)
            header = 8
            if box_size == 1:
                box_size, header = struct.unpack_from(">Q", head, 8)[0], 16
            elif box_size == 0:
                box_size = size - pos
            if box_size < header:
                return None
            if kind == b"moov":
                fh.seek(pos)
                moov = fh.read(min(box_size, 8 * 1024 * 1024))
                for inner, start, end in _boxes(moov, header, len(moov)):
                    if inner == b"mvhd" and end - start >= 12:
                        version = moov[start]
                        if version == 1 and end - start >= 12:
                            seconds = struct.unpack_from(">Q", moov, start + 4)[0]
                        else:
                            seconds = struct.unpack_from(">I", moov, start + 4)[0]
                        if seconds == 0:
                            return None  # sin fecha
                        date = MP4_EPOCH + timedelta(seconds=seconds)
                        # Los móviles la guardan en UTC; se pasa a la hora local de este equipo.
                        return date.astimezone().replace(tzinfo=None)
                return None
            pos += box_size
    return None


def taken_date(path: Path) -> datetime | None:
    """Fecha de la foto o el vídeo, o None si el archivo no la trae (o no es de un tipo conocido)."""
    suffix = path.suffix.lower()
    try:
        if suffix in (".jpg", ".jpeg"):
            with open(path, "rb") as fh:
                return jpeg_date(fh.read(MAX_READ))
        if suffix in (".heic", ".heif"):
            return heic_date(path)
        if suffix in (".mp4", ".mov", ".m4v", ".3gp"):
            return mp4_date(path)
    except (OSError, struct.error, OverflowError, ValueError):
        return None
    return None
