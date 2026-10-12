// gear stage: NEMA 17 motor on a printed plate driving an idler gear on a 608 bearing
// shows the hardware layer: standard parts, real screw lengths, holes that match, gear spacing, BOM
include <hardware.scad>
part = "all";
plate_t = 8;                      // printed plate thickness (the 7 mm bearing seat needs a floor)
motor_thread = 4.5;               // usable thread depth in the motor's M3 holes (check your motor's datasheet)
gear_mod = 1;                     // gear module
pinion_teeth = 15;                // gear on the motor shaft
idler_teeth = 40;                 // driven gear
gear_t = 6;                       // gear thickness
backlash = 0.1;                   // printed-gear play, mm (same value for both gears and the spacing)
// derived
screw_l = hw_screw_len("M3", plate_t + 2, "socket");          // shortest real M3 that reaches 2 mm into the motor
centre = hw_gear_dist(gear_mod, pinion_teeth, idler_teeth, backlash = backlash);   // centre distance, incl. profile shift
hole_pitch = 31;                  // NEMA 17 mounting-hole spacing, mm
// tables
// hw_screws: flex=hw_motor lets them run into the motor's tapped holes without a clash
parts = [
  ["plate","Motor plate","PETG",[0,0,-15],"print=auto"],
  ["pinion","Pinion","PETG",[0,0,20],"group=drive"],
  ["idler","Idler gear","PETG",[0,0,25]],
  ["hw_motor","NEMA 17 stepper","bought",[0,0,-40]],
  ["hw_screws","M3 socket head screw","ISO 4762",[0,0,15],"flex=hw_motor"],
  ["hw_bearing","608 bearing","bought",[0,0,10]]
];
checks = [ ["pinion","idler","clear"], ["hw_screws","plate","touch"], ["hw_bearing","plate","touch"], ["pinion","plate",">=",1] ];
report = [ ["screw length", screw_l], ["gear centres", centre], ["engagement in motor", screw_l - plate_t] ];
module pick(n){ if(part=="all"||part==n) children(); }
holes = [for (x=[-1,1], y=[-1,1]) [x*hole_pitch/2, y*hole_pitch/2]];
pick("plate") difference() {
  translate([-25, -25, 0]) cube([25 + centre + 20, 50, plate_t]);
  translate([0, 0, -1]) cylinder(d = 23, h = plate_t + 2, $fn = 64);                       // motor boss
  for (h = holes) translate([h[0], h[1], plate_t]) hw_screw_hole("M3,20", counterbore = 3.5);
  translate([centre, 0, plate_t - 7]) cylinder(d = 22.2, h = 8, $fn = 96);                 // bearing seat
  translate([centre, 0, -1]) cylinder(d = 12, h = plate_t + 2, $fn = 48);
}
pick("hw_motor") hw_nema(17);
pick("hw_screws") for (h = holes) translate([h[0], h[1], plate_t]) hw_screw(hw_spec("M3", screw_l));
pick("hw_bearing") translate([centre, 0, plate_t - 7]) hw_bearing("608");
pick("pinion") translate([0, 0, plate_t + 14]) hw_spur_gear(gear_mod, pinion_teeth, gear_t, shaft_diam = 5.2, backlash = backlash);   // 5 mm motor shaft
pick("idler") translate([centre, 0, plate_t + 14]) hw_spur_gear(gear_mod, idler_teeth, gear_t, shaft_diam = 8, mate = true, backlash = backlash);
