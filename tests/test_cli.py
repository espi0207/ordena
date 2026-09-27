import os
import tempfile
from pathlib import Path

import pytest

from ordena.__main__ import main
from ordena.folders import downloads_folder
from ordena.organizer import JOURNAL
from ordena.report import human_size


@pytest.fixture(autouse=True)
def no_color(monkeypatch):
    monkeypatch.delenv("FORCE_COLOR", raising=False)


@pytest.fixture
def downloads(tmp_path):
    folder = tmp_path / "Descargas"
    folder.mkdir()
    for name, content in {"factura.pdf": "f", "cv.docx": "cv", "cv (1).docx": "cv", "peli.mkv.part": "..."}.items():
        (folder / name).write_text(content, encoding="utf-8")
    return folder


def files(folder: Path) -> set[str]:
    return {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and p.name != JOURNAL}


def test_sin_aplicar_no_se_mueve_nada(downloads, capsys):
    assert main([str(downloads)]) == 0
    out = capsys.readouterr().out
    assert "3 archivos para ordenar" in out
    assert "Duplicados" in out and "si los borras, liberas 2 bytes" in out
    assert "Se quedan donde están (1): 1 descarga a medias" in out
    assert "Esto es solo el plan: no se ha movido nada." in out
    assert f"ordena {downloads} --aplicar" in out
    assert files(downloads) == {"factura.pdf", "cv.docx", "cv (1).docx", "peli.mkv.part"}
    assert not (downloads / JOURNAL).exists()


def test_detalle(downloads, capsys):
    assert main([str(downloads), "--detalle", "--sin-duplicados"]) == 0
    out = capsys.readouterr().out
    assert "  Documentos/\n    cv (1).docx\n    cv.docx\n    factura.pdf\n" in out
    assert "peli.mkv.part  (descarga a medias)" in out
    assert "Para ver adónde va cada archivo" not in out  # ya se está viendo
    assert f"ordena {downloads} --aplicar --sin-duplicados" in out  # se mantienen las opciones


def test_aplicar_y_deshacer(downloads, capsys):
    assert main([str(downloads), "--aplicar"]) == 0
    out = capsys.readouterr().out
    assert "Hecho: 3 archivos movidos." in out and f"ordena {downloads} --deshacer" in out
    moved = {"Documentos/factura.pdf", "Documentos/cv.docx", "Duplicados/cv (1).docx", "peli.mkv.part"}
    assert files(downloads) == moved

    assert main([str(downloads), "--aplicar"]) == 0
    assert "No hay nada que ordenar." in capsys.readouterr().out

    assert main([str(downloads), "--deshacer"]) == 0
    assert "3 archivos han vuelto a su sitio." in capsys.readouterr().out
    assert files(downloads) == {"factura.pdf", "cv.docx", "cv (1).docx", "peli.mkv.part"}

    assert main([str(downloads), "--deshacer"]) == 1
    assert "No hay nada que deshacer" in capsys.readouterr().err


def test_demo(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    assert main(["--demo"]) == 0
    out = capsys.readouterr().out
    (folder,) = tmp_path.iterdir()
    assert str(folder) in out
    assert "Fotos/2024/08 agosto/" in out and "IMG_20240815_183002.jpg" in out
    assert "Vídeos/2025/06 junio/" in out
    assert "IMG_20240815_183002 (1).jpg" in out and "igual que IMG_20240815_183002.jpg" in out
    # Y la carpeta de la demo se ordena y se deshace como cualquier otra.
    before = files(folder)
    assert main([str(folder), "--aplicar"]) == 0
    assert (folder / "Fotos/2024/08 agosto/IMG_20240815_183002.jpg").exists()
    assert main([str(folder), "--deshacer"]) == 0
    assert files(folder) == before


def test_no_ordena_carpetas_peligrosas(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert main([str(tmp_path)]) == 2
    assert "es tu carpeta personal" in capsys.readouterr().err

    project = tmp_path / "proyecto"
    (project / ".git").mkdir(parents=True)
    (project / "main.py").write_text("print('hola')", encoding="utf-8")
    assert main([str(project), "--aplicar"]) == 2
    assert "es un proyecto de git" in capsys.readouterr().err
    assert (project / "main.py").exists()

    assert main([tmp_path.anchor]) == 2
    assert "es la raíz del disco" in capsys.readouterr().err


def test_carpeta_que_no_existe(tmp_path, capsys):
    assert main([str(tmp_path / "no-existe")]) == 2
    assert "No existe la carpeta" in capsys.readouterr().err


@pytest.mark.skipif(os.name == "nt", reason="Windows no deja poner caracteres de control en los nombres")
def test_nombres_con_secuencias_de_escape(tmp_path, capsys):
    (tmp_path / "\x1b[2Jfactura.pdf").write_text("x", encoding="utf-8")
    assert main([str(tmp_path), "--detalle"]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert "\\x1b[2Jfactura.pdf" in out


def test_carpeta_de_descargas(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    assert downloads_folder() == tmp_path / "Downloads"
    (tmp_path / "Descargas").mkdir()
    assert downloads_folder() == tmp_path / "Descargas"
    # En un Linux en español la apunta xdg-user-dirs.
    (tmp_path / "config").mkdir()
    config = tmp_path / "config/user-dirs.dirs"
    config.write_text('# comentario\nXDG_DOWNLOAD_DIR="$HOME/Bajadas"\n', encoding="utf-8")
    assert downloads_folder() == tmp_path / "Bajadas"


def test_tamanos():
    assert human_size(0) == "0 bytes"
    assert human_size(1) == "1 byte"
    assert human_size(1536) == "1,5 KB"
    assert human_size(150 * 1024**2) == "150 MB"
    assert human_size(5 * 1024**3) == "5,0 GB"
