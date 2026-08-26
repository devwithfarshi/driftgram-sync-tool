# PyInstaller spec for Driftgram, shared by Windows and Linux.
#
# Build with:  pyinstaller packaging/driftgram.spec --noconfirm
#
# onedir, not onefile, on both platforms. onefile unpacks itself to a temp
# directory on every launch, which for a Qt app means a visible delay each
# time the user starts it and an antivirus scan of the whole payload on
# Windows. onedir is also what AppImage and .deb want to wrap anyway.
#
# The two collect_submodules calls are not belt-and-braces. Telethon builds
# its API layer by importing generated modules dynamically, and watchdog
# picks its observer backend at runtime by name; neither is visible to
# PyInstaller's static analysis, and both fail only once the app is frozen.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
GENERATED = ROOT / "packaging" / "generated"
IS_WINDOWS = sys.platform == "win32"

hidden = collect_submodules("telethon") + collect_submodules("watchdog")

# Qt modules this app never touches. PySide6-Essentials is already the slim
# wheel, but it still ships several megabytes of things like QtQuick, and
# every one of them would otherwise be copied into the installer.
excluded_qt = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.QtWebSockets", "PySide6.QtWebChannel", "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtPrintSupport", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtPositioning", "PySide6.QtSerialPort", "PySide6.QtSensors",
    "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech", "PySide6.QtStateMachine",
]

excluded = excluded_qt + [
    "tkinter", "unittest", "pydoc_data", "test", "distutils",
    "matplotlib", "numpy", "PIL", "pytest",
]

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=excluded,
    noarchive=False,
)

# Qt ships a ~20 MB software OpenGL renderer (Mesa llvmpipe) for machines with
# no usable GPU driver. It is only ever loaded to give QtQuick or QOpenGLWidget
# a context; a pure-widgets app paints through the raster engine and never asks
# for one. Dropping it is the single biggest saving available here.
UNUSED_BINARIES = {"opengl32sw.dll", "d3dcompiler_47.dll", "libGLESv2.dll", "libEGL.dll"}
a.binaries = TOC([entry for entry in a.binaries if Path(entry[0]).name not in UNUSED_BINARIES])

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="driftgram",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-packed binaries are a common false positive for antivirus
    # No console on either platform: this is a windowed app, and on Windows a
    # console would mean a black box flashing up behind the window at login.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(GENERATED / "driftgram.ico") if IS_WINDOWS else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="driftgram",
)
