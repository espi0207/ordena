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
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from .media import taken_date

JOURNAL = ".ordena-historial.jsonl"
DUPLICATES = "Duplicados"

SCREENSHOTS = "Capturas de pantalla"
SUSPICIOUS = "Sospechosos"

CATEGORIES = {
    "Documentos": ["pdf", "doc", "docx", "docm", "dotx", "odt", "ott", "rtf", "txt", "md", "pages", "tex",
                   "xps", "oxps", "wpd"],
    "Hojas de cálculo": ["xls", "xlsx", "xlsm", "xlsb", "ods", "csv", "tsv", "numbers"],
    "Presentaciones": ["ppt", "pptx", "pps", "ppsx", "potx", "odp", "key"],
    "Imágenes": ["jpg", "jpeg", "png", "gif", "webp", "bmp", "tif", "tiff", "heic", "heif", "svg", "avif",
                 "ico", "jxl", "cr2", "cr3", "nef", "arw", "dng", "raf", "orf", "rw2"],
    "Diseño": ["psd", "psb", "ai", "xcf", "fig", "sketch", "indd", "kra", "afphoto", "afdesign", "cdr", "eps"],
    "Modelos 3D": ["stl", "obj", "fbx", "3mf", "blend", "gcode", "step", "stp", "dwg", "dxf", "skp"],
    "Vídeos": ["mp4", "mov", "m4v", "mkv", "avi", "webm", "3gp", "wmv", "mpg", "mpeg", "flv", "vob", "mts", "m2ts"],
    "Subtítulos": ["srt", "ass", "ssa", "vtt", "sub"],
    "Música": ["mp3", "m4a", "m4b", "flac", "wav", "ogg", "opus", "aac", "wma", "aiff", "mid", "midi", "amr"],
    "Comprimidos": ["zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "tbz2", "xz", "zst", "lz", "lzma", "cab", "zipx"],
    "Instaladores": ["exe", "msi", "msix", "msixbundle", "appx", "dmg", "pkg", "deb", "rpm", "appimage", "apk",
                     "xapk", "apks", "flatpakref", "snap"],
    "Imágenes de disco": ["iso", "img", "vhd", "vhdx", "vmdk", "vdi", "ova", "ovf", "qcow2"],
    "Libros": ["epub", "mobi", "azw", "azw3", "djvu", "cbz", "cbr", "cb7", "fb2"],
    "Código": ["py", "js", "ts", "jsx", "tsx", "vue", "html", "css", "scss", "json", "xml", "yml", "yaml", "toml",
               "sh", "ps1", "bat", "java", "kt", "swift", "c", "cpp", "h", "cs", "go", "rs", "rb", "php", "lua",
               "sql", "ipynb", "ino"],
    "Bases de datos": ["db", "sqlite", "sqlite3", "mdb", "accdb"],
    "Certificados y claves": ["pem", "crt", "cer", "der", "p12", "pfx", "csr", "pub", "ovpn", "kdbx", "asc", "gpg"],
    "Capturas de red": ["pcap", "pcapng"],
    "Correos": ["eml", "msg", "mbox"],
    "Agenda": ["ics", "vcf"],
    "Torrents": ["torrent"],
    "Tipografías": ["ttf", "otf", "woff", "woff2", "fon", "eot"],
}  # fmt: skip
BY_EXTENSION = {ext: folder for folder, exts in CATEGORIES.items() for ext in exts}

# Descargas a medias: si se mueven, el navegador pierde la pista y la descarga se rompe.
PARTIAL = {".crdownload", ".part", ".partial", ".download", ".opdownload", ".tmp", ".!ut", ".aria2"}
SYSTEM = {"desktop.ini", "thumbs.db", ".ds_store", JOURNAL}
# Cómo llaman a las copias los navegadores y los sistemas: "foto (1).jpg", "informe - copia.pdf",
# "Copia de presupuesto.xlsx" (Google Drive), "cv copy.docx" (macOS)...
COPY_MARK = re.compile(r"( \(\d+\)| - copia( \(\d+\))?| copia| copy( \d+)?)$|^(copia de|copy of) ", re.IGNORECASE)
# Capturas de pantalla y grabaciones de pantalla, por cómo las llama cada sistema.
SCREENSHOT_NAME = re.compile(
    r"^(captura de pantalla|captura desde|screenshot|screen ?shot|grabaci[oó]n de pantalla|screen ?recording|"
    r"pantallazo)(?=[\s_.\d-]|$)",  # "Screenshot_2026...": el _ cuenta como letra para \b
    re.IGNORECASE,
)

# Lo primero que llevan dentro algunos tipos de archivo ("números mágicos"): sirve para
# reconocer un archivo que ha llegado sin extensión (o con una que no es la suya).
MAGIC = [
    (b"%PDF-", "pdf", "PDF"),
    (b"\x89PNG\r\n\x1a\n", "png", "PNG"),
    (b"\xff\xd8\xff", "jpg", "JPEG"),
    (b"GIF87a", "gif", "GIF"),
    (b"GIF89a", "gif", "GIF"),
    (b"PK\x03\x04", "zip", "ZIP"),
    (b"Rar!\x1a\x07", "rar", "RAR"),
    (b"7z\xbc\xaf\x27\x1c", "7z", "7z"),
    (b"\x1f\x8b", "gz", "gzip"),
    (b"ID3", "mp3", "MP3"),
    (b"fLaC", "flac", "FLAC"),
    (b"OggS", "ogg", "Ogg"),
    (b"{\\rtf", "rtf", "RTF"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "doc", "documento de Office antiguo"),
    (b"MZ", "exe", "programa de Windows"),
]
RIFF_TYPES = {b"WEBP": ("webp", "WebP"), b"WAVE": ("wav", "WAV"), b"AVI ": ("avi", "AVI")}

# Programas y scripts que se ejecutan con doble clic en Windows.
EXECUTABLE = {"exe", "scr", "com", "pif", "bat", "cmd", "vbs", "vbe", "js", "jse", "wsf", "wsh", "hta", "msi",
              "lnk", "ps1", "jar", "cpl", "reg"}  # fmt: skip
# Lo que un programa disfrazado finge ser.
LOOKS_HARMLESS = {
    ext
    for folder in ("Documentos", "Hojas de cálculo", "Presentaciones", "Imágenes", "Vídeos", "Música", "Comprimidos")
    for ext in CATEGORIES[folder]
}
RTL_OVERRIDE = "\u202e"  # da la vuelta al texto que le sigue: "fac\u202efdp.exe" se ve "facexe.pdf"

MONTHS = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()


@dataclass
class Move:
    source: str  # rutas relativas a la carpeta, con "/"
    target: str
    folder: str  # "Documentos", "Fotos/2024/08 agosto", "Duplicados"...
    size: int
    note: str = ""
    mtime: float = 0.0  # para saber si el archivo ha cambiado desde la vista previa


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


def sniff(path: Path) -> tuple[str, str] | None:
    """(extensión, nombre del tipo) según lo que lleva dentro el archivo, o None si no se sabe."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(64)
    except OSError:
        return None
    if head[:4] == b"RIFF" and head[8:12] in RIFF_TYPES:
        return RIFF_TYPES[head[8:12]]
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"mif1", b"msf1"):
            return "heic", "HEIC"
        return ("mov", "MOV") if brand == b"qt  " else ("mp4", "MP4")
    for magic, ext, kind in MAGIC:
        if head.startswith(magic):
            return ext, kind
    return None


def suspicious(path: Path) -> str | None:
    """Por qué parece un programa disfrazado de documento o de foto, o None si no lo parece.

    Es el truco de siempre de los adjuntos maliciosos: "factura.pdf.exe" (Windows esconde
    la última extensión), muchos espacios antes del .exe para que no se vea, el carácter
    que da la vuelta al texto, o un programa al que directamente le han puesto .pdf.
    """
    name = path.name
    if RTL_OVERRIDE in name:
        return "el nombre lleva un carácter invisible que le da la vuelta para esconder la extensión real"
    ext = path.suffix.lower().lstrip(".")
    inner = Path(path.stem.rstrip()).suffix.lower().lstrip(".")
    if ext in EXECUTABLE and inner in LOOKS_HARMLESS:
        return f"parece un .{inner}, pero es un .{ext}: un programa disfrazado. No lo abras"
    if ext in LOOKS_HARMLESS:
        found = sniff(path)
        if found and found[0] == "exe":
            return f"dice ser un .{ext}, pero por dentro es un programa de Windows. No lo abras"
    return None


def destination(path: Path, by_date: bool) -> tuple[str, str]:
    """(carpeta de destino, nota para el detalle)."""
    ext = path.suffix.lower().lstrip(".")
    folder, note = BY_EXTENSION.get(ext, "Otros"), ""
    if folder == "Otros" and (found := sniff(path)):
        ext, kind = found
        folder, note = BY_EXTENSION[ext], f"es un {kind} aunque el nombre no lo diga"
    if folder in ("Imágenes", "Vídeos") and SCREENSHOT_NAME.match(path.name):
        return SCREENSHOTS, note
    if by_date and folder in ("Imágenes", "Vídeos"):
        date = taken_date(path)
        if date:
            base = "Fotos" if folder == "Imágenes" else "Vídeos"
            return f"{base}/{date.year}/{date.month:02d} {MONTHS[date.month - 1]}", f"del {date:%d/%m/%Y}"
    return folder, note


def free_name(target: PurePosixPath, taken: set[str], root: Path) -> PurePosixPath:
    """Si ya existe (en el disco o en el plan), "nombre (2).ext", "nombre (3).ext"..."""
    candidate, n = target, 2
    while str(candidate).lower() in taken or (root / candidate).exists():
        candidate = target.with_name(f"{target.stem} ({n}){target.suffix}")
        n += 1
    return candidate


def hidden_by_attributes(info) -> bool:
    """En Windows lo oculto o del sistema va por atributos, no por el nombre."""
    return bool(getattr(info, "st_file_attributes", 0) & 0x6)  # HIDDEN | SYSTEM


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
        if name.startswith(".") or name.lower() in SYSTEM or hidden_by_attributes(entry.stat()):
            plan.skipped.append((name, "oculto o del sistema"))
        elif entry.suffix.lower() in PARTIAL:
            plan.skipped.append((name, "descarga a medias"))
        else:
            files.append(entry)

    copies = find_duplicates(files) if duplicates else {}
    taken: set[str] = set()
    for f in files:
        if reason := suspicious(f):
            folder, note = SUSPICIOUS, reason
        elif f in copies:
            folder, note = DUPLICATES, f"igual que {copies[f].name}"
        else:
            folder, note = destination(f, by_date)
        target = free_name(PurePosixPath(folder) / f.name, taken, root)
        taken.add(str(target).lower())
        info = f.stat()
        plan.moves.append(Move(f.name, str(target), folder, info.st_size, note, info.st_mtime))
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
        # Hay sistemas de archivos sin enlaces duros (el FAT de muchos USB). Se reserva el
        # nombre creando un archivo vacío con O_EXCL (falla si ya existe, de forma atómica) y
        # el rename sustituye esa reserva, que es nuestra: no se pisa nada de nadie.
        fd = os.open(dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            os.rename(src, dst)
        except BaseException:
            os.unlink(dst)
            raise
        return
    os.unlink(src)


def _log(journal, **entry) -> None:
    journal.write(json.dumps(entry, ensure_ascii=False) + "\n")
    journal.flush()


def _changed(path: Path, move: Move) -> bool:
    try:
        info = path.stat()
    except OSError:
        return False  # si ya no está, safe_move dará el error de siempre
    return info.st_size != move.size or (move.mtime and info.st_mtime != move.mtime)


def _end_with_newline(path: Path) -> None:
    """Si el historial se cortó a mitad de una línea, la siguiente no debe pegarse a ella."""
    try:
        with open(path, "rb") as fh:
            fh.seek(-1, os.SEEK_END)
            torn = fh.read(1) != b"\n"
    except OSError:
        return  # vacío o no existe
    if torn:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n")


def apply_plan(plan: Plan) -> tuple[int, list[str]]:
    """Ejecuta el plan. Devuelve (movidos, problemas)."""
    # La hora para enseñarla al deshacer y unas letras al azar por si se ordena dos veces en el mismo segundo.
    run = f"{datetime.now():%Y-%m-%dT%H:%M:%S}/{os.urandom(3).hex()}"
    done, problems = 0, []
    _end_with_newline(plan.root / JOURNAL)
    with open(plan.root / JOURNAL, "a", encoding="utf-8") as journal:
        for move in plan.moves:
            src, dst = plan.root / move.source, plan.root / move.target
            if _inside(plan.root, move.target) is None:
                # Una carpeta de destino que es un enlace a otro sitio: se saldría de la carpeta.
                problems.append(f"{move.source}: {move.folder} apunta fuera de la carpeta, no lo muevo")
                continue
            if _changed(src, move):
                problems.append(f"{move.source}: ha cambiado desde la vista previa, vuelve a mirar antes de ordenar")
                continue
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
            try:
                _log(journal, run=run, **{"from": move.source, "to": move.target})
            except OSError as exc:
                # Sin apuntarlo no se podría deshacer (p. ej. disco lleno): se devuelve y se para.
                try:
                    safe_move(dst, src)
                except OSError:
                    problems.append(f"{move.source}: está en {move.target} y no se ha podido apuntar")
                problems.append(f"no se puede escribir el historial ({exc.strerror or exc}); paro aquí")
                break
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
        # Solo dos formas válidas, y con solo sus campos: así deshacer no se encuentra sorpresas.
        if isinstance(entry.get("from"), str) and isinstance(entry.get("to"), str):
            entries.append({"run": entry["run"], "from": entry["from"], "to": entry["to"]})
        elif isinstance(entry.get("dir"), str) and "from" not in entry and "to" not in entry:
            entries.append({"run": entry["run"], "dir": entry["dir"]})
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
        # A un archivo aparte y luego se cambia por el bueno: si se corta a mitad, no se pierde nada.
        # (con nombre único y creado en exclusiva: no puede pisar ni seguir nada que ya estuviera)
        fd, tmp = tempfile.mkstemp(dir=root, prefix=JOURNAL + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in keep))
            os.replace(tmp, journal)
        except BaseException:
            os.unlink(tmp)
            raise
    else:
        journal.unlink()
    return done, problems
