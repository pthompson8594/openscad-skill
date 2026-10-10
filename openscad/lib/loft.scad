// loft.scad - smooth revolved solids with a per-angle modifier (no CSG creases).
// rev_loft(profile, n, mod): profile = [[r,z],...] from bottom to top, r >= 0;
//   an end with r = 0 closes on the axis, otherwise it gets a flat cap.
// mod = function(a, i, p) -> [r,z]: reshape point i (p = [r,z]) at angle a (degrees),
//   e.g. a thumb dish that fades in over 60 degrees with no seam.
// Watertight, faces wound for OpenSCAD; works in 2021.01 and the Manifold engine.
function _rl_pt(p, a) = [p[0] * cos(a), p[0] * sin(a), p[1]];
function _rl_tri(a, b, c, d) = [[a, b, c], [a, c, d]];

module rev_loft(profile, n = 96, mod = function(a, i, p) p) {
  m = len(profile);
  bot = profile[0][0] <= 1e-9;
  top = profile[m - 1][0] <= 1e-9;
  r0 = bot ? 1 : 0;
  r1 = top ? m - 2 : m - 1;
  k = r1 - r0 + 1;
  ring = [for (j = [0:n - 1]) let(a = 360 * j / n) for (i = [r0:r1]) _rl_pt(mod(a, i, profile[i]), a)];
  zb = bot ? mod(0, 0, profile[0])[1] : sum([for (j = [0:n - 1]) mod(360 * j / n, 0, profile[0])[1]]) / n;
  zt = top ? mod(0, m - 1, profile[m - 1])[1] : sum([for (j = [0:n - 1]) mod(360 * j / n, m - 1, profile[m - 1])[1]]) / n;
  pts = concat(ring, [[0, 0, zb], [0, 0, zt]]);
  B = n * k; T = n * k + 1;
  id = function(j, i) (j % n) * k + i;
  side = [for (j = [0:n - 1]) for (i = [0:k - 2]) each _rl_tri(id(j, i), id(j, i + 1), id(j + 1, i + 1), id(j + 1, i))];
  caps = concat([for (j = [0:n - 1]) [B, id(j, 0), id(j + 1, 0)]], [for (j = [0:n - 1]) [T, id(j + 1, k - 1), id(j, k - 1)]]);
  polyhedron(pts, concat(side, caps), convexity = 10);
}

function sum(v, i = 0) = i >= len(v) ? 0 : v[i] + sum(v, i + 1);
function smooth01(t) = let(u = max(0, min(1, t))) u * u * (3 - 2 * u);
