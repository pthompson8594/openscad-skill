part = "all";      // which piece to output, "all" for the full assembly
box_w = 100;       // inside width
box_d = 60;        // inside depth
box_h = 40;        // inside height
sheet = 3;         // sheet thickness
tab_l = 15;        // tab length
fit = 0.1;         // slot clearance per side
screw = 3.4;       // lid screw clearance hole
tap = 2.5;         // strap pilot hole, tap M3

parts = [ // id, label, note, pull-apart [x,y,z]
  ["base","Base","3 mm sheet",[0,0,0]],
  ["left","Left wall","3 mm sheet",[-40,0,0]],
  ["right","Right wall","3 mm sheet",[40,0,0]],
  ["strap","Lid strap","3 mm sheet, tap M3",[0,0,30]],
  ["lid","Lid","3 mm sheet",[0,0,70]],
  ["hw_cell","Battery","reference only"]
];

w=box_w; d=box_d; h=box_h; t=sheet; f=fit;
module wall(x) translate([x,0,0]) rotate([90,0,90]) linear_extrude(t) union(){
  square([d,h]);
  translate([d/2-tab_l/2,-t]) square([tab_l,t]);
}
module base() translate([0,0,-t]) linear_extrude(t) difference(){
  translate([-t-4,0]) square([w+2*t+8,d]);
  for(x=[-t,w]) translate([x-f,d/2-tab_l/2-f]) square([t+2*f,tab_l+2*f]);
}
module strap() translate([0,d/2-8,h-t]) linear_extrude(t) difference(){
  square([w,16]);
  for(x=[15,w-15]) translate([x,8]) circle(d=tap,$fn=24);
}
module lid() translate([0,0,h]) linear_extrude(t) difference(){
  translate([-t,0]) square([w+2*t,d]);
  for(x=[15,w-15]) translate([x,d/2]) circle(d=screw,$fn=24);
}
module pick(n){ if(part=="all"||part==n) children(); }
pick("base") base();
pick("left") wall(-t);
pick("right") wall(w);
pick("strap") strap();
pick("lid") lid();
pick("hw_cell") translate([20,10,0]) cube([60,40,30]);
