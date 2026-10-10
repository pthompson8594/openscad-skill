// Bent sheet metal. Draw the FLAT pattern in 2D (bend allowance included), list the bends, fold() does the rest.
// Bend row: [part id, x0,y0, x1,y1, angle, inside radius, parent]
//   line x0,y0 -> x1,y1 is where the bend zone STARTS, in flat-pattern coordinates; material to its LEFT moves
//   angle: + folds up (+z), - folds down; parent: index of the bend this one sits beyond, -1 = on the base
function bend_allow(angle, r, t, k=0.4) = (r + k*t) * abs(angle) * PI/180;
function bends_of(B, id) = [for(b=B) if(b[0]==id) b];
BIG = 1e4;
module _loc(b) translate([b[1],b[2],0]) rotate(atan2(b[4]-b[2], b[3]-b[1])) children();
module _unloc(b) rotate(-atan2(b[4]-b[2], b[3]-b[1])) translate([-b[1],-b[2],0]) children();
module _beyond(b, d0, d1) _loc(b) translate([-BIG,d0,-BIG]) cube([2*BIG,d1-d0,2*BIG]);
module _node(B, i, t, k, n){
  difference(){
    children();
    for(j=[0:1:len(B)-1]) if(B[j][7]==i) _beyond(B[j], 0, BIG);
  }
  for(j=[0:1:len(B)-1]) if(B[j][7]==i){
    a=B[j][5]; r=B[j][6]; ba=bend_allow(a,r,t,k); zc = a>0 ? t+r : -r;
    for(s=[0:n-1]) _loc(B[j]) translate([0,0,zc]) rotate([a*(s+.5)/n,0,0]) translate([0,-(s+.5)*ba/n,-zc]) _unloc(B[j])
      intersection(){ children(); _beyond(B[j], s*ba/n, (s+1)*ba/n); }
    _loc(B[j]) translate([0,0,zc]) rotate([a,0,0]) translate([0,-ba,-zc]) _unloc(B[j])
      _node(B, j, t, k, n) intersection(){ children(); _beyond(B[j], ba, BIG); }
  }
}
module fold(B, t, k=0.4, flat=false, n=8){
  if(flat || len(B)==0) linear_extrude(t) children();
  else _node(B, -1, t, k, n) linear_extrude(t) children();
}
