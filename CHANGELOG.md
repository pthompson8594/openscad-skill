# Changelog

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
