---
name: openscad
description: Create 3D models with OpenSCAD. Use when the user wants to design a 3D-printable part, a parametric model, an enclosure/bracket/gadget, or asks to write or render .scad code, export STL, or see a preview of a 3D shape. Also for multi-part assemblies, moving mechanisms, print-ready files (3MF, multi-material) and laser-cut or sheet-metal flat parts (DXF cut files).
---

# OpenSCAD

Parametric `.scad` → STL + numbers. 1 unit = 1 mm.

**Run scripts through their interpreter** — `bash scripts/x.sh`, `python3 scripts/x.py` — never as `scripts/x.sh`: uploaded skills are mounted read-only without the executable bit. Outputs go next to the model, never into the skill folder.

**Setup:** run `bash scripts/setup.sh` once. It installs the fast engine (OpenSCAD 2025 + Manifold; the WebAssembly build via npm if no native one has it, no sudo) and native OpenSCAD for PNGs, refreshing the package index itself. Exit 4 `NEEDS_SUDO` = nothing can render: relay the printed command, wait, continue. "PNG previews unavailable" is not a blocker — work from numbers. `bash scripts/oscad.sh --which` shows the engine.

## Token economy — follow strictly

- **Numbers before pixels.** Verify with the bbox / volume / watertight line every export prints, `--diff old.stl`, and the checks below. Each viewed image ≈ 1k tokens; numbers are more reliable than vision for dimensions.
- **When numbers don't suffice** (internal fits, sculpted surfaces, "is anything there?"): next step is a **2D section** — `bash scripts/render.sh --cut y=12` or `python3 scripts/asm.py --section y=12` — which also prints extents, in-plane overlaps and gaps. A shaded view (`--view`, `--cut3d`) comes after that, only for topology numbers and sections can't confirm.
- Iterate with `--no-png`. Edit the `.scad` with targeted string replacements, never full-file rewrites.
- `.scad` style: one params block at top — readable names, brief comment per line. Then optionally one `// derived` block (computed heights/offsets, one comment each) or a `report` table (below). Below that: short names (`w,h,d,r,t,k`), zero comments.
- Human-facing output is interactive 3D, never PNGs: `--html` for the deliverable (cut plane, tap-to-measure, pull-apart, variants), `--mark3d` for mid-design confirmation. Present both WITHOUT viewing.

## Workflow

1. Clarify size / holes / tolerances; for vague asks pick sensible defaults and state them. Standard interfaces (ATX, PSU, fan, rack, connector patterns): look up a dimensioned source every time, never from memory or old notes; say which numbers are unverified and suggest a 1:1 paper print before cutting.
2. Write the `.scad` (open `reference/cheatsheet.md` only if unsure of a specific detail).
3. `bash scripts/render.sh model.scad --no-png` → STL + bbox/volume. Non-zero exit, `ERROR:`, `NOT WATERTIGHT` or `NON-MANIFOLD` = fix first.
4. Check numbers against intent; after edits `--diff previous.stl`; internals: `--cut PLANE`.
5. Final: `bash scripts/render.sh model.scad --html` (single part) or `python3 scripts/asm.py model.scad --html` (assembly).

## Gotchas

- `$fn`: 64 iterating, 128+ final curves, 32 small holes.
- `difference()`: first child is the body. Overshoot cuts (`h+0.2` at `z=-0.1`).
- **Never put a cutter face tangent to a curved surface or on the same radius as a profile** (e.g. a cube face at `y = r` against a cylinder of radius `r`) — it leaves an open or non-manifold mesh that other tools reject. Offset ≥ 0.5 mm. Solids touching only along an edge give `NON-MANIFOLD`: overlap them or separate them.
- FDM fits (on diameter): slide +0.2, press +0.1, free +0.4; M3 clearance 3.4 mm; M3 heat-set 4.0 × 5 deep. Walls ≥ 1.2; >45° overhang needs support; `minkowski()`/`hull()` are slow.
- `cube()` is corner-at-origin; pass `center=true` deliberately.
- **Fasteners:** for every screw/nut, state which side the driver comes from and at which assembly step; check it is still reachable after parts that go on later (springs, boards, glued inlays). No check catches this.
- **Freeform blends:** a CSG cutter leaves a crease where it meets the surface. For a feature that must fade in smoothly (thumb dish, grip), copy `lib/loft.scad` beside the model and displace the profile instead:

```scad
use <loft.scad>
prof = [for (t=[0:24]) [15 - 3*pow(t/24,2), 30*t/24]];          // [r,z] bottom→top
dish = function(a,i,p) let(w = smooth01(1 - abs(((a+180)%360)-180)/60),  // ±60° fade
                            h = smooth01((p[1]-8)/14) * smooth01((26-p[1])/4))
       [p[0] - 2.5*w*h, p[1]];
rev_loft(concat(prof, [[0,30]]), n=120, mod=dish);               // r=0 end closes on axis
```

## BOSL2 (threads, fillets, gears — fetch on demand only)

`bash scripts/get_bosl2.sh` once, then:

```scad
include <BOSL2/std.scad>
include <BOSL2/threading.scad>        // only when threading
cuboid([30,20,10], rounding=2);       // filleted box, no minkowski
threaded_rod(d=10, l=20, pitch=1.5);
```

## Assemblies

Tables near the top of the `.scad`, the single source every tool reads. Values may be expressions, but OpenSCAD reads top to bottom, so put the tables **after** the parameters and derived values they use (a table above them sees `undef`). `parts`, `checks`, `travel`, `report`, `variants`, `variant`, `bends`, `k_factor` and `part` are reserved names: don't use them for your own parameters (asm.py stops with a name-clash message).

```scad
part = "all";
knob_h = 18;                      // parameters and derived values first ...
z0 = 12.4;                        // knob underside
// ... then the tables that use them
variant = "dome";  variants = ["dome","dish"];    // optional: each variant exported as its own set
parts = [ // id, label, note, pull-apart [x,y,z], "#colour", tags — only id is required
  ["base","Base","PETG",[0,0,-20],"print=auto"],
  ["knob","Knob","PETG",[0,0,25],"group=knob","print=x180"],
  ["inlay","Grip inlay","TPU",[0,0,35],"group=knob","plate=knobset","mat=TPU"],
  ["spring","Return spring","",[0,0,10],"flex=1"],
  ["hw_board","Cap board"]
];
checks = [ ["knob","hw_board",">=",0.3,"travel"], ["clip","collar","==",2.3,0.05], ["stalk","base","clear"] ];
travel = [ ["knob",[2.3,2.3,0],[5,5,0],[0,0,12]] ];  // group, ±move xyz, ±tilt° xyz, pivot (default: centre)
report = [ ["knob top", z0+knob_h], ["board top", 12] ];
module pick(n){ if(part=="all"||part==n) children(); }
pick("base") base();
```

`hw_` ids = bought/reference hardware: shown and clash-checked, never printed or cut. One id per flat piece; pieces under one id must not touch (they count as qty). Tags: `group=` moves together in travel; `flex=1` a part that bends (spring, flexure), ignored by travel; `print=x180` / `x90,z45` / `auto` (least overhang) print orientation; `plate=` parts printed together, registered, in one 3MF; `mat=` material name in the 3MF.

`python3 scripts/asm.py model.scad` exports every part in parallel, cached per part by its CSG tree (only parts whose geometry changed re-render), prints a line only for parts that CHANGED (`unchanged` = identical geometry; `same size, shape changed` is reported), OpenSCAD warnings, watertight faults, and the `report` values with deltas. Flags combine in one call:
- `--only a,b` export/check a subset; the cache stays correct for later full runs; checks naming other parts are skipped; refused with `--print/--html/--bundle/--cut/--step` (those need every part). `--all` prints every part.
- `--clash [--clear 1]` every pair: overlaps per region with volume, **depth** and where; with `--clear`, gaps under N mm. Run after every geometry change. Judge fits by depth, not volume (a 0.01 mm sliver can show several mm³). Touching = normal contact.
- `--check` evaluates `checks` (also runs with `--clash`/`--travel`); prints failures only. Ops `>= > <= < ==` (5th value = tolerance on any op; default 0.01, or 0.05 for `==`, which absorbs `$fn` faceting), `touch`, `clear`, `overlap`; malformed rows are reported. Gap is signed: negative = penetration depth. A row ending `"travel"` must hold at every travel pose. Names are part ids, else groups.
- `--travel [GROUP[:MM]]` moves each `travel` group to every axis extreme, the diagonal corners and each tilt (also combined); prints, per colliding pair, how many poses overlap and the worst one, plus the closest clearance. `--travel knob:2.3` = ad hoc ±2.3 mm on all axes; `--ignore a,b` leaves parts out for this run (as `flex=1` does permanently).
- `--section y=0` (`x=`, `z=`, tilt `y=0,rz=30`; repeatable; `--size PX`, default 720) → `model_section_*.png`, one colour per part, overlaps red; prints each part's extent in the plane, in-plane overlaps (mm²) and gaps under `--clear` (default 0.5). Axis planes report world coordinates; a tilted plane reports `u,v` from the world point on the untilted axis (`x=5,rz=30` → origin (5,0,0)).
- `--walls [1.2]` per printed part: % of surface under the limit, grouped into regions (area, thickness range, centre, span), each labelled `even wall` (a real thin wall to fix) or `tapering edge` (a feathered edge running to zero, usually fine). Follow up a region with `--section` through its centre.
- `--print` → `model_print/`: one STL per printed part named by label, oriented by `print=` and placed on the bed (separate pieces of one part each go on the bed; a warning if they would then collide); one 3MF per `plate` (bodies registered, named, material per body; re-read and volume-checked; a warning for any piece left in mid-air); per file: height, overhang area > 45°, widest flat underside (bridge).
- `--holes [GAP]` holes in sheets within GAP mm that overlap but miss (`off by N mm`). Bought-hardware patterns still need a looked-up source.
- `--cut` flat sheets → `model_cut/<id>.dxf` + `cutlist.csv`. `--step` → `model_step/<id>.step` (CadQuery, auto-installed, ~35 s first time). OpenSCAD itself cannot write STEP.
- `--bundle` (implies `--print` and `--html`) zips model + print files + cut + step + viewer as `model_<rev>.zip` and deletes older bundles of the model; every output carries the same 7-character `rev`; outputs from an older rev are left out and named. Tell the user to upload the bundle, never loose files.
- `--html [--title T]` → `model.html`: coloured touch viewer — parts table (show / see-through), pull-apart, cut plane (X/Y/Z slider, flip), tap two points to measure, variant switcher. The assembly deliverable; present unviewed.
- `--variant A,B` limit to some variants; outputs go to per-variant subfolders, lines are prefixed `[A]`.

Exit code: 0 clean · 1 a part failed, is empty, not watertight or non-manifold · 2 something was found (overlap, check failure, travel collision). Read the printed lines either way.

`python3 scripts/asm.py --selftest` plants a fault for every check (overlap, check failures, travel collision, 2 mm walls, print/3MF, section overlap, hole miss, `--only` staleness, shape-changed detection, cache, open mesh, bend, `--sweep` booleans, name clash, table order, `flex`, print pieces) and must end `selftest: PASS`; run it once after installing or editing the scripts.

**Bent sheet.** Copy `lib/sheet.scad` beside the model. Draw each bent part as ONE flat 2D pattern with the bend allowance included, list its bends, and `fold()` it:

```scad
use <sheet.scad>
flat = false; k_factor = 0.4;
ba = bend_allow(90, 2, 2, k_factor);
bends = [ // id, x0,y0, x1,y1, angle, inside radius, parent
  ["chan", 0,40, 80,40, 90, 2, -1],
  ["chan", 0,40+ba+20, 80,40+ba+20, 90, 2, 0]
];
pick("chan") fold(bends_of(bends,"chan"), 2, k_factor, flat) chan2d();
```

The line is where the bend zone STARTS in flat coordinates; material to its LEFT moves; angle + folds up, - down; parent = index (within that part) of the bend it sits beyond, -1 = base. `--cut` writes the flat pattern with bend lines on layer `BEND`; `--step` folds a true solid and compares its size with the OpenSCAD fold. Rules: straight bends only, no holes inside a bend zone, notch flat corners where flanges meet.

**Fit probes (what-ifs the tables don't cover):** one `chk.scad` with a `mode` switch; `use <model.scad>` to call its modules, or import a part's STL:

```scad
mode=0;
module hsg(){ import("part.stl"); }
if(mode==0) intersection(){ hsg(); translate([55,0,-6.5]) cube([155,1.5,2]); } // does the lip reach?
```

Run all cases in ONE call: `bash scripts/render.sh chk.scad --sweep mode=0,1,3` → one line per case (numbers, `true/false/undef`, `"quoted"` strings and `[lists]` pass as written; bare words become strings, so `--sweep part=box,lid` works). **EMPTY = clear · vol 0 with tris = surfaces touch · vol > 0 = interference** (or proof of reach). STL coords are float32: overshoot probes ≥0.05 past the surface, treat vol < 1 mm³ at a touching face as noise. Moving parts and kept clearances belong in `travel` / `checks`, not probes.

**Ask the human:** when only human eyes can settle something, `bash scripts/render.sh model.scad --mark region.stl` (4-view PNG, model gray + region red) or `--mark3d region.stl` (interactive HTML). Present UNVIEWED with a directed question.

## render.sh (single solids)

`bash scripts/render.sh model.scad [--no-png] [--cut PLANE] [--cut3d x|y|z] [--view iso|front|top|all] [--size W,H] [--diff old.stl] [--define 'v=1'] [--out NAME] [--sweep v=a,b] [--html] [--mark R.stl | --mark3d R.stl] [--no-stl]`. Previews render from the exported STL, so framing follows real geometry. `--explode N` previews the model itself with `-D explode=N` (only for a model that declares `explode = 0;` and moves parts by `explode*k`; assemblies use the parts-table pull-apart instead).

## Fallback (only if setup.sh fails entirely)

Build the STL with `scripts/meshgen.py` (pure stdlib, watertight CSG). This API summary is complete — do NOT read meshgen.py:

```python
from meshgen import cube, cylinder, sphere, union, difference, intersection, save_stl
part = difference(union(cube([20,20,8], center=True), sphere(8).translate([0,0,4])),
                  cylinder(h=20, d=6, center=True).translate([0,0,2]))
save_stl(part, "part.stl")
```

`cube(size, center=)` · `cylinder(h, r=/d=/r1=/r2=, segments=, center=)` · `sphere(r=/d=, segments=)` · chain `.translate() .rotate(deg,[ax]) .scale()` · `difference(body, *holes)`. No PNGs here — describe geometry in words. Still deliver the `.scad` source.

## Deliverables

`.scad`, interactive `.html` viewer, which params to tweak; printing: the `--print` folder (or `--bundle`); flat-pack: also the `--cut` files. Add a `--mark3d` viewer only when something needed the user's confirmation.
