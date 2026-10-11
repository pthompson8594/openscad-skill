#!/usr/bin/env node
// openscad-wasm.mjs — command-line stand-in for a recent OpenSCAD (Manifold engine),
// using the WebAssembly build from npm (openscad-wasm-prebuilt, OpenSCAD 2025.01).
// Called by oscad.sh; same arguments as `openscad`; cannot write PNG.
// Files the model reads (include/use/import, also from OPENSCADPATH) are copied
// into the engine's memory filesystem at their real paths; outputs are copied back.
import fs from "fs";
import path from "path";
import { pathToFileURL } from "url";

const here = path.dirname(new URL(import.meta.url).pathname);
const dirs = [process.env.OPENSCAD_WASM_DIR, path.join(process.env.HOME || "", ".cache/openscad-skill/wasm"), path.join(here, "wasm")];
const js = dirs.filter(Boolean).map((d) => path.join(d, "node_modules/openscad-wasm-prebuilt/dist/openscad.js")).find((f) => fs.existsSync(f));
if (!js) { console.error("ERROR: wasm OpenSCAD not installed (run setup.sh)"); process.exit(3); }
const { createOpenSCAD } = await import(pathToFileURL(js).href);

const args = process.argv.slice(2);
if (args.includes("--version") || args.includes("-v")) { console.error("OpenSCAD version 2025.01.19 (wasm, Manifold)"); process.exit(0); }
const VAL = new Set(["-o", "-d", "-m", "-D", "-p", "-P", "--export-format", "--backend", "--camera", "--imgsize", "--colorscheme", "--projection", "--view"]);

const fixed = [], outs = [];
let input = null;
for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (VAL.has(a)) {
    let v = args[++i];
    if (a === "-o" || a === "-d") { v = path.resolve(v); outs.push(v); }
    fixed.push(a, v);
  } else if (a.startsWith("-")) fixed.push(a);
  else { input = path.resolve(a); fixed.push(input); }
}
if (!input) { console.error("ERROR: no input file"); process.exit(1); }
if (outs.some((f) => /\.png$/i.test(f))) { console.error("ERROR: the wasm engine cannot render PNG"); process.exit(1); }

const H = process.env.HOME || "";
const libs = [...(process.env.OPENSCADPATH || "").split(path.delimiter).filter(Boolean),
  path.join(H, ".local/share/OpenSCAD/libraries"), path.join(H, "Documents/OpenSCAD/libraries")]
  .map((d) => path.resolve(d)).filter((d) => fs.existsSync(d));
const files = new Set();
let dynamic = false, budget = 1e9;
const MAXFILE = 200e6;
function regular(f) {           // only ordinary files of sane size: no devices, FIFOs or giant reads
  try { const st = fs.statSync(f); return st.isFile() && st.size <= MAXFILE && st.size <= budget ? st.size : -1; } catch (e) { return -1; }
}
function scan(f) {
  if (files.has(f)) return;
  const n = regular(f);
  if (n < 0) return;
  budget -= n;
  files.add(f);
  if (!/\.scad$/i.test(f)) return;
  const t = fs.readFileSync(f, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
  const d = path.dirname(f);
  for (const m of t.matchAll(/\b(?:include|use)\s*<([^>]+)>/g)) {
    const hit = [d, ...libs].map((b) => path.resolve(b, m[1])).find((p) => fs.existsSync(p));
    if (hit) scan(hit);
  }
  for (const m of t.matchAll(/\b(?:import|surface)\s*\(([^)]*)\)/g)) {
    const lit = m[1].match(/^\s*(?:file\s*=\s*)?"([^"]+)"/);
    if (lit) scan(path.resolve(d, lit[1]));
    else dynamic = true;
  }
}
scan(input);
if (dynamic) {
  const d = path.dirname(input);
  for (const e of fs.readdirSync(d)) {
    const p = path.join(d, e);
    try { if (fs.lstatSync(p).isSymbolicLink() || files.has(p)) continue; } catch (e2) { continue; }
    const n = regular(p);
    if (n >= 0) { budget -= n; files.add(p); }
  }
}

const o = await createOpenSCAD({
  noInitialRun: true,
  print: (s) => process.stdout.write(s + "\n"),
  printErr: (s) => { if (!/Could not initialize localization/.test(s)) process.stderr.write(s + "\n"); },
});
const m = o.getInstance();
const FS = m.FS;
const mkdirp = (p) => { let c = ""; for (const s of p.split("/").filter(Boolean)) { c += "/" + s; try { FS.mkdir(c); } catch (e) {} } };
for (const f of files) {
  const data = fs.readFileSync(f);
  mkdirp(path.dirname(f)); FS.writeFile(f, data);
  for (const d of libs) {
    if (f.startsWith(d + path.sep)) { const t = "/libraries/" + path.relative(d, f); mkdirp(path.dirname(t)); FS.writeFile(t, data); break; }
  }
}
for (const d of libs) mkdirp(d);
for (const f of outs) mkdirp(path.dirname(f));
if (m.ENV && libs.length) m.ENV.OPENSCADPATH = libs.join(":");
if (!fixed.some((a) => a.startsWith("--backend"))) fixed.unshift("--backend=Manifold");

let rc = 0;
try { rc = m.callMain(fixed); }
catch (e) { rc = typeof e?.status === "number" ? e.status : 1; if (typeof e?.status !== "number") console.error("ERROR: " + e); }
for (const f of outs) { try { fs.writeFileSync(f, FS.readFile(f)); } catch (e) {} }
process.exit(rc);
