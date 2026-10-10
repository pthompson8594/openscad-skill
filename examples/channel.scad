use <sheet.scad>
part = "all";      // which piece to output
flat = false;      // true = unfolded flat pattern
sheet = 2;         // thickness
k_factor = 0.4;    // bend allowance factor
rad = 2;           // inside bend radius
len_x = 80;        // channel length
base_w = 40;       // base width
wall = 20;         // wall height in the flat
lip = 10;          // return lip

ba = bend_allow(90, rad, sheet, k_factor);
parts = [
  ["chan","Channel","2 mm steel, 3 bends"]
];
bends = [ // id, x0,y0, x1,y1, angle, radius, parent
  ["chan", 0,base_w, len_x,base_w, 90, rad, -1],
  ["chan", 0,base_w+ba+wall, len_x,base_w+ba+wall, 90, rad, 0],
  ["chan", len_x,0, 0,0, 90, rad, -1]
];
module chan2d() difference(){
  translate([0,-ba-wall]) square([len_x, wall+ba+base_w+ba+wall+ba+lip]);
  translate([20,20]) circle(d=5,$fn=32);
  translate([60,base_w+ba+10]) circle(d=4,$fn=32);
}
module pick(n){ if(part=="all"||part==n) children(); }
pick("chan") fold(bends_of(bends,"chan"), sheet, k_factor, flat) chan2d();
