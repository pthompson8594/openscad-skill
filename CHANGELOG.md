# Changelog

## 2.4.0 - unreleased

From a 22-version build of a six-axis controller:

- **Split parts are flagged.** Every run counts the separate solids in each made
  part. A part that comes apart, usually because a cut went right through it, is
  reported as `PIECES` before it is printed. Parts meant to be several pieces take
  a `pieces=N` tag.
- **What to reprint.** `--against old.scad` compares with an earlier version and
  lists each part as changed (with what changed), the same, or the same shape only
  moved.
- **What stops each motion.** `--travel` now reports, for each direction, how far
  the moving group goes before it first touches something and which parts touch.
  It says when nothing stops a motion, or when the stop is well past the travel.
- **Zoomed sections.** A section can frame one part (`y=0,around=lid`) or an area
  (`y=0,box=10:30:40:52`) instead of the whole assembly.
- **Overhangs located.** The print report lists the largest overhangs with their
  height above the bed, whether each is a flat underside (bridge or support) or a
  steep slope, and where it is in the model. Faces resting on another body of the
  same multi-material print count as supported.
- **Design log.** `--log "what changed and why"` keeps `<project>_log.md` beside the
  model: one entry per version with the run's results and what to reprint, under
  sections for decisions, rejected ideas, open questions and how the user works.
  SKILL.md tells Claude to read it before resuming, record print feedback in it,
  and hand it over with the latest model. Bundles carry it.
- **`--brief`** prints only problems and one-line summaries.
- SKILL.md says how to find the scripts folder once and reuse it.

## 2.3.0 - 2026-10-18

- **Ask for parts that have no standard.** For heat-set inserts, magnets, springs,
  boards and other brand-specific parts, the skill now asks for the part number or
  datasheet before modelling them, instead of using a remembered size. The fixed
  heat-set insert size in the printing tips was removed for the same reason.

## 2.2.0 - 2026-10-12

- **Hardware layer.** `include <hardware.scad>` gives standard bought parts built from
  BOSL2's ISO and ASME tables: socket, button, countersunk and hex screws, matching
  clearance holes (close, normal or loose fit) and counterbores, nuts and nut traps,
  washers, ball bearings, spur gears and racks, and NEMA motors with their mounts.
  Metric and inch sizes both work. A screw and its hole line up when given the same
  placement, threads are off unless asked for, and meshing gears are spaced and phased
  for you, with optional backlash for printed gears.
- **Real screw lengths.** `scripts/hardware.py` lists the lengths you can actually buy
  for a size and picks one for a joint: the shortest that clears a nut by two threads
  (with washers if any), or the longest that fits a tapped hole or insert, with the
  thread engagement. When the nearest length doesn't fit it says what to change.
  `hw_screw_len()` does the same inside a model. Lengths come from the ISO series plus
  commonly stocked sizes; inch lengths are one stockist's list. Sources are in
  `lib/hw_tables.json`.
- **Bill of materials.** `asm.py --bom` (and every `--bundle`) writes `model_bom.csv`
  with bought and made parts and their quantities.
- **Bundles open anywhere.** A bundle now carries the skill's own library files that
  the model uses (hardware.scad, loft.scad, sheet.scad).
- **Clearer failures.** When a model renders empty because a library stopped it,
  `render.sh` now shows the library's error message.
- `get_bosl2.sh` installs a fixed BOSL2 release (v2.0.768, commit-checked) instead of
  whatever is newest.
- New example: `examples/gearstage.scad`, a NEMA 17 motor plate with a gear pair and a
  608 bearing.
- The self-test covers length picking, hardware placement, gear meshing, the BOM and
  bundling. CI installs BOSL2 so these run.

## 2.1.0 - 2026-10-11

- **Viewer: inspect small parts.** On a computer, right-drag or Shift-drag moves the
  model, and the wheel zooms toward the cursor. Pinch zooms toward the fingers.
  Double-click or double-tap a part, or pick it in the list and press "Zoom to it", to
  frame it and rotate around it. The zoom range now reaches the smallest part, and an
  always-visible "Reset view" button restores the full view.
- **Security review.**
  - Part ids are restricted to plain names, so a model can't make the scripts write
    outside their folders.
  - Labels are escaped in the viewer, so a label can't run script there, and colours
    are validated.
  - three.js is pinned with an integrity hash, the viewer has a content security
    policy, and Google Fonts was removed.
  - The fast engine is installed without install scripts and checked against a pinned
    hash.
  - The workflow has read-only permissions except in the release step, and its actions
    are pinned to commits.
  - Temp files are cleaned up.
  - SKILL.md and the README now cover models from untrusted sources.
  - From an independent attack test:
    - Output and delete paths are confined to the model's folder, and a variant named
      `..` is refused.
    - Bundles skip symlinks, and an `include` mentioned only inside a string is no longer
      bundled.
    - Python is never imported from the model's folder.
    - pip runs from the skill's folder, within version ranges.
    - Every OpenSCAD run has a timeout (`OSCAD_TIMEOUT`, 15 minutes by default) and
      cleans up its temp files.
    - The WebAssembly engine reads only regular files, with size limits.
    - Text the model prints is labelled `model says:`, and SKILL.md tells Claude not to
      follow instructions in it.
    - The `render.sh` viewers get the same content security policy.
  - From the re-test:
    - Symlinks planted at output file names are removed before writing (only the link,
      never its target).
    - Hard-linked files are kept out of bundles.
    - `render.sh` labels model-printed warnings too.
    - Hidden direction-control characters are stripped from labels.
    - Ids can't end in a dot.

## 2.0.2 - 2026-10-10

- **Springs that may touch only their seats.** `flex=knob,base` allows contact with those
  parts or groups in clash and travel, and still reports a spring that bows into a wall.
  `flex=1` still leaves a part out of travel entirely.
- **Several travel rows per group.** Each row is its own pose set, with an optional
  `name=`. Combining every extreme in one row overshot designs where separate stops limit
  each motion.
- **Print support.** A piece in a multi-material plate counts as supported when it rests
  within 0.1 mm of a supported piece. Liners and strips on their body are no longer
  reported as mid-air.
- **Quantities.** `qty=3` marks a part to make three times, in the print list, manifests,
  cut list and viewer.
- **Automatic test and release.** GitHub Actions runs the self-test on every push. Running
  the "Test and release" workflow publishes the top CHANGELOG version, with the skill
  file attached.

## 2.0.1 - 2026-10-10

Fixes from the first real-world use on a large assembly with sculpted parts and springs.

- **Name clash stops the run.** If a model's own parameter has the same name as a table
  (for example `travel = 2` alongside the `travel` table), asm.py now stops and names both
  lines. Before, OpenSCAD silently kept one value and the geometry went wrong.
- **Warnings are not replayed.** Model-level warnings are printed once, as `model:` lines,
  from the current file. Cached parts no longer repeat warnings that were already fixed.
- **Table order.** A `report`, `checks` or `travel` value that is undef, because the table
  sits above the variable it uses, now says so. SKILL.md shows the tables after the
  parameters.
- **`--walls` reports regions.** Thin areas are grouped, with area, thickness range,
  centre and span. Each is labelled `even wall` or `tapering edge`, so a feathered rim no
  longer hides a real thin wall.
- **Flexible parts.** The `flex=1` tag (and `--ignore a,b`) leaves springs and flexures out
  of travel checks.
- **Pieces at different heights.** `--print` puts each separate piece of a part on the bed.
  It warns if the pieces would then collide, or if a piece in a multi-material plate would
  print in mid-air.
- **Exit code.** A non-manifold part now exits 1, as SKILL.md says.

## 2.0 - 2026-10-10

Rebuilt after heavy use on a complex multi-part design, plus an independent review.

**Faster**
- Renders with OpenSCAD 2025 and the Manifold engine. Where no native build has it,
  it uses the WebAssembly build from npm, with no sudo needed. A 21-part steel case
  takes 1.8 s instead of 88 s.
- Caches each part by its CSG tree, so only parts that actually changed re-render.

**New checks**
- A `checks` table holds clearances that must stay true. Failures are printed on every run.
- A `travel` table moves a group to every limit of its travel and tilt and reports collisions.
- `--section`: a true 2D section of the assembly at any plane or angle.
- `--walls`: the thinnest wall in each part and where it is.
- Overlaps are reported region by region, with penetration depth.
- Open and non-manifold meshes are flagged, and OpenSCAD warnings are shown.

**Printing**
- `--print` writes STLs oriented for printing and named by label, plus a 3MF for each
  multi-material set with its bodies kept registered, and an overhang report.
- `--bundle` now includes the print files, drops outputs from older revisions, and
  removes older bundles.

**Also**
- Variants, a `report` table of key dimensions, and a viewer with a cut plane,
  tap-to-measure and a variant switcher.
- `lib/loft.scad` builds smooth revolved shapes whose profile can change with angle.
- `setup.sh` refreshes a stale package index itself.
- Exit codes: 0 clean, 1 a part failed, 2 something was found.

**Fixed**
- `--only` left stale STLs that a later full run treated as current.
- "unchanged" meant only "same size". It now means identical geometry.
- `--cut` gave a 3D cutaway framed on the cutter cube. It now gives a 2D section.
- `--sweep` passed `true` and `false` as strings.

## 1.0

The first version: parts table, clash and hole checks, DXF cut files, bent sheet, STEP export, viewer.
