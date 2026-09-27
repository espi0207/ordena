"""Colores para la terminal, sin librerías.

No se pinta nada si la salida no es una terminal (`ordena > plan.txt`) o si existe la
variable NO_COLOR (https://no-color.org).
"""

from __future__ import annotations

import os
import sys

CODES = {"bold": "1", "red": "31", "green": "32", "yellow": "33", "gray": "90"}

if os.name == "nt":
    os.system("")  # truco conocido: activa las secuencias ANSI en la consola de Windows


def enabled(stream=None) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    stream = stream or sys.stdout
    return hasattr(stream, "isatty") and stream.isatty()


def paint(text: str, *styles: str, stream=None) -> str:
    if not styles or not enabled(stream):
        return text
    return f"\033[{';'.join(CODES[s] for s in styles)}m{text}\033[0m"


def clean(text: str) -> str:
    """Escapa los caracteres no imprimibles de un nombre de archivo antes de sacarlo por
    pantalla: un nombre puede llevar secuencias que muevan el cursor o borren líneas."""
    if text.isprintable():
        return text
    return "".join(c if c.isprintable() else repr(c)[1:-1] for c in text)
