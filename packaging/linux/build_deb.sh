#!/usr/bin/env bash
# Build a .deb for Debian / Ubuntu / Mint from the PyInstaller output.
#
#   python packaging/build.py --app      # produces dist/driftgram/
#   packaging/linux/build_deb.sh
#
# The AppImage is the zero-effort option; the .deb is the tidy one - it gets a
# real application-menu entry, icon-theme integration and `apt remove` for
# free, which is what a user on Ubuntu expects of an installed program.
#
# The whole PyInstaller bundle goes to /opt/driftgram (the FHS location for
# self-contained third-party software) with a symlink on PATH, rather than
# scattering a private Python and a private Qt through /usr/lib.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST="$ROOT/dist"
BUNDLE="$DIST/driftgram"
GENERATED="$ROOT/packaging/generated"
VERSION="${DRIFTGRAM_VERSION:-1.0.0}"

case "$(uname -m)" in
  x86_64)  DEB_ARCH="amd64" ;;
  aarch64) DEB_ARCH="arm64" ;;
  *)       DEB_ARCH="$(uname -m)" ;;
esac

STAGE="$DIST/deb/driftgram_${VERSION}_${DEB_ARCH}"

if [[ ! -d "$BUNDLE" ]]; then
  echo "error: $BUNDLE not found. Run 'python packaging/build.py --app' first." >&2
  exit 1
fi

echo "==> Staging package tree"
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" "$STAGE/opt/driftgram" "$STAGE/usr/bin" "$STAGE/usr/share/applications"
cp -a "$BUNDLE/." "$STAGE/opt/driftgram/"
ln -sf /opt/driftgram/driftgram "$STAGE/usr/bin/driftgram"

cp "$ROOT/packaging/linux/driftgram.desktop" "$STAGE/usr/share/applications/driftgram.desktop"
for size in 16 24 32 48 64 128 256 512; do
  target="$STAGE/usr/share/icons/hicolor/${size}x${size}/apps"
  mkdir -p "$target"
  cp "$GENERATED/hicolor/${size}x${size}/apps/driftgram.png" "$target/driftgram.png"
done

INSTALLED_KB="$(du -sk "$STAGE" | cut -f1)"

cat > "$STAGE/DEBIAN/control" <<EOF
Package: driftgram
Version: $VERSION
Section: utils
Priority: optional
Architecture: $DEB_ARCH
Installed-Size: $INSTALLED_KB
Maintainer: Driftgram
Depends: libc6, libglib2.0-0, libfontconfig1, libfreetype6, libx11-6, libxkbcommon0, libxkbcommon-x11-0, libdbus-1-3
Description: Two-way folder backup to your own Telegram account
 Driftgram keeps the folders you choose backed up to your personal Telegram
 account, and brings changes back the other way as well. It runs in the
 background with a notification-area icon.
 .
 Files are sent as documents to a chat you control - Saved Messages by
 default - so they are never recompressed and never leave your account.
EOF

# Qt loads its own libraries out of /opt, so dpkg-shlibdeps has nothing useful
# to say about them; the Depends list above names only the system libraries Qt
# genuinely needs from the distribution.

cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
# Refresh the caches so the menu entry and icon appear without a re-login.
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
EOF

cat > "$STAGE/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
# Note: the user's settings, manifest and Telegram session under
# ~/.config/driftgram and ~/.local/share/driftgram are left alone on purpose,
# even on purge. Removing them would sign the user out and discard the record
# of everything already backed up.
exit 0
EOF

chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"
find "$STAGE/opt" "$STAGE/usr" -type d -exec chmod 0755 {} +

echo "==> Building package"
OUTPUT="$DIST/driftgram_${VERSION}_${DEB_ARCH}.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$OUTPUT"

echo "==> Done: $OUTPUT"
ls -lh "$OUTPUT"
dpkg-deb --info "$OUTPUT" | head -20
