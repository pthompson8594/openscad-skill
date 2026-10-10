#!/usr/bin/env python3
"""section.py OUT.png PLANE A.stl[=label] [B.stl ...] [--size PX] [--gap MM]
True 2D section through one or more STLs, one colour per part, overlaps in red.
PLANE: x | y | z (bounding-box midplane), x=5, y=-2.5, z=12, and an optional
tilt of the plane about world axes: y=0,rz=30  z=4,rx=10,ry=-5.
Prints, per part, its extent in the plane; in-plane overlaps (mm2) and gaps.
Axis planes report world coordinates; a tilted plane reports u,v measured from
the world point on the untilted axis (e.g. x=5,rz=30 -> origin (5,0,0))."""
import math, os, re, struct, subprocess, sys

COLS = ["#5f8fbf", "#c98a2b", "#5aa36b", "#b5533c", "#8a6fb5", "#3f9fa8", "#b59a3e", "#6a7f95", "#c46a9a", "#4b5a6b"]


def need(mod, pipname=None):
    """import a module, installing it with pip if missing (system, then per-user)"""
    try:
        return __import__(mod)
    except ImportError:
        pass
    import importlib, site
    err = ""
    for extra in ([], ["--user"], ["--break-system-packages"], ["--user", "--break-system-packages"]):
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", pipname or mod] + extra, capture_output=True, text=True)
        if r.returncode == 0:
            break
        err = (r.stderr.strip().splitlines() or [""])[-1]
    try:
        site.addsitedir(site.getusersitepackages())
    except Exception:
        pass
    importlib.invalidate_caches()
    try:
        return __import__(mod)
    except ImportError:
        sys.stderr.write("could not install %s with pip: %s\n" % (pipname or mod, err))
        return None


np = need("numpy") or sys.exit("section.py: needs numpy")
M3 = need("manifold3d") or sys.exit("section.py: needs manifold3d")
PIL = need("PIL", "pillow") or sys.exit("section.py: needs pillow")
from PIL import Image, ImageDraw, ImageFont  # noqa: E402


def parse(spec):
    parts = [s.strip() for s in spec.split(",") if s.strip()]
    m = re.match(r"^([xyz])(?:\s*=\s*(-?[0-9.]+))?$", parts[0])
    if not m:
        raise SystemExit("section: bad plane '%s' (use x=5, y=0,rz=30 ...)" % spec)
    rot = [0.0, 0.0, 0.0]
    for p in parts[1:]:
        r = re.match(r"^r([xyz])\s*=\s*(-?[0-9.]+)$", p)
        if not r:
            raise SystemExit("section: bad tilt '%s' (use rx=, ry=, rz=)" % p)
        rot["xyz".index(r.group(1))] = float(r.group(2))
    return m.group(1), (float(m.group(2)) if m.group(2) is not None else None), rot


def rmat(rot):
    R = np.eye(3)
    for k, a in enumerate(rot):
        if not a:
            continue
        c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
        M = [np.array([[1, 0, 0], [0, c, -s], [0, s, c]]), np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]]), np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])][k]
        R = M @ R
    return R


def frame(ax, val, rot, bb):
    u, v, n = {"x": ([0, 1, 0], [0, 0, 1], [1, 0, 0]), "y": ([1, 0, 0], [0, 0, 1], [0, -1, 0]), "z": ([1, 0, 0], [0, 1, 0], [0, 0, 1])}[ax]
    k = "xyz".index(ax)
    if val is None:
        val = (bb[k] + bb[k + 3]) / 2
    c = np.zeros(3)
    c[k] = val
    R = rmat(rot)
    B = np.array([R @ np.array(u, float), R @ np.array(v, float), R @ np.array(n, float)])
    names = ("xyz"[int(np.argmax(np.abs(B[0])))], "xyz"[int(np.argmax(np.abs(B[1])))]) if not any(rot) else ("u", "v")
    return B, c, val, names


def section(items, spec, out, size=720, gapmax=0.5):
    """items: [(label, Manifold, '#colour', id)] -> writes out PNG, returns report lines"""
    ax, val, rot = parse(spec)
    bbs = [m.bounding_box() for _, m, _, _ in items]
    bb = [min(b[i] for b in bbs) for i in range(3)] + [max(b[i + 3] for b in bbs) for i in range(3)]
    B, c, val, names = frame(ax, val, rot, bb)
    T = np.zeros((3, 4))
    T[:, :3] = B
    T[:, 3] = -B @ c
    cut = []
    for lab, m, col, pid in items:
        cs = m.transform(T.tolist()).slice(0.0)
        if cs.is_empty() or cs.area() < 1e-6:
            continue
        cut.append((lab, cs, col, pid))
    label = spec if val is None else re.sub(r"^([xyz])(=[^,]*)?", lambda mm: "%s=%g" % (mm.group(1), round(val, 3)), spec)
    if not cut:
        return ["section %s: nothing cut (model spans %s[%.1f,%.1f])" % (label, ax, bb["xyz".index(ax)], bb["xyz".index(ax) + 3])]
    b2 = np.array([cs.bounds() for _, cs, _, _ in cut])
    lo, hi = b2[:, :2].min(0), b2[:, 2:].max(0)
    span = hi - lo
    pad = 30
    sc = (size - 2 * pad) / max(span[0], span[1] * (size - 2 * pad) / (size * 1.4 - 2 * pad), 1e-6)
    W, H = int(span[0] * sc + 2 * pad), int(span[1] * sc + 2 * pad)
    font = ImageFont.load_default(size=13) if hasattr(ImageFont, "load_default") else None
    try:
        font = ImageFont.load_default(size=13)
    except TypeError:
        font = ImageFont.load_default()
    rows = (len(cut) + 1) // 2
    leg = 22 * rows + 34
    img = Image.new("RGB", (max(W, 360), H + leg), (250, 250, 250))
    count = np.zeros((H, W), np.int16)
    tox = lambda p: [(pad + (x - lo[0]) * sc, H - pad - (y - lo[1]) * sc) for x, y in p]
    for lab, cs, col, pid in cut:
        mk = np.zeros((H, W), bool)
        for poly in cs.to_polygons():
            if len(poly) < 3:
                continue
            im = Image.new("1", (W, H), 0)
            ImageDraw.Draw(im).polygon(tox(poly), fill=1)
            mk ^= np.array(im, bool)
        count += mk
        rgb = tuple(int(col.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        arr = np.array(img)
        sub = arr[:H, :W]
        sub[mk] = rgb
        img = Image.fromarray(arr)
    arr = np.array(img)
    arr[:H, :W][count > 1] = (220, 30, 30)
    img = Image.fromarray(arr)
    d = ImageDraw.Draw(img)
    for lab, cs, col, pid in cut:
        for poly in cs.to_polygons():
            if len(poly) >= 2:
                q = tox(poly)
                d.line(q + [q[0]], fill=(25, 30, 38), width=1)
    step = 10 ** math.floor(math.log10(max(span) / 4 or 1))
    for m in (5, 2, 1):
        if m * step <= max(span) / 3:
            step *= m
            break
    y0 = H - 12
    d.line([(pad, y0), (pad + step * sc, y0)], fill=(20, 20, 20), width=3)
    d.text((pad + step * sc + 6, y0 - 8), "%g mm" % step, fill=(20, 20, 20), font=font)
    d.text((6, 6), "section %s   %s right, %s up" % (label, names[0], names[1]), fill=(20, 20, 20), font=font)
    for i, (lab, cs, col, pid) in enumerate(cut):
        x, y = 8 + (i % 2) * (img.width // 2), H + 8 + (i // 2) * 22
        d.rectangle([x, y + 2, x + 14, y + 16], fill=col, outline=(30, 30, 30))
        d.text((x + 20, y + 2), lab[:40], fill=(20, 20, 20), font=font)
    if (count > 1).any():
        y = H + 8 + rows * 22
        d.rectangle([8, y + 2, 22, y + 16], fill=(220, 30, 30))
        d.text((28, y + 2), "overlap", fill=(20, 20, 20), font=font)
    img.save(out)
    lines = ["section %s -> %s: %d parts cut" % (label, out, len(cut))]
    for (lab, cs, col, pid), b in zip(cut, b2):
        lines.append("   %s: %s[%.2f,%.2f] %s[%.2f,%.2f] area %.1f mm2" % (pid, names[0], b[0], b[2], names[1], b[1], b[3], cs.area()))
    for i in range(len(cut)):
        for j in range(i + 1, len(cut)):
            a, b = cut[i], cut[j]
            ba, bb_ = b2[i], b2[j]
            if ba[0] > bb_[2] + gapmax or bb_[0] > ba[2] + gapmax or ba[1] > bb_[3] + gapmax or bb_[1] > ba[3] + gapmax:
                continue
            ov = (a[1] ^ b[1]).area()
            if ov > 1e-3:
                lines.append("   OVERLAP in plane %s x %s: %.2f mm2" % (a[3], b[3], ov))
                continue
            g = gap2d(a[1], b[1], gapmax)
            if g is not None and 0.001 < g < gapmax:
                lines.append("   gap %s ~ %s: %.2f mm" % (a[3], b[3], g))
    return lines


def gap2d(a, b, gapmax):
    """smallest in-plane distance (to ~0.001 mm) by growing a until it meets b; None if >= gapmax"""
    hit = lambda d: (a.offset(d, M3.JoinType.Round, 2.0, 96) ^ b).area() > 1e-7
    if not hit(gapmax):
        return None
    lo, hi = 0.0, gapmax
    if hit(1e-4):
        return 0.0
    for _ in range(16):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if hit(mid) else (mid, hi)
    return hi


def load_stl(path):
    d = open(path, "rb").read()
    n = struct.unpack("<I", d[80:84])[0]
    a = np.frombuffer(d, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=n, offset=84)
    tri = a["v"].astype(np.float64)
    v, inv = np.unique(tri.reshape(-1, 3).round(4), axis=0, return_inverse=True)
    f = inv.reshape(-1, 3)
    f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
    mesh = M3.Mesh(vert_properties=v.astype(np.float32), tri_verts=f.astype(np.uint32))
    mesh.merge()
    return M3.Manifold(mesh)


if __name__ == "__main__":
    args, size, gap = [], 720, 0.5
    it = iter(sys.argv[1:])
    for x in it:
        if x == "--size":
            size = int(next(it))
        elif x == "--gap":
            gap = float(next(it))
        else:
            args.append(x)
    if len(args) < 3:
        sys.exit(__doc__)
    out, spec, files = args[0], args[1], args[2:]
    items = []
    for i, f in enumerate(files):
        path, _, lab = f.partition("=")
        man = load_stl(path)
        if man.is_empty():
            print("section: %s is not a closed solid, skipped" % path)
            continue
        nm = lab or os.path.splitext(os.path.basename(path))[0]
        items.append((nm, man, COLS[i % len(COLS)], nm))
    for l in section(items, spec, out, size, gap):
        print(l)
