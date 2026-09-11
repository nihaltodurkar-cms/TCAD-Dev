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
