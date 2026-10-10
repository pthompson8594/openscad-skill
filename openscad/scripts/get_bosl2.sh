#!/usr/bin/env bash
# get_bosl2.sh — install the BOSL2 library (threads, screws, fillets, rounded
# boxes, gears, attachments) into OpenSCAD's default user library path.
# One-time, ~6 MB from GitHub. Then:  include <BOSL2/std.scad>
set -euo pipefail
case "$(uname)" in
  Darwin) LIB="$HOME/Documents/OpenSCAD/libraries" ;;
  *)      LIB="$HOME/.local/share/OpenSCAD/libraries" ;;
esac
if [[ -d "$LIB/BOSL2" ]]; then echo "BOSL2 already installed at $LIB/BOSL2"; exit 0; fi
mkdir -p "$LIB"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo ">> downloading BOSL2 ..."
if command -v git >/dev/null 2>&1 && git clone -q --depth 1 https://github.com/BelfrySCAD/BOSL2.git "$TMP/BOSL2-git" 2>/dev/null; then
  rm -rf "$TMP/BOSL2-git/.git"
else
  curl -fsSL https://github.com/BelfrySCAD/BOSL2/archive/refs/heads/master.tar.gz | tar -xz -C "$TMP"
fi
mv "$TMP"/BOSL2-* "$LIB/BOSL2"
echo "BOSL2 installed to $LIB/BOSL2"
