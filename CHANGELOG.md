# Changelog

## 2.0 - 2026-10-10

Rebuilt after a long session designing a six-axis controller, plus an independent review.

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
