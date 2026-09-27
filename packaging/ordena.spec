# Receta de PyInstaller para el programa de Windows y la app de macOS:
#     pyinstaller --noconfirm packaging/ordena.spec
# Deja el resultado en dist/ordena (y dist/ordena.app en macOS).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
sys.path.insert(0, str(root))
from ordena import __version__  # noqa: E402

icon = str(root / "packaging" / "icon.png")  # PyInstaller lo pasa a .ico o .icns con Pillow

a = Analysis(
    [str(root / "packaging" / "ordena-app.py")],
    pathex=[str(root)],
    datas=collect_data_files("ordena"),
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ordena", console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, name="ordena")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="ordena.app",
        icon=icon,
        bundle_identifier="io.github.espigares07.ordena",
        version=__version__,
        info_plist={"CFBundleDisplayName": "ordena", "NSHighResolutionCapable": True, "LSMinimumSystemVersion": "11.0"},
    )
