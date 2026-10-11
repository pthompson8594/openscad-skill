#!/usr/bin/env bash
# setup.sh — install the OpenSCAD engines this skill uses, on whatever system this is.
#   1. fast engine: OpenSCAD 2025 with Manifold. Native if the installed OpenSCAD
#      already has it; otherwise the WebAssembly build from npm (needs node 18+),
#      installed to ~/.cache/openscad-skill/wasm (no sudo).
#   2. native OpenSCAD + xvfb for PNG previews (distro package; often 2021.01).
#      The package index is refreshed and the install retried once if it fails.
# Exit 0  = ready (prints which engine renders STLs)
# Exit 4  = printing NEEDS_SUDO: nothing could render; relay the sudo command to the user.
# PNG-only gaps are reported but do not fail the setup.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WASM_DIR="${OPENSCAD_WASM_DIR:-$HOME/.cache/openscad-skill/wasm}"
WASM_PKG="openscad-wasm-prebuilt@1.2.0"
WASM_SHA512="sha512-JfXJlopHVHvsYiVYUKYDXkg8yOkABm8zclo8zPrSRBeeICR+fitesO6NRwBdAzSdbtOYh6Scmuz/XLyhllbzYA=="   # npm dist.integrity of 1.2.0

have_native() { command -v openscad >/dev/null 2>&1; }
native_manifold() { have_native && openscad --help 2>&1 | grep -qiE -- "--backend|manifold"; }

as_root() {  # run a command string as root if we can; else return 4
  if [[ $EUID -eq 0 ]]; then bash -c "$1"
  elif sudo -n true 2>/dev/null; then sudo bash -c "$1"
  else return 4; fi
}

SETUP_LOG="$(mktemp)"

# --- 1. native package (for PNGs; also the fallback engine) --------------------
SUDO_MSG=""
if ! have_native; then
  INST=""; UPD=""
  if   command -v pacman  >/dev/null 2>&1; then INST="pacman -S --needed --noconfirm openscad xorg-server-xvfb"; UPD="pacman -Sy --noconfirm"
  elif command -v apt-get >/dev/null 2>&1; then INST="DEBIAN_FRONTEND=noninteractive apt-get install -y openscad xvfb"; UPD="apt-get update"
  elif command -v dnf     >/dev/null 2>&1; then INST="dnf install -y openscad xorg-x11-server-Xvfb"; UPD="dnf makecache"
  elif command -v zypper  >/dev/null 2>&1; then INST="zypper install -y openscad xvfb-run"; UPD="zypper refresh"
  elif command -v brew    >/dev/null 2>&1; then
    echo ">> brew install --cask openscad"; brew install --cask openscad || true
  fi
  if [[ -n "$INST" ]]; then
    echo ">> $INST"
    as_root "$INST" >"$SETUP_LOG" 2>&1; rc=$?
    if [[ $rc -ne 0 && $rc -ne 4 ]]; then
      echo ">> install failed; refreshing the package index and retrying ($UPD)"
      as_root "$UPD && $INST" >>"$SETUP_LOG" 2>&1; rc=$?
    fi
    if [[ $rc -eq 4 ]]; then SUDO_MSG="sudo sh -c '$UPD && $INST'"
    elif [[ $rc -ne 0 ]]; then echo ">> native OpenSCAD did not install (see $SETUP_LOG)"; fi
  fi
fi

# --- 2. fast engine -------------------------------------------------------------
if ! native_manifold; then
  if [[ -f "$WASM_DIR/node_modules/openscad-wasm-prebuilt/dist/openscad.js" ]]; then
    echo ">> fast engine already installed in $WASM_DIR"
  elif command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1 \
       && [[ "$(node -p 'process.versions.node.split(".")[0]')" -ge 18 ]]; then
    echo ">> npm install $WASM_PKG -> $WASM_DIR (OpenSCAD 2025 + Manifold, ~11 MB)"
    mkdir -p "$WASM_DIR" && [[ -f "$WASM_DIR/package.json" ]] || echo '{"name":"openscad-skill-wasm","private":true}' > "$WASM_DIR/package.json"
    LOG="$(mktemp)"
    if npm install --prefix "$WASM_DIR" --ignore-scripts --no-audit --no-fund --silent "$WASM_PKG" >"$LOG" 2>&1; then
      GOT="$(node -e 'const l=require(process.argv[1]);const p=(l.packages||{})["node_modules/openscad-wasm-prebuilt"]||{};process.stdout.write(p.integrity||"")' "$WASM_DIR/package-lock.json" 2>/dev/null)"
      if [[ "$GOT" != "$WASM_SHA512" ]]; then
        echo ">> fast engine failed its integrity check (got '${GOT:-none}'); removed it, using native OpenSCAD"
        rm -rf "$WASM_DIR/node_modules"
      fi
    else
      echo ">> npm install failed (see $LOG); falling back to native OpenSCAD"
    fi
  else
    echo ">> node 18+ / npm not found: skipping the fast engine (big booleans will be slow on 2021.01)"
  fi
fi

# --- verify ---------------------------------------------------------------------
T="$(mktemp -d)"; echo 'difference(){cube(10);sphere(6);}' > "$T/t.scad"
if OPENSCAD_WASM_DIR="$WASM_DIR" bash "$HERE/oscad.sh" -o "$T/t.stl" --export-format binstl "$T/t.scad" >/dev/null 2>&1 && [[ -s "$T/t.stl" ]]; then
  echo "ready: STL engine = $(OPENSCAD_WASM_DIR="$WASM_DIR" bash "$HERE/oscad.sh" --which)"
  rm -rf "$T"
  if ! have_native; then
    echo "PNG previews unavailable (no native OpenSCAD)${SUDO_MSG:+ - to enable, ask the user to run: $SUDO_MSG}"
  fi
  exit 0
fi
rm -rf "$T"
if [[ -n "$SUDO_MSG" ]]; then
  echo "NEEDS_SUDO — ask the user to run:"
  echo ""
  echo "    $SUDO_MSG"
  echo ""
  echo "then re-run this script (or just render)."
  exit 4
fi
cat >&2 <<'MSG'
No OpenSCAD engine could be installed. Options:
  - install node 18+ and re-run (fast engine via npm), or
  - AppImage: https://files.openscad.org/ then ./OpenSCAD-*.AppImage --appimage-extract
    (found at ~/.local/opt/openscad.AppDir/), or
  - use scripts/meshgen.py as the STL fallback (no previews).
MSG
exit 1
