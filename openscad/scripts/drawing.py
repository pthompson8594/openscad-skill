#!/usr/bin/env python3
"""drawing.py - ISO manufacturing drawings from part meshes, called by asm.py --drawings.

One sheet per part, first-angle projection (ISO 5456-2): front view, the view from
above placed below it, the view from the left placed to its right, an isometric view,
optional section A-A and, for bent sheet, the flat pattern. Visible edges solid,
hidden edges dashed (worked out by ray casts against the solid), centre lines on
holes. Dimensions: overall sizes once each, hole positions as coordinate (ordinate)
dimensions from the view's lower-left corner, hole callouts (count, diameter, THRU
or depth, counterbore, countersink, ISO 286 fit with its limits, or text you give),
and dimensions you declare. Title block after ISO 7200 with general tolerances
ISO 2768-mK. Output: PDF (all sheets also in one file) and DXF (the sheet at paper
size, layers per line type).
"""
import datetime, json, math, os, re

import numpy as np

SHEETS = [("A4", 297.0, 210.0), ("A3", 420.0, 297.0), ("A2", 594.0, 420.0), ("A1", 841.0, 594.0)]
SCALES = [(10, 1), (5, 1), (2, 1), (1, 1), (1, 2), (1, 5), (1, 10), (1, 20), (1, 50)]
# view: (looking direction d, sheet right u, sheet up v)
VIEWS = {
    "front": ((0, 1, 0), (1, 0, 0), (0, 0, 1)),
    "top": ((0, 0, -1), (1, 0, 0), (0, 1, 0)),
    "left": ((1, 0, 0), (0, -1, 0), (0, 0, 1)),
    "right": ((-1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "bottom": ((0, 0, 1), (1, 0, 0), (0, -1, 0)),
    "rear": ((0, -1, 0), (-1, 0, 0), (0, 0, 1)),
}
NAMES = {"front": "FRONT", "top": "FROM ABOVE", "left": "FROM LEFT", "right": "FROM RIGHT", "bottom": "FROM BELOW", "rear": "REAR"}
# first-angle grid position (column, row) relative to the front view at (1, 1)
GRID = {"front": (1, 1), "top": (1, 2), "bottom": (1, 0), "left": (2, 1), "right": (0, 1), "rear": (3, 1)}
TXT = 3.5        # dimension text height, mm on paper
SMALL = 2.5
W_VIS, W_THIN = 0.5, 0.25
FEATURE_DEG = 25.0
FIT_RE = re.compile(r"^[A-Za-z]{1,2}\d{1,2}$")
TB_W, TB_H = 180.0, 44.0


# ------------------------------------------------------------------ geometry
def unit(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    return v / n if n else v


def mesh_of(man):
    m = man.to_mesh()
    V = np.asarray(m.vert_properties)[:, :3].astype(np.float64)
    F = np.asarray(m.tri_verts).astype(np.int64)
    a = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    ln = np.linalg.norm(a, axis=1)
    keep = ln > 1e-12
    F, a, ln = F[keep], a[keep], ln[keep]
    return V, F, a / ln[:, None]


def edge_table(V, F):
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    fi = np.tile(np.arange(len(F)), 3)
    e = np.sort(e, axis=1)
    key = e[:, 0] * (len(V) + 1) + e[:, 1]
    o = np.argsort(key, kind="stable")
    key, e, fi = key[o], e[o], fi[o]
    _, start, cnt = np.unique(key, return_index=True, return_counts=True)
    f2 = np.where(cnt >= 2, fi[np.minimum(start + 1, len(fi) - 1)], -1)
    return e[start], fi[start], f2, cnt


def basis(name_or_d):
    if isinstance(name_or_d, str):
        d, u, v = VIEWS[name_or_d]
        return np.array(d, float), np.array(u, float), np.array(v, float)
    d = unit(name_or_d)
    u = np.cross(d, [0, 0, 1])
    u = unit(u) if np.linalg.norm(u) > 1e-6 else np.array([1.0, 0, 0])
    return d, u, unit(np.cross(u, d))


def project_view(man, d, u, v, hidden=True, sliver=0.0):
    """edges of the solid seen along d: dict with 'vis'/'hid' polylines (Nx3 world points) and circles"""
    V, F, N = mesh_of(man)
    E, f1, f2, cnt = edge_table(V, F)
    n1 = N[f1]
    n2 = np.where((f2 >= 0)[:, None], N[np.maximum(f2, 0)], n1)
    dots = np.einsum("ij,ij->i", n1, n2)
    feat = (cnt != 2) | (dots < math.cos(math.radians(FEATURE_DEG)))
    s1, s2 = n1 @ d, n2 @ d
    sil = (s1 * s2 < 0) & (cnt == 2)
    draw = feat | sil
    if sliver > 0:
        # bent sheet: fold() builds each bend from rigid slices, which leaves narrow steps along the bend; leave their edges out
        L = np.linalg.norm(V[E[:, 1]] - V[E[:, 0]], axis=1)
        def height(fi):
            tri = V[F[fi]]
            ar = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
            return ar / np.maximum(L, 1e-9)
        hmin = np.minimum(height(f1), height(np.maximum(f2, 0)))
        draw &= ~((hmin < sliver) & (L > 3 * sliver) & (cnt == 2))
    E, n1, n2 = E[draw], n1[draw], n2[draw]
    A, B = V[E[:, 0]], V[E[:, 1]]
    diag = float(np.linalg.norm(V.max(0) - V.min(0))) + 1.0
    nrm = n1 + n2
    nl = np.linalg.norm(nrm, axis=1)
    nrm = np.where((nl > 1e-9)[:, None], nrm / np.maximum(nl, 1e-12)[:, None], n1)
    eps = 2e-3 * max(1.0, diag / 100.0)
    runs = []
    for i in range(len(E)):
        a, b = A[i], B[i]
        L = float(np.linalg.norm(b - a))
        k = 1 if not hidden else int(min(12, max(1, math.ceil(L / max(0.4, diag / 300.0)))))
        ts = np.linspace(0, 1, k + 1)
        vis = []
        for j in range(k):
            m = a + (b - a) * (ts[j] + ts[j + 1]) / 2
            o = m - d * eps + nrm[i] * eps
            vis.append(len(man.ray_cast(o.tolist(), (o - d * 2 * diag).tolist())) == 0)
        j = 0
        while j < k:
            q = j
            while q + 1 < k and vis[q + 1] == vis[j]:
                q += 1
            ka = int(E[i, 0]) if j == 0 else -(len(runs) * 2 + 1)
            kb = int(E[i, 1]) if q == k - 1 else -(len(runs) * 2 + 2)
            runs.append((vis[j], ka, kb, a + (b - a) * ts[j], a + (b - a) * ts[q + 1]))
            j = q + 1
    out = {"vis": [], "hid": [], "E": E, "A": A, "B": B}
    for flag, key in ((True, "vis"), (False, "hid")):
        if not hidden and not flag:
            continue
        out[key] = chain([(ka, kb, pa, pb) for f, ka, kb, pa, pb in runs if f == flag])
    out["V"], out["F"], out["N"] = V, F, N
    return out


def chain(segs):
    """join segments that share a mesh vertex (and nothing else) into polylines; closed loops end where they start"""
    adj = {}
    for i, (ka, kb, pa, pb) in enumerate(segs):
        adj.setdefault(ka, []).append(i)
        adj.setdefault(kb, []).append(i)
    used = [False] * len(segs)
    lines = []

    def walk(i, frm):
        ka, kb, pa, pb = segs[i]
        pts, keys = ([pa, pb], [ka, kb]) if ka == frm else ([pb, pa], [kb, ka])
        used[i] = True
        cur = keys[-1]
        while len(adj.get(cur, [])) == 2:
            nx = [j for j in adj[cur] if not used[j]]
            if not nx:
                break
            j = nx[0]
            used[j] = True
            ja, jb, qa, qb = segs[j]
            if ja == cur:
                pts.append(qb)
                cur = jb
            else:
                pts.append(qa)
                cur = ja
        return pts, keys[0], cur

    for start_open in (True, False):
        for i, (ka, kb, pa, pb) in enumerate(segs):
            if used[i]:
                continue
            if start_open and len(adj[ka]) == 2 and len(adj[kb]) == 2:
                continue
            frm = ka if (not start_open or len(adj[ka]) != 2) else kb
            pts, k0, k1 = walk(i, frm)
            pts2 = np.array(pts)
            lines.append((pts2, k0 == k1 and len(pts) > 3))
    return lines


def flat_loops(view, d, tol=1e-3):
    """closed loops of drawn edges lying in planes square to the view: candidate circles (holes, bosses)"""
    E, A, B = view["E"], view["A"], view["B"]
    za, zb = A @ d, B @ d
    keep = np.abs(za - zb) < tol
    segs = [(int(E[i, 0]), int(E[i, 1]), A[i], B[i]) for i in np.where(keep)[0]]
    return [pts for pts, closed in chain(segs) if closed]


def fit_circle2d(p2, depth):
    if len(p2) < 11 or np.std(depth) > 0.01:
        return None
    c = p2[:-1].mean(0) if np.allclose(p2[0], p2[-1]) else p2.mean(0)
    r = np.linalg.norm(p2 - c, axis=1)
    if r.mean() < 0.2 or (r.max() - r.min()) > max(0.004 * r.mean(), 0.003):
        return None
    return c, float(r.mean())


# ------------------------------------------------------------------ holes
def holes_in_view(man, view, d, u, v, origin):
    """concentric circle groups seen end-on -> hole/boss descriptions"""
    groups = []
    vis_pts = {}
    for pts, closed in view["vis"]:
        for q in pts:
            vis_pts[tuple(np.round(q, 4))] = True
    for pts in flat_loops(view, d):
        flag = "vis" if sum(tuple(np.round(q, 4)) in vis_pts for q in pts) > len(pts) / 2 else "hid"
        if True:
            p2 = np.stack([pts @ u, pts @ v], 1)
            fc = fit_circle2d(p2, pts @ d)
            if fc is None:
                continue
            c, r = fc
            z = float(np.mean(pts @ d))
            for g in groups:
                if np.linalg.norm(g["c"] - c) < 0.02:
                    g["loops"].append((r, z, flag == "vis"))
                    break
            else:
                groups.append({"c": c, "loops": [(r, z, flag == "vis")]})
    out = []
    for g in groups:
        c3 = u * g["c"][0] + v * g["c"][1]
        rs = {}
        for r, z, vis in g["loops"]:
            k = next((x for x in rs if abs(x - r) < 0.01), r)
            rs.setdefault(k, []).append((z, vis))
        holes, bosses = {}, {}
        for r, zl in rs.items():
            zs = sorted(set(round(z, 4) for z, _ in zl))
            mids = [(a + b) / 2 for a, b in zip(zs, zs[1:]) if b - a > 0.02]
            if mids:
                solid = any(inside(man, c3 + u * (r - 0.03) + d * zm, d) for zm in mids)
            else:
                # one flat loop (the other end meets a curved face): a pocket or hole has material just outside it
                # on one side of the loop's plane and air just inside on that side; a boss end is the other way round
                sides = [inside(man, c3 + u * (r + 0.03) + d * (zs[0] + e), d) and not inside(man, c3 + u * (r - 0.03) + d * (zs[0] + e), d)
                         for e in (-0.05, 0.05)]
                solid = not any(sides)
            (bosses if solid else holes)[r] = zl
        for r, zl in bosses.items():
            out.append({"c": g["c"], "kind": "boss", "d": 2 * r, "visible": any(vis for _, vis in zl), "far": False})
        if holes:
            r0 = min(holes)
            rim = intervals(man, c3 + u * (r0 + 0.05), d)
            cen = intervals(man, c3, d)
            far = bool(rim) and any(x - 0.01 <= rim[0][0] + 0.01 < y for x, y in cen)
            out += classify(man, g["c"], holes, d, u, v, -1 if far else 1)
    return out


def inside(man, P, d, far=1e4):
    """point-in-solid by ray parity"""
    P = np.asarray(P, float)
    return len(man.ray_cast(P.tolist(), (P + d * far).tolist())) % 2 == 1


def intervals(man, P, dirv, big=1e4):
    """material along a line through P: [(enter, exit)] as distances along dirv from P"""
    o = np.asarray(P, float) - dirv * big
    t = sorted(h.distance * 2 * big - big for h in man.ray_cast(o.tolist(), (o + dirv * 2 * big).tolist()))
    return [(t[i], t[i + 1]) for i in range(0, len(t) - 1, 2)]


def classify(man, c, holes, d, u, v, sign):
    """hole radii of one concentric group -> one hole with counterbore / countersink; sign -1 = it opens on the far side.
    Depth comes from the material along the axis: around the rim against at the centre."""
    rs = {r: [(sign * z, vis) for z, vis in zl] for r, zl in holes.items()}
    radii = sorted(rs, reverse=True)
    inner = radii[-1]
    c3 = u * c[0] + v * c[1]
    dd = d * sign
    rim = []
    for e in (u, v, -u, -v):
        iv = intervals(man, c3 + e * (inner + 0.05), dd)
        if iv:
            rim.append(iv)
    cen = intervals(man, c3, dd)
    item = {"c": c, "visible": any(vis for r in radii for _, vis in rs[r]), "d": 2 * inner, "far": sign < 0, "kind": "hole"}
    if not rim:
        item["depth"] = None
        return [item]
    first = min(rim, key=lambda iv: iv[0][0])[0]
    a, b = first
    floor = min([x for x, y in cen if a - 0.01 <= x < b] + [b])
    item["top"] = a
    item["depth"] = None if floor >= b - 0.02 else round(floor - a, 3)
    if len(radii) >= 2:
        R = radii[0]
        zr = sorted(z for z, _ in rs[R])
        zn = sorted(z for z, _ in rs[radii[1]])
        if len(zr) >= 2 and abs(zr[-1] - zn[0]) < 0.05:
            item["cbore"] = (2 * R, round(zr[-1] - zr[0], 3))
        elif len(zr) == 1 and zn and zn[0] > zr[0] + 0.01:
            ang = 2 * math.degrees(math.atan2(R - radii[1], zn[0] - zr[0]))
            item["csink"] = (2 * R, round(ang))
    return [item]


def nice(x):
    """a measured size as it would be written: faceting leaves e.g. 3.41 for a 3.4 hole"""
    r1 = round(x, 1)
    return r1 if abs(x - r1) < 0.016 else round(x, 2)


def fmt(x):
    s = ("%.2f" % nice(x)).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def limits_text(size, cls, fits):
    rows = fits.get(cls)
    if not rows:
        return None
    for a, b, up, lo in rows:
        if a < size <= b:
            f = lambda x: "0" if x == 0 else "%+.3f" % (x / 1000.0)
            return "(%s/%s)" % (f(up), f(lo))
    return None


def callout(h, n, rule, fits):
    t = callout_core(h, n, rule, fits)
    return t + (" FAR SIDE" if h.get("far") and h.get("depth") is not None else "")


def callout_core(h, n, rule, fits):
    pre = "%d× " % n if n > 1 else ""
    dia = "Ø%s" % fmt(h["d"])
    if h["kind"] == "boss":
        if rule and FIT_RE.match(rule):
            lt = limits_text(h["d"], rule, fits)
            return pre + "%s %s%s" % (dia, rule, " " + lt if lt else "")
        return pre + (rule or dia)
    depth = "THRU" if h.get("depth") is None else "↧%s" % fmt(h["depth"])
    if rule and FIT_RE.match(rule):
        lt = limits_text(h["d"], rule, fits)
        base = "%s %s%s %s" % (dia, rule, " " + lt if lt else "", depth)
    elif rule:
        base = "%s (%s %s)" % (rule, dia, depth)
    else:
        base = "%s %s" % (dia, depth)
    if h.get("cbore"):
        base += "  ⌴Ø%s ↧%s" % (fmt(h["cbore"][0]), fmt(h["cbore"][1]))
    if h.get("csink"):
        base += "  ⌵Ø%s×%d°" % (fmt(h["csink"][0]), h["csink"][1])
    return pre + base


# ------------------------------------------------------------------ sheet primitives
class Sheet:
    def __init__(self):
        self.p = []

    def line(self, pts, kind="vis"):
        pts = [tuple(map(float, q)) for q in pts]
        if len(pts) >= 2:
            self.p.append(("line", pts, kind))

    def circle(self, c, r, kind="vis"):
        self.p.append(("circle", (float(c[0]), float(c[1])), float(r), kind))

    def text(self, x, y, s, h=TXT, rot=0, ha="left", va="bottom", kind="text"):
        self.p.append(("text", float(x), float(y), s, h, rot, ha, va, kind))

    def arrow(self, tip, direction, L=3.0, W=0.55):
        t = np.asarray(tip, float)
        dd = unit(direction)
        nn = np.array([-dd[1], dd[0]])
        b = t - dd * L
        self.p.append(("fill", [tuple(t), tuple(b + nn * W), tuple(b - nn * W)]))

    def hatch(self, polys, spacing=2.5, ang=45.0):
        """45 degree hatch lines clipped to polygons (even-odd)"""
        if not polys:
            return
        ca, sa = math.cos(math.radians(-ang)), math.sin(math.radians(-ang))
        R = np.array([[ca, -sa], [sa, ca]])
        rp = [np.asarray(p) @ R.T for p in polys]
        ys = np.concatenate([p[:, 1] for p in rp])
        Ri = R.T
        y = math.floor(ys.min() / spacing) * spacing + spacing / 2
        while y < ys.max():
            xs = []
            for p in rp:
                q = np.roll(p, -1, axis=0)
                for (x1, y1), (x2, y2) in zip(p, q):
                    if (y1 <= y < y2) or (y2 <= y < y1):
                        xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
            xs.sort()
            for a, b in zip(xs[0::2], xs[1::2]):
                self.line([np.array([a, y]) @ Ri.T, np.array([b, y]) @ Ri.T], "thin")
            y += spacing


_TP = {}


def text_runs(s, h):
    """split text into font runs and the two symbols drawn as lines (counterbore, countersink)"""
    if "tp" not in _TP:
        from matplotlib.textpath import TextToPath
        from matplotlib.font_manager import FontProperties
        _TP["tp"], _TP["fp"] = TextToPath(), FontProperties(family="DejaVu Sans")
    em = h / 0.73
    fp = _TP["fp"].copy()
    fp.set_size(em)
    out, x = [], 0.0
    for part in re.split(r"([⌴⌵])", s):
        if not part:
            continue
        if part in "⌴⌵":
            out.append(("sym", part, x))
            x += 0.95 * h
        else:
            w = _TP["tp"].get_text_width_height_descent(part, fp, ismath=False)[0]
            out.append(("str", part, x))
            x += w
    return out, x


def sym_lines(kind, x, y, h):
    w = 0.8 * h
    if kind == "⌴":
        return [[(x, y + h), (x, y), (x + w, y), (x + w, y + h)]]
    return [[(x, y + h), (x + w / 2, y), (x + w, y + h)]]


def text_width(s, h):
    return text_runs(s, h)[1]


# ------------------------------------------------------------------ dimensions
def dim_linear(sh, p1, p2, off, value, horiz, extra=""):
    """dimension between sheet points p1, p2 measured along x (horiz) or y, dimension line at offset `off` (sheet coord)"""
    (x1, y1), (x2, y2) = p1, p2
    if horiz:
        a, b = (min(x1, x2), max(x1, x2))
        ya, yb = (y1, y2) if x1 <= x2 else (y2, y1)
        g = 1.0 if off > max(y1, y2) else -1.0
        sh.line([(a, ya + g * 1.0), (a, off + g * 2)], "thin")
        sh.line([(b, yb + g * 1.0), (b, off + g * 2)], "thin")
        sh.line([(a, off), (b, off)], "thin")
        txt = fmt(value) + extra
        tw = text_width(txt, TXT)
        if b - a > 8:
            sh.arrow((a, off), (-1, 0))
            sh.arrow((b, off), (1, 0))
        else:
            sh.line([(a - 6, off), (a, off)], "thin")
            sh.line([(b, off), (b + 6, off)], "thin")
            sh.arrow((a, off), (1, 0))
            sh.arrow((b, off), (-1, 0))
        sh.text((a + b) / 2 - tw / 2, off + 0.8, txt)
    else:
        a, b = (min(y1, y2), max(y1, y2))
        xa, xb = (x1, x2) if y1 <= y2 else (x2, x1)
        g = 1.0 if off > max(x1, x2) else -1.0
        sh.line([(xa + g * 1.0, a), (off + g * 2, a)], "thin")
        sh.line([(xb + g * 1.0, b), (off + g * 2, b)], "thin")
        sh.line([(off, a), (off, b)], "thin")
        txt = fmt(value) + extra
        tw = text_width(txt, TXT)
        if b - a > 8:
            sh.arrow((off, a), (0, -1))
            sh.arrow((off, b), (0, 1))
        else:
            sh.line([(off, a - 6), (off, a)], "thin")
            sh.line([(off, b), (off, b + 6)], "thin")
            sh.arrow((off, a), (0, 1))
            sh.arrow((off, b), (0, -1))
        sh.text(off - 0.8, (a + b) / 2 - tw / 2, txt, rot=90)


def ordinate(sh, origin, items, along_x, edge, base):
    """coordinate dimensioning (ISO 129-1): extension lines from the view edge to a baseline, model values beyond it.
    Crowded values get their labels spread apart with a short jog. items: [(paper offset, model value)]"""
    ox, oy = origin
    seen, pts = set(), []
    for off, val in sorted([(0.0, 0.0)] + list(items)):
        k = round(val, 2)
        if k in seen:
            continue
        seen.add(k)
        pts.append((off, val))
    gap = TXT * 1.25
    want = [o for o, _ in pts]
    pos = list(want)
    for _ in range(50):                      # spread labels to at least `gap` apart, staying near their lines
        moved = False
        for i in range(1, len(pos)):
            if pos[i] - pos[i - 1] < gap:
                push = (gap - (pos[i] - pos[i - 1])) / 2
                pos[i - 1] -= push
                pos[i] += push
                moved = True
        if not moved:
            break
    jog = 3.0 if any(abs(a - b) > 0.05 for a, b in zip(pos, want)) else 0.0
    for (off, val), lp in zip(pts, pos):
        t = fmt(val)
        tw = text_width(t, TXT)
        if along_x:
            x, lx = ox + off, ox + lp
            sh.line([(x, edge - 1), (x, base), (lx, base - jog), (lx, base - jog - 1.5)], "thin")
            sh.text(lx + TXT / 2 - 0.3, base - jog - 3 - tw, t, rot=90)
        else:
            y, ly = oy + off, oy + lp
            sh.line([(edge - 1, y), (base, y), (base - jog, ly), (base - jog - 1.5, ly)], "thin")
            sh.text(base - jog - 3 - tw, ly - TXT / 2 + 0.2, t)
    if along_x:
        sh.circle((ox, edge - 3.5), 0.9, "thin")
    else:
        sh.circle((edge - 3.5, oy), 0.9, "thin")


def ordinate_room(vals, s):
    """paper room the coordinate labels need at scale s (a second, staggered level when values crowd)"""
    if not vals:
        return 0.0
    vs = sorted(set([0.0] + [round(v, 2) for v in vals]))
    w = max(text_width(fmt(v), TXT) for v in vs)
    crowded = any((b - a) * s < TXT * 1.25 for a, b in zip(vs, vs[1:]))
    return w + 10 + (3 if crowded else 0)


def levels(pv, maxn=10):
    """u and v positions (from the view's lower-left) of straight visible edges square to the sheet axes"""
    us, vs = set(), set()
    for pts, closed in pv["vis"]:
        q = np.stack([pts @ pv["u"], pts @ pv["v"]], 1) - pv["lo2"]
        rng = q.max(0) - q.min(0)
        if rng[1] < 1e-3 and rng[0] > 0.5:
            vs.add(round(float(q[0, 1]), 2))
            continue
        if rng[0] < 1e-3 and rng[1] > 0.5:
            us.add(round(float(q[0, 0]), 2))
            continue
        for a, b in zip(q, q[1:]):
            if abs(a[1] - b[1]) < 1e-3 and abs(a[0] - b[0]) > 0.5:
                vs.add(round(float(a[1]), 2))
            elif abs(a[0] - b[0]) < 1e-3 and abs(a[1] - b[1]) > 0.5:
                us.add(round(float(a[0]), 2))
    span = pv["hi2"] - pv["lo2"]
    us |= {0.0, round(float(span[0]), 2)}
    vs |= {0.0, round(float(span[1]), 2)}
    return (sorted(us) if len(us) <= maxn else [0.0, round(float(span[0]), 2)]), (sorted(vs) if len(vs) <= maxn else [0.0, round(float(span[1]), 2)])


# ------------------------------------------------------------------ one sheet
def plan_part(p, opts, rows, fits, flat=None):
    import manifold3d as M
    man = p["man"]
    if p.get("bends"):
        # fold() joins its bend slices with hair-thin overlaps; tidy them so they don't draw as extra lines.
        # Formed views only carry overall sizes; the flat pattern (exact) carries the cutting dimensions.
        man = man.simplify(0.025)
    names = [x.strip() for x in opts.get("views", "front,top,left").split(",") if x.strip() in VIEWS] or ["front", "top", "left"]
    V0 = np.asarray(man.to_mesh().vert_properties)[:, :3]
    lo, hi = V0.min(0), V0.max(0)
    views = {}
    sl = 0.0
    for n in names:
        d, u, v = basis(n)
        pv = project_view(man, d, u, v, sliver=sl)
        pts = np.concatenate([V0 @ u[:, None], V0 @ v[:, None]], 1)
        pv.update(name=n, d=d, u=u, v=v, lo2=pts.min(0), hi2=pts.max(0), title=NAMES[n])
        views[n] = pv
    if "views" not in opts:
        sigs = []
        for n in list(names):
            pv = views[n]
            sig = frozenset((round(float(a), 1), round(float(b), 1)) for pts, _ in pv["vis"] for a, b in
                            zip(pts @ pv["u"] - pv["lo2"][0], pts @ pv["v"] - pv["lo2"][1]))
            if any(sig == q for q in sigs) and n != "front":
                names.remove(n)
                del views[n]
            else:
                sigs.append(sig)
    sec = None
    if opts.get("section"):
        m = re.match(r"^\s*([xyz])\s*=\s*(-?[0-9.]+)\s*$", opts["section"])
        if m:
            ax, c = m.group(1), float(m.group(2))
            dname = {"x": "left", "y": "front", "z": "top"}[ax]
            d, u, v = basis(dname)
            k = "xyz".index(ax)
            off = c * d[k]
            part = man.trim_by_plane(d.tolist(), float(off))
            if not part.is_empty():
                T = np.zeros((3, 4))
                T[0, :3], T[1, :3], T[2, :3] = u, v, d
                T[2, 3] = -off
                cs = man.transform(T.tolist()).slice(0.0)
                polys = [np.asarray(q) for q in cs.to_polygons()]
                pv = project_view(part, d, u, v, hidden=False)
                V1 = np.asarray(part.to_mesh().vert_properties)[:, :3]
                pts = np.concatenate([V1 @ u[:, None], V1 @ v[:, None]], 1)
                host = "top" if ax in "xy" else "front"
                pv.update(name="section", d=d, u=u, v=v, lo2=pts.min(0), hi2=pts.max(0), title="SECTION A–A", polys=polys,
                          plane=(ax, c), host=host if host in views else None)
                sec = pv
    iso = None
    if opts.get("iso", "yes") != "no":
        d, u, v = basis((-1, 1, -1))
        pv = project_view(man, d, u, v, hidden=False, sliver=sl)
        pts = np.concatenate([V0 @ u[:, None], V0 @ v[:, None]], 1)
        pv.update(name="iso", d=d, u=u, v=v, lo2=pts.min(0), hi2=pts.max(0), title="ISOMETRIC")
        iso = pv
    fl = None
    if flat is not None:
        fm = M.Manifold(M.Mesh(vert_properties=flat[0].astype(np.float32), tri_verts=flat[1].astype(np.uint32)))
        if not fm.is_empty():
            d, u, v = basis("top")
            pv = project_view(fm, d, u, v, hidden=False)
            Vf = np.asarray(fm.to_mesh().vert_properties)[:, :3]
            pts = np.concatenate([Vf @ u[:, None], Vf @ v[:, None]], 1)
            pv.update(name="flat", d=d, u=u, v=v, lo2=pts.min(0), hi2=pts.max(0), title="FLAT PATTERN")
            pv["holes"] = holes_in_view(fm, pv, d, u, v, None)
            fl = pv
    # holes: each concentric group gets its callout in the first view it is seen end-on (visible preferred)
    seen = []
    for n in names:
        pv = views[n]
        hs = holes_in_view(man, pv, pv["d"], pv["u"], pv["v"], None)
        pv["holes"] = []
        for h in hs:
            c3 = pv["u"] * h["c"][0] + pv["v"] * h["c"][1]
            axis = pv["d"]
            dup = False
            for (q3, ax2, d2) in seen:
                if abs(abs(np.dot(axis, ax2)) - 1) < 1e-6 and np.linalg.norm(np.cross(c3 - q3, axis)) < 0.05 and abs(d2 - h["d"]) < 0.02:
                    dup = True
            if dup:
                continue
            seen.append((c3, axis, h["d"]))
            pv["holes"].append(h)
    return {"views": views, "names": names, "sec": sec, "iso": iso, "flat": fl, "lo": lo, "hi": hi}


def margins(pv, nd_h=0, nd_v=0, callouts=0, cw=0.0):
    return {"l": 10 + 9 * nd_v, "b": 10 + 9 * nd_h, "t": 9, "r": 8 + (cw + 14 if callouts else 0)}


def draw_sheet(p, plan, opts, rows, fits, meta):
    views, names = plan["views"], plan["names"]
    # what each view carries
    ext_axis = {}
    for n in names:
        for k, vec in (("u", views[n]["u"]), ("v", views[n]["v"])):
            ax = int(np.argmax(np.abs(vec)))
            ext_axis.setdefault(ax, (n, k))
    rules = {}
    for r in rows:
        if len(r) >= 4 and r[0] == "hole" and r[1] == p["id"] and isinstance(r[2], (int, float)):
            rules.setdefault(float(r[2]), str(r[3]))
    decl = [r for r in rows if len(r) >= 5 and r[0] == "dim" and r[1] == p["id"] and r[2] in views]
    info = {}
    pvs = dict(views)
    if plan["flat"] is not None:
        pvs["flat"] = plan["flat"]
    for n in list(pvs):
        pv = pvs[n]
        hs = pv["holes"]
        groups = []
        for h in hs:
            rr = lambda t: tuple(nice(x) for x in t) if t else None
            sig = (h["kind"], nice(h["d"]), nice(h["depth"]) if h.get("depth") is not None else None, rr(h.get("cbore")), rr(h.get("csink")), h.get("far"))
            for g in groups:
                if g["sig"] == sig:
                    g["items"].append(h)
                    break
            else:
                groups.append({"sig": sig, "items": [h]})
        for g in groups:
            h = g["items"][0]
            rule = next((t for dd, t in rules.items() if abs(dd - h["d"]) < 0.03), None)
            g["text"] = callout(h, len(g["items"]), rule, fits)
        hdim = [k for (ax, (vn, k)) in ext_axis.items() if vn == n and k == "u"] or (["u"] if n == "flat" else [])
        vdim = [k for (ax, (vn, k)) in ext_axis.items() if vn == n and k == "v"] or (["v"] if n == "flat" else [])
        hx = [h for h in hs if h["kind"] == "hole"]
        has_hx = bool(hx)
        lu, lv = levels(pv, maxn=2 if (p.get("bends") and n != "flat") else 10)
        if n == "flat":
            for bd in meta.get("bends") or []:
                if len(bd) >= 8 and abs(bd[1] - bd[3]) < 1e-6:
                    lu = sorted(set(lu) | {round(bd[1] - pv["lo2"][0], 2)})
                elif len(bd) >= 8 and abs(bd[2] - bd[4]) < 1e-6:
                    lv = sorted(set(lv) | {round(bd[2] - pv["lo2"][1], 2)})
        formed = bool(p.get("bends")) and n != "flat"
        hpos = [] if formed else hx
        ox = sorted(set([round(h["c"][0] - pv["lo2"][0], 2) for h in hpos] + (lu if (hdim or hpos) else [])))
        oy = sorted(set([round(h["c"][1] - pv["lo2"][1], 2) for h in hpos] + (lv if (vdim or hpos) else [])))
        # a coordinate chain with more than the two outer edges replaces the overall size on that axis
        if len(ox) <= 2 and not hpos:
            ox = []
        if len(oy) <= 2 and not hpos:
            oy = []
        if formed:
            pv["title"] = pv["title"] + " (FORMED, REFERENCE)"
        nh = (1 if hdim and not ox else 0)
        nv = (1 if vdim and not oy else 0)
        dh = [r for r in decl if r[2] == n and (len(r) < 6 or r[5] != "v")]
        dv = [r for r in decl if r[2] == n and len(r) >= 6 and r[5] == "v"]
        cw = max([text_width(g["text"], TXT) for g in groups] + [0])
        info[n] = {"groups": groups, "hdim": bool(hdim) and not ox, "vdim": bool(vdim) and not oy, "holes": has_hx, "nh": nh, "nv": nv,
                   "dh": dh, "dv": dv, "cw": cw, "ox": ox, "oy": oy}
    # sizes on paper per scale
    def boxes(s):
        out = {}
        for n in names:
            pv, I = views[n], info[n]
            w, h = (pv["hi2"] - pv["lo2"]) * s
            out[n] = (w, h, {"l": 8 + 9 * I["nv"] + ordinate_room(I["oy"], s), "b": 8 + 9 * I["nh"] + ordinate_room(I["ox"], s), "t": 7 + 9 * len(I["dh"]),
                             "r": 8 + 9 * len(I["dv"]) + (I["cw"] + 16 if I["groups"] else 0)})
        if "flat" in info:
            pv, I = pvs["flat"], info["flat"]
            w, h = (pv["hi2"] - pv["lo2"]) * s
            out["flat"] = (w, h, {"l": 8 + 9 * I["nv"] + ordinate_room(I["oy"], s), "b": 8 + 9 * I["nh"] + ordinate_room(I["ox"], s), "t": 7,
                                  "r": 8 + (I["cw"] + 16 if I["groups"] else 0) + 22})
        for key in ("sec", "iso"):
            pv = plan[key]
            if pv is not None:
                w, h = (pv["hi2"] - pv["lo2"]) * s * (0.6 if key == "iso" else 1.0)
                out[key] = (w, h, {"l": 8, "b": 8, "t": 9, "r": 8})
        return out

    def layout(s, W, H):
        bx = boxes(s)
        cols, rws = {}, {}
        for n in names:
            c, r = GRID[n]
            w, h, m = bx[n]
            cols[c] = max(cols.get(c, 0), w + m["l"] + m["r"])
            rws[r] = max(rws.get(r, 0), h + m["t"] + m["b"])
        extra = [k for k in ("sec", "flat", "iso") if k in bx]
        free_c = max(cols) + 1
        aw, ah = W - 30, H - 20 - TB_H - 4
        gw, gh = sum(cols.values()), sum(rws.values())
        ew = [bx[k][0] + bx[k][2]["l"] + bx[k][2]["r"] for k in extra]
        eh = [bx[k][1] + bx[k][2]["t"] + bx[k][2]["b"] for k in extra]
        right = (gw + (max(ew) if extra else 0), max(gh, sum(eh)))
        below = (max(gw, sum(ew)), gh + (max(eh) if extra else 0))
        if os.environ.get("DRAWDEBUG"):
            print("layout s=%g %gx%g grid %.0fx%.0f right %.0fx%.0f below %.0fx%.0f avail %.0fx%.0f" % (s, W, H, gw, gh, right[0], right[1], below[0], below[1], aw, ah), {k: (round(v[0]), round(v[1]), {q: round(z) for q, z in v[2].items()}) for k, v in bx.items()})
        if right[0] <= aw and right[1] <= ah:
            return True, bx, cols, rws, extra, "right"
        if below[0] <= aw and below[1] <= ah:
            return True, bx, cols, rws, extra, "below"
        return False, bx, cols, rws, extra, "right"

    want_sheet = (opts.get("sheet") or "").upper()
    best = {}
    for nm, W, H in SHEETS:
        if want_sheet and nm != want_sheet:
            continue
        for a, b in SCALES:
            if a / b > 1 and not opts.get("enlarge", "yes") != "no":
                pass
            ok, *rest = layout(a / b, W, H)
            if ok:
                best[nm] = (nm, W, H, a, b, a / b, rest)
                break
    choice = None
    if want_sheet and want_sheet in best:
        choice = best[want_sheet]
    elif "A4" in best and (best["A4"][5] >= 1 or "A3" not in best or best["A3"][5] < 2 * best["A4"][5]):
        choice = best["A4"]
    else:
        for nm, W, H in SHEETS[1:]:
            if nm in best:
                choice = best[nm]
                break
    if not choice:
        nm, W, H = SHEETS[-1]
        a, b = SCALES[-1]
        choice = (nm, W, H, a, b, a / b, layout(a / b, W, H)[1:])
    nm, W, H, a, b, s, (bx, cols, rws, extra, where_) = choice
    sh = Sheet()
    # frame
    sh.line([(20, 10), (W - 10, 10), (W - 10, H - 10), (20, H - 10), (20, 10)], "frame")
    sh.line([(0, 0), (W, 0), (W, H), (0, H), (0, 0)], "thin")
    top = H - 10
    x0 = 20
    colx, x = {}, x0
    for c in sorted(cols):
        colx[c] = x
        x += cols[c]
    rowy, y = {}, top
    for r in sorted(rws):
        rowy[r] = y
        y -= rws[r]
    placed = {}
    for n in names:
        c, r = GRID[n]
        w, h, m = bx[n]
        # align: same column -> same left of geometry; same row -> same top of geometry
        lx = colx[c] + max((bx[k][2]["l"] for k in names if GRID[k][0] == c), default=m["l"])
        ty = rowy[r] - max((bx[k][2]["t"] for k in names if GRID[k][1] == r), default=m["t"])
        placed[n] = (lx, ty - h)
    if where_ == "right":
        ex_x, ey = x, top
        for k in extra:
            w, h, m = bx[k]
            placed[k] = (ex_x + m["l"], ey - m["t"] - h)
            ey -= h + m["t"] + m["b"]
    else:
        ex_x, ey = x0, y
        for k in extra:
            w, h, m = bx[k]
            placed[k] = (ex_x + m["l"], ey - m["t"] - h)
            ex_x += w + m["l"] + m["r"]

    def to2(pv, P, sc, org):
        q = np.stack([P @ pv["u"], P @ pv["v"]], -1) if P.ndim > 1 else np.array([P @ pv["u"], P @ pv["v"]])
        return (q - pv["lo2"]) * sc + np.asarray(org)

    def draw_edges(pv, sc, org, hidden=True):
        circles = []
        for flag in (("hid", "vis") if hidden else ("vis",)):
            for pts, closed in pv[flag]:
                q = to2(pv, pts, sc, org)
                fc = fit_circle2d(np.stack([pts @ pv["u"], pts @ pv["v"]], 1), pts @ pv["d"]) if closed else None
                if fc is not None:
                    cc = (fc[0] - pv["lo2"]) * sc + np.asarray(org)
                    sh.circle(cc, fc[1] * sc, flag)
                    circles.append((cc, fc[1] * sc))
                else:
                    sh.line(q, flag)
        return circles

    def draw_view(n):
        pv, I = pvs[n], info[n]
        org = placed[n]
        circ = draw_edges(pv, s, org, hidden=(n != "flat"))
        w, h, m = bx[n]
        sh.text(org[0], org[1] + h + 2.5, pv["title"], SMALL, kind="label")
        # centre marks on holes and bosses
        for g in I["groups"]:
            for it in g["items"]:
                cc = (it["c"] - pv["lo2"]) * s + np.asarray(org)
                rr = it["d"] / 2 * s + 2
                sh.line([(cc[0] - rr, cc[1]), (cc[0] + rr, cc[1])], "center")
                sh.line([(cc[0], cc[1] - rr), (cc[0], cc[1] + rr)], "center")
        # hole positions, then overall sizes beyond them
        if I["ox"]:
            ordinate(sh, org, [(x * s, x) for x in I["ox"]], True, org[1], org[1] - 6)
        if I["oy"]:
            ordinate(sh, org, [(y * s, y) for y in I["oy"]], False, org[0], org[0] - 6)
        if I["hdim"]:
            dim_linear(sh, (org[0], org[1]), (org[0] + w, org[1]), org[1] - 8 - ordinate_room(I["ox"], s), w / s, True)
        if I["vdim"]:
            dim_linear(sh, (org[0], org[1]), (org[0], org[1] + h), org[0] - 8 - ordinate_room(I["oy"], s), h / s, False)
        for i, r in enumerate(I["dh"]):
            P1, P2 = to2(pv, np.array(r[3], float), s, org), to2(pv, np.array(r[4], float), s, org)
            val = abs(np.dot(np.array(r[4], float) - np.array(r[3], float), pv["u"]))
            dim_linear(sh, P1, P2, org[1] + h + 6 + 9 * i, val, True, dim_extra(val, r, fits))
        for i, r in enumerate(I["dv"]):
            P1, P2 = to2(pv, np.array(r[3], float), s, org), to2(pv, np.array(r[4], float), s, org)
            val = abs(np.dot(np.array(r[4], float) - np.array(r[3], float), pv["v"]))
            dim_linear(sh, P1, P2, org[0] + w + 6 + 9 * i, val, False, dim_extra(val, r, fits))
        # callouts: a column to the right, leaders to one hole of each group
        cx = org[0] + w + 8 + 9 * len(I["dv"]) + 6
        cy = org[1] + h - 2
        for g in sorted(I["groups"], key=lambda g: -max(it["c"][1] for it in g["items"])):
            it = max(g["items"], key=lambda it: it["c"][1] * 0.5 + it["c"][0])
            cc = (it["c"] - pv["lo2"]) * s + np.asarray(org)
            rr = it["d"] / 2 * s
            pt = cc + np.array([rr, rr]) * 0.7071
            sh.line([pt, (cx - 2, cy + 1.2), (cx, cy + 1.2)], "thin")
            sh.arrow(pt, pt - np.array([cx - 2, cy + 1.2]), 2.5, 0.45)
            sh.text(cx + 0.8, cy, g["text"])
            cy -= TXT + 4

    for n in names + (["flat"] if "flat" in info else []):
        draw_view(n)
    sec = plan["sec"]
    if sec is not None:
        org = placed["sec"]
        draw_edges(sec, s, org, hidden=False)
        polys = [(np.asarray(pp) - sec["lo2"]) * s + np.asarray(org) for pp in sec["polys"]]
        sh.hatch(polys, 2.5)
        for pp in polys:
            sh.line(list(pp) + [pp[0]], "vis")
        w, h, m = bx["sec"]
        sh.text(org[0], org[1] + h + 2.5, "SECTION A–A", SMALL, kind="label")
        host = sec.get("host")
        if host:
            hv, ho = views[host], placed[host]
            ax, c = sec["plane"]
            k = "xyz".index(ax)
            P = np.zeros(3)
            P[k] = c
            hw_, hh_, _ = bx[host]
            q = to2(hv, P, s, ho)
            along_u = abs(hv["u"][k]) < 0.5
            if along_u:
                a1, a2 = (ho[0] - 4, q[1]), (ho[0] + hw_ + 4, q[1])
            else:
                a1, a2 = (q[0], ho[1] - 4), (q[0], ho[1] + hh_ + 4)
            sh.line([a1, a2], "center")
            dd = np.array([np.dot(sec["d"], hv["u"]), np.dot(sec["d"], hv["v"])])
            for e in (a1, a2):
                e = np.asarray(e)
                sh.line([e, e + dd * 6], "vis")
                sh.arrow(e + dd * 6, dd, 2.5, 0.5)
                sh.text(e[0] + dd[0] * 7 + 0.5, e[1] + dd[1] * 7 - 1.5, "A", TXT)
    iso = plan["iso"]
    if iso is not None:
        org = placed["iso"]
        draw_edges(iso, s * 0.6, org, hidden=False)
        w, h, m = bx["iso"]
        sh.text(org[0], org[1] + h + 2.5, "ISOMETRIC (reduced, not to scale)", SMALL, kind="label")
    fl = plan["flat"]
    if fl is not None:
        org = placed["flat"]
        for i, bd in enumerate(meta.get("bends") or []):
            if len(bd) < 8:
                continue
            P1 = (np.array([bd[1], bd[2]]) - fl["lo2"]) * s + np.asarray(org)
            P2 = (np.array([bd[3], bd[4]]) - fl["lo2"]) * s + np.asarray(org)
            sh.line([P1, P2], "center")
            if P2[0] < P1[0] or (abs(P2[0] - P1[0]) < 1e-6 and P2[1] < P1[1]):
                P1, P2 = P2, P1
            L = P2 - P1
            q = P1 + unit(L) * 2 if np.linalg.norm(L) > 0 else P1
            sh.text(q[0], q[1] + 0.8, "BEND %d: %s %g° R%s" % (i + 1, "UP" if bd[5] >= 0 else "DOWN", abs(bd[5]), fmt(bd[6])), SMALL,
                    rot=math.degrees(math.atan2(L[1], L[0])) if abs(L[1]) > abs(L[0]) else 0)
    title_block(sh, W, H, p, opts, meta, nm, a, b)
    sh.callouts = [(pvs[n]["title"].split(" (")[0], g["text"]) for n in pvs for g in info[n]["groups"]]
    sh.dims = [(r[2], r[5] if len(r) > 5 else "h", dim_extra(0, r, fits).strip()) for r in decl]
    return sh, (nm, W, H, a, b)


def dim_extra(val, r, fits):
    if len(r) >= 7 and r[6]:
        t = str(r[6])
        if FIT_RE.match(t):
            lt = limits_text(val, t, fits)
            return " %s%s" % (t, " " + lt if lt else "")
        return " " + t
    return ""


def proj_symbol(sh, x, y, s=1.0):
    """ISO 5456-2 first-angle symbol: truncated cone, its end view to the right"""
    h1, h2, L = 5 * s, 9 * s, 11 * s
    cy = y
    sh.line([(x, cy - h1 / 2), (x + L, cy - h2 / 2), (x + L, cy + h2 / 2), (x, cy + h1 / 2), (x, cy - h1 / 2)], "vis")
    sh.line([(x - 2 * s, cy), (x + L + 2 * s, cy)], "center")
    cx = x + L + 5 * s + h2 / 2
    sh.circle((cx, cy), h2 / 2, "vis")
    sh.circle((cx, cy), h1 / 2, "vis")
    sh.line([(cx - h2 / 2 - 2 * s, cy), (cx + h2 / 2 + 2 * s, cy)], "center")
    sh.line([(cx, cy - h2 / 2 - 2 * s), (cx, cy + h2 / 2 + 2 * s)], "center")


def title_block(sh, W, H, p, opts, meta, size, a, b):
    x1, y1 = W - 10 - TB_W, 10
    x2, y2 = W - 10, 10 + TB_H
    sh.line([(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)], "vis")
    rows = [y1 + 11, y1 + 22, y1 + 33]
    for yy in rows:
        sh.line([(x1, yy), (x2, yy)], "thin")
    for xx, ya, yb in ((x1 + 60, y1, y1 + 33), (x1 + 120, y1, y1 + 33), (x1 + 150, y1, y1 + 22)):
        sh.line([(xx, ya), (xx, yb)], "thin")

    def field(x, y, label, value, h=TXT):
        sh.text(x + 1.5, y + 7.2, label, 1.8, kind="label")
        sh.text(x + 1.5, y + 1.8, value, h)
    field(x1, rows[2], "TITLE", p["label"][:60], 5)
    field(x1, rows[1], "DRAWING NUMBER", meta["number"][:28])
    field(x1 + 60, rows[1], "REVISION", meta["rev"])
    field(x1 + 120, rows[1], "DATE", meta["date"])
    field(x1 + 150, rows[1], "SHEET", "1/1")
    field(x1, rows[0], "MATERIAL", (opts.get("mat") or p["tags"].get("mat") or "-")[:30], 3)
    field(x1 + 60, rows[0], "FINISH", (opts.get("finish") or "-")[:30], 3)
    field(x1 + 120, rows[0], "QTY", str(opts.get("qty") or p.get("qty", 1)))
    field(x1 + 150, rows[0], "SIZE / SCALE", "%s  %d:%d" % (size, a, b), 3)
    field(x1, y1, "GENERAL TOLERANCES", opts.get("tol", "ISO 2768-mK"), 3)
    field(x1 + 60, y1, "UNITS", "mm", 3)
    field(x1 + 120, y1, "PROJECTION", "", 3)
    proj_symbol(sh, x1 + 124, y1 + 4.2, 0.55)
    # notes to the left of the title block
    notes = ["Dimensions in mm. Do not scale the drawing.",
             "General tolerances %s unless stated." % opts.get("tol", "ISO 2768-mK"),
             "Break sharp edges 0.2-0.5 mm. Remove burrs."]
    if opts.get("ra"):
        notes.append("Surface roughness Ra %s µm unless stated." % opts["ra"])
    if p.get("bends"):
        notes.append("Bend allowance from K-factor %g; check against your bending tools." % meta.get("kf", 0.4))
    notes += [n.strip() for n in str(opts.get("notes", "")).split(";") if n.strip()]
    ny = y2 - 3
    sh.text(20 + 4, ny, "NOTES", SMALL, kind="label", va="top")
    ny -= 5
    room = x1 - 24 - 4
    for i, n in enumerate(notes):
        words, cur, lines = ("%d. %s" % (i + 1, n)).split(), "", []
        for wd in words:
            t = (cur + " " + wd).strip()
            if cur and text_width(t, SMALL) > room:
                lines.append(cur)
                cur = "   " + wd
            else:
                cur = t if not cur.startswith("   ") else cur + " " + wd
        lines.append(cur)
        for ln in lines:
            if ny < 12:
                break
            sh.text(20 + 4, ny, ln, SMALL, va="top")
            ny -= 3.6


# ------------------------------------------------------------------ renderers
STY = {"vis": (W_VIS, "-"), "hid": (W_THIN, (0, (3.0, 1.5))), "center": (W_THIN, (0, (8.0, 1.5, 1.0, 1.5))),
       "thin": (W_THIN, "-"), "frame": (0.7, "-")}


def render_pdf(sheets, path_one, single_paths):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.patches import Circle, Polygon
    matplotlib.rcParams["pdf.fonttype"] = 42
    matplotlib.rcParams["font.family"] = "DejaVu Sans"
    figs = []
    for sh, (nm, W, H, a, b), meta in sheets:
        fig = plt.figure(figsize=(W / 25.4, H / 25.4))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, W)
        ax.set_ylim(0, H)
        ax.axis("off")
        pt = 72 / 25.4
        for q in sh.p:
            if q[0] == "line":
                lw, ls = STY.get(q[2], STY["thin"])
                xs, ys = zip(*q[1])
                ax.plot(xs, ys, color="black", lw=lw * pt, ls=ls, solid_capstyle="butt", dash_capstyle="butt")
            elif q[0] == "circle":
                lw, ls = STY.get(q[3], STY["thin"])
                ax.add_patch(Circle(q[1], q[2], fill=False, lw=lw * pt, ls=ls, ec="black"))
            elif q[0] == "fill":
                ax.add_patch(Polygon(q[1], closed=True, fc="black", ec="black", lw=0.1))
            elif q[0] == "text":
                _, x, y, s, h, rot, ha, va, kind = q
                runs, tw = text_runs(s, h)
                c, sn = math.cos(math.radians(rot)), math.sin(math.radians(rot))
                for kd, part, dx in runs:
                    px, py = x + dx * c, y + dx * sn
                    if va == "top":
                        px, py = px + h * sn, py - h * c
                    if kd == "str":
                        ax.text(px, py, part, fontsize=h / 0.73 * pt, rotation=rot, rotation_mode="anchor", ha="left", va="baseline",
                                color="black")
                    else:
                        for ln in sym_lines(part, 0, 0, h):
                            P = [(px + lx * c - ly * sn, py + lx * sn + ly * c) for lx, ly in ln]
                            xs, ys = zip(*P)
                            ax.plot(xs, ys, color="black", lw=W_THIN * pt)
        figs.append(fig)
    for fig, path in zip(figs, single_paths):
        fig.savefig(path, format="pdf")
        fig.savefig(path[:-4] + "_preview.png", format="png", dpi=80)
    with PdfPages(path_one) as pp:
        for fig in figs:
            pp.savefig(fig)
    for fig in figs:
        plt.close(fig)


def render_dxf(sh, size, path, meta):
    import ezdxf
    nm, W, H, a, b = size
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    lay = {"vis": ("VISIBLE", "CONTINUOUS", 50), "hid": ("HIDDEN", "DASHED", 25), "center": ("CENTER", "CENTER", 25),
           "thin": ("THIN", "CONTINUOUS", 25), "frame": ("FRAME", "CONTINUOUS", 70)}
    for k, (n, lt, lw) in lay.items():
        if n not in doc.layers:
            doc.layers.add(n, linetype=lt if lt in doc.linetypes else "CONTINUOUS", lineweight=lw)
    for n in ("TEXT", "ARROWS"):
        doc.layers.add(n)
    msp = doc.modelspace()
    for q in sh.p:
        if q[0] == "line":
            msp.add_lwpolyline(q[1], dxfattribs={"layer": lay.get(q[2], lay["thin"])[0]})
        elif q[0] == "circle":
            msp.add_circle(q[1], q[2], dxfattribs={"layer": lay.get(q[3], lay["thin"])[0]})
        elif q[0] == "fill":
            msp.add_solid([q[1][0], q[1][1], q[1][2]], dxfattribs={"layer": "ARROWS"})
        elif q[0] == "text":
            _, x, y, s, h, rot, ha, va, kind = q
            runs, tw = text_runs(s, h)
            c, sn = math.cos(math.radians(rot)), math.sin(math.radians(rot))
            for kd, part, dx in runs:
                px, py = x + dx * c, y + dx * sn
                if va == "top":
                    px, py = px + h * sn, py - h * c
                if kd == "str":
                    t = msp.add_text(part, height=h, rotation=rot, dxfattribs={"layer": "TEXT"})
                    t.set_placement((px, py))
                else:
                    for ln in sym_lines(part, 0, 0, h):
                        msp.add_lwpolyline([(px + lx * c - ly * sn, py + lx * sn + ly * c) for lx, ly in ln], dxfattribs={"layer": "TEXT"})
    doc.saveas(path)


def make(parts, rows, opts_by_part, outdir, model, rev, fits, kf=0.4, flats=None):
    """parts: dicts with id, label, tags, qty, man, bends. Returns report lines."""
    out, sheets, singles = [], [], []
    date = datetime.date.today().isoformat()
    for p in parts:
        opts = opts_by_part.get(p["id"], {})
        flat = (flats or {}).get(p["id"])
        plan = plan_part(p, opts, rows, fits, flat)
        meta = {"number": "%s-%s" % (model, p["id"]), "rev": rev, "date": date, "bends": p.get("bends"), "kf": kf}
        sh, size = draw_sheet(p, plan, opts, rows, fits, meta)
        base = os.path.join(outdir, re.sub(r"[^A-Za-z0-9_.-]+", "_", p["label"]).strip("_") or p["id"])
        render_dxf(sh, size, base + ".dxf", meta)
        sheets.append((sh, size, meta))
        singles.append(base + ".pdf")
        nh = sum(len(v["holes"]) for v in plan["views"].values())
        out.append("drawing: %s.pdf + .dxf | %s %d:%d | views %s%s%s | %d hole/boss features" % (
            os.path.basename(base), size[0], size[3], size[4], ", ".join(plan["names"]),
            ", section A-A" if plan["sec"] is not None else "", ", flat pattern" if plan["flat"] is not None else "", nh))
        for view, t in sh.callouts:
            out.append("   %s: %s" % (view.lower(), t))
    if sheets:
        allp = os.path.join(outdir, "%s_drawings.pdf" % model)
        render_pdf(sheets, allp, singles)
        out.append("drawing: all sheets in %s" % os.path.basename(allp))
    return out
