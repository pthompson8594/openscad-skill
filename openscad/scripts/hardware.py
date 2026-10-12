#!/usr/bin/env python3
"""hardware.py - standard fastener data: real lengths, length picking, table generation.

  hardware.py sizes                      sizes and heads available
  hardware.py lengths M3 [--head socket] lengths you can buy (standard + commonly stocked)
  hardware.py pick M3 --grip 9.5 --nut   shortest real length that clears a nut by 1-2 threads
  hardware.py pick M3 --grip 6 --into 8  longest real length that stops 0.5 mm short in 8 mm of thread
  hardware.py gen                        rewrite lib/hw_tables.scad from lib/hw_tables.json

grip = distance from the screw's seat (under the head; for countersunk heads the top
surface) to the far face of the clamped stack, in mm (inch sizes too). Data and sources:
lib/hw_tables.json.
"""
import argparse, json, math, os, sys
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(os.path.dirname(HERE), "lib")
INCH = 25.4
STD = {"socket": "iso4762", "button": "iso7380", "flat": "iso10642", "hex": "iso4017"}


def data():
    return json.load(open(os.path.join(LIB, "hw_tables.json")))


def is_inch(size):
    return not size.upper().startswith("M")


def norm(size):
    s = size.strip()
    return s.upper() if s[:1] in "mM" else s


def lengths(d, size, head="socket", extras=True):
    """[(length_mm, label, kind)] sorted; kind = 'standard' | 'common' | 'stock'"""
    size = norm(size)
    out = []
    if is_inch(size):
        tab = d["screw_lengths"]["asme_b18_3_shcs"]["sizes"]
        for v in tab.get(size, []):
            out.append((v * INCH, frac(v), "stock"))
    else:
        tab = d["screw_lengths"].get(STD.get(head.split()[0], "iso4762"), d["screw_lengths"]["iso4762"])["sizes"].get(size)
        if tab:
            for v in tab.get("standard", []):
                out.append((float(v), "%g mm" % v, "standard"))
            if extras:
                for v in tab.get("common_extra", []):
                    out.append((float(v), "%g mm" % v, "common"))
    return sorted(set(out))


GAUGE = {"#0": 0.060, "#1": 0.073, "#2": 0.086, "#3": 0.099, "#4": 0.112, "#5": 0.125, "#6": 0.138, "#8": 0.164, "#10": 0.190, "#12": 0.216}


def diameter_mm(size):
    """nominal major diameter in mm (UTS numbered sizes per ASME B1.1 gauge diameters)"""
    size = norm(size)
    if not is_inch(size):
        return float(size[1:])
    head = size.split("-")[0]
    if head in GAUGE:
        return GAUGE[head] * INCH
    return float(Fraction(head)) * INCH


def frac(v):
    f = Fraction(round(v * 64), 64)
    w, r = divmod(f.numerator, f.denominator)
    if not r:
        return '%d"' % w
    return ('%d-%d/%d"' % (w, r, f.denominator)) if w else ('%d/%d"' % (r, f.denominator))


def nut(d, size, kind="normal"):
    n = d["nuts"]["sizes"].get(norm(size))
    if not n:
        return None
    k = n.get(kind) or n.get("normal")
    return {"pitch": n["pitch"], "thickness": k["thickness"], "width": k["width"], "kind": kind if kind in n else "normal"}


def washer_t(d, size, series):
    w = d["washers"]
    if is_inch(size):
        key = size.split("-")[0]
        row = w["uss_sae"]["sizes"].get(key, {})
        r = row.get(series) or row.get("sae") or row.get("uss")
        return r["t"] * INCH if r else None
    r = w["iso7089"]["sizes"].get(norm(size))
    return float(r["h"]) if r else None


def fmt(mm, inch):
    if not inch:
        return "%g mm" % round(mm, 2)
    return "%.2f mm (%s)" % (mm, frac(mm / INCH)) if abs(mm / INCH * 64 - round(mm / INCH * 64)) < 0.15 else "%.2f mm (about %s)" % (mm, frac(mm / INCH))


def pick(d, size, grip, head="socket", nutkind=None, washers=0, wseries="sae", into=None, protrude=2.0, extras=True):
    size = norm(size)
    inch = is_inch(size)
    L = lengths(d, size, head, extras)
    if not L:
        return ["no length data for %s %s - look up a stockist table" % (size, head)]
    stack = grip
    wt = 0.0
    if washers:
        wt = washer_t(d, size, wseries) or 0.0
        stack += washers * wt
    lines = []
    lab = lambda x: "%s%s" % (x[1], "" if x[2] in ("standard", "stock") else " (common, not in the ISO series)")
    if into is not None:
        ok = [x for x in L if stack < x[0] <= stack + into - 0.5 + 1e-6]   # 0.5 mm short of the bottom
        d_nom = diameter_mm(size)
        if ok:
            best = ok[-1]
            eng = best[0] - stack
            lines.append("use %s %s - engages %s of the %s available, %s short of the bottom (rule of thumb: about %s in steel, twice that in aluminium or plastic)" % (
                size, lab(best), fmt(eng, inch), fmt(into, inch), fmt(into - eng, inch), fmt(1.0 * d_nom, inch)))
            if eng < 1.0 * d_nom:
                lines.append("   short engagement: deepen the threaded hole or insert, or thin the clamped part")
        else:
            longer = [x for x in L if x[0] > stack + into - 0.5 + 1e-6]
            shorter = [x for x in L if x[0] <= stack]
            if shorter:
                lines.append("no length fits: %s %s doesn't reach the thread" % (size, lab(shorter[-1])))
            if longer:
                lines.append("   %s %s would bottom out - make the threaded depth %s or more" % (size, lab(longer[0]), fmt(longer[0][0] - stack + 0.5, inch)))
        return lines
    if nutkind:
        n = nut(d, size, nutkind)
        if not n:
            return ["no nut data for %s" % size]
        need = stack + n["thickness"] + protrude * n["pitch"]
        full = stack + n["thickness"]
        ok = [x for x in L if x[0] >= need - 1e-6]
        short = [x for x in L if x[0] < need - 1e-6]
        if ok:
            b = ok[0]
            lines.append("use %s %s - %s past the %s nut (%s thick)%s" % (
                size, lab(b), fmt(b[0] - full, inch), n["kind"], fmt(n["thickness"], inch),
                "" if not washers else ", %d washer%s %s each" % (washers, "s" if washers > 1 else "", fmt(wt, inch))))
            if b[0] - need > 3 * n["pitch"] + 2:
                lines.append("   that's long: the tip sticks out %s - check nothing behind the nut is in the way" % fmt(b[0] - full, inch))
        else:
            lines.append("no listed length reaches %s; longest is %s" % (fmt(need, inch), lab(L[-1])))
        if short:
            s = short[-1]
            gap = need - s[0]
            if s[0] >= full:
                lines.append("   or %s %s: only %s past the nut (less than %g threads) - fine if it can't loosen" % (size, lab(s), fmt(s[0] - full, inch), protrude))
            else:
                alt = nut(d, size, "thin") if n["kind"] == "normal" else None
                tip = " or use a thin nut (%s)" % fmt(alt["thickness"], inch) if alt and alt["thickness"] < n["thickness"] and s[0] >= stack + alt["thickness"] + protrude * n["pitch"] else ""
                lines.append("   or %s %s: make the clamped stack %s thinner%s" % (size, lab(s), fmt(gap, inch), tip))
        return lines
    ok = [x for x in L if x[0] >= stack - 1e-6]
    lines.append(("shortest %s that passes %s: %s" % (size, fmt(stack, inch), lab(ok[0]))) if ok else "nothing listed is %s long" % fmt(stack, inch))
    return lines


def gen(d):
    def s(v):
        return json.dumps(v)
    rows = []
    for std, t in d["screw_lengths"].items():
        for size, v in t["sizes"].items():
            if isinstance(v, dict):
                rows.append("  [%s,%s,%s,%s]" % (s(std), s(size), s([float(x) for x in v.get("standard", [])]), s([float(x) for x in v.get("common_extra", [])])))
            else:
                rows.append("  [%s,%s,%s,[]]" % (s(std), s(size), s([round(x * INCH, 4) for x in v])))
    wash = []
    for size, r in d["washers"]["iso7089"]["sizes"].items():
        wash.append("  [%s,\"iso7089\",%g,%g,%g]" % (s(size), r["d1"], r["d2"], r["h"]))
    for size, r in d["washers"]["uss_sae"]["sizes"].items():
        for ser, v in r.items():
            if isinstance(v, dict) and "id" in v:
                wash.append("  [%s,%s,%g,%g,%g]" % (s(size), s(ser), round(v["id"] * INCH, 3), round(v["od"] * INCH, 3), round(v["t"] * INCH, 3)))
    out = ("// GENERATED by scripts/hardware.py gen from hw_tables.json - do not edit; sources are listed there\n"
           "// lengths in mm: [standard, size, [standard lengths], [commonly stocked extra lengths]]\n"
           "HW_LENGTHS = [\n%s\n];\n// washers in mm: [size, series, inner d, outer d, thickness]\nHW_WASHERS = [\n%s\n];\n") % (",\n".join(rows), ",\n".join(wash))
    p = os.path.join(LIB, "hw_tables.scad")
    open(p, "w").write(out)
    print("wrote %s (%d length rows, %d washers)" % (p, len(rows), len(wash)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["sizes", "lengths", "pick", "gen"])
    ap.add_argument("size", nargs="?")
    ap.add_argument("--head", default="socket")
    ap.add_argument("--grip", type=float, help="seat to far face of the clamped parts, mm")
    ap.add_argument("--nut", nargs="?", const="normal", choices=["normal", "thin"])
    ap.add_argument("--washers", type=int, default=0, help="number of washers in the stack")
    ap.add_argument("--washer-series", default="sae", choices=["sae", "uss"])
    ap.add_argument("--into", type=float, help="thread depth available in a tapped hole or insert, mm")
    ap.add_argument("--protrude", type=float, default=2.0, help="threads wanted past the nut (default 2)")
    ap.add_argument("--standard-only", action="store_true", help="ignore commonly stocked non-ISO lengths")
    a = ap.parse_args(argv)
    d = data()
    if a.cmd == "gen":
        return gen(d)
    if a.cmd == "sizes":
        for size, hs in d["heads"]["sizes"].items():
            print("%-8s heads: %s" % (size, ", ".join(sorted(hs))))
        return
    if not a.size:
        sys.exit("hardware.py: give a size, e.g. M3 or #8-32")
    if a.cmd == "lengths":
        L = lengths(d, a.size, a.head, not a.standard_only)
        if not L:
            sys.exit("no length data for %s %s" % (a.size, a.head))
        print("%s %s: %s" % (norm(a.size), a.head, ", ".join(x[1] + ("*" if x[2] == "common" else "") for x in L)))
        if any(x[2] == "common" for x in L):
            print("   * commonly stocked, not in the ISO length series")
        if is_inch(a.size):
            print("   inch lengths are one supplier's stock (Bolt Depot), not a standard list")
        return
    if a.grip is None:
        sys.exit("hardware.py pick: --grip is required")
    for l in pick(d, a.size, a.grip, a.head, a.nut, a.washers, a.washer_series, a.into, a.protrude, not a.standard_only):
        print(l)


if __name__ == "__main__":
    main()
