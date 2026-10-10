#!/usr/bin/env python3
"""meshgen.py — zero-dependency parametric solid modeling + binary STL export.

Fallback for environments without OpenSCAD installed (e.g. the Claude app
code sandbox). Build solids from primitives and real boolean operations
(union / difference / intersection) via a self-contained BSP CSG engine,
then save a printable STL. Pure Python standard library only.

Example
-------
    from meshgen import cube, cylinder, sphere, union, difference, save_stl
    body = union(cube([20,20,8], center=True),
                 sphere(8).translate([0,0,4]))
    part = difference(body, cylinder(h=20, d=6, center=True).translate([0,0,2]))
    save_stl(part, "part.stl")

CSG core is an MIT-licensed port of Evan Wallace's csg.js.
"""
import math, struct, sys
sys.setrecursionlimit(100000)


class Vector:
    __slots__ = ("x", "y", "z")
    def __init__(self, x, y, z): self.x, self.y, self.z = x, y, z
    def clone(self):    return Vector(self.x, self.y, self.z)
    def negated(self):  return Vector(-self.x, -self.y, -self.z)
    def plus(self, a):  return Vector(self.x+a.x, self.y+a.y, self.z+a.z)
    def minus(self, a): return Vector(self.x-a.x, self.y-a.y, self.z-a.z)
    def times(self, k): return Vector(self.x*k, self.y*k, self.z*k)
    def over(self, k):  return Vector(self.x/k, self.y/k, self.z/k)
    def dot(self, a):   return self.x*a.x + self.y*a.y + self.z*a.z
    def lerp(self, a, t): return self.plus(a.minus(self).times(t))
    def length(self):   return math.sqrt(self.dot(self))
    def unit(self):
        L = self.length()
        return self.over(L) if L else Vector(0, 0, 0)
    def cross(self, a):
        return Vector(self.y*a.z - self.z*a.y,
                      self.z*a.x - self.x*a.z,
                      self.x*a.y - self.y*a.x)


class Vertex:
    __slots__ = ("pos", "normal")
    def __init__(self, pos, normal): self.pos, self.normal = pos, normal
    def clone(self):  return Vertex(self.pos.clone(), self.normal.clone())
    def flip(self):   self.normal = self.normal.negated()
    def interpolate(self, o, t):
        return Vertex(self.pos.lerp(o.pos, t), self.normal.lerp(o.normal, t))


COPLANAR, FRONT, BACK, SPANNING = 0, 1, 2, 3


class Plane:
    EPS = 1e-5
    __slots__ = ("normal", "w")
    def __init__(self, normal, w): self.normal, self.w = normal, w
    @staticmethod
    def from_points(a, b, c):
        n = b.minus(a).cross(c.minus(a)).unit()
        return Plane(n, n.dot(a))
    def clone(self): return Plane(self.normal.clone(), self.w)
    def flip(self):  self.normal = self.normal.negated(); self.w = -self.w

    def split(self, poly, cofront, coback, front, back):
        ptype = 0
        types = []
        for v in poly.vertices:
            t = self.normal.dot(v.pos) - self.w
            ty = BACK if t < -self.EPS else (FRONT if t > self.EPS else COPLANAR)
            ptype |= ty
            types.append(ty)
        if ptype == COPLANAR:
            (cofront if self.normal.dot(poly.plane.normal) > 0 else coback).append(poly)
        elif ptype == FRONT:
            front.append(poly)
        elif ptype == BACK:
            back.append(poly)
        else:
            f, b = [], []
            n = len(poly.vertices)
            for i in range(n):
                j = (i + 1) % n
                ti, tj = types[i], types[j]
                vi, vj = poly.vertices[i], poly.vertices[j]
                if ti != BACK:  f.append(vi)
                if ti != FRONT: b.append(vi.clone() if ti != BACK else vi)
                if (ti | tj) == SPANNING:
                    t = (self.w - self.normal.dot(vi.pos)) / \
                        self.normal.dot(vj.pos.minus(vi.pos))
                    v = vi.interpolate(vj, t)
                    f.append(v); b.append(v.clone())
            if len(f) >= 3: front.append(Polygon(f, poly.shared))
            if len(b) >= 3: back.append(Polygon(b, poly.shared))


class Polygon:
    __slots__ = ("vertices", "shared", "plane")
    def __init__(self, vertices, shared=None):
        self.vertices, self.shared = vertices, shared
        self.plane = Plane.from_points(vertices[0].pos, vertices[1].pos, vertices[2].pos)
    def clone(self):
        return Polygon([v.clone() for v in self.vertices], self.shared)
    def flip(self):
        self.vertices.reverse()
        for v in self.vertices: v.flip()
        self.plane.flip()


class Node:
    def __init__(self, polygons=None):
        self.plane = None; self.front = None; self.back = None; self.polygons = []
        if polygons: self.build(polygons)
    def clone(self):
        n = Node()
        n.plane = self.plane.clone() if self.plane else None
        n.front = self.front.clone() if self.front else None
        n.back  = self.back.clone()  if self.back  else None
        n.polygons = [p.clone() for p in self.polygons]
        return n
    def invert(self):
        for p in self.polygons: p.flip()
        if self.plane: self.plane.flip()
        if self.front: self.front.invert()
        if self.back:  self.back.invert()
        self.front, self.back = self.back, self.front
    def clip_polygons(self, polygons):
        if not self.plane: return polygons[:]
        front, back = [], []
        for p in polygons:
            self.plane.split(p, front, back, front, back)
        if self.front: front = self.front.clip_polygons(front)
        back = self.back.clip_polygons(back) if self.back else []
        return front + back
    def clip_to(self, bsp):
        self.polygons = bsp.clip_polygons(self.polygons)
        if self.front: self.front.clip_to(bsp)
        if self.back:  self.back.clip_to(bsp)
    def all_polygons(self):
        out = self.polygons[:]
        if self.front: out += self.front.all_polygons()
        if self.back:  out += self.back.all_polygons()
        return out
    def build(self, polygons):
        if not polygons: return
        if not self.plane: self.plane = polygons[0].plane.clone()
        front, back = [], []
        for p in polygons:
            self.plane.split(p, self.polygons, self.polygons, front, back)
        if front:
            if not self.front: self.front = Node()
            self.front.build(front)
        if back:
            if not self.back: self.back = Node()
            self.back.build(back)


class CSG:
    def __init__(self, polygons=None): self.polygons = polygons or []
    def clone(self): return CSG([p.clone() for p in self.polygons])

    def union(self, o):
        a, b = Node(self.clone().polygons), Node(o.clone().polygons)
        a.clip_to(b); b.clip_to(a); b.invert(); b.clip_to(a); b.invert()
        a.build(b.all_polygons()); return CSG(a.all_polygons())
    def subtract(self, o):
        a, b = Node(self.clone().polygons), Node(o.clone().polygons)
        a.invert(); a.clip_to(b); b.clip_to(a); b.invert(); b.clip_to(a)
        b.invert(); a.build(b.all_polygons()); a.invert()
        return CSG(a.all_polygons())
    def intersect(self, o):
        a, b = Node(self.clone().polygons), Node(o.clone().polygons)
        a.invert(); b.clip_to(a); b.invert(); a.clip_to(b); b.clip_to(a)
        a.build(b.all_polygons()); a.invert(); return CSG(a.all_polygons())

    # --- transforms (return a new CSG) ---
    def _apply(self, fp, fn):
        out = []
        for p in self.polygons:
            vs = [Vertex(fp(v.pos), fn(v.normal).unit()) for v in p.vertices]
            out.append(Polygon(vs, p.shared))
        return CSG(out)
    def translate(self, v):
        t = Vector(*v); return self._apply(lambda p: p.plus(t), lambda n: n)
    def scale(self, s):
        s = (s, s, s) if isinstance(s, (int, float)) else s
        sv = Vector(*s)
        return self._apply(lambda p: Vector(p.x*sv.x, p.y*sv.y, p.z*sv.z),
                           lambda n: Vector(n.x/sv.x, n.y/sv.y, n.z/sv.z))
    def rotate(self, deg, axis):
        ax = Vector(*axis).unit(); a = math.radians(deg)
        c, s, t = math.cos(a), math.sin(a), 1 - math.cos(a)
        x, y, z = ax.x, ax.y, ax.z
        m = ((t*x*x+c,   t*x*y-s*z, t*x*z+s*y),
             (t*x*y+s*z, t*y*y+c,   t*y*z-s*x),
             (t*x*z-s*y, t*y*z+s*x, t*z*z+c))
        def rot(p):
            return Vector(m[0][0]*p.x+m[0][1]*p.y+m[0][2]*p.z,
                          m[1][0]*p.x+m[1][1]*p.y+m[1][2]*p.z,
                          m[2][0]*p.x+m[2][1]*p.y+m[2][2]*p.z)
        return self._apply(rot, rot)


# --- primitives -------------------------------------------------------------
def cube(size=1.0, center=False):
    sx, sy, sz = (size, size, size) if isinstance(size, (int, float)) else size
    ox, oy, oz = (-sx/2, -sy/2, -sz/2) if center else (0, 0, 0)
    def corner(i):
        return Vector(ox + sx*(i & 1), oy + sy*((i >> 1) & 1), oz + sz*((i >> 2) & 1))
    faces = (((0, 4, 6, 2), (-1, 0, 0)), ((1, 3, 7, 5), (1, 0, 0)),
             ((0, 1, 5, 4), (0, -1, 0)), ((2, 6, 7, 3), (0, 1, 0)),
             ((0, 2, 3, 1), (0, 0, -1)), ((4, 5, 7, 6), (0, 0, 1)))
    polys = []
    for idx, nrm in faces:
        n = Vector(*nrm)
        polys.append(Polygon([Vertex(corner(i), n) for i in idx]))
    return CSG(polys)


def cylinder(h=1.0, r=None, r1=None, r2=None, d=None, segments=48, center=False):
    if d is not None: r = d / 2
    if r is not None: r1 = r2 = r
    if r1 is None: r1 = 1.0
    if r2 is None: r2 = r1
    z0 = -h/2 if center else 0.0
    s, e = Vector(0, 0, z0), Vector(0, 0, z0 + h)
    az = e.minus(s).unit()
    ax = (Vector(1, 0, 0) if abs(az.z) > 0.5 else Vector(0, 0, 1)).cross(az).unit()
    ay = ax.cross(az).unit()

    def pt(stack, sl, blend):
        ang = sl * 2 * math.pi
        rad = r1 if stack == 0 else r2
        out = ax.times(math.cos(ang)).plus(ay.times(math.sin(ang)))
        pos = s.plus(e.minus(s).times(stack)).plus(out.times(rad))
        nrm = out.times(1 - abs(blend)).plus(az.times(blend))
        return Vertex(pos, nrm)
    polys = []
    sv, ev = Vertex(s, az.negated()), Vertex(e, az)
    for i in range(segments):
        t0, t1 = i / segments, (i + 1) / segments
        polys.append(Polygon([sv.clone(), pt(0, t0, -1), pt(0, t1, -1)]))
        polys.append(Polygon([pt(0, t1, 0), pt(0, t0, 0), pt(1, t0, 0), pt(1, t1, 0)]))
        polys.append(Polygon([ev.clone(), pt(1, t1, 1), pt(1, t0, 1)]))
    return CSG(polys)


def sphere(r=1.0, d=None, segments=32):
    if d is not None: r = d / 2
    slices = segments
    stacks = max(2, segments // 2)

    def vtx(theta, phi):
        theta *= 2 * math.pi; phi *= math.pi
        dr = Vector(math.cos(theta) * math.sin(phi),
                    math.sin(theta) * math.sin(phi),
                    math.cos(phi))
        return Vertex(dr.times(r), dr)
    polys = []
    for i in range(slices):
        for j in range(stacks):
            vs = [vtx(i / slices, j / stacks)]
            if j > 0:          vs.append(vtx((i + 1) / slices, j / stacks))
            if j < stacks - 1: vs.append(vtx((i + 1) / slices, (j + 1) / stacks))
            vs.append(vtx(i / slices, (j + 1) / stacks))
            vs.reverse()  # wind CCW so plane normal points outward (radial)
            polys.append(Polygon(vs))
    return CSG(polys)


# --- combinators ------------------------------------------------------------
def union(*objs):
    r = objs[0]
    for o in objs[1:]: r = r.union(o)
    return r


def difference(a, *rest):
    for o in rest: a = a.subtract(o)
    return a


def intersection(*objs):
    r = objs[0]
    for o in objs[1:]: r = r.intersect(o)
    return r


# --- export -----------------------------------------------------------------
def _heal_tjunctions(tris):
    """Split triangle edges at vertices of neighboring triangles (T-junctions),
    which BSP clipping produces, so the exported STL is truly watertight."""
    verts = {}          # rounded position -> canonical (x,y,z)
    def key(p): return (round(p[0], 5), round(p[1], 5), round(p[2], 5))
    tris = [tuple(key((v.x, v.y, v.z)) for v in t) for t in tris]
    for t in tris:
        for v in t: verts[v] = v
    pts = list(verts)
    # uniform grid over vertices for fast edge->point candidate lookup
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; zs = [p[2] for p in pts]
    diag = max(max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs), 1e-9)
    cell = diag / 64
    grid = {}
    for p in pts:
        grid.setdefault((int(p[0]//cell), int(p[1]//cell), int(p[2]//cell)), []).append(p)
    eps = max(1e-4, diag * 1e-6)  # must exceed the 1e-5 key rounding above

    def on_edge(a, b, p):
        if p == a or p == b: return None
        ab = tuple(b[i]-a[i] for i in range(3))
        ap = tuple(p[i]-a[i] for i in range(3))
        L2 = sum(c*c for c in ab)
        if L2 < eps*eps: return None
        t = sum(ap[i]*ab[i] for i in range(3)) / L2
        if t <= 1e-7 or t >= 1 - 1e-7: return None
        d2 = sum((ap[i]-t*ab[i])**2 for i in range(3))
        return t if d2 < eps*eps else None

    def edge_pts(a, b):
        lo = [min(a[i], b[i]) for i in range(3)]; hi = [max(a[i], b[i]) for i in range(3)]
        found = []
        for cx in range(int((lo[0]-eps)//cell), int((hi[0]+eps)//cell)+1):
            for cy in range(int((lo[1]-eps)//cell), int((hi[1]+eps)//cell)+1):
                for cz in range(int((lo[2]-eps)//cell), int((hi[2]+eps)//cell)+1):
                    for p in grid.get((cx, cy, cz), ()):
                        t = on_edge(a, b, p)
                        if t is not None: found.append((t, p))
        found.sort()
        return [p for _, p in found]

    out = []
    for t in tris:
        ring, split = [], False
        for i in range(3):
            a, b = t[i], t[(i+1) % 3]
            ring.append(a)
            mids = edge_pts(a, b)
            if mids: split = True; ring.extend(mids)
        if not split:
            out.append(t); continue
        # fan from centroid: valid for a (convex) triangle with collinear edge points
        c = tuple(sum(p[i] for p in ring)/len(ring) for i in range(3))
        for i in range(len(ring)):
            out.append((c, ring[i], ring[(i+1) % len(ring)]))
    return out


def save_stl(csg, path, name="meshgen", heal=True):
    tris = []
    for p in csg.polygons:
        vs = p.vertices
        for i in range(1, len(vs) - 1):
            tris.append((vs[0].pos, vs[i].pos, vs[i + 1].pos))
    if heal:
        tris = [tuple(Vector(*v) for v in t) for t in _heal_tjunctions(tris)]
    with open(path, "wb") as f:
        f.write(name.encode()[:80].ljust(80, b"\0"))
        f.write(struct.pack("<I", len(tris)))
        for a, b, c in tris:
            n = b.minus(a).cross(c.minus(a)).unit()
            f.write(struct.pack("<3f", n.x, n.y, n.z))
            for v in (a, b, c):
                f.write(struct.pack("<3f", v.x, v.y, v.z))
            f.write(struct.pack("<H", 0))
    return len(tris)


if __name__ == "__main__":
    body = union(cube([20, 20, 8], center=True), sphere(8).translate([0, 0, 4]))
    part = difference(body, cylinder(h=20, d=6, center=True).translate([0, 0, 2]))
    n = save_stl(part, "meshgen_demo.stl")
    print(f"wrote meshgen_demo.stl ({n} triangles)")
