# M34-S6 — Impact Ionization, Local and Nonlocal, in Device2D/Device3D

Written 2026-09-11. The user's decisions (this session): **2D first, then
3D; the ionization coefficients see the field component along each
carrier's current.** This amends the frozen cores `device2d.py` and
`device3d.py`; the user's request is the sign-off, and the house gates
apply (default-off bit-identity, FD-Jacobian first, goldens md5-checked).

## 0. Why this is two pieces

Nonlocal impact ionization (M34-S2) does not generate anything by
itself: it evaluates the LOCAL model's coefficients at an effective
field. Device2D/Device3D refuse `Models(impact=True)` today ("M15 scope;
2D/3D ports are a follow-up slice"), so the local coupled model has to
exist there first:

| piece | what | device |
|---|---|---|
| S6a | M15's coupled local II ported | Device2D |
| S6b | S6a ported | Device3D |
| S6c | the S2 effective field on a grid | Device2D, then Device3D |

Unstructured meshes keep refusing (their refusal list already includes
`impact` and `impact_nonlocal`).

## 1. Local model in 2D/3D (S6a/S6b)

M15 in 1D: `G_i = Kgen * (alpha_n(E_i) Sn_i + alpha_p(E_i) Sp_i)`,
`Kgen = 0.5/(q R0)`, `S_i` the sum of the two incident edges' smoothed
current magnitudes `s(J) = sqrt(J^2 + eps^2)` (eps = 1e-6 x the largest
edge current), `E_i` the average of the two incident edges' |E|.

Grid form, per node and per carrier c, with every axis a:

    S_a,c = mean over the node's incident a-edges of J0 * s(J_c,e)
    E_a   = mean over the node's incident a-edges of |E_e|
    M_c   = sqrt(sum_a S_a,c^2)                    (current magnitude)
    E_par,c = sum_a E_a * (S_a,c / M_c)            (field along current)
    G     = (1/(q R0)) * (alpha_n(E_par,n) M_n + alpha_p(E_par,p) M_p)

**Field along the current (the user's choice).** E_par is the per-axis
field magnitude projected on the direction of the per-axis current
magnitude: a strong field ACROSS the current does not ionize. It is
sign-free per axis, exactly like M15 (which uses |E| and |J|); where
field and current are aligned -- drift-dominated transport, the only
place alpha is not zero -- it is |E . J_hat|.

**Reduction to M15.** In a transversely uniform device the transverse
edge currents are zero, so s gives exactly eps there and
M = sqrt(S_x^2 + eps^2), which differs from M15's S_x by
eps^2/(2 S_x) -- ~5e-13 relative where the current is near its maximum,
i.e. where ionization happens; E_par = E_x * S_x/M differs by the same
factor. The reduction is therefore round-off-close without treating any
axis differently.

**Jacobian.** Analytic, per edge: an edge's current and |E| enter the
generation of both its end nodes. With `K = 1/(q R0)`:

    dG/dS_a,c = K [alpha_c' (E_a - E_par,c S_a,c/M_c) + alpha_c S_a,c/M_c]
    dG/dE_a   = K sum_c alpha_c' S_a,c

chained through `dS/dJ_e = J0 s'(J_e)/count`, the existing SG edge
derivatives (psi and the carrier density at both ends, M13 fd chain
included), and `d|E_e|/dpsi = +-sign(dpsi) VT/(LD h)`. Stamped +G on
the electron row and -G on the hole row, after the continuity rows and
before the Dirichlet stamping; not at Dirichlet nodes (their rows are
replaced -- M15 is interior-only too).

**Newton.** M15 needs its strength ladder (`_II_STAGES`, a scalar on the
live term and its Jacobian, starting with a generation-free stage) and a
backtracking line search on the 2-norm merit to get through the stiff
onset. Device2D/Device3D get both, active only when `impact=True`; the
existing density-floor update test stays. `impact=False` runs the
existing loop once -- bit-identical.

## 2. Nonlocal field on a grid (S6c)

`lambda dE_eff/ds + E_eff = |E|` along each carrier's flow, on the grid's
edge graph, generalizing `ii_nonlocal.effective_field`:

- per edge, the relaxation source is the field ALONG THAT EDGE, so the
  effective field is built from the field along the flow;
- direction per edge: strong edges (>= 100 V/cm) from the field sign
  (electrons toward higher psi, holes lower); weaker edges inherit from
  the nearest strong edge on the SAME grid line (a transversely uniform
  device then reproduces 1D exactly);
- a node with several inflowing edges takes their mean (1D's rule);
- exact per-edge exponential integrator, topological (Kahn) order; a
  cycle -- impossible among strong edges, since psi rises along them --
  is broken by processing leftover nodes in potential order;
- E_eff = W |E_edge| with W stored sparse (weights decay as
  exp(-d/lambda); entries below 1e-15 of a row's largest dropped), which
  gives the dense-but-bounded Jacobian block.

E_par is replaced by E_eff per carrier; everything else in section 1 is
unchanged.

## 3. Gates (each file red first)

S6a/S6b (`tests/test_m34_s6_impact_2d3d.py`):
- default-off bit-identity (2D and 3D goldens md5-checked);
- dimensional reduction: a transversely uniform 2D/3D M15 diode ramped
  to a multiplying bias equals Device1D M15 (psi, densities vs n+p,
  current) to a tolerance set from measurement;
- FD Jacobian, M15 G-B methodology, every column of a small device;
- field along the current: a unit check that a field purely across the
  current gives E_par = 0 and one along it gives E_par = |E|;
- genuinely 2D: at the same reverse bias a curved (corner) junction
  multiplies more than the planar one -- the curvature effect. No
  published curvature value is gated: the source for the Baliga-Ghandhi
  cylindrical-junction curves (Solid-State Electron. 19, 739 (1976)) is
  paywalled, and the openly hosted follow-up (Anantharam & Bhat, IEEE
  TED 1980) treats punched-through diodes with Fulop's alpha = A E^7,
  not the abrupt-junction formula;
- convergence through a reverse ramp.

S6c: reduction to Device1D S2; FD Jacobian; the effective field lags a
narrow field peak in 2D (Slotboom's claim), matches the local field in a
wide plateau; convergence.

## 4. Pre-existing tests expected to change

Any test asserting that Device2D/Device3D refuse `impact=True` (the
refusal this port removes) and M34-S2's own refusal test once S6c
lands -- each listed in the history entry with the reason.

## 5. Status and measured findings (2026-09-12)

**S6a (Device2D) and S6b (Device3D) landed; S6c not started.** 3D
(measured 2026-09-12): a 3x3-transverse diode reduces to Device1D's
fixed point under the same limits as 2D; the generation FD gate passes
on a 3D cube-corner junction with transverse nodes graded onto the 2 um
planes (a uniform 1 um transverse mesh left the G peak on the finely
meshed x-face, y-currents < 10% of x; an earlier graded mesh gave
119,852 nodes and ran for over 20 minutes), and 10% damage to dalpha/dE
or the smoothed sign reads 1.2e-1 / 1.1e-1 there. Kernel: `pytcad/pytcad/ii_grid.py` (`grid_impact`), one
function for both devices. Gates: `tests/test_m34_s6_impact_2d3d.py`.
Default-off: impact-off 2D/3D bias solutions (2D planar, 2D corner, 2D
`btbt_nonlocal` refresh, 3D planar) byte-identical in md5 to the pre-edit
run, `PYTCAD_ACCEL=0` and `=1`, after every edit of the Newton loop.

Three departures from section 1 / Device1D's M15 rule, each forced by a
measurement:

1. **The Jacobian includes dG/d eps.** M15's smoothing eps = 1e-6 max|J|
   ties G at every node to the unknowns of the largest-|J| edge. M15
   neglects that term; in 1D it is second order in eps. In 2D a
   current-free transverse axis enters E_par with weight eps/M, which
   makes it first order: omitting it left a 1e-4 FD mismatch, identical
   at every FD step (so not truncation).
2. **Convergence is judged on the FULL Newton correction.** Device1D's
   M15 test reads the line-search-damped update, so a small lam passes
   it with the Newton correction still large. Measured on M15's own
   diode at -30V: the state `Device1D.solve_bias` returns carries 0.698
   of the discrete solution's current (one undamped Newton step moves
   it there and it stays); M = 1.066 reported, 1.5275 at the fixed
   point. The 2D port with the full-correction test lands on the fixed
   point (an extra undamped step moves its current by 4.4e-16).
3. **A failed line search takes the full step.** lam = 0 repeats the
   identical iterate until max_iter (measured: a corner diode at -34V,
   stage 0.7, merit at its round-off floor 1.8e-19 with a 1.4e-8
   update left).

**M34-S7 -- Device1D's convergence test fixed (user sign-off 2026-09-12).**
Finding 2 applied to Device1D itself: M15 (`impact`), M16 (`btbt`) and
M34-S1/S2 (1D nonlocal) all went through the damped test. The stiff
paths of Device1D, Device2D and Device3D now share one set of rules, each
constant in `device.py` with its measurement:

- convergence judged on the full Newton correction, before damping;
- that correction measured against a density floor of 1e-8
  (`_STIFF_DENSITY_FLOOR`; M11-S5's 1e-10 elsewhere). The raw metric
  sits at O(1) on the n+ side's p ~ 1e-19 holes at every step, and at
  1e-10 sub-floor densities hold a 2-5e-18 round-off limit cycle (M15 at
  -32V, M34-S2 at -20V) above the 1e-18 tolerance it implies;
- line search only outside Newton's region, full correction >= 1e-3
  (`_LS_NEWTON_REGION`): at a round-off merit floor the search accepted
  partial steps by noise and stopped the quadratic finish (M15, -40V);
- at most 10 halvings (`_LS_MAX_HALVINGS`, was 40), then the full step:
  M16's tunnel diode accepted lam = 4.8e-7 at merit 1.3e-28 forever.

The plain (no generation model) paths are untouched: goldens md5
unchanged, 2D/3D impact-off digests byte-identical in both accel modes.
Gate: `tests/test_m34_s7_device1d_convergence.py` (the returned state is a
fixed point of the device's own undamped Newton step, for M15, M16 and
M34-S1 devices; M15 was red at 6e-6 / 43%, M16 failed to converge).

**M15's G-C gap was this artifact.** With the fix, M_sim/M_int =
0.761-0.764 at 0.85 BV on three meshes (h_min 5e-8..1e-8), mesh-flat to
0.4%; the removed M15 plan's "G-C ROOT CAUSE" (M_sim/M_int 0.21-0.28,
blamed on the local-field approximation; `git show
e948fbe^:pytcad/M15-IONIZATION-PLAN.md`) measured the damped test's early
stop. `test_g_c_multiplication_matches_integral` is back on the plan's
[0.5, 2.0] band; `test_g_c_mesh_sensitivity` now gates mesh flatness and
that band instead of M_sim/M_int < 0.5.

**FD methodology for the generation.** At these biases G is ~1e-5 to
1e-17 scaled against O(1) Poisson/transport entries, so inside the full
rows its derivatives sit below round-off and a full-residual FD gate is
blind to them (the first version of the gate passed while seeing
nothing). The gate compares the stamped G and its own Jacobian (device
caches `_ii_gs_cache`, `_ii_jac_cache`); potential step 1e-9 max(|psi|,1)
(1e-7 gave 1.1e-3 truncation), density step 1e-7 u (the 1e-4 floor gave
1e-4 truncation); columns moving G by < 1e-9 of its peak are below FD
round-off and skipped. Damaging dalpha/dE or the smoothed sign by 10%
measures 1e-1 -- the gate is sighted.

**Measured (2D):** reduction to Device1D's fixed point at -30V: psi
2.3e-13, densities vs the 1e-10 floor 8e-12 (n) / 4e-9 (p), p-contact
current 4.4e-16, same-state G 6e-9 of peak. Curvature (coarse corner vs
planar, same x mesh): M from 1.0000 to 1.1275 (planar) and 1.3344
(corner) over -2..-20V, monotone, corner above planar at every bias.

**Known limitation (pre-existing, default path, not changed):** Device2D's
plain Newton fails on the coarse corner at -8V with 4V steps -- |dpsi|
3e-14 but |dn/n| ~2e-6 oscillating at densities just above the M11-S5
floor, where the reverse current pins them only to round-off. 2V steps
converge.

**Suites (2026-09-12, after S6a/S6b + S7).** Fast, `PYTCAD_ACCEL=0`:
1730 passed, 13 skipped, 1 xfailed, 39 warnings (the pre-existing
count). Fast, `PYTCAD_ACCEL=1`: 1738 passed, 5 skipped, 1 xfailed, 39
warnings. Slow battery: 27 passed, 10 warnings. The six m13 golden md5s
match section 1 of `M34-PLAN.md` before and after. Nothing committed.
