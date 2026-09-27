"""Textos que comparten la terminal y la ventana: tamaños, plurales, el orden de las
carpetas en el resumen y la fecha de cada vez que se ordenó."""

from __future__ import annotations

from datetime import datetime

from .organizer import CATEGORIES, DUPLICATES

ORDER = [*CATEGORIES, "Otros", DUPLICATES]


def human_size(size: float) -> str:
    """1536 -> "1,5 KB", con coma decimal."""
    if size < 1024:
        return "1 byte" if size == 1 else f"{int(size)} bytes"
    unit = "bytes"
    for bigger in ("KB", "MB", "GB", "TB"):
        if size < 1024:
            break
        size, unit = size / 1024, bigger
    return (f"{size:.0f}" if size >= 100 else f"{size:.1f}".replace(".", ",")) + f" {unit}"


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def summary_key(folder: str) -> tuple[int, bool, str]:
    """Las fotos de "Fotos/2024/08 agosto" se cuentan en "Fotos/2024" (los meses salen en --detalle) y
    va justo antes de "Imágenes", que son las que no tienen fecha."""
    top, *rest = folder.split("/")
    label = f"{top}/{rest[0]}" if rest else top
    position = ORDER.index("Imágenes") if top == "Fotos" else ORDER.index(top) if top in ORDER else len(ORDER)
    return position, not rest, label


def run_date(run: str) -> datetime:
    """La fecha de una ejecución del historial ("2026-09-27T10:15:02/a1b2c3")."""
    return datetime.fromisoformat(run.split("/")[0])
