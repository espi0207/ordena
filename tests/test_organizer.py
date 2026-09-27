import json
import os
import shutil
from pathlib import Path

import pytest

from ordena import organizer
from ordena.organizer import JOURNAL, apply_plan, build_plan, read_journal, safe_move, undo_last

FIXTURES = Path(__file__).parent / "fixtures"


def make(folder: Path, files: dict[str, str | bytes], days_ago: dict[str, int] | None = None) -> None:
    for name, content in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        if days_ago and name in days_ago:
            when = path.stat().st_mtime - days_ago[name] * 86400
            os.utime(path, (when, when))


def targets(plan) -> dict[str, str]:
    return {m.source: m.target for m in plan.moves}


def snapshot(folder: Path) -> dict[str, tuple[bytes, int]]:
    """Todo lo que hay en la carpeta: contenido y fecha de modificación de cada archivo."""
    return {
        p.relative_to(folder).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in folder.rglob("*")
        if p.is_file() and p.name != JOURNAL
    }


def test_cada_tipo_a_su_carpeta(tmp_path):
    names = ["factura.pdf", "cuentas.XLSX", "charla.pptx", "canción.mp3", "fotos.zip", "setup.exe",
             "libro.epub", "letra.ttf", "script.py", "captura.png", "peli.mkv", "LEEME", "raro.xyz"]  # fmt: skip
    make(tmp_path, {name: name for name in names})
    assert targets(build_plan(tmp_path)) == {
        "factura.pdf": "Documentos/factura.pdf",
        "cuentas.XLSX": "Hojas de cálculo/cuentas.XLSX",
        "charla.pptx": "Presentaciones/charla.pptx",
        "canción.mp3": "Música/canción.mp3",
        "fotos.zip": "Comprimidos/fotos.zip",
        "setup.exe": "Instaladores/setup.exe",
        "libro.epub": "Libros/libro.epub",
        "letra.ttf": "Tipografías/letra.ttf",
        "script.py": "Código/script.py",
        "captura.png": "Imágenes/captura.png",
        "peli.mkv": "Vídeos/peli.mkv",
        "LEEME": "Otros/LEEME",
        "raro.xyz": "Otros/raro.xyz",
    }


def test_fotos_y_videos_por_fecha(tmp_path):
    for name in ("camara.jpg", "iphone.heic", "sin_exif.jpg", "video.mp4", "sin_fecha.mp4"):
        shutil.copy(FIXTURES / name, tmp_path / name)
    plan = build_plan(tmp_path)
    assert targets(plan) == {
        "camara.jpg": "Fotos/2024/08 agosto/camara.jpg",
        "iphone.heic": "Fotos/2025/07 julio/iphone.heic",
        "sin_exif.jpg": "Imágenes/sin_exif.jpg",
        "video.mp4": "Vídeos/2024/05 mayo/video.mp4",  # el 6 de mayo en cualquier zona horaria
        "sin_fecha.mp4": "Vídeos/sin_fecha.mp4",
    }
    assert {m.source: m.note for m in plan.moves}["camara.jpg"] == "del 15/08/2024"
    # Y sin fechas, todo junto.
    assert set(targets(build_plan(tmp_path, by_date=False)).values()) == {
        "Imágenes/camara.jpg", "Imágenes/iphone.heic", "Imágenes/sin_exif.jpg",
        "Vídeos/video.mp4", "Vídeos/sin_fecha.mp4",
    }  # fmt: skip


def test_lo_que_no_se_toca(tmp_path):
    make(tmp_path, {
        "serie.mkv.crdownload": "a medias (Chrome)",
        "disco.iso.part": "a medias (Firefox)",
        "app.dmg.download": "a medias (Safari)",
        ".oculto": "x",
        "desktop.ini": "x",
        "Thumbs.db": "x",
        "Trabajo/informe.pdf": "ya estaba en una carpeta",
        "nota.txt": "esto sí",
    })  # fmt: skip
    try:
        (tmp_path / "enlace.pdf").symlink_to(tmp_path / "nota.txt")  # los enlaces se dejan
    except OSError:
        pass  # en Windows crear enlaces necesita permisos especiales
    plan = build_plan(tmp_path)
    assert targets(plan) == {"nota.txt": "Documentos/nota.txt"}
    assert dict(plan.skipped) == {
        ".oculto": "oculto o del sistema",
        "app.dmg.download": "descarga a medias",
        "desktop.ini": "oculto o del sistema",
        "disco.iso.part": "descarga a medias",
        "serie.mkv.crdownload": "descarga a medias",
        "Thumbs.db": "oculto o del sistema",
    }


def test_duplicados(tmp_path):
    photo = (FIXTURES / "camara.jpg").read_bytes()
    make(
        tmp_path,
        {
            "foto.jpg": photo,
            "foto (1).jpg": photo,  # más antiguo, pero con nombre de copia
            "Copia de presupuesto.xlsx": "presupuesto",
            "presupuesto.xlsx": "presupuesto",
            "notas.txt": "iguales",
            "notas-bis.txt": "iguales",  # nombres normales los dos: se queda el más antiguo
            "vacio1.txt": "",
            "vacio2.txt": "",  # los vacíos no son copias de nada
            "misma-talla-a.txt": "aaaa",
            "misma-talla-b.txt": "bbbb",
        },
        days_ago={"foto (1).jpg": 30, "notas-bis.txt": 10},
    )
    plan = build_plan(tmp_path)
    dupes = {m.source: (m.target, m.note) for m in plan.duplicates}
    assert dupes == {
        "foto (1).jpg": ("Duplicados/foto (1).jpg", "igual que foto.jpg"),
        "Copia de presupuesto.xlsx": ("Duplicados/Copia de presupuesto.xlsx", "igual que presupuesto.xlsx"),
        "notas.txt": ("Duplicados/notas.txt", "igual que notas-bis.txt"),
    }
    assert targets(plan)["foto.jpg"] == "Fotos/2024/08 agosto/foto.jpg"
    assert not build_plan(tmp_path, duplicates=False).duplicates


def test_nombres_que_ya_existen(tmp_path):
    make(tmp_path, {
        "Documentos/informe.pdf": "el que ya estaba",
        "Documentos/informe (2).pdf": "otro que ya estaba",
        "informe.pdf": "el nuevo",
    })  # fmt: skip
    plan = build_plan(tmp_path)
    assert targets(plan) == {"informe.pdf": "Documentos/informe (3).pdf"}
    apply_plan(plan)
    assert (tmp_path / "Documentos/informe.pdf").read_text(encoding="utf-8") == "el que ya estaba"
    assert (tmp_path / "Documentos/informe (2).pdf").read_text(encoding="utf-8") == "otro que ya estaba"
    assert (tmp_path / "Documentos/informe (3).pdf").read_text(encoding="utf-8") == "el nuevo"


def test_aplicar_y_deshacer_lo_deja_todo_igual(tmp_path):
    for name in ("camara.jpg", "iphone.heic", "video.mov"):
        shutil.copy2(FIXTURES / name, tmp_path / name)
    make(tmp_path, {"a.pdf": "a", "b.docx": "b", "b (1).docx": "b", "x.part": "a medias", "Mío/nota.txt": "mía"})
    (tmp_path / "Documentos").mkdir()  # una carpeta que ya existía, vacía: tiene que seguir ahí
    before = snapshot(tmp_path)

    done, problems = apply_plan(build_plan(tmp_path))
    assert (done, problems) == (6, [])
    assert set(snapshot(tmp_path)) == {
        "Fotos/2024/08 agosto/camara.jpg", "Fotos/2025/07 julio/iphone.heic", "Vídeos/2024/05 mayo/video.mov",
        "Documentos/a.pdf", "Documentos/b.docx", "Duplicados/b (1).docx", "x.part", "Mío/nota.txt",
    }  # fmt: skip
    assert not build_plan(tmp_path).moves  # una segunda vez no hay nada que hacer

    done, problems = undo_last(tmp_path)
    assert (done, problems) == (6, [])
    assert snapshot(tmp_path) == before  # mismos archivos, mismo contenido, misma fecha
    dirs = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_dir()}
    assert dirs == {"Documentos", "Mío"}
    assert not (tmp_path / JOURNAL).exists()
    assert undo_last(tmp_path) == (0, [])


def test_deshacer_va_de_una_vez_en_una_vez(tmp_path):
    make(tmp_path, {"lunes.pdf": "1"})
    apply_plan(build_plan(tmp_path))
    make(tmp_path, {"martes.pdf": "2"})
    apply_plan(build_plan(tmp_path))

    assert undo_last(tmp_path) == (1, [])
    assert (tmp_path / "martes.pdf").exists() and (tmp_path / "Documentos/lunes.pdf").exists()
    assert undo_last(tmp_path) == (1, [])
    assert (tmp_path / "lunes.pdf").exists() and not (tmp_path / "Documentos").exists()


def test_mover_nunca_pisa(tmp_path, monkeypatch):
    make(tmp_path, {"a.txt": "a", "b.txt": "b"})
    with pytest.raises(FileExistsError):
        safe_move(tmp_path / "a.txt", tmp_path / "b.txt")
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "a"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "b"

    # En un USB con FAT no hay enlaces duros: se comprueba y se renombra.
    def no_links(src, dst):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "link", no_links)
    with pytest.raises(FileExistsError):
        safe_move(tmp_path / "a.txt", tmp_path / "b.txt")
    safe_move(tmp_path / "a.txt", tmp_path / "c.txt")
    assert not (tmp_path / "a.txt").exists() and (tmp_path / "c.txt").read_text(encoding="utf-8") == "a"


def test_si_uno_falla_sigue_con_los_demas(tmp_path, monkeypatch):
    make(tmp_path, {"a.pdf": "a", "bloqueado.pdf": "b", "c.pdf": "c"})
    real_move = organizer.safe_move

    def flaky_move(src, dst):
        if src.name == "bloqueado.pdf":
            raise PermissionError(13, "Permission denied")
        real_move(src, dst)

    monkeypatch.setattr(organizer, "safe_move", flaky_move)
    done, problems = apply_plan(build_plan(tmp_path))
    assert done == 2 and problems == ["bloqueado.pdf: Permission denied"]
    assert [e["from"] for e in read_journal(tmp_path) if "from" in e] == ["a.pdf", "c.pdf"]
    monkeypatch.undo()
    assert undo_last(tmp_path) == (2, [])
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.pdf", "bloqueado.pdf", "c.pdf"]


def test_deshacer_no_pisa_lo_nuevo(tmp_path):
    make(tmp_path, {"cv.pdf": "el viejo", "foto.png": "png"})
    apply_plan(build_plan(tmp_path))
    make(tmp_path, {"cv.pdf": "uno nuevo que se ha descargado después"})

    done, problems = undo_last(tmp_path)
    assert done == 1 and problems == ["cv.pdf: ya hay otro archivo con ese nombre, no lo piso"]
    assert (tmp_path / "cv.pdf").read_text(encoding="utf-8") == "uno nuevo que se ha descargado después"
    assert (tmp_path / "Documentos/cv.pdf").read_text(encoding="utf-8") == "el viejo"

    # Se queda pendiente: apartando el nuevo, otro --deshacer lo termina.
    (tmp_path / "cv.pdf").rename(tmp_path / "cv nuevo.pdf")
    assert undo_last(tmp_path) == (1, [])
    assert (tmp_path / "cv.pdf").read_text(encoding="utf-8") == "el viejo"
    assert not (tmp_path / "Documentos").exists() and not (tmp_path / JOURNAL).exists()


def test_deshacer_si_el_usuario_ya_lo_ha_movido(tmp_path):
    make(tmp_path, {"a.pdf": "a", "b.pdf": "b"})
    apply_plan(build_plan(tmp_path))
    (tmp_path / "Documentos/b.pdf").unlink()
    done, problems = undo_last(tmp_path)
    assert done == 1 and problems == ["Documentos/b.pdf: ya no está (¿lo has movido o borrado tú?)"]
    assert not (tmp_path / JOURNAL).exists()  # no hay nada que reintentar


def test_un_historial_manipulado_no_saca_nada_de_la_carpeta(tmp_path):
    folder = tmp_path / "Descargas"
    make(tmp_path, {"secreto.txt": "fuera", "Descargas/Documentos/a.pdf": "a"})
    lines = [
        {"run": "1", "from": "robado.txt", "to": "../secreto.txt"},  # traer algo de fuera
        {"run": "1", "from": "../fuera.pdf", "to": "Documentos/a.pdf"},  # sacar algo fuera
        {"run": "1", "from": "Otra/a.pdf", "to": "Documentos/a.pdf"},  # a una subcarpeta
        {"run": "1", "from": 5, "to": ["x"]},
        "no es un objeto",
        {"run": "1", "dir": "../../"},
    ]
    text = "\n".join(json.dumps(line) for line in lines) + "\n{roto"
    (folder / JOURNAL).write_text(text, encoding="utf-8")

    done, problems = undo_last(folder)
    assert done == 0 and len(problems) == 3
    assert all("apunta fuera de la carpeta" in p for p in problems)
    assert (tmp_path / "secreto.txt").read_text(encoding="utf-8") == "fuera"
    assert (folder / "Documentos/a.pdf").read_text(encoding="utf-8") == "a"
    assert not (tmp_path / "fuera.pdf").exists() and not (folder / "robado.txt").exists()
    assert tmp_path.exists()
