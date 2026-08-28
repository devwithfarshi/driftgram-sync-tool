#!/usr/bin/env bash
# Build Driftgram.AppImage from the PyInstaller output.
#
#   python packaging/build.py --app      # produces dist/driftgram/
#   packaging/linux/build_appimage.sh
#
# AppImage is the primary Linux format here because it asks nothing of the
# user: one file, chmod +x, double-click. No package manager, no root, no
# distro-specific packages - which matters a great deal when the audience is
# people who have never opened a terminal.
#
# Build on the OLDEST distro you intend to support. An AppImage bundles almost
# everything but still links against the host glibc, so one built on Ubuntu
# 22.04 runs on 24.04 while the reverse fails with a GLIBC version error.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST="$ROOT/dist"
BUNDLE="$DIST/driftgram"
APPDIR="$DIST/Driftgram.AppDir"
GENERATED="$ROOT/packaging/generated"
ARCH="${ARCH:-$(uname -m)}"
VERSION="${DRIFTGRAM_VERSION:-1.0.0}"

if [[ ! -d "$BUNDLE" ]]; then
  echo "error: $BUNDLE not found. Run 'python packaging/build.py --app' first." >&2
  exit 1
fi

echo "==> Assembling AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications"
cp -a "$BUNDLE/." "$APPDIR/usr/bin/"

# Icons: the .desktop file names "driftgram", and both the AppImage tooling and
# the desktop that later integrates it look the name up in the usual places.
for size in 16 24 32 48 64 128 256 512; do
  target="$APPDIR/usr/share/icons/hicolor/${size}x${size}/apps"
  mkdir -p "$target"
  cp "$GENERATED/hicolor/${size}x${size}/apps/driftgram.png" "$target/driftgram.png"
done
cp "$GENERATED/driftgram.png" "$APPDIR/driftgram.png"
cp "$GENERATED/hicolor/256x256/apps/driftgram.png" "$APPDIR/.DirIcon"

cp "$ROOT/packaging/linux/driftgram.desktop" "$APPDIR/usr/share/applications/driftgram.desktop"
cp "$ROOT/packaging/linux/driftgram.desktop" "$APPDIR/driftgram.desktop"

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/usr/bin/env bash
# AppRun is what actually starts when the AppImage is executed.
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="${HERE}/usr/bin:${PATH}"
# Not LD_LIBRARY_PATH: PyInstaller's bundle already resolves its own libraries
# through RPATH, and forcing the bundled ones ahead of the host's has a habit
# of breaking the system's GTK file dialog and its OpenGL drivers.
exec "${HERE}/usr/bin/driftgram" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

echo "==> Fetching appimagetool"
# Cached in build/, NOT dist/. dist/ holds shippable artifacts only: CI uploads
# it with a glob, so a build tool left there gets attached to the GitHub release
# as though it were something a user should download.
TOOL="$ROOT/build/appimagetool-$ARCH.AppImage"
mkdir -p "$(dirname "$TOOL")"
if [[ ! -x "$TOOL" ]]; then
  curl -fsSL -o "$TOOL" \
    "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
  chmod +x "$TOOL"
fi

echo "==> Building AppImage"
OUTPUT="$DIST/Driftgram-$VERSION-$ARCH.AppImage"
# --appimage-extract-and-run: appimagetool is itself an AppImage, and CI
# containers usually have no FUSE for it to mount itself with.
ARCH="$ARCH" "$TOOL" --appimage-extract-and-run "$APPDIR" "$OUTPUT"

chmod +x "$OUTPUT"
echo "==> Done: $OUTPUT"
ls -lh "$OUTPUT"
