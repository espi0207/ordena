"""Decidir adónde va cada archivo, moverlo sin pisar nada y poder deshacerlo.

Reglas que no se saltan nunca:
- no se borra nada: los duplicados van a una carpeta aparte, no a la papelera;
- no se sobrescribe nada: si el destino existe, se busca otro nombre;
- cada movimiento se apunta en un historial antes de pasar al siguiente, así que se
  puede deshacer aunque el programa se corte a mitad.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from .media import taken_date

JOURNAL = ".ordena-historial.jsonl"
DUPLICATES = "Duplicados"

CATEGORIES = {
    "Documentos": ["pdf", "doc", "docx", "odt", "rtf", "txt", "md", "pages", "tex"],
    "Hojas de cálculo": ["xls", "xlsx", "ods", "csv", "numbers"],
    "Presentaciones": ["ppt", "pptx", "odp", "key"],
    "Imágenes": ["jpg", "jpeg", "png", "gif", "webp", "bmp", "tif", "tiff", "heic", "heif", "svg", "avif",
                 "cr2", "cr3", "nef", "arw", "dng", "raf", "orf", "rw2"],
    "Vídeos": ["mp4", "mov", "m4v", "mkv", "avi", "webm", "3gp", "wmv", "mpg", "mpeg"],
    "Música": ["mp3", "m4a", "flac", "wav", "ogg", "opus", "aac", "wma", "aiff"],
    "Comprimidos": ["zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz", "zst"],
    "Instaladores": ["exe", "msi", "dmg", "pkg", "deb", "rpm", "appimage", "apk", "flatpakref"],
    "Libros": ["epub", "mobi", "azw", "azw3", "djvu", "cbz", "cbr"],
    "Código": ["py", "js", "ts", "html", "css", "json", "xml", "yml", "yaml", "sh", "ps1", "bat",
               "java", "c", "cpp", "h", "cs", "go", "rs", "rb", "php", "sql", "ipynb"],
    "Tipografías": ["ttf", "otf", "woff", "woff2"],
}  # fmt: skip
BY_EXTENSION = {ext: folder for folder, exts in CATEGORIES.items() for ext in exts}

# Descargas a medias: si se mueven, el navegador pierde la pista y la descarga se rompe.
PARTIAL = {".crdownload", ".part", ".partial", ".download", ".opdownload", ".tmp", ".!ut", ".aria2"}
SYSTEM = {"desktop.ini", "thumbs.db", ".ds_store", JOURNAL}
# Cómo llaman a las copias los navegadores y los sistemas: "foto (1).jpg", "informe - copia.pdf",
# "Copia de presupuesto.xlsx" (Google Drive), "cv copy.docx" (macOS)...
COPY_MARK = re.compile(r"( \(\d+\)| - copia( \(\d+\))?| copia| copy( \d+)?)$|^(copia de|copy of) ", re.IGNORECASE)
MONTHS = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()


@dataclass
class Move:
    source: str  # rutas relativas a la carpeta, con "/"
    target: str
    folder: str  # "Documentos", "Fotos/2024/08 agosto", "Duplicados"...
    size: int
    note: str = ""


@dataclass
class Plan:
    root: Path
    moves: list[Move] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def duplicates(self) -> list[Move]:
        return [m for m in self.moves if m.folder == DUPLICATES]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def find_duplicates(files: list[Path]) -> dict[Path, Path]:
    """Archivos con el mismo contenido: {copia: original}.

    Primero se agrupan por tamaño (dos archivos de distinto tamaño no pueden ser iguales)
    y solo se calcula el SHA-256 de los que coinciden: así casi nunca hay que leer nada.
    """
    by_size: dict[int, list[Path]] = defaultdict(list)
    for f in files:
        size = f.stat().st_size
        if size:  # los archivos vacíos son todos "iguales", pero no son copias de nada
            by_size[size].append(f)
    copies = {}
    for same_size in by_size.values():
        if len(same_size) < 2:
            continue
        by_hash: dict[str, list[Path]] = defaultdict(list)
        for f in same_size:
            try:
                by_hash[sha256(f)].append(f)
            except OSError:
                continue  # si no se puede leer, no se puede saber si es copia: se ordena normal
        for group in by_hash.values():
            if len(group) < 2:
                continue
            # Se queda el del nombre "limpio" (sin "(1)" ni "copia") y, si hay empate, el más antiguo.
            original = min(group, key=lambda f: (bool(COPY_MARK.search(f.stem)), f.stat().st_mtime, f.name))
            for f in group:
                if f != original:
                    copies[f] = original
    return copies


def destination(path: Path, by_date: bool) -> tuple[str, str]:
    """(carpeta de destino, nota para el detalle)."""
    ext = path.suffix.lower().lstrip(".")
    folder = BY_EXTENSION.get(ext, "Otros")
    if by_date and folder in ("Imágenes", "Vídeos"):
        date = taken_date(path)
        if date:
            base = "Fotos" if folder == "Imágenes" else "Vídeos"
            return f"{base}/{date.year}/{date.month:02d} {MONTHS[date.month - 1]}", f"del {date:%d/%m/%Y}"
    return folder, ""


def free_name(target: PurePosixPath, taken: set[str], root: Path) -> PurePosixPath:
    """Si ya existe (en el disco o en el plan), "nombre (2).ext", "nombre (3).ext"..."""
    candidate, n = target, 2
    while str(candidate).lower() in taken or (root / candidate).exists():
        candidate = target.with_name(f"{target.stem} ({n}){target.suffix}")
        n += 1
    return candidate


def build_plan(root: Path, by_date: bool = True, duplicates: bool = True) -> Plan:
    """Qué se haría con cada archivo, sin tocar nada. Solo los archivos sueltos de la
    carpeta: las subcarpetas que ya hay se dejan tal cual."""
    root = root.resolve()
    plan = Plan(root)
    files = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        name = entry.name
        if entry.is_symlink() or not entry.is_file():
            continue
        if name.startswith(".") or name.lower() in SYSTEM:
            plan.skipped.append((name, "oculto o del sistema"))
        elif entry.suffix.lower() in PARTIAL:
            plan.skipped.append((name, "descarga a medias"))
        else:
            files.append(entry)

    copies = find_duplicates(files) if duplicates else {}
    taken: set[str] = set()
    for f in files:
        if f in copies:
            folder, note = DUPLICATES, f"igual que {copies[f].name}"
        else:
            folder, note = destination(f, by_date)
        target = free_name(PurePosixPath(folder) / f.name, taken, root)
        taken.add(str(target).lower())
        plan.moves.append(Move(f.name, str(target), folder, f.stat().st_size, note))
    return plan


def safe_move(src: Path, dst: Path) -> None:
    """Mueve sin pisar nunca un archivo que ya exista.

    Comprobar primero y mover después deja un hueco en el que otro programa podría crear
    el destino. En Linux y macOS se usa un enlace duro, que falla si el destino existe (y
    eso lo comprueba el sistema de forma atómica), y luego se quita el original. En
    Windows, rename ya se niega a sobrescribir.
    """
    if os.name == "nt":
        os.rename(src, dst)
        return
    try:
        os.link(src, dst)
    except FileExistsError:
        raise
    except OSError:
        # Hay sistemas de archivos sin enlaces duros (el FAT de muchos USB): se hace a la antigua.
        if os.path.lexists(dst):
            raise FileExistsError(17, "File exists", str(dst)) from None
        os.rename(src, dst)
        return
    os.unlink(src)


def _log(journal, **entry) -> None:
    journal.write(json.dumps(entry, ensure_ascii=False) + "\n")
    journal.flush()


def apply_plan(plan: Plan) -> tuple[int, list[str]]:
    """Ejecuta el plan. Devuelve (movidos, problemas)."""
    # La hora para enseñarla al deshacer y unas letras al azar por si se ordena dos veces en el mismo segundo.
    run = f"{datetime.now():%Y-%m-%dT%H:%M:%S}/{os.urandom(3).hex()}"
    done, problems = 0, []
    with open(plan.root / JOURNAL, "a", encoding="utf-8") as journal:
        for move in plan.moves:
            src, dst = plan.root / move.source, plan.root / move.target
            try:
                # Las carpetas nuevas también se apuntan, para quitarlas al deshacer (y solo esas).
                new_dirs = [p for p in reversed(dst.parents) if p != plan.root and plan.root in p.parents]
                for folder in new_dirs:
                    if not folder.exists():
                        folder.mkdir()
                        _log(journal, run=run, dir=folder.relative_to(plan.root).as_posix())
                safe_move(src, dst)
            except OSError as exc:
                problems.append(f"{move.source}: {exc.strerror or exc}")
                continue
            # Apuntado nada más moverlo: si se corta aquí, deshacer sabe hasta dónde llegó.
            _log(journal, run=run, **{"from": move.source, "to": move.target})
            done += 1
    return done, problems


def read_journal(root: Path) -> list[dict]:
    path = root / JOURNAL
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue  # una línea a medias si se cortó justo al escribirla
        if not isinstance(entry, dict) or not isinstance(entry.get("run"), str):
            continue
        is_move = isinstance(entry.get("from"), str) and isinstance(entry.get("to"), str)
        if is_move or isinstance(entry.get("dir"), str):
            entries.append(entry)
    return entries


def last_run(root: Path) -> str | None:
    entries = read_journal(root.resolve())
    return entries[-1]["run"] if entries else None


def _inside(root: Path, relative: str) -> Path | None:
    """El historial es un archivo que cualquiera puede editar: que no nos haga tocar nada fuera."""
    path = (root / relative).resolve()
    return path if root in path.parents else None


def undo_last(root: Path) -> tuple[int, list[str]]:
    """Deshace la última vez que se ordenó la carpeta. Devuelve (devueltos, problemas).

    Lo que no se puede devolver porque ya hay otro archivo con ese nombre se queda en el
    historial, para poder intentarlo otra vez cuando se haya apartado el que molesta.
    """
    root = root.resolve()
    entries = read_journal(root)
    if not entries:
        return 0, []
    last = entries[-1]["run"]
    done, problems, retry = 0, [], []
    for entry in reversed([e for e in entries if e["run"] == last and "from" in e]):
        moved, original = _inside(root, entry["to"]), _inside(root, entry["from"])
        if not moved or not original or original.parent != root:
            problems.append(f"{entry['from']}: el historial apunta fuera de la carpeta, no lo toco")
            continue
        if not moved.exists():
            problems.append(f"{entry['to']}: ya no está (¿lo has movido o borrado tú?)")
            continue
        try:
            safe_move(moved, original)
        except FileExistsError:
            problems.append(f"{entry['from']}: ya hay otro archivo con ese nombre, no lo piso")
            retry.append(entry)
            continue
        except OSError as exc:
            problems.append(f"{entry['to']}: {exc.strerror or exc}")
            retry.append(entry)
            continue
        done += 1

    # Las carpetas que se crearon al ordenar, si han quedado vacías (de dentro a fuera).
    created = [e for e in entries if e["run"] == last and "dir" in e]
    for entry in reversed(created):
        folder = _inside(root, entry["dir"])
        if not folder:
            continue
        try:
            folder.rmdir()
        except OSError:
            if retry and folder.exists():
                retry.append(entry)  # hará falta quitarla cuando se vuelva a intentar
            # si no, es que tiene cosas que no son nuestras y se queda

    pending = {id(e) for e in retry}
    keep = [e for e in entries if e["run"] != last or id(e) in pending]
    journal = root / JOURNAL
    if keep:
        journal.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in keep), encoding="utf-8")
    else:
        journal.unlink()
    return done, problems
