# M46 -- Schottky/tunnel contacts: couple, then lift

ARCHITECTURE.md's own scope note: "Same shape as M44: couple
schottky.py into a device core first, then lift dimensionally."

## 1. What schottky.py already had (M28)

Standalone, gated physics: Schottky-Mott barrier height, image-force
lowering, thermionic-emission I-V, Padovani-Stratton field-emission
(tunnel-contact) formulas. Explicitly NOT coupled into any device
Newton core (module's own honesty clause). `tests/test_m28_schottky.py`
(9 gates) covers this standalone layer and is untouched.

## 2. S1 scope decision

Two ways to couple a Schottky contact into Device1D's Newton solve:

(a) **Dirichlet approximation**: pin the contact node's majority-
    carrier density at its barrier-limited equilibrium value (Nc or Nv
    times exp(-phi_B/kT)) instead of the ohmic contact's doping-
    limited one, through the SAME `psi0 = V/VT + ln(n0/nie)` formula
    the ohmic path already uses. Zero new Jacobian rows -- the
    existing Dirichlet-contact code path and its FD-Jacobian gates
    already cover this shape exactly.
(b) **Robin (thermionic-flux) BC**: replace the majority carrier's
    contact row with `J = q*v_R*(n - n0)`, `v_R = A*T^2/(q*Nc)` -- the
    physically complete treatment, but a genuinely new stamped
    Jacobian row needing its own FD-Jacobian gate and convergence
    validation.

**S1 implements (a).** It is not the complete physics, but it is
SAFE (reuses an already-gated code path with zero Jacobian risk) and
already reproduces the qualitative behavior this milestone exists to
show: rectification, barrier-height-dependent depletion, and
barrier-limited (sub-ohmic) forward injection -- confirmed directly,
not assumed (see gates below). (b) is named as S2, not attempted here.

## 3. What was built

- `pytcad/pytcad/device.py`: new `SchottkyContact` dataclass
  (`phi_metal_eV`, `A_star` -- the latter stored for future S2 use,
  unread by S1's Dirichlet approximation). `Device1D.__init__` gained
  `schottky_left=None, schottky_right=None` (additive; `None` on both
  sides is bit-identical to before `_contact_values` was touched at
  all -- confirmed, G1). `_contact_values` branches per side: a
  Schottky side reuses `schottky.py`'s own `schottky_barrier_height_n`
  (imported, not re-derived) to get phi_Bn from the metal work
  function and the node's own `chi_arr`, then computes the barrier-
  limited majority density from `self.nc_s`/`self.nv_s` (already
  computed per-node) instead of the local-neutrality formula; the
  minority carrier still comes from mass action, and `psi0` uses the
  IDENTICAL formula the ohmic branch already used.
- No changes to `device2d.py`, `device3d.py`, `schottky.py`, `dg.py`,
  `gui/`, `workbench/`. `Device1D.solve_bias` needed NO change either
  -- the Schottky/ohmic distinction lives entirely inside
  `_contact_values`, which `solve_bias` already calls once per bias
  point.

## 4. Gates (`tests/test_m46_s1_schottky_device1d.py`, 4/4 green)

- **G1** `schottky_left=schottky_right=None` bit-identical to the pre-
  S1 ohmic-only construction.
- **G2** contact-node density is suppressed relative to ohmic, and the
  suppression grows monotonically with the metal work function
  (measured at phi_m = 4.3/4.8/5.3 eV).
- **G3** the device RECTIFIES: forward current (+0.3 V) exceeds
  reverse current (-0.3 V) magnitude by more than 1000x (measured:
  ~53,000x at phi_m=4.8 eV) -- the qualitative signature this
  milestone exists to demonstrate.
- **G4** forward current under the Schottky contact is smaller than
  under an equivalent ohmic contact at the same bias (measured: 3.75
  vs 2999 A/cm^2) -- distinguishes a genuine barrier effect from a
  cosmetic psi shift.

## 5. Verification

`tests/test_m46_s1_schottky_device1d.py` + `test_m28_schottky.py` +
`test_m13_goldens.py` + `test_validation.py`: 32 passed. Full fast
suite (`tests/ gui/tests/ -n 6 -m "not slow"`): **1934 passed, 5 skipped, 1 xfailed, 0 failed** (+4 over M42-S4's baseline).

## 6. Honest limits

- **Dirichlet approximation only** (section 2's choice (a)) -- no
  finite thermionic recombination velocity, so forward/reverse
  saturation-current MAGNITUDES will not quantitatively match
  `schottky.py`'s own `thermionic_current_density`/`schottky_iv`
  formulas; only the qualitative barrier-height-dependent, rectifying
  behavior is claimed.
- **1D only.** Device2D/Device3D are untouched -- no `SchottkyContact`
  parameter exists there, no dimensional lift attempted this slice.
- **No tunnel/field-emission contact coupling.** `schottky.py`'s
  Padovani-Stratton field-emission formulas remain standalone;
  `SchottkyContact` models only the thermionic-emission (rectifying)
  regime, not the degenerate "ohmic via tunneling" contact.
- **Equilibrium AND bias both work** (unlike M20/M42's DG, which is
  equilibrium-only) -- this is a genuine difference in scope, not an
  oversight: the Dirichlet approximation needs no bias-only refusal
  because it never touches the Jacobian's flux terms.
- **No performance claim, no benchmarks row.**

## 7. S2 results (landed 2026-09-18, same day as S1)

Implemented section 2's choice (b): the Robin thermionic-flux BC,
selected by giving `SchottkyContact.A_star` a real value (`None`, the
default, keeps S1's Dirichlet approximation bit-identically).

**Key finding that made this safe and fast**: `device.py` already had
the EXACT equation shape needed -- M14's `Models(S_n=..., S_p=...)`
surface-recombination Robin BC (`_residual_jacobian`'s "Dirichlet
contacts (Robin on n/p...)" block) replaces a contact's Dirichlet row
with `J_edge + S*(carrier - n0) = 0`, gated by its own FD-Jacobian
test since M14. Thermionic emission (Sze & Ng) is the SAME equation
with `v_R = A* T^2 / (q Nc_or_Nv)` in place of `S`, and S1's own
barrier-limited `n0`/`p0` (already computed in `_contact_values`) in
place of M14's bulk-equilibrium target. So S2 needed ZERO new Jacobian
derivation -- only per-node selection of which velocity/target value
feeds the already-gated formula. Combining a Robin-mode
`SchottkyContact` with a nonzero `Models.S_n`/`S_p` is refused (both
would compete for the same row; `S_n`/`S_p` are global to both
contacts in this module's own existing design, not per-side).

### Gates (`tests/test_m46_s2_schottky_robin.py`, 6/6 green)

- **G1** FD-Jacobian of the Robin row (mirrors
  `test_m14_surface_mobility.py`'s own G-E gate exactly) -- passed on
  the first run.
- **G2** `A_star=None` still reproduces S1's Dirichlet approximation
  bit-identically.
- **G3** at equilibrium, Robin and Dirichlet give IDENTICAL psi/n/p --
  the same `Jn=0 forces n=n0 regardless of v_R` invariant M14's own
  gate already documents, now confirmed for the Schottky case too.
- **G4** the Robin BC's forward current is quantitatively close to
  `schottky.py`'s own `thermionic_current_density` analytic formula
  (measured ratio 0.86-0.90 across V=0.05-0.3 V, numeric always
  slightly BELOW analytic -- the expected direction, since the DD
  solve's bulk series resistance is not present in the pure analytic
  formula, which assumes the entire bias appears across the barrier).
- **G5** Robin forward current is smaller than the Dirichlet
  approximation's at the same bias (0.536 vs 3.75 A/cm^2 at 0.3 V,
  phi_m=4.8 eV) -- the interface recombination velocity is a genuine
  additional bottleneck the Dirichlet approximation lacks.
- **G6** `S_n`/`S_p` combined with a Robin-mode `SchottkyContact` is
  refused.

### Verification

`test_m46_s1_schottky_device1d.py` + `test_m46_s2_schottky_robin.py`
+ `test_m28_schottky.py` + `test_m14_surface_mobility.py` +
`test_m13_goldens.py` + `test_validation.py`: 49 passed. Full fast
suite (`tests/ gui/tests/ -n 6 -m "not slow"`): **1940 passed, 5 skipped, 1 xfailed, 0 failed** (+6 over S1's baseline).

### Honest limits (S2 specifically)

- **Still 1D only.** The 2D/3D dimensional lift (their own
  `add_contact`-style machinery needing a parallel
  `add_schottky_contact`) was NOT attempted this slice -- a real,
  separate piece of work (Device2D/Device3D's contact/BC layout is
  structurally different from Device1D's fixed two-node convention).
- **~10-15% current deviation from the pure analytic formula** (G4) is
  expected and physical (bulk series resistance), not a bug, but means
  this is not a drop-in replacement for `schottky_iv` at high forward
  bias where series resistance dominates.
- **Minority carrier stays Dirichlet** at its mass-action value --
  only the majority carrier gets the thermionic Robin treatment,
  matching the physical picture (Schottky contacts are majority-
  carrier devices) but not a fully general treatment of minority
  injection.
- **No tunnel/field-emission (Padovani-Stratton) coupling still.**
  `SchottkyContact` only ever models the thermionic-emission regime.
- **No performance claim, no benchmarks row.**

## 8. S3 results (landed 2026-09-18, same day as S1/S2)

Dimensionally lifted to Device2D (full S1+S2 parity) and Device3D
(S1 Dirichlet approximation only -- Device3D has no M14 S_n/S_p Robin
machinery to reuse for S2, and refuses `Models.S_n`/`S_p` outright
already; extending that is a separate, un-scoped piece of work, not
attempted here).

### What was built

- **`pytcad/pytcad/device2d.py`**: new `SchottkyBC(DirichletBC)` class
  -- a SUBCLASS, not a new dispatch branch, so every existing
  `isinstance(bc, DirichletBC)` site (Poisson row, BTBT/impact "live
  node" mask, `terminal_current`) treats it correctly with ZERO
  changes. `add_schottky_contact(name, i, j, phi_metal_eV, A_star=None,
  V=0.0)`. `_bc_contact_values` gained a `SchottkyBC` branch (direct
  lift of Device1D's own barrier-density formula, refused under
  `fd`/`incomplete_ion`). The M14 G-C `S_n`/`S_p` Robin block in
  `_residual_jacobian` was generalized from a single GLOBAL
  velocity/target to a PER-NODE one, so a Robin-mode `SchottkyBC`
  (`A_star` given) can override just its own majority carrier's row
  with `v_R = A* T^2/(q Nc_or_Nv)` while every other contact (and the
  Schottky contact's own minority carrier) keeps its prior behavior
  exactly. Refused in combination with a nonzero global
  `Models.S_n`/`S_p` (both would compete for the same row).
- **`pytcad/pytcad/device3d.py`**: same `SchottkyBC(DirichletBC)` +
  `add_schottky_contact` shape, but `add_schottky_contact` itself
  refuses `A_star != None` (S2's Robin mode) -- Device3D's own
  constructor already refuses `Models.S_n`/`S_p` unconditionally (no
  Robin-BC machinery exists there to generalize). `_bc_contact_values`
  gained the SAME `SchottkyBC` branch as Device2D (Dirichlet
  approximation only).
- No changes to `device.py`, `dg_grid.py`, `schottky.py`, `gui/`,
  `workbench/`.

### A hard-debug finding, kept in the record

The first draft of Device2D's per-node Robin/Dirichlet splitting
dropped the `+1`/`+2` column-index offsets when building
`strip_rows_list` (rows meant for the n/p continuity equations were
marked as if they were the psi row). Caught immediately by the FD-
Jacobian gate (worst relative error exactly `1.0` -- a completely
wrong row, not a rounding issue) before any physics gate was trusted;
traced to the specific lines via a targeted worst-column/worst-row
probe (landed on an ORDINARY ohmic contact node, not even a Schottky
one -- the bug corrupted the shared M14 machinery for every contact,
not just Schottky ones). Fixed by restoring the offsets; the same
gate then passed at 1.7e-9. This is exactly the scenario the amendment
protocol's "FD-Jacobian first" rule exists to catch, and it did.

### Gates (`tests/test_m46_s3_schottky_2d3d.py`, 10/10 green)

- **G1** FD-Jacobian, Device2D Robin mode.
- **G2** FD-Jacobian, Device3D Dirichlet mode.
- **G3** Device2D: `A_star=None` and a Robin-mode contact give
  IDENTICAL equilibrium (the `Jn=0` invariant, confirmed again one
  dimension up).
- **G4** (2 tests) the load-bearing dimensional-lift gate: a
  transversely-uniform Device2D reduces to Device1D's own
  `SchottkyContact` result at equilibrium to floating-point noise, and
  a transversely-uniform Device3D reduces to Device2D the same way --
  a genuine two-level chain (3D -> 2D -> 1D).
- **G5** (2 tests, `A_star` in `{None, richardson_a_star("Si","n")}`)
  Device2D rectifies under bias in BOTH modes.
- **G6** Device3D solves cleanly under bias (no warnings) and
  rectifies.
- **G7** (2 tests) Device2D refuses `S_n`/`S_p` combined with a
  Robin-mode `SchottkyBC`; Device3D refuses the Robin mode outright.

### Verification

`test_m46_s1_schottky_device1d.py` + `test_m46_s2_schottky_robin.py`
+ `test_m46_s3_schottky_2d3d.py` + `test_m28_schottky.py` +
`test_m14_surface_mobility.py` + `test_m13_goldens.py` +
`test_validation.py` + `test_validation_2d.py` +
`test_validation_3d.py` + `test_m41_incomplete_ion_2d3d.py`: **101
passed**. Full fast suite (`tests/ gui/tests/ -n 6 -m "not slow"`):
**1950 passed, 5 skipped, 1 xfailed, 0 failed** (+10 over S1/S2's baseline).

### Honest limits (S3 specifically)

- **Device3D has NO Robin (S2) mode** -- Dirichlet approximation only,
  a real scope gap (not an oversight) tied to Device3D's own missing
  M14 S_n/S_p infrastructure.
- **Device2D's Robin generalization is per-node but still per-BC
  majority-only** -- a single `SchottkyBC` cannot mix majority-type
  behavior differently across its own nodes in a way this wasn't
  already designed for (it handles it correctly via the `is_n` mask,
  but this was not stress-tested on a contact straddling a real p-n
  junction).
- **No performance claim, no benchmarks row.**
- M46 is now essentially complete for its own stated scope
  ("coupled, then 2D/3D") -- the one remaining named gap is Device3D's
  Robin mode, which needs M14's own S_n/S_p ported to 3D first (a
  separate, unscoped milestone in its own right, not named anywhere
  in M46's own charter).
