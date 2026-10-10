# openscad skill

A Claude skill for designing parts and multi-part assemblies in OpenSCAD.
It checks its work with numbers instead of pictures, which keeps token use low
and catches errors a render cannot show.

It runs in a normal Claude chat with code execution, including from a phone,
and in Claude Code.

## What it does

- **Single parts:** writes a parametric `.scad`, exports STL, and verifies the
  bounding box and volume against the intent. Each edit is compared with the
  previous version.
- **Fast engine:** renders with OpenSCAD 2025 and the Manifold engine. Where
  no native build has it, it uses the WebAssembly build from npm. A 21-part
  steel rack case renders in 1.8 s, against 88 s with OpenSCAD 2021.01.
- **Assemblies:** one parts table at the top of the model drives everything.
  A single command exports every part in parallel, re-renders only parts whose
  geometry changed, and prints a line only for the parts that changed. It also
  flags open or non-manifold meshes and OpenSCAD warnings.
- **Collision check:** tests every pair of parts and reports each overlap with
  its depth and location, plus gaps under a clearance you choose.
- **Checks that stay checked:** a `checks` table of clearances (">= 0.3 mm",
  "== 2.3 mm", "clear", "touch"). Every run prints only the ones that fail.
- **Moving parts:** a `travel` table moves a group of parts to every limit of
  its travel and tilt and reports any collision and the closest clearance.
- **Sections:** a true 2D section of the whole assembly at any plane or angle,
  one colour per part, with overlaps and gaps in that plane listed.
- **Print files:** wall thickness, overhang area and the widest flat underside
  per part; STLs oriented for printing and named by label; a 3MF per
  multi-material set with the bodies kept registered.
- **Variants:** each value of a `variant` setting exports as its own set, and
  the viewer shows them side by side or one at a time.
- **Dimension report:** a `report` table of key heights printed every run,
  with changes marked.
- **Hole alignment:** finds holes in touching sheets that overlap but are not
  concentric.
- **Flat cut files:** for laser, plasma or waterjet work it flattens every
  sheet in the assembly to a DXF outline and writes a cut list with quantity,
  size, thickness and cut length.
- **Bent sheet:** draw a part as one flat pattern, list its bends, and it is
  folded in 3D for the assembly. The cut file gets bend lines on their own
  layer, and the STEP file is a true folded solid with cylindrical bends.
- **STEP solids:** for shops that take STEP, it writes each sheet as a true
  solid with its thickness, then re-imports the file and checks it.
- **One revision, one bundle:** every output carries the same short revision
  code, and a single zip holds the model, cut files, STEP files and viewer, so
  an old file cannot be uploaded by mistake.
- **Viewer:** a self-contained HTML page with touch controls, a parts table
  with show and see-through toggles for each part, a pull-apart slider, a cut
  plane, tap-to-measure and a variant switcher.
- **Smooth blends:** `lib/loft.scad` builds a revolved solid whose profile can
  change with angle. Use it for grips and thumb dishes that fade in without a
  crease.
- **Self-test:** builds a tiny model with planted faults and proves each check
  catches them.

## Install

**Claude apps (claude.ai):** download `openscad.skill` from the
[latest release](https://github.com/pthompson8594/openscad-skill/releases), or
zip the `openscad` folder yourself. Then go to Customize > Skills > + > Create
skill > Upload a skill. Code execution must be turned on.

**Claude Code:** copy the `openscad` folder to `~/.claude/skills/`, or run:

```
npx skills add pthompson8594/openscad-skill --skill openscad
```

**First run:** ask Claude to run `bash scripts/setup.sh` and then
`python3 scripts/asm.py --selftest`. Setup should end with
`STL engine = wasm (Manifold)` (or `native ... (Manifold)`), and the self-test
should end with `selftest: PASS`.

## Help test it

The skill works well in Claude's own sandbox, which is Linux with Node 22,
where everything below has been run. It has not yet been tried on:

- macOS or Windows (WSL) with Claude Code on your own machine
- OpenSCAD 2024 or later installed natively (the script should detect Manifold
  and use it)
- real laser, plasma or waterjet cutting from the DXF files, and real prints
  from the 3MF files
- large models with 50 or more parts

If something fails or reads wrong, please
[open an issue](https://github.com/pthompson8594/openscad-skill/issues/new/choose)
with the output of `bash scripts/oscad.sh --which` and of the self-test.
Reports that it worked on a new setup are just as useful.

## What it installs when it runs

Be aware of this before using it. On first use the skill may install:

- OpenSCAD, through the system package manager (`bash scripts/setup.sh`), used for
  PNG previews and as a fallback engine. If that needs `sudo` and nothing else
  can render, it prints the command and stops.
- `openscad-wasm-prebuilt` 1.2.0 from npm (OpenSCAD 2025.01 with Manifold,
  about 11 MB) into `~/.cache/openscad-skill/wasm`. Needs Node 18 or newer. It
  is skipped when the installed OpenSCAD already has Manifold.
- `numpy`, `manifold3d`, `pillow` and `scipy` from PyPI, used for the checks,
  sections and wall thickness.
- `cadquery` from PyPI, only when STEP export is requested. It is a large
  download, about 165 MB installed.

The viewer page loads three.js from cdnjs and a font from Google Fonts. It
makes no other network requests.

## Using it

Ask for the thing you want, for example "design a wall bracket for a 25 mm
pipe" or "make a laser-cut box, 100 by 60 by 40 mm inside, from 3 mm sheet".

For an assembly, the model starts with a table like this:

```scad
part = "all";
parts = [ // id, label, note, pull-apart [x,y,z], "#colour" - only id is required
  ["base","Base","3 mm sheet",[0,0,0]],
  ["lid","Lid","3 mm sheet",[0,0,70]],
  ["hw_cell","Battery","reference only"]
];
module pick(n){ if(part=="all"||part==n) children(); }
pick("base") base();
```

Ids that start with `hw_` are bought or reference hardware. They are shown
and collision-checked but never cut.

Then one command does the rest:

```
python3 openscad/scripts/asm.py examples/box.scad --clash --holes --cut --step --html --bundle
python3 openscad/scripts/asm.py --selftest
```

Run the scripts through `bash` or `python3` as shown. When a skill is uploaded
to Claude, its files lose the executable bit, so `./scripts/setup.sh` gives
"Permission denied".

`examples/box.scad` is a small five-sheet box to try it on, and
`examples/channel.scad` is a folded channel with three bends.
`examples/knob.scad` is a moving joystick knob with two top variants and a
TPU grip ring. Run it with `--clash --travel --section y=0 --walls --print`.
It contains a deliberate fault: at 3° of tilt the knob hits the board,
because 0.4 mm of gap is too little. Setting `gap = 1.2` fixes it, and the
checks then pass.

## Limits

- Round holes come out as true circles in the cut files and true cylinders in
  the STEP files. Other curves, such as rounded corners and slots, stay as
  short straight segments, as fine as the model's `$fn`.
- STEP and cut files cover flat and bent sheet only. Printed parts export as
  STL.
- Bends must be straight, with no holes or cut-outs inside the bend zone. The
  bend allowance uses a K-factor (0.4 by default), which your shop may set
  differently.
- Hole alignment does not yet look at holes on folded parts.
- Travel checks test discrete poses: every limit, the diagonal corners and
  each tilt. They do not test a continuous sweep between poses.
- Wall thickness is measured by casting rays inward from 20,000 surface
  samples. A wall thinner than the sample spacing can be missed.
- 3MF files carry body names, colours and material names. Assign the actual
  filaments in the slicer.
- Hole alignment only covers holes in the sheets you model. Patterns on bought
  hardware (power supplies, fans, motherboards) must be looked up from a
  dimensioned source and checked against the real part.
- The cut and STEP files have not been run on a real machine yet. Open them in your own
  software and cut a test piece first.
- Tested on Linux with OpenSCAD 2021.01 and the 2025.01 WebAssembly build.
  The self-test passes on both.

## Licence

MIT No Attribution (MIT-0): use, change and share it freely, with no need to
credit anyone. See `LICENSE`.

The fast engine (`openscad-wasm-prebuilt`, a WebAssembly build of OpenSCAD,
GPL-2.0) and the other packages listed above are not part of this repository.
`setup.sh` downloads them on first use, under their own licences.
