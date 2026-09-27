"""Qué carpeta ordenar por defecto, cuáles no tocar nunca y cómo abrir una en el explorador."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Por si alguien se equivoca de carpeta: ordenar los archivos sueltos de estas rompería cosas.
SYSTEM_DIRS = ["/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/opt", "/proc", "/sbin", "/sys", "/usr",
               "/System", "/Library"]  # fmt: skip
WINDOWS_DIRS = ["SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"]


def downloads_folder() -> Path:
    home = Path.home()
    # En Linux la carpeta cambia de nombre con el idioma ("Descargas"): la apunta xdg-user-dirs.
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "user-dirs.dirs"
    try:
        for line in config.read_text(encoding="utf-8").splitlines():
            if line.startswith("XDG_DOWNLOAD_DIR="):
                value = line.split("=", 1)[1].strip().strip('"')
                return Path(value.replace("$HOME", str(home)))
    except OSError:
        pass
    for name in ("Downloads", "Descargas"):
        if (home / name).is_dir():
            return home / name
    return home / "Downloads"


def refuse_reason(folder: Path) -> str | None:
    if folder == Path(folder.anchor):
        return "es la raíz del disco"
    if folder == Path.home().resolve():
        return "es tu carpeta personal; mejor una de dentro, como Descargas o Escritorio"
    if (folder / ".git").exists():
        return "es un proyecto de git y moverle los archivos lo rompería"
    system = [Path(d) for d in SYSTEM_DIRS if os.name != "nt"]
    system += [Path(os.environ[v]) for v in WINDOWS_DIRS if os.environ.get(v)]
    for path in system:
        if path.exists() and (folder == path.resolve() or path.resolve() in folder.parents):
            return "es una carpeta del sistema"
    return None


def open_in_file_manager(folder: Path) -> None:
    """Abre la carpeta en el Explorador, el Finder o lo que haya en Linux."""
    if sys.platform == "win32":
        os.startfile(folder)  # solo existe en Windows
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])
