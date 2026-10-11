#!/usr/bin/env bash
# render.sh — render an OpenSCAD model to STL + numbers (+ optional PNG), no X server needed.
#
# Usage:
#   render.sh MODEL.scad [--no-png] [--size W,H] [--view iso|front|top|all]
#                        [--cut PLANE] [--cut3d x|y|z] [--explode N] [--diff OLD.stl]
#                        [--define 'var=value' ...] [--out BASENAME] [--sweep var=a,b,c]
#
# STL is exported with the fastest engine (scripts/oscad.sh); after export the
# bounding box, volume, triangle count and a watertight check are printed.
# --no-png     numbers only (the cheapest loop).
# --view V     PNG previews drawn from the exported STL, so framing follows real
#              geometry (large cutter cubes no longer shrink the model).
# --cut PLANE  true 2D section from the STL: x | y | z (midplane), y=12, x=0,rz=30
#              -> MODEL_cut.png + extents (the next step when numbers don't suffice).
# --cut3d AX   shaded cutaway PNG (model cut open at the AX midplane), from the STL.
# --explode N  PNG previews from the model with -D explode=N (assembly convention).
# --diff OLD   compare bbox+volume against a previous STL, no images.
# --define     -D for openscad, repeatable, e.g. --define 'part="cap"'.
# --out NAME   output basename (default: model path minus .scad).
# --sweep v=a,b  one numbers line per value (probes). Numbers, true/false/undef, "quoted"
#              strings and [lists] pass as written; bare words become strings.
# --html       interactive viewer of this one solid -> MODEL.html (for the human).
# --mark R.stl / --mark3d R.stl   show a region on the model (PNG / interactive).

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# Python always runs from the skill's own folder, so modules planted next to a model
# (struct.py, re.py ...) are never imported; every path handed to it is absolute.
py() { (cd "$HERE" && python3 "$@"); }
absp() { echo "$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"; }
TMO=(); command -v timeout >/dev/null 2>&1 && TMO=(timeout "${OSCAD_TIMEOUT:-900}")
export OPENSCADPATH="$(dirname "$HERE")/lib${OPENSCADPATH:+:$OPENSCADPATH}"

MODEL=""; SIZE="320,320"; VIEW="iso"; DO_STL=1; CUT=""; CUT3D=""; EXPLODE=""; DIFF=""; OUTBASE=""
DEFINES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --size)  SIZE="$2"; shift 2 ;;
    --view)  VIEW="$2"; shift 2 ;;
    --cut)   CUT="$2"; shift 2 ;;
    --cut3d) CUT3D="$2"; shift 2 ;;
    --explode) EXPLODE="$2"; shift 2 ;;
    --diff)  DIFF="$2"; shift 2 ;;
    --define) DEFINES+=(-D "$2"); shift 2 ;;
    --sweep) SWEEP="$2"; shift 2 ;;
    --mark)  MARK="$2"; shift 2 ;;
    --mark3d) MARK3D="$2"; shift 2 ;;
    --html)  HTML3D=1; shift ;;
    --out)   OUTBASE="$2"; shift 2 ;;
    --stl)   DO_STL=1; shift ;;
    --no-stl) DO_STL=0; shift ;;
    --no-png) VIEW="none"; shift ;;
    -h|--help) sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "error: unknown flag '$1' (render.sh --help)" >&2; exit 2 ;;
    *) MODEL="$1"; shift ;;
  esac
done

if [[ -z "$MODEL" || ! -f "$MODEL" ]]; then
  echo "error: pass a path to a .scad file" >&2; exit 2
fi
MODEL="$(absp "$MODEL")"
for v in MARK MARK3D DIFF; do [[ -n "${!v:-}" && -f "${!v}" ]] && printf -v "$v" '%s' "$(absp "${!v}")"; done

if [[ -n "$CUT" ]]; then
  py -c "import re,sys; s=sys.argv[1].split(','); ok=re.fullmatch(r'[xyz](=-?[0-9.]+)?',s[0].strip()) and all(re.fullmatch(r'r[xyz]=-?[0-9.]+',x.strip()) for x in s[1:]); sys.exit(0 if ok else 1)" "$CUT" \
    || { echo "error: bad --cut plane '$CUT' (use x, y=12, z=4,rx=10)" >&2; exit 2; }
fi
if [[ -n "${SWEEP:-}" ]]; then
  var="${SWEEP%%=*}"
  IFS=',' read -ra VALS <<< "${SWEEP#*=}"
  PASS=(); for ((i=1; i<${#DEFINES[@]}; i+=2)); do PASS+=(--define "${DEFINES[$i]}"); done
  for v in "${VALS[@]}"; do
    if [[ "$v" =~ ^-?[0-9.]+(e-?[0-9]+)?$ || "$v" =~ ^(true|false|undef)$ || "$v" == \"* || "$v" == \[* ]]; then d="$var=$v"; else d="$var=\"$v\""; fi
    echo "== $var=$v"
    bash "$0" "$MODEL" --no-png --define "$d" --out "${OUTBASE:-$(basename "${MODEL%.scad}")}_${var}_${v}" \
      ${PASS[@]+"${PASS[@]}"} 2>&1 | grep -E 'bbox|EMPTY|FAILED|ERROR|WATERTIGHT' || true
  done
  exit 0
fi

# --- engines: STL via oscad.sh (fastest), PNG via native openscad -------------
if ! bash "$HERE/oscad.sh" --which >/dev/null 2>&1; then
  cat >&2 <<'MSG'
OpenSCAD not found. Run scripts/setup.sh (installs the fast engine and, where it
can, native OpenSCAD for PNG previews). If nothing installs, fall back to
scripts/meshgen.py for the STL.
MSG
  exit 3
fi
NATIVE=""
for c in "$(command -v openscad 2>/dev/null || true)" "$HOME/.local/bin/openscad" "$HOME/.local/opt/openscad.AppDir/usr/bin/openscad" \
         /usr/bin/openscad /usr/local/bin/openscad "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"; do
  [[ -n "$c" && -x "$c" ]] && { NATIVE="$c"; break; }
done

base="${MODEL%.scad}"
if [[ -n "$OUTBASE" ]]; then
  [[ "$OUTBASE" =~ ^[A-Za-z0-9._-]+$ && "$OUTBASE" != *..* ]] || { echo "error: --out must be a plain name" >&2; exit 2; }
  base="$(dirname "$MODEL")/$OUTBASE"
fi

XVFB=""
if [[ -z "${DISPLAY:-}" ]] && command -v xvfb-run >/dev/null 2>&1; then
  XVFB="xvfb-run -a"
fi

run_oscad() {
  local out
  if ! out="$(${TMO[@]+"${TMO[@]}"} bash "$HERE/oscad.sh" "$@" 2>&1)"; then
    if grep -q "top level object is empty" <<<"$out"; then
      echo ">> EMPTY geometry | vol 0 mm^3 (for intersection checks: no overlap)"
      return 0
    fi
    echo "$out" | grep -vE '^\s*(Geometries|Geometry cache|CGAL|Total rendering|Top level|Convex|Facets|Vertices|Halfedges|Edges|Genus|Volumes|Simple|Status|Rendering|Parsing|Compiling)' | tail -25 >&2
    echo "RENDER FAILED (openscad exited non-zero)" >&2
    exit 1
  fi
  grep -q "top level object is empty" <<<"$out" && echo ">> EMPTY geometry | vol 0 mm^3 (for intersection checks: no overlap)"
  echo "$out" | grep -E '^(WARNING|ERROR|DEPRECATED)' | sort -u || true
}

run_png() {
  if [[ -z "$NATIVE" ]]; then
    echo ">> PNG skipped: no native OpenSCAD (setup.sh installs it where it can); numbers above still hold" >&2
    return 0
  fi
  local out
  if ! out="$(${TMO[@]+"${TMO[@]}"} $XVFB "$NATIVE" "$@" 2>&1)"; then
    echo "$out" | tail -25 >&2
    echo "RENDER FAILED (openscad exited non-zero)" >&2
    if echo "$out" | grep -q "X server"; then
      echo "hint: PNGs need a display — install xvfb (apt-get install -y xvfb)" >&2
    fi
    exit 1
  fi
  echo "$out" | grep -E '^(WARNING|ERROR)' | sort -u || true
}

stl_info() {  # line1 summary, line2 "MX MY MZ", line3 "VOL", line4 "LOX LOY LOZ HIX HIY HIZ"
  py - "$(absp "$1")" <<'PY'
import struct, sys
d = open(sys.argv[1],'rb').read()
n = struct.unpack('<I', d[80:84])[0]
lo = [1e30]*3; hi = [-1e30]*3; vol6 = 0.0; edges = {}; vid = {}
def key(p):
    k = (round(p[0],4), round(p[1],4), round(p[2],4))
    return vid.setdefault(k, len(vid))
for i in range(n):
    t = struct.unpack('<9f', d[84+i*50+12:84+i*50+48])
    for j in range(9):
        a = j % 3
        lo[a] = min(lo[a], t[j]); hi[a] = max(hi[a], t[j])
    ax,ay,az,bx,by,bz,cx,cy,cz = t
    vol6 += ax*(by*cz-bz*cy) - ay*(bx*cz-bz*cx) + az*(bx*cy-by*cx)
    ids = [key(t[0:3]), key(t[3:6]), key(t[6:9])]
    if len(set(ids)) < 3: continue
    for a, b in ((0,1),(1,2),(2,0)):
        e = (min(ids[a],ids[b]), max(ids[a],ids[b]))
        edges[e] = edges.get(e, 0) + 1
op = sum(1 for c in edges.values() if c % 2)
nm = sum(1 for c in edges.values() if c > 2)
print("size %.2f x %.2f x %.2f mm | vol %.0f mm^3 | x:[%.2f,%.2f] y:[%.2f,%.2f] z:[%.2f,%.2f] | %d tris%s"
      % (hi[0]-lo[0], hi[1]-lo[1], hi[2]-lo[2], abs(vol6)/6,
         lo[0], hi[0], lo[1], hi[1], lo[2], hi[2], n,
         (" | NOT WATERTIGHT (%d open edges) - often a cutter face tangent to a surface" % op) if op else
         (" | NON-MANIFOLD (%d edges shared by >2 faces) - solids touching along an edge" % nm) if nm else ""))
print("%.4f %.4f %.4f" % ((lo[0]+hi[0])/2, (lo[1]+hi[1])/2, (lo[2]+hi[2])/2))
print("%.1f" % (abs(vol6)/6))
print("%.4f %.4f %.4f %.4f %.4f %.4f" % tuple(lo + hi))
PY
}


if [[ "${HTML3D:-0}" == 1 ]]; then
  run_oscad -o "${base}.stl" --export-format binstl ${DEFINES[@]+"${DEFINES[@]}"} "$MODEL"
  INFO=$(stl_info "${base}.stl"); echo ">> bbox $(echo "$INFO" | sed -n 1p)"
  py "$HERE/mark3d.py" "${base}.stl" "${base}.html"
  echo ">> HTML -> ${base}.html (interactive 3D — for the human)"
  exit 0
fi

if [[ -n "${MARK3D:-}" ]]; then
  [[ -f "$MARK3D" ]] || { echo "--mark3d: '$MARK3D' not found" >&2; exit 2; }
  run_oscad -o "${base}.stl" --export-format binstl ${DEFINES[@]+"${DEFINES[@]}"} "$MODEL"
  py "$HERE/mark3d.py" "${base}.stl" "$MARK3D" "${base}_marked.html"
  echo ">> HTML -> ${base}_marked.html (interactive 3D — for the human)"
  exit 0
fi

if [[ -n "${MARK:-}" ]]; then
  [[ -f "$MARK" ]] || { echo "--mark: '$MARK' not found" >&2; exit 2; }
  [[ -n "$NATIVE" ]] || { echo "--mark needs native OpenSCAD for PNGs; use --mark3d" >&2; exit 2; }
  [[ "$SIZE" == "320,320" ]] && SIZE="760,760"
  run_oscad -o "${base}.stl" --export-format binstl ${DEFINES[@]+"${DEFINES[@]}"} "$MODEL"
  W="$(mktemp -p . --suffix=.scad)"
  printf 'color([0.6,0.6,0.6,0.30]) import("%s");\ncolor([0.85,0.1,0.1]) import("%s");\n' \
    "$(absp "${base}.stl")" "$(absp "$MARK")" > "$W"
  MI="$(stl_info "$MARK")"
  MMID="$(echo "$MI" | sed -n 2p)"
  ZD="$(echo "$MI" | sed -n 1p | py -c "import sys,re;n=[float(x) for x in re.findall(r'[-\\d.]+',sys.stdin.readline())[:3]];print(max(max(n)*5,45))")"
  run_png -o "${base}_mk1.png" --imgsize="$SIZE" --viewall --autocenter --colorscheme=Tomorrow --camera="0,0,0,55,0,25,140"  "$W"
  run_png -o "${base}_mk2.png" --imgsize="$SIZE" --viewall --autocenter --colorscheme=Tomorrow --camera="0,0,0,90,0,0,140"   "$W"
  run_png -o "${base}_mk3.png" --imgsize="$SIZE" --viewall --autocenter --colorscheme=Tomorrow --camera="0,0,0,125,0,25,140" "$W"
  run_png -o "${base}_mk4.png" --imgsize="$SIZE" --colorscheme=Tomorrow --camera="${MMID// /,},55,0,25,$ZD" "$W"
  py - "$base" $MMID <<'PY'
import sys
from PIL import Image, ImageDraw
b=sys.argv[1]; mid=sys.argv[2:5]
ims=[Image.open(f"{b}_mk{i}.png") for i in (1,2,3,4)]
w,h=ims[0].size; pad=6
out=Image.new("RGB",(w*2+pad*3,h*2+pad*3),(40,40,40))
labels=["iso","front","underside",f"zoom @ ({', '.join('%.0f'%float(m) for m in mid)})"]
for i,(im,lb) in enumerate(zip(ims,labels)):
    x=pad+(i%2)*(w+pad); y=pad+(i//2)*(h+pad)
    out.paste(im,(x,y)); d=ImageDraw.Draw(out)
    d.rectangle([x,y,x+9*len(lb)+10,y+22],fill=(40,40,40)); d.text((x+6,y+4),lb,fill=(240,240,240))
out.save(f"{b}_marked.png")
PY
  rm -f "$W" "${base}"_mk[1-4].png
  echo ">> PNG  -> ${base}_marked.png (4 views: model gray, $(basename "$MARK") red — for the human)"
  exit 0
fi

INFO=""
if [[ "$DO_STL" == 1 ]]; then
  echo ">> STL  -> ${base}.stl"
  rm -f "${base}.stl"
  run_oscad -o "${base}.stl" --export-format binstl ${DEFINES[@]+"${DEFINES[@]}"} "$MODEL"
  if [[ ! -f "${base}.stl" ]]; then
    VIEW="none"
  else
    INFO=$(stl_info "${base}.stl")
    echo ">> bbox $(echo "$INFO" | sed -n 1p)"
    if [[ -n "$DIFF" ]]; then
      if [[ ! -f "$DIFF" ]]; then echo "--diff: '$DIFF' not found" >&2; exit 2; fi
      OLD=$(stl_info "$DIFF")
      echo ">> diff vs $DIFF"
      echo "   old:  $(echo "$OLD" | sed -n 1p)"
      py -c "import sys; nv=float('$(echo "$INFO" | sed -n 3p)'); ov=float('$(echo "$OLD" | sed -n 3p)'); print('   dvol: %+.0f mm^3 (%+.1f%%)' % (nv-ov, 100*(nv-ov)/ov if ov else 0))"
    fi
  fi
fi

# --- PNG previews: from the STL (frames real geometry), or the model if exploding
EXPARG=()
[[ -n "$EXPLODE" ]] && EXPARG=(-D "explode=$EXPLODE")
SRC="$MODEL"; SRCDEF=(${DEFINES[@]+"${DEFINES[@]}"})
if [[ -z "$EXPLODE" && -n "$INFO" ]]; then
  SRC="${base}_view.scad"; SRCDEF=()
  printf 'import("%s");\n' "$(absp "${base}.stl")" > "$SRC"
fi

render_view() {
  local name="$1" cam="$2"
  echo ">> PNG  -> ${base}_${name}.png"
  run_png -o "${base}_${name}.png" --imgsize="$SIZE" --viewall --autocenter \
            --colorscheme=Tomorrow --view=axes --camera="$cam" ${SRCDEF[@]+"${SRCDEF[@]}"} "${EXPARG[@]}" "$SRC"
}

case "$VIEW" in
  none)  : ;;
  iso)   render_view iso   "0,0,0,55,0,25,140" ;;
  front) render_view front "0,0,0,90,0,0,140" ;;
  top)   render_view top   "0,0,0,0,0,0,140" ;;
  all)
    render_view iso   "0,0,0,55,0,25,140"
    render_view front "0,0,0,90,0,0,140"
    render_view top   "0,0,0,0,0,0,140"
    ;;
  *) echo "unknown --view '$VIEW' (use iso|front|top|all)" >&2; exit 2 ;;
esac
[[ "$SRC" == "${base}_view.scad" ]] && rm -f "$SRC"

# --- 2D section (default) and shaded cutaway (opt-in), both from the STL ------
if [[ -n "$CUT" ]]; then
  [[ -n "$INFO" ]] || { echo "--cut needs the STL step (omit --no-stl)" >&2; exit 2; }
  CS="${SIZE%%,*}"; (( CS < 640 )) && CS=640
  py "$HERE/section.py" "${base}_cut.png" "$CUT" "$(absp "${base}.stl")=$(basename "$base")" --size "$CS" \
    | sed 's/^/>> /'
fi
if [[ -n "$CUT3D" ]]; then
  [[ -n "$INFO" ]] || { echo "--cut3d needs the STL step (omit --no-stl)" >&2; exit 2; }
  read -r LX LY LZ HX HY HZ <<< "$(echo "$INFO" | sed -n 4p)"
  read -r MX MY MZ <<< "$(echo "$INFO" | sed -n 2p)"
  case "$CUT3D" in
    x) TR="translate([$LX-1,$LY-1,$LZ-1]) cube([$MX-($LX)+1,$HY-($LY)+2,$HZ-($LZ)+2]);" ;;
    y) TR="translate([$LX-1,$LY-1,$LZ-1]) cube([$HX-($LX)+2,$MY-($LY)+1,$HZ-($LZ)+2]);" ;;
    z) TR="translate([$LX-1,$LY-1,$MZ]) cube([$HX-($LX)+2,$HY-($LY)+2,$HZ-($MZ)+1]);" ;;
    *) echo "unknown --cut3d '$CUT3D' (use x|y|z)" >&2; exit 2 ;;
  esac
  CW="${base}_cutwrap.scad"
  printf 'difference(){ import("%s"); %s }\n' "$(absp "${base}.stl")" "$TR" > "$CW"
  echo ">> PNG  -> ${base}_cut3d.png (cutaway at $CUT3D midplane)"
  run_png -o "${base}_cut3d.png" --imgsize="$SIZE" --viewall --autocenter --colorscheme=Tomorrow \
    --camera="0,0,0,55,0,25,140" "$CW"
  rm -f "$CW"
fi

echo "done."
