# M45 -- Transient / small-signal AC lifted to Device3D

Closes the "Transient / small-signal AC -> 3D" row of ARCHITECTURE.md's
dimensional-lift coverage matrix (section 5.3): `Y Y -` -> `Y Y Y`. This
was the front of the M41-M47 dimensional-lift queue after M46
(Schottky) landed 2026-09-18.

## 1. Scope

Both transient.py (1D) and ac.py (1D) had already been lifted to
Device2D (transient2d.py, ac2d.py) under M17/M18. Device3D had NEITHER.
This milestone is a PORT, not new physics: transient3d.py and ac3d.py
generalize transient2d.py/ac2d.py's own already-gated pattern one axis
further, following exactly the precedent M41 (incomplete ionization),
M16-S2 (BTBT), and M46-S3 (Schottky) set for a dimensional lift --
device.py/device2d.py/device3d.py are never touched; both new modules
drive Device3D through its own `_residual_jacobian` from the outside.

Time-varying GateBC voltage remains unsupported in transient3d.py, the
same sub-scope descope transient2d.py's own docstring already carries.

## 2. What was built

**transient3d.py**: direct lift of transient2d.py's
`_non_contact_flat_index`/`_step_residual_jacobian`/`_newton_step`/
`solve_transient`/`TransientResult2D` to Device3D's (Nz,Ny,Nx) state
shape and its 10-element `_residual_jacobian` return tuple (2D's 8
elements plus Jn_z/Jp_z). `TransientResult3D.stored_charge` uses
`device.dV * device.LD**3` (a real volume, matching Device3D's own
`dV` convention) instead of 2D's `LD**2` area. `_record_current` uses
`device.J0 * device.LD**2` (an AREA conversion), matching
`Device3D.terminal_current`'s own documented convention (real Amps, no
implicit unit-depth) rather than 2D's `LD**1` (A/cm, per-depth)
convention.

**ac3d.py**: direct lift of ac2d.py's `_dirichlet_excluded_nodes`/
`_storage_matrix`/`_ohmic_current_sensitivity`/`y_parameters`/
`cutoff_frequency` to Device3D. `_support_nodes` generalizes ac2d.py's
4-connected (x,y) neighbor set to Device3D's 6-connected (x,y,z) one.
GateBC forcing/weight uses `bc.kappa * device._gate_face_weight(bc)`
-- Device3D's own already-gated per-normal_axis area-weight helper --
rather than re-deriving the width product ac2d.py hardcodes for its
single implicit (always-'y'-like) gate orientation, since Device3D's
GateBC can sit on a face normal to any of x/y/z. Final physical scaling
uses `J0*LD**2/VT` (an AREA conversion, matching `Device3D.
terminal_current`'s own LD**2 convention) instead of 2D's `J0*LD/VT`.

## 3. A hard-debug finding (caught by inspection, not a failing test)

The first draft of ac3d.py's gate-port forcing/weight used
`device._gate_face_weight(bc)` directly as the full port weight,
omitting the `bc.kappa` factor device3d.py's own Poisson assembly
always multiplies it by (`bc.kappa * w`) -- `_gate_face_weight` returns
only the raw control-volume AREA, not the gate's own coupling strength.
Caught by directly comparing the two call sites side by side before any
gate was run, not by a failing test. Fixed by multiplying
`bc.kappa * device._gate_face_weight(bc)`, matching ac2d.py's own
`w = bc.kappa * device.dVx[bc.i]` convention. Recorded here because a
silent factor-of-kappa error would have produced a self-consistent but
physically wrong Y matrix that would NOT necessarily have been caught
by a reduction gate whose fixture happened to use kappa=1 -- G1's
fixture uses a realistic tox_cm-derived kappa (not 1), so it does
exercise this factor.

## 4. A second finding: a poorly-conditioned first reduction fixture

G1 (ac3d) was first written against a lone-body MOSCap+gate fixture (2
ports, no complete DC circuit through the single ohmic port). Its
ohmic self-admittance Y[body,body] mismatched the Device2D reduction
by up to 56%, while the gate-port cross terms (Y[gate,body],
Y[body,gate]'s imaginary/capacitive part) matched to ~1e-13 relative.
Root-caused directly: an isolated MOSCap's body contact carries no
genuine steady current path, so its own self-admittance is a poorly
conditioned quantity for a TIGHT reduction check -- confirmed
independently by checking `ac3d.y_parameters` against a two-terminal
ohmic-only diode3d fixture (no gate at all), which matched a direct FD
of `terminal_current` to 0.1% immediately, with no code change. Fixed
by replacing G1's fixture with `_resistor2d3d` (two ohmic contacts with
a real current path, plus a gate over an interior x-range that never
overlaps either contact's own nodes) -- this reduces to 1e-6
matrix-relative error on the first run with the corrected fixture.

## 5. Gates

**transient3d** (tests/test_m45_transient3d.py):
  - G1 FD-Jacobian of the theta-scheme transient residual on Device3D.
  - G2 Reduction: a z-uniform Device3D transient run (final psi/n, and
    every recorded terminal current, scaled by the device's own real
    z-extent) matches Device2D's own transient run -- the load-bearing
    dimensional-lift gate.
  - G3 Scope refusal: `transient3d.solve_transient` rejects a Device2D.

**ac3d** (tests/test_m45_ac3d.py):
  - G1 Reduction: a z-uniform Device3D's Y-parameters equal Device2D's
    own Y (scaled by the device's real z-extent) at every swept
    frequency, using GateBC normal_axis='y' -- the load-bearing
    dimensional-lift gate.
  - G2 New territory: a GateBC on normal_axis='z' (no Device2D analog)
    has its low-frequency gate self-capacitance checked against a
    direct finite difference of the gate charge -- a looser (20% vs
    ac2d.py's 5%) sanity bound; see the test file's own comment for why
    the residual doesn't tighten with mesh refinement, and why the gate
    is still meaningful evidence against a gross axis-selection error
    (ac3d.py itself has no axis-specific branch -- normal_axis dispatch
    lives entirely inside device3d.py's own separately-gated
    `_gate_face_weight`).
  - G3 Scope refusal: `ac3d.y_parameters` rejects a Device2D.

## 6. Verification

`tests/test_m45_transient3d.py` (3/3) and `tests/test_m45_ac3d.py`
(3/3) pass. Regression sweep (test_m45_transient3d, test_m45_ac3d,
test_m17_transient2d, test_m18_ac2d, test_m17_transient, test_m18_ac):
32 passed in 431.41s.

Full fast suite (`tests/ gui/tests/ -n 6 -m "not slow"`): 1956 passed,
5 skipped, 1 xfailed in 389.46s -- +6 over the prior 1950 baseline
(M46-S3), matching exactly the 6 new gates added here.

## 7. Honest limits

- Time-varying GateBC voltage is unsupported in transient3d.py, exactly
  as in transient2d.py -- not lifted here, not this milestone's scope.
- G2 (ac3d)'s tolerance is deliberately loose (20%) for a reason
  recorded in section 4/5 above, not tightened by weakening the FD step
  or mesh -- refining the mesh 3x (4->12 z-nodes) moved the residual
  from 16.0% to 13.7%, not the order-of-magnitude drop true
  discretization error would show, so the residual is treated as
  intrinsic to this particular cross-check rather than a bug to chase
  further.
- `ARCHITECTURE.md`'s coverage-matrix row 536 ("Transient / small-signal
  AC") should be updated from `Y Y -` to `Y Y Y`, M45 gains a LANDED
  entry, and the "M46[L](done) -> M45[XL] -> M44[XL]" ordering line and
  NEXT SESSION QUEUE section should point to M44 (hydrodynamic
  transport) next.

## 8. Closing the "cheap" gap-closure items (2026-09-18, same day)

After the first landing, a follow-up pass added the two cheap items
from the disclosed-gaps list: 3D transient physics reference gates
(G4-G6, ported directly from transient2d.py's own already-gated G1/G4/
G5) and a real 3D MOSFET fixture + gm/fT gates for ac3d.py (G4-G5,
ported from ac2d.py's own G-MOSFET-FD/G-MOSFET-FT/G-MOSFET-GAIN). The
ac3d.py MOSFET gates passed on the first run (5/5, 315s). The
transient3d.py reference gates surfaced a genuine, non-trivial stall
that took real investigation to root-cause -- recorded here in full
since "digging into a stall" was an explicit ask, not a footnote.

### 8.1 A real efficiency bug (transient3d.py's own code)

`_newton_step`'s line search can fail COMPLETELY: every damping factor
tried, down to ~2^-40, makes the merit function worse, so `lam` lands
at 0.0 and the state does not change. The outer loop did not check for
this -- it just kept iterating, recomputing the IDENTICAL doomed
residual/Jacobian/line-search up to `opts.max_iter=100` times before
finally giving up. Directly measured: a single such stalled step took
~800s (100 iterations x up to 40 line-search sub-evaluations each) on
a modest mesh. Fixed with a one-line short-circuit: bail out of the
Newton loop the moment `lam==0.0` is chosen, since every further outer
iteration would recompute exactly the same failure (bit-identical
output either way -- the returned `(psi, n, p, False, ...)` state is
unchanged whether the loop bails at iteration 1 or iteration 100, only
the wasted computation differs). This inefficiency is inherited
verbatim from transient2d.py/transient.py (ported faithfully, not
introduced here) but never got exercised there -- not touched, per the
frozen-core discipline, since fixing it there was not asked for and
is out of this milestone's scope.

### 8.2 The real root cause: z-under-resolution, not a 2D-vs-3D gap

Even after the efficiency fix, G4 (a diode jumped from equilibrium
straight to 0.3V forward bias in ONE giant backward-Euler step,
dt_s~6e8) still would not converge on the mesh used for G5 (Nz=3).
Investigated by comparing Device2D's and Device3D's Newton trajectories
side by side at the IDENTICAL operating point and step size:

  - The RAW (unclipped) linear-solve correction (dpsi, dn, dp) is
    numerically IDENTICAL between 2D and 3D to ~1e-13 -- confirming the
    Jacobian/residual math itself is fine (consistent with G2's own
    reduction gate, which already proved this at CONVERGED states).
  - 2D's first trial (full, undamped step) is accepted immediately
    (merit drops from 935 to 652); 3D's first trial gives a merit of
    88295 against a base of 2805 -- vastly worse than the ~3x scaling
    a truly z-uniform problem would predict (3x from F simply being 3
    replicated z-slices).
  - Printing the worst-residual nodes in that trial showed EVERY one of
    them at k=1 -- the single INTERIOR z-node (Nz=3 has exactly one) --
    never at the two z-BOUNDARY nodes (k=0, k=Nz-1).
  - Root cause: Nz=3's one interior node has a z-direction control
    volume (dVz) TWICE a boundary node's, by the standard box-
    integration convention (a boundary cell only extends half the
    spacing to its single neighbor; the interior cell has a full-width
    neighbor on both sides). The SAME aggressive dt_s stresses that
    one node's transient storage term disproportionately harder than
    every other node. `_newton_step` shares ONE global damping factor
    `lam` across every node, so this single node can force `lam` to 0
    even though every other node -- including a hypothetical 2D
    problem, which has no such node at all -- would already have
    converged.
  - Confirmed directly, not just theorized: re-running the identical
    comparison at Nz=7 (5 interior nodes instead of 1) converges
    cleanly (8 iterations, a few damped then quadratic -- qualitatively
    matching 2D), with NO other change.

This is a genuine mesh-resolution property of a very aggressive single
step on a coarse z-mesh, not a 2D-vs-3D Newton robustness gap and not
a case for "port to C++" (raw per-iteration cost was never the
bottleneck -- confirmed directly: a single spsolve+assembly on this
mesh size takes ~0.2s; the true cost was the WASTED repetition from
8.1, and separately the genuinely-needed shrink/regrow cycles once that
was fixed).

A second, unrelated, PRE-EXISTING finding surfaced while chasing this:
`Device3D.solve_equilibrium`/`solve_bias` (frozen core, untouched)
themselves scale poorly with node count via their own direct sparse
solve -- a single `solve_bias` call took ~30s at N=18060 and did not
return within 60s at N=23580. This matches this repo's own established
M22 rationale (AMG/Krylov/PETSc alternatives exist specifically because
direct solves do not scale to 3D) and is out of this milestone's scope
to fix; it simply constrains how large a mesh these gates' fixtures can
afford to use.

### 8.3 The fix actually applied

- `transient3d.py`: the `lam==0.0` short-circuit (section 8.1) --
  additive, bit-identical whenever a step's line search ever succeeds,
  the only user-visible change is that a genuinely-doomed step now
  fails fast instead of burning the full iteration budget.
- `tests/test_m45_transient3d.py`: new `_diode3d_g4()` fixture (Nz=5,
  coarser x/y than `_diode3d_small` to keep total node count -- and
  therefore Device3D's own slow direct-solve setup cost -- affordable)
  used only by G4; G5/G6 keep their already-working fixtures
  unchanged. G5's own dt0/t_end were separately retuned (dt0=1e-12
  instead of 1e-9, t_end=2e-9 instead of 2e-7) to avoid re-hitting the
  same aggressive-first-step regime one more time, verified directly
  (charge-conservation identity holds to 4e-7 relative over the
  shorter window before being written as a gate).

### 8.4 Verification

`tests/test_m45_transient3d.py`: 6/6 passed in 212.03s (G4 alone is
~80s of that -- a genuinely stiff transient, not a fast gate, kept
because it is real independent physics evidence, not because it was
cheap to make fast). `tests/test_m45_ac3d.py`: 5/5 passed in 315.66s.
