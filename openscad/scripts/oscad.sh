#!/usr/bin/env bash
# oscad.sh — run the fastest OpenSCAD available; same arguments as `openscad`.
#   1. native OpenSCAD that has the Manifold engine (2024+ builds)
#   2. the WebAssembly build with Manifold (installed by setup.sh, needs node)
#   3. native OpenSCAD 2021.01 (CGAL, slow on big booleans)
# PNG output always uses native OpenSCAD (the wasm build cannot draw).
# OSCAD_ENGINE=native|wasm forces one.   oscad.sh --which   prints the choice.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

native() {
  if command -v openscad >/dev/null 2>&1; then command -v openscad; return; fi
  for c in "$HOME/.local/bin/openscad" "$HOME/.local/opt/openscad.AppDir/usr/bin/openscad" \
           /usr/bin/openscad /usr/local/bin/openscad "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"; do
    [[ -x "$c" ]] && { echo "$c"; return; }
  done
  return 1
}

wasm_dir() {
  for d in "${OPENSCAD_WASM_DIR:-}" "$HOME/.cache/openscad-skill/wasm" "$HERE/wasm"; do
    [[ -n "$d" && -f "$d/node_modules/openscad-wasm-prebuilt/dist/openscad.js" ]] && { echo "$d"; return; }
  done
  return 1
}

NAT="$(native || true)"
MFLAG=""
if [[ -n "$NAT" ]]; then
  H="$("$NAT" --help 2>&1 || true)"
  if grep -q -- "--backend" <<<"$H"; then MFLAG="--backend=Manifold"
  elif grep -qi "manifold" <<<"$H"; then MFLAG="--enable=manifold"; fi
fi
WD="$(wasm_dir || true)"
command -v node >/dev/null 2>&1 || WD=""

png=0
prev=""
for a in "$@"; do
  [[ "$prev" == "-o" && "$a" == *.png ]] && png=1
  [[ "$a" == -o*.png ]] && png=1
  prev="$a"
done

pick="${OSCAD_ENGINE:-}"
if [[ -z "$pick" ]]; then
  if [[ $png == 1 ]]; then pick=native
  elif [[ -n "$NAT" && -n "$MFLAG" ]]; then pick=native
  elif [[ -n "$WD" ]]; then pick=wasm
  else pick=native; fi
fi

if [[ "${1:-}" == "--which" ]]; then
  if [[ "$pick" == wasm ]]; then echo "wasm (Manifold) via node; PNG previews: ${NAT:-none}"
  elif [[ -n "$NAT" && -n "$MFLAG" ]]; then echo "native $NAT (Manifold)"
  elif [[ -n "$NAT" ]]; then echo "native $NAT ($("$NAT" --version 2>&1 | head -1 | sed 's/OpenSCAD version //'), CGAL - slow; run setup.sh for the fast engine)"
  else echo "none - run setup.sh"; exit 3; fi
  exit 0
fi

if [[ "$pick" == wasm ]]; then
  [[ -n "$WD" ]] || { echo "ERROR: wasm OpenSCAD not installed (run setup.sh)" >&2; exit 3; }
  OPENSCAD_WASM_DIR="$WD" exec node "$HERE/openscad-wasm.mjs" "$@"
fi
[[ -n "$NAT" ]] || { echo "ERROR: OpenSCAD not found (run setup.sh)" >&2; exit 3; }
if [[ $png == 1 || -z "$MFLAG" ]]; then exec "$NAT" "$@"; fi
exec "$NAT" "$MFLAG" "$@"
