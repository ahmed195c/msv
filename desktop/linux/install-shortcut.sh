#!/bin/sh
# Adds "نظام التصاريح والعقود" to this user's applications menu and desktop.
# Run once from inside the MSV-Desktop folder:  ./install-shortcut.sh
# Run it again after moving the folder, so the shortcut points to the new place.
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/app/msv-desktop"
ICON="$HERE/app/msv-desktop.png"

if [ ! -f "$APP" ]; then
  echo "app/msv-desktop not found next to this script." >&2
  exit 1
fi
chmod +x "$APP" "$HERE/app/msv-desktop-debug" 2>/dev/null || true

ENTRY="[Desktop Entry]
Type=Application
Name=نظام التصاريح والعقود
Name[en]=MSV Desktop
Exec=\"$APP\"
Path=$HERE/app
Icon=$ICON
Terminal=false
Categories=Office;
"

MENU_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$MENU_DIR"
printf '%s' "$ENTRY" > "$MENU_DIR/msv-desktop.desktop"
chmod +x "$MENU_DIR/msv-desktop.desktop"

DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$DESKTOP_DIR" ]; then
  printf '%s' "$ENTRY" > "$DESKTOP_DIR/msv-desktop.desktop"
  chmod +x "$DESKTOP_DIR/msv-desktop.desktop"
  gio set "$DESKTOP_DIR/msv-desktop.desktop" metadata::trusted true 2>/dev/null || true
fi

echo "Done: the app is in the applications menu and on the desktop."
