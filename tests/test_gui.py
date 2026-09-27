import os
import sys

import pytest

tk = pytest.importorskip("tkinter")

from ordena import gui  # noqa: E402


@pytest.mark.skipif(
    sys.platform.startswith("linux") and not os.environ.get("DISPLAY"),
    reason="en Linux hace falta una pantalla (en la CI, xvfb-run)",
)
def test_la_ventana_ordena_y_deshace():
    # Lo mismo que hace la CI con el programa ya instalado: abrir la ventana con una carpeta
    # de ejemplo, ordenarla, deshacerlo y comprobar que todo vuelve a estar como estaba.
    assert gui.self_check() == 0
