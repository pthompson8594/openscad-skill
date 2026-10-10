# OpenSCAD cheatsheet

## 3D primitives
```scad
cube([x,y,z], center=true);     // box
sphere(r=5);                    // or sphere(d=10)
cylinder(h=10, r=4);            // r1=,r2= for cone/frustum
cylinder(h=10, d=8, center=true);
polyhedron(points=[...], faces=[...]);
```

## 2D primitives (extrude into 3D)
```scad
circle(r=5); square([10,4], center=true); polygon(points=[...]);
text("Hi", size=6, halign="center");
linear_extrude(height=3, twist=0, scale=1) <2d shape>;
rotate_extrude(angle=360) translate([10,0]) circle(2);   // ring/torus
```

## Transforms (apply to the child that follows)
```scad
translate([x,y,z]) ...
rotate([ax,ay,az]) ...        // degrees
scale([sx,sy,sz]) ...
mirror([1,0,0]) ...
color("red") ... ; color([r,g,b,a]) ...
```

## Boolean ops
```scad
union()        { a(); b(); }   // combine
difference()   { body(); hole1(); hole2(); }   // first child minus the rest
intersection() { a(); b(); }   // overlap only
hull()         { a(); b(); }   // convex wrap (great for rounded shapes)
minkowski()    { shape(); sphere(2); }   // round/inflate edges (slow)
```

## Smoothness & resolution
```scad
$fn = 64;          // facets per full circle (global)
cylinder(h=5, r=3, $fn=128);   // per-object override
// or $fa (min angle) / $fs (min size) instead of $fn
```

## Parametric pattern (recommended file skeleton)
```scad
// ---- parameters ----
wall      = 2;
width     = 40;
depth     = 30;
height    = 20;
hole_d    = 5;
clearance = 0.3;   // add to holes that fit real parts
$fn       = 96;

// ---- model ----
module box() {
    difference() {
        cube([width, depth, height], center=true);
        translate([0,0,wall])
            cube([width-2*wall, depth-2*wall, height], center=true);
    }
}

module mount_hole() {
    // overshoot through the wall so it's manifold
    translate([0,0,-height/2-0.1])
        cylinder(h=wall+0.2, d=hole_d+clearance);
}

box();
translate([width/3,0,0]) mount_hole();
```

## Loops & logic
```scad
for (i = [0:5])      translate([i*10,0,0]) cube(3);
for (a = [0:60:300]) rotate([0,0,a]) translate([10,0,0]) cylinder(h=2,d=3);
if (cond) cube(2); else sphere(2);
x = cond ? 1 : 2;                 // ternary
points = [for (i=[0:10]) [i, i*i]];   // list comprehension
```

## Modules & functions
```scad
module gusset(t=2, l=10) { /* geometry */ }   // returns geometry
function area(w,h) = w*h;                       // returns a value
```

## Handy library
```scad
use <BOSL2/std.scad>   // if installed: rounding(), screws, gears, etc.
```

## Export notes
- STL export ignores `color()` and needs a closed, manifold solid.
- Make subtractions overshoot surfaces (`h+0.2`, start at `-0.1`) to avoid zero-thickness faces / non-manifold warnings.
- Use `--render` (CGAL/Manifold) for final exports; preview (F5) is fast but approximate.
