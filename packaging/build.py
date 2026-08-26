"""One command to build Driftgram for the platform you are on.

    python packaging/build.py            # icons + app bundle
    python packaging/build.py --installer  # ...and the platform installer

Windows produces dist/driftgram/ and, with --installer, a per-user setup exe
(needs Inno Setup 6 on PATH, or at its default install location).
Linux produces dist/driftgram/ and, with --installer, an AppImage and a .deb.

There is no cross-compiling here and there cannot be: PyInstaller freezes the
interpreter and libraries of the machine it runs on. A Windows installer has
to be built on Windows and a Linux package on Linux, which is what the GitHub
Actions workflow does with a matrix of two runners.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
VERSION = os.environ.get("DRIFTGRAM_VERSION", "1.0.0")

INNO_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
]


def run(command, **kwargs) -> None:
    printable = " ".join(str(part) for part in command)
    print(f"\n$ {printable}", flush=True)
    subprocess.run(command, check=True, cwd=str(ROOT), **kwargs)


def step(text: str) -> None:
    print(f"\n=== {text} ===", flush=True)


def build_icons() -> None:
    step("Icons")
    run([sys.executable, str(PACKAGING / "make_icons.py")])


def build_app(clean: bool) -> None:
    step("Application bundle")
    if clean:
        shutil.rmtree(DIST / "driftgram", ignore_errors=True)
        shutil.rmtree(BUILD, ignore_errors=True)
    run([
        sys.executable, "-m", "PyInstaller",
        str(PACKAGING / "driftgram.spec"),
        "--noconfirm",
        "--distpath", str(DIST),
        "--workpath", str(BUILD),
    ])

    bundle = DIST / "driftgram"
    total = sum(f.stat().st_size for f in bundle.rglob("*") if f.is_file())
    print(f"\nBundle: {bundle}  ({total / 1024 / 1024:.0f} MB)")


def selftest() -> None:
    step("Self-test of the built app")
    executable = DIST / "driftgram" / ("driftgram.exe" if sys.platform == "win32" else "driftgram")
    if not executable.exists():
        raise SystemExit(f"built app not found at {executable}")

    # Captured rather than inherited: the built exe is a windowed (GUI
    # subsystem) binary, so its stdout is not attached to the parent's console
    # and the checks would otherwise pass in complete silence - leaving a CI
    # log that proves nothing.
    print(f"\n$ {executable} --selftest", flush=True)
    result = subprocess.run(
        [str(executable), "--selftest"], cwd=str(ROOT), capture_output=True, text=True
    )
    print(result.stdout.rstrip() or "(no output)", flush=True)
    if result.returncode != 0:
        print(result.stderr.rstrip(), file=sys.stderr)
        raise SystemExit(f"self-test failed with exit code {result.returncode}")


def find_inno() -> Path:
    found = shutil.which("iscc") or shutil.which("ISCC")
    if found:
        return Path(found)
    for candidate in INNO_CANDIDATES:
        if candidate.exists():
            return candidate
    raise SystemExit(
        "Inno Setup 6 not found. Install it from https://jrsoftware.org/isdl.php "
        "(or add ISCC.exe to PATH) to build the Windows installer."
    )


def build_windows_installer() -> None:
    step("Windows installer")
    (DIST / "installer").mkdir(parents=True, exist_ok=True)
    run([
        str(find_inno()),
        f"/DAppVersion={VERSION}",
        str(PACKAGING / "windows" / "driftgram.iss"),
    ])
    for produced in sorted((DIST / "installer").glob("*.exe")):
        print(f"Installer: {produced}  ({produced.stat().st_size / 1024 / 1024:.0f} MB)")


def build_linux_packages() -> None:
    step("Linux packages")
    env = {**os.environ, "DRIFTGRAM_VERSION": VERSION}
    for script in ("build_appimage.sh", "build_deb.sh"):
        path = PACKAGING / "linux" / script
        path.chmod(0o755)
        try:
            run(["bash", str(path)], env=env)
        except subprocess.CalledProcessError as exc:
            # dpkg-deb is missing on non-Debian hosts and appimagetool needs a
            # network fetch. Neither should sink a build that has already
            # produced a working bundle - report and carry on.
            print(f"\n!! {script} failed (exit {exc.returncode}); continuing.", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Driftgram for this platform")
    parser.add_argument("--app", action="store_true", help="Only build the app bundle")
    parser.add_argument("--icons", action="store_true", help="Only regenerate icons")
    parser.add_argument("--installer", action="store_true", help="Also build the platform installer")
    parser.add_argument("--no-clean", action="store_true", help="Reuse the previous build directory")
    args = parser.parse_args()

    if args.icons:
        build_icons()
        return 0

    build_icons()
    build_app(clean=not args.no_clean)
    selftest()

    if args.installer and not args.app:
        if sys.platform == "win32":
            build_windows_installer()
        elif sys.platform.startswith("linux"):
            build_linux_packages()
        else:
            print(f"No installer defined for {sys.platform}; the bundle is in {DIST / 'driftgram'}.")

    print("\nBuild finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
