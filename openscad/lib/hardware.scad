// hardware.scad - standard bought parts for assemblies, built from BOSL2's ISO/ASME tables.
// The skill scripts find this file (asm.py bundles carry it); BOSL2 via scripts/get_bosl2.sh. Then:
//   include <hardware.scad>
// It brings in BOSL2 (std, screws, ball_bearings, gears, nema_steppers) - don't include those again.
// Placement: a screw's SEAT is at z=0 (under the head; countersunk heads: the flush top) and
// its shaft runs down -Z, so hw_screw and hw_screw_hole line up when given the same transform.
// Nuts, washers and bearings sit on z=0. Threads are off by default (fast renders, same
// envelope for clash checks); pass thread=true only for parts that are printed threaded.
// Specs: "M3,12" (mm) or "#8-32,1/2" / "1/4-20,1" (inches). Sizes and lengths you can buy:
// scripts/hardware.py lengths M3 ; length for a joint: scripts/hardware.py pick M3 --grip 9.5 --nut
include <BOSL2/std.scad>
include <BOSL2/screws.scad>
include <BOSL2/ball_bearings.scad>
include <BOSL2/gears.scad>
include <BOSL2/nema_steppers.scad>
include <hw_tables.scad>
include <fits.scad>             // ISO 286 fits: fit_dev("H7", 22), fit_mid, fit_min, fit_max

function _hw_cs(head) = is_string(head) && starts_with(head, "flat");

// ---- screws, nuts, washers
// round features get enough facets to read as circles (OpenSCAD's default makes an M3 hole a hexagon)
module hw_screw(spec, head = "socket", thread = false, drive = "none") {
  $fs = min($fs, 0.25); $fa = min($fa, 6);
  screw(spec, head = head, thread = thread, drive = drive, anchor = _hw_cs(head) ? "head_top" : "head_bot");
}

// hole for a screw in a printed or cut part; fit "close" | "normal" | "loose" = ISO 273 fine/medium/coarse
// (ASME B18.2.8 for inch). Give a length longer than the material so it cuts clean through.
// counterbore = depth of a head pocket above the seat (0 = none): put the seat that far below the surface,
// e.g. translate([x, y, plate_t - 3.5]) hw_screw_hole("M3,20", counterbore = 3.5).
module hw_screw_hole(spec, head = "socket", fit = "normal", counterbore = 0, thread = false) {
  $fs = min($fs, 0.25); $fa = min($fa, 6);
  screw_hole(spec, head = _hw_cs(head) ? head : (counterbore > 0 ? head : "none"), thread = thread, tolerance = fit,
             counterbore = counterbore, anchor = _hw_cs(head) ? "head_top" : (counterbore > 0 ? "head_bot" : TOP));
}

module hw_nut(spec, thickness = "normal", shape = "hex", thread = false) {
  $fs = min($fs, 0.25); $fa = min($fa, 6);
  nut(spec, shape = shape, thickness = thickness, thread = thread, anchor = BOT);
}

// pocket for a nut, top at z=0 going down; set $slop (e.g. 0.1) for printed clearance
module hw_nut_trap(spec, depth, shape = "hex", thickness = "normal") {
  nut_trap_inline(depth, spec, shape = shape, anchor = TOP);
}

// washer from hw_tables (ISO 7089 for metric; "sae" or "uss" for inch sizes like "1/4", "#8")
function hw_washer_dims(size, series = "iso7089") =
  let(r = [for (w = HW_WASHERS) if (w[0] == size && w[1] == series) w])
  assert(len(r) > 0, str("no washer data for ", size, " ", series, " - see hw_tables.json"))
  [r[0][2], r[0][3], r[0][4]];

module hw_washer(size, series = "iso7089") {
  $fs = min($fs, 0.25); $fa = min($fa, 6);
  w = hw_washer_dims(size, series);
  difference() { cylinder(d = w[1], h = w[2]); translate([0, 0, -1]) cylinder(d = w[0], h = w[2] + 2); }
}

// ---- real lengths
// lengths you can buy for a size and head, in mm (metric: ISO series, plus commonly stocked if extras)
function hw_screw_lengths(size, head = "socket", extras = true) =
  let(std = starts_with(size, "M") ? (_hw_cs(head) ? "iso10642" : head == "button" ? "iso7380" : head == "hex" ? "iso4017" : "iso4762")
                                   : "asme_b18_3_shcs",
      r = [for (x = HW_LENGTHS) if (x[0] == std && x[1] == size) x])
  len(r) == 0 ? [] : sort(concat(r[0][2], extras ? r[0][3] : []));

// shortest real length >= need (mm); undef if none
function hw_screw_len(size, need, head = "socket", extras = true) =
  let(c = [for (l = hw_screw_lengths(size, head, extras)) if (l >= need - 1e-6) l]) len(c) ? c[0] : undef;

// spec string for a size and a length in mm, e.g. hw_spec("M3", 16) -> "M3,16", hw_spec("#8-32", 19.05) -> "#8-32,0.75"
function hw_spec(size, l) = starts_with(size, "M") ? str(size, ",", l) : str(size, ",", round(l / 25.4 * 64) / 64);

// ---- bearings, gears, motors (BOSL2, standard sizes)
module hw_bearing(code) { ball_bearing(code, anchor = BOT); }               // "608", "625", "6000" ...
// Gears mesh along +X: put the first gear on its axis, the mate at [hw_gear_dist(...), 0, 0]
// with mate=true (its teeth are phased to fall between the first gear's). Rotate or move the
// pair together to aim it elsewhere. Small tooth counts get BOSL2's automatic profile shift,
// which hw_gear_dist includes. backlash (mm) opens the mesh for printed gears - give the same
// value to both gears and to hw_gear_dist.
module hw_spur_gear(mod, teeth, thickness, shaft_diam = 0, helical = 0, herringbone = false, mate = false, backlash = 0) {
  spur_gear(mod = mod, teeth = teeth, thickness = thickness, shaft_diam = shaft_diam, helical = mate ? -helical : helical,
            herringbone = herringbone, backlash = backlash, gear_spin = mate ? 90 - 180 / teeth : -90);
}
function hw_gear_dist(mod, teeth1, teeth2, helical = 0, backlash = 0) =
  gear_dist(mod = mod, teeth1 = teeth1, teeth2 = teeth2, helical = helical, backlash = backlash);
module hw_rack(mod, teeth, thickness, width = 10) { rack(mod = mod, teeth = teeth, thickness = thickness, width = width); }
module hw_nema(size = 17) { nema_stepper_motor(size); }                       // motor body; face plate at z=0
module hw_nema_mount(size = 17, depth = 5) { nema_mount_mask(size = size, depth = depth); }
