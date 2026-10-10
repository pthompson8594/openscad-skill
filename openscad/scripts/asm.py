#!/usr/bin/env python3
"""asm.py model.scad [flags]  - export, check and package a multi-part OpenSCAD model.

Reads the `parts` table (and optional `checks`, `travel`, `report`, `variants`,
`bends` tables) from model.scad, exports every part (parallel, cached per part by
its CSG tree), prints one line per part that changed, then runs the asked checks.
  --only a,b       export/check just these parts (cache stays correct)
  --all            print every part line, not only changed ones
  --clash [--clear MM]  every pair: overlap regions (mm3, depth, where); gaps under MM
  --check          evaluate the `checks` table (also runs with --clash/--travel)
  --travel [G[:MM]]     move each `travel` group (or G by +-MM) to its extremes and test
  --section PLANE  2D section of the whole assembly, e.g. y=0, z=12, x=5,rz=30 (repeatable)
  --walls [MM]     thinnest wall per printed part; share of surface under MM (default 1.2)
  --print          print set -> <model>_print/: oriented STLs named by label, 3MF per plate,
                   overhang report
  --variant A,B    only these values of the `variants` table
  --holes [GAP]    holes in sheets within GAP mm (default 1) that overlap but miss
  --cut            flat sheets -> <model>_cut/*.dxf + cutlist.csv
  --step           flat sheets -> <model>_step/*.step (true solids, re-imported and checked)
  --bundle         zip model + print + cut + step + viewer as <model>_<rev>.zip
  --html [--title T]    interactive viewer -> <model>.html
  --selftest       planted faults; every check must catch its fault
Table rows: ["id","Label","note",[ex,ey,ez],"#colour","group=G","print=x180","plate=P","mat=PETG"]
(only id is required).
"""
import argparse, base64, hashlib, itertools, json, math, os, re, struct, subprocess, sys, zipfile
from concurrent.futures import ThreadPoolExecutor

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
OSCAD = os.path.join(HERE, "oscad.sh")


def need(mod, pipname=None):
    try:
        return __import__(mod)
    except ImportError:
        for extra in ([], ["--break-system-packages"]):
            if subprocess.run([sys.executable, "-m", "pip", "install", "-q", pipname or mod] + extra, capture_output=True).returncode == 0:
                break
        try:
            return __import__(mod)
        except ImportError:
            return None


np = need("numpy") or sys.exit("asm.py: needs numpy (pip install numpy)")

STEEL = ["#5f6f80", "#74879a", "#8a9bb0", "#a7b4c2", "#4b5a6b", "#9fb0c2", "#c98a2b", "#d9dee4"]
HW = ["#3f7d5a", "#b5533c", "#b98a3e", "#3b4047", "#2f5f8f", "#3f7fb5", "#6a6f78", "#7a5c8f"]
TAGS = ("group", "print", "plate", "mat", "flex", "qty")
USERLIBS = [os.path.expanduser("~/.local/share/OpenSCAD/libraries"), os.path.expanduser("~/Documents/OpenSCAD/libraries")]
PFX = [""]
FAULTS = {"render": 0, "found": 0}
IGNORE = set()


def say(*a):
    print(PFX[0] + " ".join(str(x) for x in a))


# ---------------------------------------------------------------- engine ----
def scad_env(native=False):
    e = dict(os.environ)
    e["OPENSCADPATH"] = os.path.join(os.path.dirname(HERE), "lib") + os.pathsep + e.get("OPENSCADPATH", "")
    if native:
        e["OSCAD_ENGINE"] = "native"
    return e


def run_scad(args, native=False):
    return subprocess.run(["bash", OSCAD] + args, capture_output=True, text=True, env=scad_env(native))


_ENG = {}


def engine():
    if "id" not in _ENG:
        r = subprocess.run(["bash", OSCAD, "--which"], capture_output=True, text=True, env=scad_env())
        _ENG["id"] = r.stdout.strip() or "none"
        _ENG["native"] = bool(re.search(r"native|PNG previews: /", _ENG["id"]))
    return _ENG["id"]


def defargs(defs):
    out = []
    for k, v in defs:
        out += ["-D", "%s=%s" % (k, json.dumps(v) if isinstance(v, str) else v)]
    return out


def warnings_of(stderr):
    seen, out = set(), []
    for l in stderr.splitlines():
        if re.match(r"^(WARNING|ERROR|DEPRECATED)", l):
            l = re.sub(r"\s+", " ", l.strip())[:200]
            if l not in seen:
                seen.add(l)
                out.append(l)
    return out


def deps(scad, seen=None):
    """files the model reads: itself, include/use (recursive), literal import()/surface()"""
    seen = set() if seen is None else seen
    p = os.path.abspath(scad)
    if p in seen or not os.path.isfile(p):
        return seen
    seen.add(p)
    if not p.endswith(".scad"):
        return seen
    t = open(p, errors="replace").read()
    t = re.sub(r"/\*.*?\*/", "", t, flags=re.S)
    t = re.sub(r"//[^\n]*", "", t)
    d = os.path.dirname(p)
    libs = [d] + [x for x in scad_env()["OPENSCADPATH"].split(os.pathsep) if x] + USERLIBS
    for name in re.findall(r"\b(?:include|use)\s*<([^>]+)>", t):
        for b in libs:
            q = os.path.join(b, name)
            if os.path.isfile(q):
                deps(q, seen)
                break
    for name in re.findall(r"\b(?:import|surface)\s*\(\s*(?:file\s*=\s*)?\"([^\"]+)\"", t):
        q = os.path.join(d, name)
        if os.path.isfile(q):
            seen.add(os.path.abspath(q))
    return seen


def hash_files(files, extra=""):
    h = hashlib.sha1(extra.encode())
    for f in sorted(files):
        h.update(f.encode())
        h.update(open(f, "rb").read())
    return h.hexdigest()


# ----------------------------------------------------------- tables ----------
TABLES = ["parts", "bends", "k_factor", "checks", "travel", "report", "variants", "variant"]


def scad_to_json(s):
    out = []
    for i, chunk in enumerate(re.split(r'("(?:\\.|[^"\\])*")', s)):
        if i % 2:
            out.append(chunk)
        else:
            chunk = re.sub(r"\bundef\b", "null", chunk)
            chunk = re.sub(r"-?\binf\b|\bnan\b", "null", chunk)
            out.append(chunk)
    return json.loads("".join(out))


def evaluate(scad, defs, cachedir):
    key = hash_files(deps(scad), engine() + json.dumps(defs))
    cf = os.path.join(cachedir, ".tables.json")
    if os.path.exists(cf):
        c = json.load(open(cf))
        if c.get("key") == key and c["t"].get("parts"):
            return c["t"]
    d = os.path.dirname(os.path.abspath(scad))
    w = os.path.join(d, ".asm_eval_%d.scad" % os.getpid())
    e = w[:-5] + ".echo"
    open(w, "w").write("include <%s>\n" % os.path.basename(scad) + "".join(
        'echo(ASM_%s=is_undef(%s)?"__undef__":%s);\n' % (n, n, n) for n in TABLES))
    r = run_scad(["-o", e] + defargs([("part", "__none__")] + defs) + [w])
    txt = (open(e).read() if os.path.exists(e) else "") + "\n" + r.stdout + "\n" + r.stderr
    clash_ = []
    for name, l1, l2, l3 in re.findall(r"WARNING: [\"']?(\w+)[\"']? was assigned on line (\d+)(?: of [\"'][^\"'\n]*[\"'])? but was overwritten(?: on line (\d+)| in file [^\n]*?, line (\d+))?", txt):
        if name in TABLES:
            l2 = l2 or l3
            clash_.append("`%s` is assigned twice (line %s%s): asm.py reads it as the %s table, and OpenSCAD keeps only one value for the whole file" % (
                name, l1, " and %s" % l2 if l2 else "", name))
    if clash_:
        sys.exit("asm.py: name clash - rename your own variable:\n  " + "\n  ".join(clash_))
    for f in (w, e):
        if os.path.exists(f):
            os.remove(f)
    t = {}
    for n in TABLES:
        m = re.search(r"ECHO: ASM_%s = (.*)" % n, txt)
        v = None
        if m:
            try:
                v = scad_to_json(m.group(1).strip())
            except Exception:
                v = None
        t[n] = None if v == "__undef__" else v
    if not isinstance(t["parts"], list):
        errs = [l for l in txt.splitlines() if l.startswith("ERROR") or l.startswith("WARNING: Can't open")]
        if errs:
            sys.exit("asm.py: model failed to evaluate:\n" + "\n".join(errs[:5]))
        sys.exit("asm.py: no `parts = [ ... ];` table found")
    if not t["parts"]:
        sys.exit("asm.py: the parts table is empty")
    t["_warn"] = [re.sub(r" in file \S*?([^/\s]+), line", r" in \1, line", x) for x in warnings_of(txt)]
    os.makedirs(cachedir, exist_ok=True)
    json.dump({"key": key, "t": t}, open(cf, "w"))
    return t


def parse_parts(rows):
    out = []
    for r in rows:
        r = [r] if isinstance(r, str) else r
        p = {"id": r[0], "label": r[0].replace("hw_", "").replace("_", " ").capitalize(), "note": "", "ex": None, "color": None, "tags": {}}
        strs = []
        for x in r[1:]:
            if isinstance(x, str):
                m = re.match(r"^(%s)=(.*)$" % "|".join(TAGS), x)
                if m:
                    p["tags"][m.group(1)] = m.group(2).strip()
                elif x.startswith("#"):
                    p["color"] = x
                else:
                    strs.append(x)
            elif isinstance(x, list):
                p["ex"] = x
        if strs:
            p["label"] = strs[0]
        if len(strs) > 1:
            p["note"] = strs[1]
        p["hw"] = p["id"].startswith("hw_")
        p["group"] = p["tags"].get("group", p["id"])
        fx = p["tags"].get("flex", "")
        p["flex_all"] = fx.lower() in ("1", "true", "yes", "all")
        p["flex_with"] = set() if p["flex_all"] or not fx else {x.strip() for x in fx.split(",") if x.strip()}
        try:
            p["qty"] = max(1, int(p["tags"].get("qty", "1")))
        except ValueError:
            p["qty"] = 1
        out.append(p)
    return out


# ------------------------------------------------------------ meshes ---------
def read_stl(path):
    d = open(path, "rb").read()
    n = struct.unpack("<I", d[80:84])[0]
    a = np.frombuffer(d, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=n, offset=84)
    return a["v"].astype(np.float64)


def write_stl(path, tri):
    tri = np.asarray(tri, dtype=np.float64)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = n / np.where(ln == 0, 1, ln)
    rec = np.zeros(len(tri), dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    rec["n"], rec["v"] = n, tri
    with open(path, "wb") as f:
        f.write(b"asm.py".ljust(80, b" ") + struct.pack("<I", len(tri)) + rec.tobytes())


def weld(tri, dec=4):
    v, inv = np.unique(tri.reshape(-1, 3).round(dec), axis=0, return_inverse=True)
    f = inv.reshape(-1, 3)
    return v, f


def edge_faults(tri):
    """(open edges, edges shared by more than two faces) on the welded mesh"""
    v, f = weld(tri)
    f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
    if not len(f):
        return 0, 0
    e = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
    _, cnt = np.unique(e, axis=0, return_counts=True)
    return int((cnt % 2 == 1).sum()), int((cnt > 2).sum())


def open_edges(tri):
    return edge_faults(tri)[0]


def stats(tri):
    op, nm = edge_faults(tri)
    lo, hi = tri.reshape(-1, 3).min(0), tri.reshape(-1, 3).max(0)
    vol = float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6)
    return {"lo": lo.round(3).tolist(), "hi": hi.round(3).tolist(), "vol": round(abs(vol), 1), "tris": len(tri),
            "hash": hashlib.sha1(tri.astype(np.float32).tobytes()).hexdigest()[:16], "open": op, "nonman": nm}


_M3 = {}


def m3():
    if "m" not in _M3:
        _M3["m"] = need("manifold3d")
    return _M3["m"]


def manifold(p):
    if "man" not in p:
        M = m3()
        p["man"] = None
        if M is not None and p.get("tri") is not None:
            v, f = weld(p["tri"])
            f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
            mesh = M.Mesh(vert_properties=v.astype(np.float32), tri_verts=f.astype(np.uint32))
            mesh.merge()
            man = M.Manifold(mesh)
            p["man"] = None if man.is_empty() else man
    return p["man"]


# ------------------------------------------------------------ export ---------
def part_warnings(w, model_warn):
    key = lambda x: re.sub(r" in (file )?.*", "", re.sub(r" of [\"'][^\"']*[\"']", "", x)).replace("'", '"')
    mw = {key(x) for x in model_warn}
    return [x for x in w if key(x) not in mw]


def export(scad, parts, outdir, defs, model_warn=()):
    os.makedirs(outdir, exist_ok=True)
    kf = os.path.join(outdir, ".keys.json")
    keys = json.load(open(kf)) if os.path.exists(kf) else {}
    if os.path.exists(os.path.join(outdir, ".key")):
        os.remove(os.path.join(outdir, ".key"))
    eng = engine()
    dep = hash_files(deps(scad), eng + json.dumps(defs))
    native = "native" in eng or "PNG previews: /" in eng
    workers = max(1, min(8, os.cpu_count() or 2))

    def csg_key(p):
        f = os.path.join(outdir, ".%s.csg" % p["id"])
        da = defargs([("part", p["id"])] + defs)
        r = run_scad(["-o", f] + da + [scad], native=native)
        if (r.returncode or not os.path.exists(f)) and native:
            r = run_scad(["-o", f] + da + [scad])
        if r.returncode or not os.path.exists(f):
            return None
        txt = open(f, errors="replace").read()
        os.remove(f)
        files = set()
        for name in re.findall(r"(?:import|surface)\(\s*file\s*=\s*\"([^\"]+)\"", txt):
            q = name if os.path.isabs(name) else os.path.join(os.path.dirname(os.path.abspath(scad)), name)
            if os.path.isfile(q):
                files.add(q)
        return hash_files(files, eng + "\n" + txt + json.dumps(p.get("bends") or []))

    stl = lambda p: os.path.join(outdir, p["id"] + ".stl")
    todo = []
    for p in parts:
        k = keys.get(p["id"], {})
        p["warn"] = part_warnings(k.get("warn", []), model_warn)
        if k.get("dep") == dep and os.path.exists(stl(p)):
            continue
        todo.append(p)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        ck = list(ex.map(csg_key, todo))
    render = []
    for p, c in zip(todo, ck):
        k = keys.get(p["id"], {})
        if c and k.get("csg") == c and os.path.exists(stl(p)):
            k["dep"] = dep
            keys[p["id"]] = k
        else:
            p["_csg"] = c
            render.append(p)

    def one(p):
        f = stl(p)
        tmp = os.path.join(outdir, ".%s.tmp.stl" % p["id"])
        da = defargs([("part", p["id"])] + defs)
        r = run_scad(["-o", tmp, "--export-format", "binstl"] + da + [scad])
        w = warnings_of(r.stderr)
        if p.get("bends"):
            ft = tmp[:-8] + ".flat.tmp.stl"
            r2 = run_scad(["-o", ft, "--export-format", "binstl"] + da + ["-D", "flat=true", scad])
            if os.path.exists(ft):
                os.replace(ft, f[:-4] + ".flat.stl")
            w += [x for x in warnings_of(r2.stderr) if x not in w]
        if r.returncode or not os.path.exists(tmp):
            for g in (tmp, f):
                if os.path.exists(g):
                    os.remove(g)
            errs = [l for l in w if l.startswith("ERROR")] or (r.stderr.strip().splitlines() or ["failed"])[-1:]
            return p, errs[0][:200], w
        os.replace(tmp, f)
        return p, None, w

    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(one, render))
    for p, err, w in res:
        w = part_warnings(w, model_warn)
        p["err"], p["warn"] = err, w
        if err:
            keys.pop(p["id"], None)
        else:
            keys[p["id"]] = {"dep": dep, "csg": p.get("_csg"), "warn": w}
    json.dump(keys, open(kf, "w"))
    return len(render)


def load(scad, parts, outdir, defs=(), model_warn=()):
    n = export(scad, parts, outdir, list(defs), model_warn)
    for p in parts:
        p["stl"] = os.path.join(outdir, p["id"] + ".stl")
        p.setdefault("err", None)
        p["tri"] = read_stl(p["stl"]) if os.path.exists(p["stl"]) and os.path.getsize(p["stl"]) > 84 else None
        if p["tri"] is not None and len(p["tri"]) == 0:
            p["tri"] = None
        if p["tri"] is not None:
            p["st"] = stats(p["tri"])
    return n


def report(parts, outdir, show_all, rendered):
    nf = os.path.join(outdir, ".numbers.json")
    prev = json.load(open(nf)) if os.path.exists(nf) else {}
    cur = dict(prev) if len(parts) < len(prev) else {}
    same = 0
    for p in parts:
        for w in p.get("warn") or []:
            say("%s: %s" % (p["id"], w))
        if p.get("tri") is None:
            say("%s: EMPTY or failed (%s)" % (p["id"], p.get("err") or "no geometry"))
            FAULTS["render"] += 1
            continue
        s = p["st"]
        cur[p["id"]] = s
        if s["open"]:
            FAULTS["render"] += 1
            say("%s: NOT WATERTIGHT (%d open edges) - usually a cutter face tangent to a surface; offset it" % (p["id"], s["open"]))
        elif s["nonman"]:
            FAULTS["render"] += 1
            say("%s: NON-MANIFOLD (%d edges shared by more than 2 faces) - solids touching along an edge; overlap or separate them" % (p["id"], s["nonman"]))
        o = prev.get(p["id"])
        size = " x ".join("%.1f" % (s["hi"][k] - s["lo"][k]) for k in range(3))
        sz = o and o["lo"] == s["lo"] and o["hi"] == s["hi"] and abs(o["vol"] - s["vol"]) < 0.5
        if o and not show_all and o.get("hash") == s["hash"]:
            same += 1
            continue
        d = " (new)" if not o else (" (unchanged)" if o.get("hash") == s["hash"] else " (same size, shape changed)" if sz else " (dvol %+.0f)" % (s["vol"] - o["vol"]))
        say("%s: %s | vol %.0f%s | x[%.1f,%.1f] y[%.1f,%.1f] z[%.1f,%.1f]" % (p["id"], size, s["vol"], d, s["lo"][0], s["hi"][0], s["lo"][1], s["hi"][1], s["lo"][2], s["hi"][2]))
    if same:
        say("unchanged: %d parts (identical geometry)" % same)
    say("parts: %d rendered, %d from cache | engine: %s" % (rendered, len(parts) - rendered, engine().split(";")[0]))
    json.dump(cur, open(nf, "w"))


def fmt(v):
    if isinstance(v, (int, float)):
        return "%g" % round(v, 3)
    if isinstance(v, list):
        return "[" + ",".join(fmt(x) for x in v) + "]"
    return str(v)


def dims_report(rows, outdir):
    if not rows:
        return
    nf = os.path.join(outdir, ".report.json")
    prev = json.load(open(nf)) if os.path.exists(nf) else {}
    out, cur = [], {}
    for r in rows:
        if not isinstance(r, list) or len(r) < 2:
            continue
        name, v = str(r[0]), r[1]
        if v is None:
            out.append("%s undef (is it defined below the report table? put tables after the values they use)" % name)
            continue
        cur[name] = v
        o = prev.get(name)
        ch = ""
        if o is not None and o != v:
            ch = " (%+g)" % round(v - o, 3) if isinstance(v, (int, float)) and isinstance(o, (int, float)) else " (was %s)" % fmt(o)
        out.append("%s %s%s" % (name, fmt(v), ch))
    say("report: " + " | ".join(out))
    json.dump(cur, open(nf, "w"))


# ------------------------------------------------------------ clash ----------
def regions(I):
    out = []
    for r in I.decompose():
        v = r.volume()
        if v < 0.01:
            continue
        bb = r.bounding_box()
        ext = [bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]]
        a = r.surface_area()
        ts = 2 * v / a if a else 0
        t = ts if ts < 0.25 * min(ext) else min(ext)
        out.append({"vol": v, "bb": bb, "depth": t})
    return sorted(out, key=lambda x: -x["vol"])


def where(bb):
    return "x[%.1f,%.1f] y[%.1f,%.1f] z[%.1f,%.1f]" % (bb[0], bb[3], bb[1], bb[4], bb[2], bb[5])


def bbox_far(A, B, pad):
    a, b = A.bounding_box(), B.bounding_box()
    return any(a[k] > b[k + 3] + pad or b[k] > a[k + 3] + pad for k in range(3))


def overlap_lines(na, nb, I):
    vol = I.volume()
    rs = regions(I)
    if len(rs) <= 1:
        r = rs[0] if rs else {"depth": 0, "bb": I.bounding_box()}
        return ["OVERLAP %s x %s: %.1f mm3, depth ~%.2f mm at %s" % (na, nb, vol, r["depth"], where(r["bb"]))]
    out = ["OVERLAP %s x %s: %.1f mm3 in %d places" % (na, nb, vol, len(rs))]
    for i, r in enumerate(rs[:6]):
        out.append("   %d: %.1f mm3, depth ~%.2f mm at %s" % (i + 1, r["vol"], r["depth"], where(r["bb"])))
    if len(rs) > 6:
        out.append("   ... %d more" % (len(rs) - 6))
    return out


def clash(parts, clear):
    if m3() is None:
        say("clash: could not install manifold3d (pip install manifold3d), skipped")
        return
    ms = []
    for p in parts:
        if p.get("tri") is None:
            continue
        if manifold(p) is None:
            say("clash: %s is not a closed solid, skipped" % p["id"])
            continue
        ms.append(p)
    pad = max(clear, 0) + 0.01
    hits = near = touch = pairs = flexed = 0
    for a, b in itertools.combinations(ms, 2):
        A, B = a["man"], b["man"]
        if bbox_far(A, B, pad):
            continue
        if flex_pair(a, b):
            flexed += 1
            continue
        pairs += 1
        I = A ^ B
        if I.volume() > 0.05:
            hits += 1
            FAULTS["found"] += 1
            for l in overlap_lines(a["id"], b["id"], I):
                say(l)
            continue
        g = A.min_gap(B, pad)
        if g < 1e-4:
            touch += 1
        elif clear > 0 and g < clear:
            near += 1
            say("gap %s ~ %s: %.2f mm" % (a["id"], b["id"], g))
    say("clash: %d overlapping, %d under %.2g mm, %d touching, %d pairs tested%s" % (hits, near, max(clear, 0), touch, pairs,
        ", %d flex contacts allowed" % flexed if flexed else ""))


def flex_pair(a, b):
    """contact between a and b is allowed because one of them flexes into the other"""
    return any(x["flex_with"] & {y["id"], y["group"]} for x, y in ((a, b), (b, a)))


def members(parts, name, group=False):
    """checks: a part id wins over a group of the same name; travel: the whole group"""
    ok = [p for p in parts if manifold(p) is not None]
    ids = [p for p in ok if p["id"] == name]
    grp = [p for p in ok if p["group"] == name]
    return (grp or ids) if group else (ids or grp)


def union(ms):
    out = ms[0]
    for m in ms[1:]:
        out = out + m
    return out


def gap_metric(A, B, want):
    """signed distance: >0 clearance, <0 penetration depth (deepest overlap region)"""
    I = A ^ B
    if I.volume() > 0.05:
        rs = regions(I)
        return -(max(r["depth"] for r in rs) if rs else 0.0)
    search = max(2.0, abs(want) * 2 + 1)
    return A.min_gap(B, search)


OPS = (">=", ">", "<=", "<", "==", "touch", "clear", "overlap")


def check_rows(rows):
    out, bad = [], []
    for r in rows or []:
        if isinstance(r, list) and len(r) >= 4 and r[3] is None and r[2] in OPS[:5]:
            say("CHECK ? %s ~ %s: value is undef - define it above the checks table" % (r[0], r[1]))
            FAULTS["found"] += 1
            continue
        if not isinstance(r, list) or len(r) < 3 or r[2] not in OPS or (r[2] in OPS[:5] and (len(r) < 4 or not isinstance(r[3], (int, float)))):
            bad.append(r)
            continue
        c = {"a": r[0], "b": r[1], "op": r[2], "val": r[3] if len(r) > 3 and isinstance(r[3], (int, float)) else 0.0,
             "tol": 0.05 if r[2] == "==" else 0.01, "travel": "travel" in r[3:]}
        if len(r) > 4 and isinstance(r[4], (int, float)):
            c["tol"] = r[4]
        out.append(c)
    return out, bad


def check_ok(c, g):
    op, v, t = c["op"], c["val"], c["tol"]
    return {">=": g >= v - t, ">": g > v - t, "<=": g <= v + t, "<": g < v + t, "==": abs(g - v) <= t,
            "touch": abs(g) <= max(t, 1e-3), "clear": g > 1e-4, "overlap": g < 0}.get(op, False)


def run_checks(parts, rows, poses=None, subset=None):
    cs, malformed = check_rows(rows)
    for r in malformed:
        say("CHECK ? malformed row %s - use [a, b, op, value(, tolerance)(, \"travel\")], op one of %s" % (json.dumps(r), " ".join(OPS)))
        FAULTS["found"] += 1
    skipped = 0
    if subset is not None:
        keep = []
        for c in cs:
            if members(parts, c["a"]) and members(parts, c["b"]):
                keep.append(c)
            else:
                skipped += 1
        cs = keep
    if not cs:
        if skipped:
            say("checks: %d skipped (parts outside --only)" % skipped)
        return
    if m3() is None:
        say("checks: manifold3d unavailable, skipped")
        return
    good = bad = 0
    for c in cs:
        A, B = members(parts, c["a"]), members(parts, c["b"])
        if not A or not B:
            say("CHECK ? %s %s %s: part or group not found" % (c["a"], c["op"], c["b"]))
            bad += 1
            continue
        g = gap_metric(union([p["man"] for p in A]), union([p["man"] for p in B]), c["val"])
        worst, at = g, "rest"
        if c["travel"] and poses:
            for grp, (gname, plist) in poses.items():
                ga = {p["id"] for p in members(parts, gname, True)}
                mv_a, mv_b = any(p["id"] in ga for p in A), any(p["id"] in ga for p in B)
                if not (mv_a or mv_b) or (mv_a and mv_b):
                    continue
                for name, tf in plist:
                    ma = union([tf(p["man"]) if p["id"] in ga else p["man"] for p in A])
                    mb = union([tf(p["man"]) if p["id"] in ga else p["man"] for p in B])
                    gg = gap_metric(ma, mb, c["val"])
                    if not check_ok(c, gg) or (c["op"] in (">=", ">", "clear") and gg < worst) or (c["op"] in ("<=", "<") and gg > worst):
                        worst, at = gg, grp + " " + name
                        if not check_ok(c, gg):
                            break
        ok = check_ok(c, worst)
        good += ok
        bad += not ok
        if not ok:
            val = "overlap, depth %.2f mm" % -worst if worst < 0 else "%.3f mm" % worst
            say("CHECK FAIL %s ~ %s %s %s: %s%s" % (c["a"], c["b"], c["op"], fmt(c["val"]) if c["op"] not in ("touch", "clear", "overlap") else "", val,
                                                   "" if at == "rest" else " at " + at))
    FAULTS["found"] += bad
    say("checks: %d pass, %d FAIL%s" % (good, bad, ", %d skipped (parts outside --only)" % skipped if skipped else ""))


# ------------------------------------------------------------ travel ---------
def pose_list(d, r):
    ax = [k for k in range(3) if d[k]]
    rx = [k for k in range(3) if r[k]]
    poses = []

    def name(t, rr):
        s = ["%s%+g" % ("xyz"[k], t[k]) for k in range(3) if t[k]] + ["r%s%+g" % ("xyz"[k], rr[k]) for k in range(3) if rr[k]]
        return " ".join(s)

    trans = []
    for k in ax:
        for s in (1, -1):
            t = [0, 0, 0]
            t[k] = s * d[k]
            trans.append(t)
    if len(ax) >= 2:
        for signs in itertools.product((1, -1), repeat=len(ax)):
            t = [0, 0, 0]
            for k, s in zip(ax, signs):
                t[k] = s * d[k]
            trans.append(t)
    rots = []
    for k in rx:
        for s in (1, -1):
            q = [0, 0, 0]
            q[k] = s * r[k]
            rots.append(q)
    for t in trans:
        poses.append((t, [0, 0, 0]))
    for q in rots:
        poses.append(([0, 0, 0], q))
        for t in trans:
            poses.append((t, q))
    seen, out = set(), []
    for t, q in poses:
        n = name(t, q)
        if n not in seen:
            seen.add(n)
            out.append((n, t, q))
    return out


def travel_poses(parts, rows, only):
    res, seen = {}, {}
    for r in rows or []:
        if not isinstance(r, list) or not r:
            continue
        g = r[0]
        names = [x[5:] for x in r[1:] if isinstance(x, str) and x.startswith("name=")]
        seen[g] = seen.get(g, 0) + 1
        label = names[0] if names else (g if seen[g] == 1 else "%s#%d" % (g, seen[g]))
        r = [x for x in r if not (isinstance(x, str) and x.startswith("name="))]
        if only and g not in only and label not in only:
            continue
        if any(x is None for x in r[1:2]) or (len(r) > 1 and isinstance(r[1], list) and None in r[1]):
            say("travel %s: a value is undef - define it above the travel table" % g)
            continue
        d = r[1] if len(r) > 1 else 0
        d = [d] * 3 if isinstance(d, (int, float)) else list(d) + [0] * (3 - len(d))
        q = r[2] if len(r) > 2 and r[2] is not None else [0, 0, 0]
        q = [q] * 3 if isinstance(q, (int, float)) else list(q) + [0] * (3 - len(q))
        ms = members(parts, g, True)
        if not ms:
            say("travel %s: no parts with that id or group" % g)
            continue
        if len(r) > 3 and isinstance(r[3], list):
            piv = r[3]
        else:
            bb = union([p["man"] for p in ms]).bounding_box()
            piv = [(bb[k] + bb[k + 3]) / 2 for k in range(3)]
        plist = []
        for n, t, rr in pose_list(d, q):
            def tf(m, t=t, rr=rr, piv=piv):
                return m.translate([-piv[0], -piv[1], -piv[2]]).rotate(rr).translate([piv[0] + t[0], piv[1] + t[1], piv[2] + t[2]])
            plist.append((n, tf))
        res[label] = (g, plist)
    return res


def travel(parts, poses, clear):
    for label, (g, plist) in poses.items():
        mv = members(parts, g, True)
        ids = {p["id"] for p in mv}
        others = [p for p in parts if p["id"] not in ids and manifold(p) is not None and not p["flex_all"] and p["id"] not in IGNORE]
        mv = [p for p in mv if not p["flex_all"] and p["id"] not in IGNORE]
        skipped = sorted({p["id"] for p in parts if p["flex_all"] or p["id"] in IGNORE})
        hit, bad_poses, best = {}, set(), (1e9, "", "")
        for name, tf in plist:
            for p in mv:
                A = tf(p["man"])
                for o in others:
                    B = o["man"]
                    if bbox_far(A, B, max(clear, 1.0)) or flex_pair(p, o):
                        continue
                    I = A ^ B
                    if I.volume() > 0.05:
                        rs = regions(I)
                        dp = max(r["depth"] for r in rs) if rs else 0.0
                        bad_poses.add(name)
                        h = hit.setdefault((p["id"], o["id"]), {"n": 0, "worst": None})
                        h["n"] += 1
                        if h["worst"] is None or dp > h["worst"][0]:
                            h["worst"] = (dp, name, I.volume(), rs[0]["bb"] if rs else I.bounding_box())
                        continue
                    gp = A.min_gap(B, max(clear, 1.0))
                    if gp < best[0]:
                        best = (gp, "%s ~ %s" % (p["id"], o["id"]), name)
        fl = sorted({"%s~%s" % (p["id"], w) for p in parts for w in p["flex_with"]})
        say("travel %s: %d poses, %d with overlap%s%s" % (label, len(plist), len(bad_poses), " (ignoring %s)" % ", ".join(skipped) if skipped else "",
                                                        " (flex contacts allowed: %s)" % ", ".join(fl) if fl else ""))
        FAULTS["found"] += len(hit)
        for (a, b), h in sorted(hit.items(), key=lambda kv: -kv[1]["worst"][0]):
            dp, name, vol, bb = h["worst"]
            say("   OVERLAP %s x %s at %d/%d poses; worst depth ~%.2f mm (%.1f mm3) at %s, %s" % (a, b, h["n"], len(plist), dp, vol, name, where(bb)))
        if best[1]:
            say("   closest without overlap: %.2f mm (%s) at %s" % best)
        elif not hit:
            say("   nothing within %.1f mm at any pose" % max(clear, 1.0))


# ------------------------------------------------------------ walls ----------
def walls(parts, thr, samples=20000):
    if m3() is None:
        say("walls: manifold3d unavailable, skipped")
        return
    for p in parts:
        if p["hw"] or manifold(p) is None:
            continue
        man = p["man"]
        mesh = man.to_mesh()
        v = np.asarray(mesh.vert_properties)[:, :3].astype(np.float64)
        f = np.asarray(mesh.tri_verts)
        t = v[f]
        n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        ar = np.linalg.norm(n, axis=1) / 2
        ok = ar > 1e-9
        t, n, ar = t[ok], n[ok] / (2 * ar[ok, None]), ar[ok]
        rng = np.random.default_rng(1)
        k = min(samples, len(t) * 4)
        idx = rng.choice(len(t), size=k, p=ar / ar.sum())
        b = rng.dirichlet([1, 1, 1], size=k)
        pts = np.einsum("ij,ijk->ik", b, t[idx])
        nn = n[idx]
        cap = max(thr * 4, 6.0)
        th = np.full(k, np.inf)
        for i in range(k):
            o = pts[i] - nn[i] * 1e-4
            hits = man.ray_cast(o.tolist(), (o - nn[i] * cap).tolist())
            for h in hits:
                dd = h.distance * cap
                if dd > 1e-3:
                    th[i] = dd
                    break
        thin = np.where(th < thr)[0]
        if not len(thin):
            fin = th[np.isfinite(th)]
            say("walls %s: nothing under %.2g mm%s" % (p["id"], thr, " (thinnest %.2f mm)" % fin.min() if len(fin) else " (every wall over %.1f mm)" % cap))
            continue
        per = ar.sum() / k
        sp = need("scipy")
        from scipy.spatial import cKDTree
        par = np.arange(len(thin))

        def find(x):
            while par[x] != x:
                par[x] = par[par[x]]
                x = par[x]
            return x
        for i, j in cKDTree(pts[thin]).query_pairs(max(1.5, thr * 1.5)):
            par[find(i)] = find(j)
        roots = np.array([find(i) for i in range(len(thin))])
        regs = []
        for r in np.unique(roots):
            sel = thin[roots == r]
            tv = th[sel]
            lo3, hi3 = pts[sel].min(0), pts[sel].max(0)
            p10, med, p90 = np.percentile(tv, [10, 50, 90])
            kind = "tapering edge" if (p90 - p10) > 0.4 * thr or tv.min() < 0.25 * med else "even wall"
            regs.append((len(sel) * per, tv.min(), med, kind, (lo3 + hi3) / 2, hi3 - lo3))
        regs.sort(key=lambda x: -x[0])
        say("walls %s: %.1f%% of surface under %.2g mm, in %d region%s" % (p["id"], len(thin) / k * 100, thr, len(regs), "" if len(regs) == 1 else "s"))
        for a_, mn, md, kind, c3, e3 in regs[:5]:
            say("   %s: %.0f mm2, %.2f-%.2f mm (median %.2f) around x%.1f y%.1f z%.1f, spans %.1f x %.1f x %.1f" % (
                kind, a_, mn, min(md * 2, thr), md, c3[0], c3[1], c3[2], e3[0], e3[1], e3[2]))
        if len(regs) > 5:
            say("   ... %d smaller regions" % (len(regs) - 5))


# ------------------------------------------------------------ print ----------
def rot_matrix(spec):
    R = np.eye(3)
    for tok in re.findall(r"([xyz])\s*(-?[0-9.]+)", spec or ""):
        a = math.radians(float(tok[1]))
        c, s = math.cos(a), math.sin(a)
        M = {"x": [[1, 0, 0], [0, c, -s], [0, s, c]], "y": [[c, 0, s], [0, 1, 0], [-s, 0, c]], "z": [[c, -s, 0], [s, c, 0], [0, 0, 1]]}[tok[0]]
        R = np.array(M) @ R
    return R


def overhang(tri, angle=45.0):
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ar = np.linalg.norm(n, axis=1) / 2
    ok = ar > 1e-9
    nz = np.zeros(len(tri))
    nz[ok] = n[ok, 2] / (2 * ar[ok])
    z0 = tri[:, :, 2].min()
    bed = np.all(tri[:, :, 2] < z0 + 0.05, axis=1)
    over = (nz < -math.cos(math.radians(angle))) & ~bed
    flat = (nz < -0.985) & ~bed
    span, fz = 0.0, 0.0
    if flat.any():
        sub = tri[flat]
        v, f = weld(sub, 3)
        par = np.arange(len(v))

        def find(x):
            while par[x] != x:
                par[x] = par[par[x]]
                x = par[x]
            return x
        for a, b, c in f:
            ra = find(a)
            par[find(b)] = ra
            par[find(c)] = ra
        root = np.array([find(x) for x in f[:, 0]])
        far = ar[flat]
        best = None
        for r in np.unique(root):
            sel = root == r
            area = far[sel].sum()
            if best is None or area > best[0]:
                pts = sub[sel].reshape(-1, 3)
                e = pts.max(0) - pts.min(0)
                best = (area, min(e[0], e[1]), float(pts[:, 2].mean()))
        span, fz = best[1], best[2]
    return float(ar[over].sum()), span, fz


ORIENTS = ["", "x90", "x180", "x270", "y90", "y270"]


def orient(p):
    spec = p["tags"].get("print", "")
    if spec and spec != "auto" and not re.fullmatch(r"\s*[xyz]\s*-?[0-9.]+(\s*,\s*[xyz]\s*-?[0-9.]+)*\s*", spec):
        say("print: %s has unknown print=%s (use x180, x90,z45 or auto); printing as modelled" % (p["id"], spec))
        p["tags"]["print"] = ""
        return ""
    if spec == "auto":
        best = None
        for o in ORIENTS:
            t = p["tri"] @ rot_matrix(o).T
            a, _, _ = overhang(t)
            h = t[:, :, 2].max() - t[:, :, 2].min()
            if best is None or (a, h) < (best[1], best[2]):
                best = (o, a, h)
        spec = best[0]
    return spec


def write_3mf(path, items, title):
    mats, objs, comps = [], [], []
    for it in items:
        m = it["mat"]
        if m not in [x[0] for x in mats]:
            mats.append((m, it["color"]))
    oid = 2
    for it in items:
        v, f = weld(it["tri"], 5)
        f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
        vs = "".join('<vertex x="%.5f" y="%.5f" z="%.5f"/>' % tuple(x) for x in v)
        ts = "".join('<triangle v1="%d" v2="%d" v3="%d"/>' % tuple(x) for x in f)
        pi = [x[0] for x in mats].index(it["mat"])
        objs.append('<object id="%d" type="model" name="%s" pid="1" pindex="%d"><mesh><vertices>%s</vertices><triangles>%s</triangles></mesh></object>' % (oid, xml_esc(it["name"]), pi, vs, ts))
        comps.append('<component objectid="%d"/>' % oid)
        oid += 1
    base = "".join('<base name="%s" displaycolor="%sFF"/>' % (xml_esc(m), (c or "#888888").upper()[:7]) for m, c in mats)
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             '<metadata name="Title">%s</metadata><resources><basematerials id="1">%s</basematerials>%s'
             '<object id="%d" type="model" name="%s"><components>%s</components></object></resources>'
             '<build><item objectid="%d"/></build></model>') % (xml_esc(title), base, "".join(objs), oid, xml_esc(title), "".join(comps), oid)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr("3D/3dmodel.model", model)


def read_3mf(path):
    """objects -> (name, triangles) from a 3MF written by write_3mf (used by the self-check)"""
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    root = ET.fromstring(zipfile.ZipFile(path).read("3D/3dmodel.model"))
    out = []
    for o in root.iter("{%s}object" % ns["m"]):
        mesh = o.find("m:mesh", ns)
        if mesh is None:
            continue
        v = np.array([[float(x.get(k)) for k in "xyz"] for x in mesh.iter("{%s}vertex" % ns["m"])])
        f = np.array([[int(x.get(k)) for k in ("v1", "v2", "v3")] for x in mesh.iter("{%s}triangle" % ns["m"])])
        out.append((o.get("name"), v[f]))
    return out


def xml_esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def safe(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "part"


def float_note(fn, tris):
    """pieces resting on nothing: not on the bed and not touching (within 0.1 mm) a supported piece"""
    M = m3()
    if M is None:
        return
    pcs = []
    for tri in tris:
        man = manifold({"tri": tri})
        if man is not None:
            pcs += man.decompose()
    sup = [c.bounding_box()[2] < 0.05 for c in pcs]
    grew = True
    while grew:
        grew = False
        for i, c in enumerate(pcs):
            if sup[i]:
                continue
            for j, d in enumerate(pcs):
                if sup[j] and not bbox_far(c, d, 0.1) and c.min_gap(d, 0.1) <= 0.1:
                    sup[i] = grew = True
                    break
    up = [c.bounding_box()[2] for c, s_ in zip(pcs, sup) if not s_]
    if up:
        FAULTS["found"] += 1
        say("print: %s has %d of %d pieces resting on nothing (lowest at z %.1f) - they would print in mid-air; split them into their own parts or support them" % (
            fn, len(up), len(pcs), min(up)))


def drop_pieces(fn, tri):
    """separate pieces of one printed part: each placed on the bed where it stands in x,y"""
    man = manifold({"tri": tri})
    if man is None:
        return tri, ""
    cs = man.decompose()
    if len(cs) < 2 or all(c.bounding_box()[2] < 0.05 for c in cs):
        return tri, ""
    moved = [c.translate([0, 0, -c.bounding_box()[2]]) for c in cs]
    hit = any((moved[i] ^ moved[j]).volume() > 0.01 for i in range(len(moved)) for j in range(i + 1, len(moved)))
    if hit:
        FAULTS["found"] += 1
        say("print: %s has pieces at different heights that collide when each is put on the bed - split them into their own parts" % fn)
        return tri, ""
    out = []
    for c in moved:
        mh = c.to_mesh()
        v = np.asarray(mh.vert_properties)[:, :3].astype(np.float64)
        out.append(v[np.asarray(mh.tri_verts)])
    return np.concatenate(out), " | %d separate pieces, each placed on the bed" % len(cs)


def print_set(parts, outdir, rev, scad, colors):
    if os.path.isdir(outdir):
        for f in os.listdir(outdir):
            os.remove(os.path.join(outdir, f))
    os.makedirs(outdir, exist_ok=True)
    pr = [p for p in parts if not p["hw"] and p.get("tri") is not None]
    plates, singles = {}, []
    for p in pr:
        (plates.setdefault(p["tags"]["plate"], []) if p["tags"].get("plate") else singles).append(p)
    lines, names, qtys = [], set(), {}

    def uniq(n):
        b, i = n, 2
        while n in names:
            n, i = "%s_%d" % (b, i), i + 1
        names.add(n)
        return n

    for p in singles:
        spec = orient(p)
        t = p["tri"] @ rot_matrix(spec).T
        lo, hi = t.reshape(-1, 3).min(0), t.reshape(-1, 3).max(0)
        t = t - np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
        fn = uniq(safe(p["label"])) + ".stl"
        t, note = drop_pieces(fn, t)
        write_stl(os.path.join(outdir, fn), t)
        a, span, fz = overhang(t)
        h = hi[2] - lo[2]
        h = t[:, :, 2].max() - t[:, :, 2].min()
        qtys[fn[:-4]] = p["qty"]
        lines.append("%s%s | %s | %.1f mm tall | overhang %.0f mm2%s%s" % (fn, " x%d" % p["qty"] if p["qty"] > 1 else "", spec or "as modelled", h, a,
                     " | widest flat underside %.1f mm at z %.1f" % (span, fz) if span > 0.5 else "", note))
    for name, ps in plates.items():
        specs = {orient(p) for p in ps if p["tags"].get("print")}
        spec = sorted(specs)[0] if specs else ""
        if len(specs) > 1:
            say("print: plate %s has members with different print= tags; using %s" % (name, spec or "as modelled"))
        R = rot_matrix(spec)
        ts = [p["tri"] @ R.T for p in ps]
        allp = np.concatenate([t.reshape(-1, 3) for t in ts])
        lo, hi = allp.min(0), allp.max(0)
        sh = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
        items = [{"name": p["label"], "tri": t - sh, "mat": p["tags"].get("mat") or p["label"], "color": colors.get(p["id"])} for p, t in zip(ps, ts)]
        fn = uniq(safe(name)) + ".3mf"
        write_3mf(os.path.join(outdir, fn), items, name)
        float_note(fn, [it["tri"] for it in items])
        back = read_3mf(os.path.join(outdir, fn))
        okv = all(abs(stats(b)["vol"] - stats(it["tri"])["vol"]) < max(0.5, 1e-3 * stats(it["tri"])["vol"]) for (_, b), it in zip(back, items))
        a, span, fz = overhang(np.concatenate([it["tri"] for it in items]))
        lines.append("%s | %s | %d bodies registered (%s) | %.1f mm tall | overhang %.0f mm2%s" % (
            fn, spec or "as modelled", len(items), ", ".join("%s=%s" % (it["name"], it["mat"]) for it in items), hi[2] - lo[2], a,
            "" if okv else " | RE-READ CHECK FAILED"))
    for l in lines:
        say("print: " + l)
    manifest(outdir, rev, scad, {k: v for k, v in qtys.items() if v > 1})
    say("print: %d files -> %s (rev %s)" % (len(lines), outdir, rev))


# ------------------------------------------------------------ section --------
def sections(parts, specs, base, size, clear, colors):
    import section as S
    ok = [p for p in parts if manifold(p) is not None]
    items = [(p["label"] + ("" if p["label"] == p["id"] else " (%s)" % p["id"]), p["man"], p["color"] or S.COLS[i % len(S.COLS)], p["id"])
             for i, p in enumerate(ok)]
    for spec in specs:
        out = "%s_section_%s.png" % (base, re.sub(r"[^A-Za-z0-9.+-]+", "_", spec))
        for l in S.section(items, spec, out, size, max(clear, 0.5)):
            say(l)


# ------------------------------------------------------------ sheets ---------
def components(tri):
    v, f = weld(tri)
    par = np.arange(len(v))

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    for a, b, c in f:
        ra, rb, rc = find(a), find(b), find(c)
        par[rb] = ra
        par[find(rc)] = ra
    root = np.array([find(x) for x in f[:, 0]])
    return [(v, f[root == r]) for r in np.unique(root)]


def outline(v, f, keep=False):
    pts = v[np.unique(f)]
    ext = pts.max(0) - pts.min(0)
    ax = int(np.argmin(ext))
    lo, hi = pts[:, ax].min(), pts[:, ax].max()
    on_lo, on_hi = np.abs(pts[:, ax] - lo) < 1e-3, np.abs(pts[:, ax] - hi) < 1e-3
    if not np.all(on_lo | on_hi) or ext[ax] < 0.05:
        return None
    face = f[np.all(np.abs(v[f][:, :, ax] - lo) < 1e-3, axis=1)]
    cnt = {}
    for t in face:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            k = (min(a, b), max(a, b))
            cnt[k] = cnt.get(k, 0) + 1
    adj = {}
    for (a, b), c in cnt.items():
        if c == 1:
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)
    u, w = [k for k in range(3) if k != ax]
    if ext[u] < ext[w] and not keep:
        u, w = w, u
    o = np.array([pts[:, u].min(), pts[:, w].min()])
    loops, seen = [], set()
    for s in adj:
        if s in seen:
            continue
        loop, prev, cur = [s], None, s
        seen.add(s)
        while True:
            nxt = [n for n in adj[cur] if n != prev]
            nxt = [n for n in nxt if n not in seen] or [n for n in nxt if n == s]
            if not nxt or nxt[0] == s:
                break
            prev, cur = cur, nxt[0]
            seen.add(cur)
            loop.append(cur)
        p2 = v[loop][:, [u, w]] - o
        kp = []
        for i in range(len(p2)):
            a, b, c = p2[i - 1], p2[i], p2[(i + 1) % len(p2)]
            if abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])) > 1e-6:
                kp.append(b)
        if len(kp) >= 3:
            loops.append(np.array(kp))
    if not loops:
        return None
    area = [abs(float(np.sum(l[:, 0] * np.roll(l[:, 1], -1) - np.roll(l[:, 0], -1) * l[:, 1])) / 2) for l in loops]
    holes3d = []
    for l, ar in zip(loops, area):
        cr = l[:, 0] * np.roll(l[:, 1], -1) - np.roll(l[:, 0], -1) * l[:, 1]
        sa = float(cr.sum()) / 2 or 1e-9
        c2 = np.array([float(((l[:, 0] + np.roll(l[:, 0], -1)) * cr).sum()), float(((l[:, 1] + np.roll(l[:, 1], -1)) * cr).sum())]) / (6 * sa) + o
        c3 = np.zeros(3)
        c3[u], c3[w], c3[ax] = c2[0], c2[1], (lo + hi) / 2
        holes3d.append({"c": c3, "ax": ax, "lo": float(lo), "hi": float(hi), "r": math.sqrt(ar / math.pi)})
    per = [float(np.sum(np.linalg.norm(l - np.roll(l, -1, axis=0), axis=1))) for l in loops]
    big = int(np.argmax(area))
    holes3d.pop(big)
    return {"o": o, "holes3d": holes3d, "loops": loops, "t": float(ext[ax]), "w": float(ext[u]), "h": float(ext[w]), "holes": len(loops) - 1,
            "area": area[big] - (sum(area) - area[big]), "cut": sum(per), "sig": (len(loops), round(sum(area), 1), round(sum(per), 1))}


def as_circle(l):
    if len(l) < 8:
        return None
    c = l.mean(0)
    r = np.linalg.norm(l - c, axis=1)
    e = np.linalg.norm(l - np.roll(l, -1, axis=0), axis=1)
    if (r.max() - r.min()) > 1e-3 * r.mean() or (e.max() - e.min()) > 0.02 * e.mean():
        return None
    return float(c[0]), float(c[1]), float(r.mean())


def write_dxf(path, loops, bends=(), t=0, kf=0.4):
    o = ["0", "SECTION", "2", "ENTITIES"]
    for l in loops:
        c = as_circle(l)
        if c:
            o += ["0", "CIRCLE", "8", "0", "10", "%.4f" % c[0], "20", "%.4f" % c[1], "40", "%.4f" % c[2]]
            continue
        o += ["0", "POLYLINE", "8", "0", "66", "1", "70", "1"]
        for x, y in l:
            o += ["0", "VERTEX", "8", "0", "10", "%.4f" % x, "20", "%.4f" % y]
        o += ["0", "SEQEND"]
    for x0, y0, x1, y1, a, r, par in bends:
        ba, L = (r + kf * t) * abs(a) * math.pi / 180, math.hypot(x1 - x0, y1 - y0)
        nx, ny = -(y1 - y0) / L * ba / 2, (x1 - x0) / L * ba / 2
        o += ["0", "LINE", "8", "BEND", "10", "%.4f" % (x0 + nx), "20", "%.4f" % (y0 + ny), "11", "%.4f" % (x1 + nx), "21", "%.4f" % (y1 + ny)]
    o += ["0", "ENDSEC", "0", "EOF"]
    open(path, "w").write("\n".join(o) + "\n")


def pieces(parts):
    out, skipped = [], []
    for p in parts:
        if p["hw"] or p.get("tri") is None:
            continue
        if p.get("bends"):
            fl = p["stl"][:-4] + ".flat.stl"
            cs = components(read_stl(fl)) if os.path.exists(fl) else []
            o = outline(*cs[0], keep=True) if len(cs) == 1 else None
            if o is None:
                skipped.append(p["id"] + " (flat pattern must be one flat piece)")
                continue
            o["bends"] = [[b[1] - o["o"][0], b[2] - o["o"][1], b[3] - o["o"][0], b[4] - o["o"][1], b[5], b[6], b[7]] for b in p["bends"]]
            o["kf"], o["size3d"] = p["kf"], sorted(p["st"]["hi"][k] - p["st"]["lo"][k] for k in range(3))
            out.append((p["id"], p.get("qty", 1), o))
            continue
        groups = {}
        for v, f in components(p["tri"]):
            o = outline(v, f)
            if o is None:
                skipped.append(p["id"])
                continue
            groups.setdefault(o["sig"], []).append(o)
        for n, (sig, g) in enumerate(sorted(groups.items(), key=lambda kv: -kv[1][0]["area"])):
            out.append((p["id"] + ("" if len(groups) == 1 else "_%d" % (n + 1)), len(g) * p.get("qty", 1), g[0]))
    return out, sorted(set(skipped))


def manifest(d, rev, scad, qty=None):
    import datetime
    files = sorted(f for f in os.listdir(d) if f != "MANIFEST.txt")
    files = [f + ("  x%d" % qty[f.rsplit(".", 1)[0]] if qty and f.rsplit(".", 1)[0] in qty else "") for f in files]
    open(os.path.join(d, "MANIFEST.txt"), "w").write("model %s\nrev %s\nmade %s\n%s\n" % (os.path.basename(scad), rev, datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "\n".join(files)))


def fold_solid(cq, flat, rows, t, kf):
    BIG = 1e4

    def box(b, d0, d1):
        ang = math.degrees(math.atan2(b[3] - b[1], b[2] - b[0]))
        return cq.Solid.makeBox(2 * BIG, d1 - d0, 2 * BIG, cq.Vector(-BIG, d0, -BIG)).rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), ang).translate(cq.Vector(b[0], b[1], 0))

    def node(i, solid):
        kids = [j for j, b in enumerate(rows) if b[6] == i]
        own = solid
        for j in kids:
            own = own.cut(box(rows[j], 0, BIG))
        out = [own]
        for j in kids:
            b = rows[j]
            a, r = b[4], b[5]
            L = math.hypot(b[2] - b[0], b[3] - b[1])
            ux, uy = (b[2] - b[0]) / L, (b[3] - b[1]) / L
            nx, ny = -uy, ux
            ba, zc = (r + kf * t) * abs(a) * math.pi / 180, (t + r if a > 0 else -r)
            A0, A1 = cq.Vector(b[0], b[1], zc), cq.Vector(b[0] + ux, b[1] + uy, zc)
            strip = solid.intersect(box(b, 0, ba))
            for f in strip.Faces():
                c = f.Center()
                if f.geomType() == "PLANE" and abs((c.x - b[0]) * nx + (c.y - b[1]) * ny) < 1e-6:
                    out.append(cq.Solid.revolve(f.outerWire(), f.innerWires(), abs(a), A0, A1) if a > 0 else cq.Solid.revolve(f.outerWire(), f.innerWires(), abs(a), A1, A0))
            for c in node(j, solid.intersect(box(b, ba, BIG))):
                out.append(c.translate(cq.Vector(-ba * nx, -ba * ny, 0)).rotate(A0, A1, a))
        return out

    ps = [q for q in node(-1, flat) if q.Volume() > 1e-6]
    res = ps[0]
    for q in ps[1:]:
        res = res.fuse(q)
    return res.clean(), sum(q.Volume() for q in ps)


def step(parts, stepdir, rev, scad):
    cq = need("cadquery")
    if cq is None:
        say("step: could not install cadquery (pip install cadquery), skipped")
        return
    os.makedirs(stepdir, exist_ok=True)
    ps, skipped = pieces(parts)
    bad = 0
    for name, qty, o in ps:
        ws, exp = [], 0.0
        big = int(np.argmax([abs(float(np.sum(l[:, 0] * np.roll(l[:, 1], -1) - np.roll(l[:, 0], -1) * l[:, 1])) / 2) for l in o["loops"]]))
        for i, l in enumerate(o["loops"]):
            c = as_circle(l) if i != big else None
            a = abs(float(np.sum(l[:, 0] * np.roll(l[:, 1], -1) - np.roll(l[:, 0], -1) * l[:, 1])) / 2)
            if c:
                ws.append(cq.Wire.makeCircle(c[2], cq.Vector(c[0], c[1], 0), cq.Vector(0, 0, 1)))
                a = math.pi * c[2] ** 2
            else:
                ws.append(cq.Wire.makePolygon([cq.Vector(float(x), float(y), 0) for x, y in l], close=True))
            exp += a if i == big else -a
        outer = ws.pop(big)
        sol = cq.Solid.extrudeLinear(outer, ws, cq.Vector(0, 0, o["t"]))
        want, note = exp * o["t"], ""
        if o.get("bends"):
            sol, want = fold_solid(cq, sol, o["bends"], o["t"], o["kf"])
            bb = sol.BoundingBox()
            got = sorted([bb.xlen, bb.ylen, bb.zlen])
            if max(abs(g - m) for g, m in zip(got, o["size3d"])) > 0.5:
                note = " folded size %s differs from the OpenSCAD model %s" % ([round(g, 1) for g in got], [round(m, 1) for m in o["size3d"]])
        f = os.path.join(stepdir, name + ".step")
        sol.exportStep(f)
        back = cq.importers.importStep(f)
        n, vol = len(back.solids().vals()), back.val().Volume()
        good = n == 1 and back.val().isValid() and abs(vol - want) < max(0.5, 1e-4 * vol) and not note
        if note:
            say("STEP %s:%s" % (name, note))
        bad += not good
        if not good:
            say("STEP %s: FAILED re-import check (solids %d, vol %.1f, expected %.1f)" % (name, n, vol, want))
    manifest(stepdir, rev, scad, {n: q for n, q, _ in ps})
    nb = sum(1 for _, _, o in ps if o.get("bends"))
    say("step: %d solids written and re-imported (%d folded, cross-checked against the OpenSCAD fold), %d failed -> %s (rev %s)" % (len(ps), nb, bad, stepdir, rev))
    if skipped:
        say("step: not flat, skipped: " + ", ".join(skipped))


def cut(parts, cutdir, rev, scad):
    os.makedirs(cutdir, exist_ok=True)
    rows = []
    ps, skipped = pieces(parts)
    for name, qty, o in ps:
        write_dxf(os.path.join(cutdir, name + ".dxf"), o["loops"], o.get("bends", ()), o["t"], o.get("kf", 0.4))
        rows.append((name, qty, o["w"], o["h"], o["t"], o["holes"], o["cut"], o["area"], len(o.get("bends", ()))))
    say("cut: file | qty | size mm | t | holes | cut mm | bends")
    for r in rows:
        say("%s | %d | %.1f x %.1f | %.2g | %d | %.0f | %d" % (r[:7] + (r[8],)))
    with open(os.path.join(cutdir, "cutlist.csv"), "w") as fh:
        fh.write("file,qty,width_mm,height_mm,thickness_mm,holes,cut_length_mm,area_mm2,bends\n")
        for r in rows:
            fh.write("%s.dxf,%d,%.2f,%.2f,%.2f,%d,%.1f,%.1f,%d\n" % r)
    tot = sum(r[1] * r[6] for r in rows)
    manifest(cutdir, rev, scad, {n: q for n, q, _ in ps})
    say("cut: %d files, %d pieces, %.1f m total cut length -> %s (rev %s)" % (len(rows), sum(r[1] for r in rows), tot / 1000, cutdir, rev))
    if skipped:
        say("cut: not flat, skipped: " + ", ".join(skipped))


def holes(parts, gap, dmax=30):
    hs = []
    for p in parts:
        if p["hw"] or p.get("tri") is None:
            continue
        for n, (v, f) in enumerate(components(p["tri"])):
            o = outline(v, f)
            for h in (o["holes3d"] if o else []):
                if 2 * h["r"] <= dmax:
                    hs.append((p["id"], n, h))
    ok = bad = 0
    for i in range(len(hs)):
        for j in range(i + 1, len(hs)):
            (ia, na, a), (ib, nb, b) = hs[i], hs[j]
            if (ia, na) == (ib, nb) or a["ax"] != b["ax"] or max(a["lo"], b["lo"]) - min(a["hi"], b["hi"]) > gap:
                continue
            d = a["c"] - b["c"]
            d[a["ax"]] = 0
            off = float(np.linalg.norm(d))
            if off < 0.02:
                ok += 1
            elif off < a["r"] + b["r"]:
                bad += 1
                say("HOLES %s ~ %s: off by %.2f mm at x%.1f y%.1f z%.1f" % (ia, ib, off, a["c"][0], a["c"][1], a["c"][2]))
    say("holes: %d aligned pairs, %d misaligned, %d holes in sheets within %.2g mm" % (ok, bad, len(hs), gap))
    return ok, bad


# ------------------------------------------------------------ viewer ---------
def colours(parts):
    out, si, hi = {}, 0, 0
    for p in parts:
        c = p["color"]
        if not c:
            c = HW[hi % len(HW)] if p["hw"] else STEEL[si % len(STEEL)]
            hi, si = hi + p["hw"], si + (not p["hw"])
        out[p["id"]] = c
    return out


def html(sets, path, title, rev=""):
    data, xoff = [], 0.0
    multi = len(sets) > 1
    for vname, parts in sets:
        ok = [p for p in parts if p.get("tri") is not None]
        if not ok:
            continue
        allp = np.concatenate([p["tri"].reshape(-1, 3) for p in ok])
        lo, hi = allp.min(0), allp.max(0)
        c = (lo + hi) / 2
        cols = colours(parts)
        shift = [xoff - lo[0], 0, 0] if multi else [0, 0, 0]
        for p in ok:
            s = p["st"]
            pc = (np.array(s["lo"]) + np.array(s["hi"])) / 2
            dims = " x ".join("%g" % round(d, 1 if d < 10 else 0) for d in sorted((s["hi"][k] - s["lo"][k] for k in range(3)), reverse=True)) + " mm"
            data.append({"id": p["id"], "label": p["label"], "note": (p["note"] + ", " if p["note"] else "") + dims + (", make %d" % p["qty"] if p.get("qty", 1) > 1 else ""), "hw": p["hw"], "color": cols[p["id"]],
                         "ex": p["ex"] if p["ex"] is not None else ((pc - c) * 0.9).round(1).tolist(), "variant": vname or "", "shift": shift,
                         "b64": base64.b64encode(open(p["stl"], "rb").read()).decode()})
        xoff += (hi[0] - lo[0]) * 1.25 + 10
    tpl = open(os.path.join(HERE, "view3d.html")).read()
    open(path, "w").write(tpl.replace("__TITLE__", xml_esc(title)).replace("__REV__", rev).replace("__PARTS__", json.dumps(data)))
    say("html: %s (%d kB) - interactive, for the human; present unviewed" % (path, os.path.getsize(path) // 1024))


# ------------------------------------------------------------ selftest -------
SELF = """part="all";
h = 6;
parts = [
  ["a","Plate A","",[0,0,0],"group=pa"],["b","Plate B"],["c","Block","",[0,0,0],"group=blk","print=x180"],["d","Pin","",[0,0,0],"plate=p1","mat=TPU"],["e","Sleeve","",[0,0,0],"plate=p1","mat=PETG"]
];
checks = [ ["c","b","==",0], ["d","e",">=",0.45], ["d","e","<=",0.4], ["a","b","touch"] ];
travel = [ ["blk",[0,0,1]] ];
report = [ ["block top", 3+h] ];
module pick(n){ if(part=="all"||part==n) children(); }
pick("a") difference(){ cube([40,30,2]); translate([10,10,-1]) cylinder(d=4,h=4,$fn=24); translate([30,20,-1]) cylinder(d=4,h=4,$fn=24); }
pick("b") translate([0,0,2]) difference(){ cube([40,30,2]); translate([11,10,-1]) cylinder(d=4,h=4,$fn=24); translate([30,20,-1]) cylinder(d=4,h=4,$fn=24); }
pick("c") translate([35,25,3]) cube([5,5,h]);
pick("d") translate([60,0,0]) cylinder(d=4,h=10,$fn=32);
pick("e") translate([60,0,0]) difference(){ cylinder(d=8,h=8,$fn=32); translate([0,0,-1]) cylinder(d=5,h=10,$fn=32); }
"""


def selftest():
    import tempfile, io, contextlib
    d = tempfile.mkdtemp()
    f = os.path.join(d, "t.scad")
    open(f, "w").write(SELF)
    res = []
    say("engine: " + engine())

    def run(*args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main([f] + list(args))
        return buf.getvalue()

    out = run("--clash", "--travel", "--walls", "--print", "--section", "x=37")
    res.append(("clash finds the planted 25 mm3 overlap with its depth", re.search(r"OVERLAP b x c: 25\.0 mm3, depth ~1\.00", out) is not None))
    res.append(("checks: planted ==0 and <=0.4 fail, >=0.45 and touch pass", "checks: 2 pass, 2 FAIL" in out and "CHECK FAIL c ~ b ==" in out and "CHECK FAIL d ~ e <=" in out))
    res.append(("travel: block moving 1 mm down hits plate B", re.search(r"travel blk: 2 poses, 1 with overlap", out) is not None and "OVERLAP c x b at 1/2 poses; worst depth ~2.00 mm" in out))
    res.append(("walls: 2 mm plates read as 2.00 mm", re.search(r"walls a: nothing under 1\.2 mm \(thinnest 2\.00", out) is not None))
    res.append(("print: block flipped, pin+sleeve in one 3MF", "Block.stl | x180" in out and re.search(r"p1\.3mf \| as modelled \| 2 bodies registered", out) is not None and "RE-READ" not in out))
    res.append(("section x=37: b and c overlap 5 mm2 in plane, in world coordinates", "OVERLAP in plane b x c: 5.00 mm2" in out and "c: y[25.00,30.00] z[3.00,9.00]" in out))
    res.append(("report table printed", "report: block top 9" in out))
    out2 = run("--holes")
    res.append(("holes: 1 aligned pair, 1 planted 1 mm miss", "holes: 1 aligned pair" in out2 and "1 misaligned" in out2))
    open(f, "w").write(SELF.replace("h = 6;", "h = 9;"))
    outo = run("--only", "a")
    out3 = run("--all")
    res.append(("--only then full run re-exports the changed part (no stale STL)", re.search(r"c: 5\.0 x 5\.0 x 9\.0", out3) is not None and "a: 40.0 x 30.0 x 2.0 | vol 2350 (unchanged)" in out3))
    res.append(("report table shows the change", "report: block top 12 (+3)" in outo))
    open(f, "w").write(SELF.replace("h = 6;", "h = 9;").replace("translate([10,10,-1]) cylinder", "translate([10,12,-1]) cylinder"))
    out4 = run()
    res.append(("moving an internal hole reports 'same size, shape changed'", "a: " in out4 and "same size, shape changed" in out4))
    res.append(("cache: untouched parts are not re-rendered", "1 rendered" in out4))
    t = read_stl(os.path.join(d, "t_parts", "c.stl"))
    res.append(("watertight check flags a mesh with a missing triangle", open_edges(t) == 0 and open_edges(t[1:]) == 3))
    o = outline(*components(read_stl(os.path.join(d, "t_parts", "b.stl")))[0])
    res.append(("cut outline area x thickness = volume", o is not None and o["holes"] == 2 and abs(o["area"] * o["t"] - stats(read_stl(os.path.join(d, "t_parts", "b.stl")))["vol"]) < 0.5))
    fb = os.path.join(d, "b.scad")
    open(fb, "w").write('use <sheet.scad>\npart="all";\nfold([["l",0,20,30,20,90,1,-1]],2,0.4,false) square([30,20+bend_allow(90,1,2)+15]);\n')
    fs = os.path.join(d, "b.stl")
    run_scad(["-o", fs, "--export-format", "binstl", fb])
    st = stats(read_stl(fs)) if os.path.exists(fs) else None
    res.append(("fold: 90 degree flange lands at y 23, z 18", bool(st) and abs(st["hi"][1] - 23) < 0.05 and abs(st["hi"][2] - 18) < 0.05))
    fs2 = os.path.join(d, "sw.scad")
    open(fs2, "w").write("big=false;\nif(big) cube(20); else cube(5);\n")
    sw = subprocess.run(["bash", os.path.join(HERE, "render.sh"), fs2, "--sweep", "big=false,true"], capture_output=True, text=True).stdout
    res.append(("render.sh --sweep passes booleans as booleans", "size 5.00 x 5.00" in sw and "size 20.00 x 20.00" in sw))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main([f, "--only", "a", "--check"])
    res.append(("--only skips checks on parts outside the subset", "skipped (parts outside --only)" in buf.getvalue() and "FAIL" not in buf.getvalue().split("checks:")[-1].split("skipped")[0].replace("0 FAIL", "")))
    f2 = os.path.join(d, "rw.scad")
    rw = """part="all";
travel = 2;
parts = [ ["k","Knob","",[0,0,0],"group=k"], ["s","Spring","",[0,0,0],"flex=1"], ["b","Bumpers"], ["p","Pin","",[0,0,0],"plate=pl"], ["c","Cap","",[0,0,0],"plate=pl"] ];
travel = [ ["k",[1,0,0]] ];
report = [ ["top", ktop] ];
ktop = 9;
module pick(n){ if(part=="all"||part==n) children(); }
pick("k") cube(5);
pick("s") translate([5.5,0,0]) cube([1,5,5]);
pick("b") { translate([20,0,0]) cube(3); translate([30,0,5]) cube(3); }
pick("p") translate([40,0,0]) cube([3,3,8]);
pick("c") translate([40,0,10]) cube([3,3,2]);
"""
    open(f2, "w").write(rw)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            main([f2])
        msg = ""
    except SystemExit as e:
        msg = str(e)
    res.append(("a model parameter named like a table stops with a name-clash message", "`travel` is assigned twice" in msg))
    open(f2, "w").write(rw.replace("travel = 2;", "travel_mm = 2;"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main([f2, "--travel", "--print"])
    o5 = buf.getvalue()
    res.append(("a table above the value it uses says so", "top undef (is it defined below" in o5))
    res.append(("flex=1 parts are left out of travel", "ignoring s" in o5 and "0 with overlap" in o5))
    res.append(("print: separate pieces go on the bed; a mid-air plate piece is flagged", "2 separate pieces, each placed on the bed" in o5 and "pl.3mf has 1 of 2 pieces resting on nothing" in o5))
    f3 = os.path.join(d, "fx.scad")
    open(f3, "w").write("""part="all";
parts = [ ["k","Knob"], ["s","Spring","",[0,0,0],"flex=k"], ["w","Wall"], ["b","Base","",[0,0,0],"plate=pl","qty=3"], ["l","Liner","",[0,0,0],"plate=pl"] ];
travel = [ ["k",[1,0,0],"name=push"], ["k",[0,0,1],"name=lift"], ["s",[0.6,0,0]] ];
module pick(n){ if(part=="all"||part==n) children(); }
pick("k") cube(5);
pick("s") translate([5,0,0]) cube([2,5,5]);
pick("w") translate([7.5,0,0]) cube([1,5,5]);
pick("b") translate([20,0,0]) cube([5,5,4]);
pick("l") translate([20,0,4.02]) cube([5,5,1]);
""")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main([f3, "--clash", "--travel", "--print"])
    o6 = buf.getvalue()
    res.append(("flex=k: spring may touch the knob, not the wall", "1 flex contacts allowed" in o6 and "OVERLAP s x w" in o6 and "s x k" not in o6 and "k x s" not in o6))
    res.append(("travel: several named rows per group", "travel push: 2 poses" in o6 and "travel lift: 2 poses" in o6))
    res.append(("print: a liner resting 0.02 mm above its body is supported; qty shown", "resting on nothing" not in o6 and "pl.3mf" in o6))
    for name, good in res:
        print(("PASS " if good else "FAIL ") + name)
    allok = all(g for _, g in res)
    print("selftest: " + ("PASS" if allok else "FAIL (outputs in %s)" % d))
    if not allok:
        print(out + out2 + out3 + out4)
    return allok


# ------------------------------------------------------------ main -----------
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("scad", nargs="?")
    ap.add_argument("--holes", nargs="?", const=1.0, type=float, default=None)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--html", action="store_true")
    ap.add_argument("--clash", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--clear", type=float, default=0)
    ap.add_argument("--travel", nargs="?", const="", default=None)
    ap.add_argument("--section", action="append", default=[])
    ap.add_argument("--ignore", default="")
    ap.add_argument("--size", type=int, default=720)
    ap.add_argument("--walls", nargs="?", const=1.2, type=float, default=None)
    ap.add_argument("--print", dest="prnt", action="store_true")
    ap.add_argument("--variant", default="")
    ap.add_argument("--cut", action="store_true")
    ap.add_argument("--step", action="store_true")
    ap.add_argument("--bundle", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--title", default="")
    a = ap.parse_args(argv)
    if a.selftest or not a.scad:
        return selftest() if a.selftest else ap.print_usage()
    if engine().startswith("none"):
        sys.exit("asm.py: no OpenSCAD found - run scripts/setup.sh")
    if a.only and (a.prnt or a.html or a.bundle or a.cut or a.step):
        sys.exit("asm.py: --only checks a subset; --print/--html/--bundle/--cut/--step need every part - run them without --only")
    sys.path.insert(0, HERE)
    import section as S
    for spec in a.section:
        S.parse(spec)
    IGNORE.update(x for x in a.ignore.split(",") if x)
    base = os.path.splitext(a.scad)[0]
    t0 = evaluate(a.scad, [], base + "_parts")
    vs = t0.get("variants") or [None]
    if t0.get("variants") and t0.get("variant") is None:
        say("variants: the model has a `variants` table but no `variant` variable, so every set would be identical - using one set")
        vs = [None]
    if a.variant:
        want = a.variant.split(",")
        vs = [v for v in vs if str(v) in want] or sys.exit("asm.py: no such variant (have %s)" % t0.get("variants"))
    rev = hash_files(deps(a.scad))[:7]
    sets = []
    for v in vs:
        defs = [("variant", v)] if v is not None else []
        PFX[0] = "[%s] " % v if v is not None else ""
        sub = "" if v is None else os.sep + safe(str(v))
        t = t0 if v is None else evaluate(a.scad, defs, base + "_parts" + sub)
        parts = parse_parts(t["parts"])
        if a.only:
            parts = [p for p in parts if p["id"] in a.only.split(",")]
        outdir = base + "_parts" + sub
        kf = t.get("k_factor") if isinstance(t.get("k_factor"), (int, float)) else 0.4
        for p in parts:
            p["bends"], p["kf"] = [b for b in (t.get("bends") or []) if b and b[0] == p["id"]], kf
        for w_ in t.get("_warn") or []:
            say("model: " + w_)
        n = load(a.scad, parts, outdir, defs, t.get("_warn") or [])
        report(parts, outdir, a.all, n)
        dims_report(t.get("report"), outdir)
        poses = travel_poses(parts, t.get("travel"), None) if t.get("travel") else {}
        if a.travel:
            g, _, mm = a.travel.partition(":")
            if mm:
                try:
                    poses = travel_poses(parts, [[g, [float(mm), float(mm), float(mm)]]], None)
                except ValueError:
                    sys.exit("asm.py: --travel GROUP:MM needs a number after the colon")
            else:
                poses = {k: x for k, x in poses.items() if k == g or x[0] == g}
                if not poses:
                    say("travel %s: not in the travel table (rows: %s); use --travel %s:MM for an ad hoc check" % (g, ", ".join(sorted(travel_poses(parts, t.get("travel"), None))) or "none", g))
        if a.clash or a.clear > 0:
            clash(parts, a.clear)
        if (a.clash or a.check or a.travel is not None) and t.get("checks"):
            run_checks(parts, t["checks"], poses if a.travel is not None or any("travel" in r[3:] for r in t["checks"] if isinstance(r, list)) else None,
                       subset=a.only or None)
        if a.travel is not None:
            if not poses and not a.travel:
                say("travel: no `travel` table rows (or pass --travel GROUP:MM)")
            travel(parts, poses, a.clear)
        if a.section:
            sections(parts, a.section, base + sub.replace(os.sep, "_"), a.size, a.clear, colours(parts))
        if a.walls is not None:
            walls(parts, a.walls)
        if a.holes is not None:
            holes(parts, a.holes)
        if a.cut:
            cut(parts, base + "_cut" + sub, rev, a.scad)
        if a.step:
            step(parts, base + "_step" + sub, rev, a.scad)
        if a.prnt or a.bundle:
            print_set(parts, base + "_print" + sub, rev, a.scad, colours(parts))
        sets.append((v, parts))
    PFX[0] = ""
    if a.html or a.bundle:
        html(sets, base + ".html", a.title or os.path.basename(base), rev)
    if a.bundle:
        z = "%s_%s.zip" % (base, rev)
        root = os.path.dirname(os.path.abspath(a.scad))
        old = [f for f in os.listdir(root) if re.fullmatch(re.escape(os.path.basename(base)) + r"_[0-9a-f]{7}\.zip", f) and f != os.path.basename(z)]
        for f in old:
            os.remove(os.path.join(root, f))
        got = set()
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(deps(a.scad)):
                if f.startswith(root + os.sep) and f.endswith(".scad"):
                    zf.write(f, os.path.relpath(f, root))
            stale = []
            for d in (base + "_print", base + "_cut", base + "_step"):
                for dp, _, fns in os.walk(d):
                    mf = os.path.join(dp, "MANIFEST.txt")
                    if not fns:
                        continue
                    if not os.path.exists(mf) or ("rev %s\n" % rev) not in open(mf).read():
                        stale.append(os.path.relpath(dp, root))
                        continue
                    got.add(os.path.basename(d).rsplit("_", 1)[-1])
                    for fn in sorted(fns):
                        zf.write(os.path.join(dp, fn), os.path.relpath(os.path.join(dp, fn), root))
            zf.write(base + ".html", os.path.basename(base) + ".html")
        say("bundle: %s (model + %s + viewer, all rev %s; hardware left out)" % (z, " + ".join({"print": "print files", "cut": "cut files", "step": "STEP files"}[k] for k in ("print", "cut", "step") if k in got) or "no fabrication files", rev))
        if old:
            say("bundle: removed older bundle%s %s so only the current one can be sent" % ("s" if len(old) > 1 else "", ", ".join(old)))
        if stale:
            say("bundle: left out %s - made from an older revision; rerun with --cut/--step to include" % ", ".join(stale))


if __name__ == "__main__":
    r = main()
    if r is not None:
        sys.exit(0 if r else 1)
    sys.exit(1 if FAULTS["render"] else 2 if FAULTS["found"] else 0)
