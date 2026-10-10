// joystick knob on a stalk over a board: travel, checks, variants, multi-material print
part = "all";
variant = "dome";                 // knob top: dome | dish
variants = ["dome","dish"];
knob_d = 30;                      // knob diameter
knob_h = 18;                      // knob height
gap = 0.4;                        // knob to cap board clearance at rest
travel_mm = 2.0;                  // knob travel each way in x and y
tilt = 3;                         // knob tilt each way, degrees
groove = [6,10];                  // grip groove from / to height on the knob
grip_t = 1.5;                     // TPU grip ring thickness
board_z = 10;                     // cap board underside
// derived
z0 = board_z + 2 + gap;           // knob underside
parts = [
  ["base","Base","PETG",[0,0,-20],"print=auto"],
  ["knob","Knob","PETG",[0,0,25],"group=knob","plate=knob","mat=PETG"],
  ["grip","Grip ring","TPU",[0,0,25],"group=knob","plate=knob","mat=TPU","#3b4047"],
  ["stalk","Stalk","PETG",[0,0,10],"group=knob","print=auto"],
  ["hw_board","Cap board","bought PCB",[0,0,0]]
];
checks = [ ["knob","hw_board",">=",0.3,"travel"], ["stalk","base","clear","travel"], ["grip","knob","touch"] ];
travel = [ ["knob",[travel_mm,travel_mm,0],[tilt,tilt,0],[0,0,2]] ];
report = [ ["knob top", z0+knob_h], ["board top", board_z+2], ["grip band", groove] ];
module pick(n){ if(part=="all"||part==n) children(); }
pick("base") difference(){ cylinder(d=60,h=board_z,$fn=96); translate([0,0,-1]) cylinder(d=16,h=board_z+2,$fn=48); }
pick("hw_board") translate([0,0,board_z]) difference(){ cylinder(d=58,h=2,$fn=96); translate([0,0,-1]) cylinder(d=16,h=4,$fn=48); }
pick("stalk") translate([0,0,2]) cylinder(d=8,h=z0-2+2,$fn=48);
pick("knob") translate([0,0,z0]) difference(){
  intersection(){
    cylinder(d=knob_d,h=knob_h,$fn=96);
    if(variant=="dome") translate([0,0,knob_h-40]) sphere(r=40,$fn=96); else cylinder(d=knob_d+1,h=knob_h+1);
  }
  translate([0,0,-1]) cylinder(d=8,h=3,$fn=48);
  if(variant=="dish") translate([0,0,knob_h+30-3]) sphere(r=30,$fn=96);
  translate([0,0,groove[0]]) difference(){ cylinder(d=knob_d+1,h=groove[1]-groove[0],$fn=96); translate([0,0,-1]) cylinder(d=knob_d-2*grip_t,h=groove[1]-groove[0]+2,$fn=96); }
}
pick("grip") translate([0,0,z0+groove[0]]) difference(){ cylinder(d=knob_d,h=groove[1]-groove[0],$fn=96); translate([0,0,-1]) cylinder(d=knob_d-2*grip_t,h=groove[1]-groove[0]+2,$fn=96); }
