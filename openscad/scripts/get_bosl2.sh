#!/usr/bin/env bash
# get_bosl2.sh — install the BOSL2 library (threads, screws, fillets, rounded
# boxes, gears, attachments) into OpenSCAD's default user library path.
# One-time, ~6 MB from GitHub, pinned to the release the skill is tested with.
# Then:  include <BOSL2/std.scad>
set -euo pipefail
TAG=v2.0.768
COMMIT=974a8a4c1cf3040bc54ea5410a64c2c1af0f484f
case "$(uname)" in
  Darwin) LIB="$HOME/Documents/OpenSCAD/libraries" ;;
  *)      LIB="$HOME/.local/share/OpenSCAD/libraries" ;;
esac
if [[ -d "$LIB/BOSL2" ]]; then
  echo "BOSL2 already installed at $LIB/BOSL2 ($(grep -o 'BOSL_VERSION *= *\[[0-9, ]*\]' "$LIB/BOSL2/version.scad" 2>/dev/null || echo 'version unknown'); the skill is tested with $TAG)"
  exit 0
fi
mkdir -p "$LIB"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo ">> downloading BOSL2 $TAG ..."
if command -v git >/dev/null 2>&1 && git -c advice.detachedHead=false clone -q --depth 1 --branch "$TAG" https://github.com/BelfrySCAD/BOSL2.git "$TMP/BOSL2-git" 2>/dev/null; then
  got="$(git -C "$TMP/BOSL2-git" rev-parse HEAD)"
  [[ "$got" == "$COMMIT" ]] || { echo "BOSL2 $TAG is commit $got, expected $COMMIT - not installing" >&2; exit 1; }
  rm -rf "$TMP/BOSL2-git/.git"
else
  curl -fsSL "https://github.com/BelfrySCAD/BOSL2/archive/$COMMIT.tar.gz" | tar -xz -C "$TMP"
fi
mv "$TMP"/BOSL2-* "$LIB/BOSL2"
echo "BOSL2 installed to $LIB/BOSL2"
