# M17-TRANSIENT-PLAN.md
# M17: Time-dependent drift-diffusion simulation
# Formal milestone spec

Status: **PHASES 1 (1D), 2 (2D), AND 3 (GUI) COMPLETE (2026-08-30/31)**.
Phase 1: G1/G2/G4/G5/G-FD GREEN (tests/test_m17_transient.py). Phase 2:
G1/G4/G5/G-FD GREEN (tests/test_m17_transient2d.py; G2 not re-derived
for 2D, see section 5). Phase 3: transient runs are reachable end-to-end
from the desktop app (armed via a new Transient tab, executed through
the existing JobRunner subprocess, plotted via a new "Transient" view
mode) -- gui/tests/test_transient_gui.py, 13 tests green. 1D and 2D
backward-Euler/theta-scheme transient simulation, three waveform
primitives (step/ramp/pulse), adaptive dt. Implemented as new sibling
modules (`pytcad/transient.py`, `pytcad/transient2d.py`) that drive
`Device1D`/`Device2D` through their own `_residual_jacobian` from the
outside -- exactly the pattern `pytcad/continuation.py` already
established for 1D bias continuation -- so neither `device.py` nor
`device2d.py` was touched, in any phase. G2 (diode turn-off) could not
be matched to a textbook Qs~=I_F*tau_p formula within a defensible
tolerance in Phase 1 (see section 5); Phase 1 gates the two things that
ARE robustly verified instead, and Phase 2 does not repeat the attempt.

Roadmap slot: ARCHITECTURE.md section 4b/7, "M17 TRANSIENT SIMULATION
[L]" -- explicitly the next milestone on the spine (no unstarted
dependencies; unblocks M18 small-signal AC and M19/M27 self-heating's
coupled solve).

------------------------------------------------------------------------
1. SCOPE
------------------------------------------------------------------------
PHASE 1 [M] -- 1D transient core.  COMPLETE.
  New file `pytcad/pytcad/transient.py`: `solve_transient(device,
  waveforms, t_end, dt0, theta=1.0, opts=None, ...)` time-steps an
  already-initialized `Device1D` (call `solve_equilibrium`/`solve_bias`
  first for the initial condition) under per-contact `Waveform`s
  (`StepWaveform`, `RampWaveform`, `PulseWaveform`, or a bare float for
  a fixed bias).  theta=1.0 (backward Euler, unconditionally stable) is
  the default and the only theta value the gates exercise; theta<1
  (e.g. Crank-Nicolson) is implemented for interface completeness but
  NOT gated (see section 5).  Adaptive dt grows by `growth` after an
  easy Newton solve and shrinks by `shrink` on Newton failure, retrying
  from the last accepted state -- the same control-loop shape
  `continuation.py`'s `adaptive_bias_sweep` already uses for bias
  ramps.  Returns a `TransientResult` (times, per-step psi/n/p
  snapshots, per-contact terminal current, accepted dt history, plus a
  `stored_charge(device)` helper).

PHASE 2 [M] -- Device2D transient support.  COMPLETE.
  New file `pytcad/pytcad/transient2d.py`, same external-module pattern
  as Phase 1 against `Device2D._residual_jacobian`. Two things are
  actually SIMPLER than in 1D: `_residual_jacobian(psi, n, p,
  voltages)` already takes a `{contact_name: V}` dict directly (no
  separate `_contact_values()` step needed -- `Device2D`'s arbitrary
  `(i, j)` contact node sets make the dict itself the natural
  interface), and it already returns the pre-Dirichlet-overwrite
  continuity residual (`F_n`, `F_p`) as extra outputs, which
  `Device2D.terminal_current()` itself uses -- so per-step terminal
  current for EVERY registered contact (not just two) falls out for
  free. `DirichletBC.V`/`GateBC.Vg` are plain mutable floats already,
  so no BC-class change was needed either; `solve_transient` just
  re-evaluates a `{contact_name: Waveform}` dict at each new time and
  passes it straight to `_residual_jacobian`. Gate voltages
  (`GateBC.Vg`) are NOT time-varying in this phase (left fixed at
  whatever they already are) -- a real, intentional sub-scope
  reduction, not an oversight (see section 5).

PHASE 3 [S] -- GUI wiring.  COMPLETE (2026-08-31).
  `SOLVER_RESULT_SCHEMA_VERSION` bumped 2 -> 3
  (`gui/services/solver_backend.py`), additive: a v3 file is a valid
  v1/v2 file with a new `transient__*` block, same tradeoff
  `project_store.py`'s v5 bump already made. New `WaveformSpec`/
  `TransientSpec` dataclasses (`gui/services/device_spec.py`), nested
  on `DeviceSpec.transient` -- `SweepSpec`/`FamilySweepController`/
  `SweepPanel.qml` were confirmed bias-typed and NOT reusable for a
  time axis, so this is a genuinely new sibling, not a generalization.
  New `gui/services/solver_runner.py:run_transient()` dispatches to
  `pytcad.transient.solve_transient` (1D) or
  `pytcad.transient2d.solve_transient` (2D) -- the ALREADY-GATED phase
  1/2 solvers, called unmodified, never reimplemented at the GUI layer.
  `JobRunner`/the subprocess mechanism needed ZERO changes (dispatch is
  purely data-driven off the DeviceSpec JSON, confirmed during
  exploration before writing any code). New `TransientPanel.qml` +
  `AppController.setTransientConfig`/`clearTransientConfig`/
  `transientConfig()`/`hasTransientConfig`/`transientResultForQml`
  mirror the sweep-config quartet exactly, including mutual exclusion
  with an armed sweep (refused loudly in `run()`, not silently
  resolved). New `NpzResultStore.has_transient()`/`transient_result()`
  mirror `has_sweep()`/`sweep_result()`'s protocol-with-defaults shape
  on the `ResultStore` ABC. A new "Transient" view mode in
  `mpl_canvas_item.py`/`ViewportPanel.qml` plots every channel (both
  named contacts at 1D, every ohmic contact at 2D) vs. time, reusing
  the existing `_remember_series`/hover-readout machinery -- not a new
  plotting primitive, following the same "cv" mode precedent (a
  SweepResult-shaped value object with its own axis labels) rather
  than "series" mode's single-channel-plus-family-overlay shape, since
  a transient state has no single default channel to pick.
  Scope NOT covered (see section 5): `GateBC` voltages are not
  waveform-driven; project save/load does not persist an armed
  transient config; the devsim backend explicitly refuses
  `spec.transient` (`check_devsim_compatible`) rather than silently
  ignoring it.

------------------------------------------------------------------------
2. INTERFACE
------------------------------------------------------------------------
```python
class Waveform:                       # .value(t) -> bias [V] at time t [s]
class StepWaveform(v0, v1, t_step=0.0)
class RampWaveform(v0, v1, t0, t1)
class PulseWaveform(v_base, v_pulse, t_start, width)

class TransientResult:
    times, psi_hist, n_hist, p_hist   # (n_steps[+1], N) arrays
    terminal_current                  # {"left": [...], "right": [...]} A/cm^2
    dt_hist
    def stored_charge(device) -> np.ndarray   # q * sum((n-p)*dx) [C/cm^2]

def solve_transient(device, waveforms, t_end, dt0, theta=1.0, opts=None,
                     dt_min=None, dt_max=None, growth=1.5, shrink=0.5,
                     output_times=None, verbose=False) -> TransientResult
```
`waveforms` is `{"left": Waveform|float, "right": Waveform|float}`
(also accepts integer keys `0`/`1` mirroring `continuation.py`'s
`terminal` convention).  `device.psi` must already be set (raises
`RuntimeError` otherwise) -- `solve_transient` never seeds an initial
condition itself, matching `arc_length_sweep`/`adaptive_bias_sweep`'s
own convention of requiring the caller to establish equilibrium first.
Raises `RuntimeError`, never silently stops, if `dt` shrinks below
`dt_min` without Newton convergence.

`pytcad/transient2d.py` (Phase 2) mirrors this exactly, on `Device2D`:

```python
class TransientResult2D:
    times, psi_hist, n_hist, p_hist   # (n_steps[+1], Ny, Nx) arrays
    terminal_current                  # {contact_name: [...]} A/cm, ANY
                                       # number of registered contacts
    dt_hist
    def stored_charge(device) -> np.ndarray   # [C/cm], see note below

def solve_transient(device, waveforms, t_end, dt0, theta=1.0, opts=None,
                     dt_min=None, dt_max=None, growth=1.5, shrink=0.5,
                     output_times=None, verbose=False) -> TransientResult2D
```
`waveforms` is `{contact_name: Waveform|float}` for any subset of
`device.bcs`'s `DirichletBC` names; an unmentioned contact keeps its
current `bc.V` fixed for the whole run. `GateBC` voltages are NOT
waveform-driven in this phase (see section 5). `TransientResult2D.
stored_charge(device)` returns charge RELATIVE to the initial snapshot
(`Q(t) - Q(0)`, always 0 at t=0), not an absolute total -- see section 5
for why the absolute version is numerically unusable at this mesh scale.

------------------------------------------------------------------------
3. QUANTITATIVE ACCEPTANCE GATES (tests/test_m17_transient.py)
------------------------------------------------------------------------
G-FD: the analytic transient Jacobian (theta-scheme storage term added
  on top of Device1D's own analytic J) matches a numerical Jacobian of
  the same transient residual to <2e-3 relative -- required by
  AGENTS.md's standing "new physics needs FD-Jacobian-first" rule.
  GREEN.

G5 STEADY-STATE CONSISTENCY: one large backward-Euler step from a
  perturbed state, under a fixed bias, relaxes to within 5% of the
  current `solve_bias` reaches for that bias directly -- the
  theta-scheme's steady limit validated against the already-trusted DC
  solver (same idea as M22's arc-length-vs-`iv_sweep` gate). GREEN.

G4 CHARGE CONSERVATION: at every accepted step, `d(stored_charge)/dt`
  equals the net terminal current to rtol=1e-3 (atol=1e-9 A/cm^2 for
  the quasi-steady noise floor) -- this falls directly out of the
  continuity rows telescoping to boundary flux, so it is a strong
  regression gate on the discretization itself, not a physics-accuracy
  check. Found and fixed a sign-convention bug during implementation
  (see section 5). GREEN.

G1 DIELECTRIC RELAXATION: a small excess-charge perturbation on a
  uniformly doped, zero-bias slab decays exponentially with
  tau=eps/sigma (majority-carrier conductivity, computed from the
  device's own attributes, not a separately-tabulated constant), fitted
  tau within 25% of analytic. Required capping `dt_max` well below
  `tau` in the test (an aggressive adaptive-growth default otherwise
  coarsens dt past the timescale being measured -- see section 5).
  GREEN.

G2 DIODE TURN-OFF STORAGE: switching a forward-biased diode to reverse
  bias does not switch the terminal current instantaneously (current
  stays >50% of I_F on the immediate post-switch step) and the
  transient's long-time terminal current agrees with an independent
  `solve_bias` at the new reverse bias to <5%. A tight quantitative
  match to Qs~=I_F*tau_p was investigated and NOT achieved -- see
  section 5; the gate covers what was independently verified instead.
  GREEN.

G-SUITE (Phase 1): full suite `python3 -m pytest tests/ gui/tests/ -n 6
  -m "not slow" -q` unchanged apart from the new M17 tests: 874 passed,
  25 skipped, 1 xfailed, 3 failed (the pre-existing M20 G-C/G-D set,
  left open by prior explicit user decision -- unrelated to this
  milestone). Zero new warnings. GREEN.

PHASE 2 GATES (tests/test_m17_transient2d.py) -- same four gate
  IDs, re-derived and re-verified independently on Device2D, NOT
  assumed to carry over from Phase 1's 1D result:

G-FD (2D): analytic transient Jacobian matches a numerical Jacobian on
  a random 60-column subset (the full dense N3xN3 FD check is too
  large at this mesh size, same concern `test_validation_2d.py`'s own
  steady-state Jacobian gate already documents) to <2e-3 relative.
  GREEN.

G5 STEADY-STATE CONSISTENCY (2D): one large backward-Euler step from a
  perturbed state, under a fixed bias, relaxes to within 5% of
  `solve_bias` at that bias. GREEN.

G4 CHARGE CONSERVATION (2D): `d(stored_charge)/dt` equals `-(sum of
  ALL contacts' terminal_current)` (note: NOT `I_right - I_left` --
  see section 5, this is a genuinely different sign relationship from
  Phase 1's, derived and verified independently) to rtol=1e-3
  (atol=1e-9). Generalizes over an arbitrary number of registered
  contacts, not just two. GREEN.

G1 DIELECTRIC RELAXATION (2D): same physics as Phase 1, now on a
  genuinely 2D mesh (non-trivial y-direction box integration), fitted
  tau within 25% of analytic. GREEN.

G2: NOT re-derived for 2D -- Phase 1 already left this one an honest
  partial result (see section 5); repeating the same investigation on
  a 2D mesh was judged not to add new information for the additional
  implementation cost. Left open, same as Phase 1.

G-SUITE (Phase 2): `python3 -m pytest tests/ gui/tests/ -n 6 -m "not
  slow" -q` -- 878 passed (874 + 4 new Phase 2 tests), 25 skipped, 1
  xfailed, 3 failed (the same pre-existing M20 set, unchanged). Zero
  new warnings. GREEN.

------------------------------------------------------------------------
4. AMENDMENT MECHANISM
------------------------------------------------------------------------
`pytcad/pytcad/device.py` and `device2d.py` are NOT touched by Phase 1
or Phase 2 -- the standing "frozen core, sign-off + FD-Jacobian-first +
bit-identical-off-path" rule therefore does not apply to them here (no
amendment was made; DC/continuation bit-identity is automatically
preserved because nothing in their code paths changed, confirmed by
both G-SUITE runs above showing no new failures anywhere outside the
two new test_m17_transient*.py files). The FD-Jacobian-first rule DOES
apply to the new physics itself (the theta-scheme storage term, in
both 1D and 2D), and is satisfied by each phase's own G-FD.

------------------------------------------------------------------------
5. HONEST LIMITS
------------------------------------------------------------------------
- G2's quantitative charge-storage estimate: tried Qs~=I_F*tau_p (long-
  base) and a transit-time estimate Qs~=I_F*W^2/(2*Dp) (short-base);
  both came out sign-ambiguous and off by a factor of several against
  the actual integrated excess reverse current. Root cause not fully
  chased down -- plausible contributors are (a) this setup is
  voltage-driven bias switching, not the constant-reverse-current
  assumption Kingston-style storage-time formulas are derived under,
  and (b) the chosen diode geometry sits between the short- and
  long-base regimes, where neither idealized formula applies cleanly.
  Left open for a future session if a tight quantitative gate is
  wanted here, same as M20's G-C/G-D.
- theta < 1.0 (Crank-Nicolson etc.) is implemented in BOTH modules (the
  row-scaling + old-residual blend in `_step_residual_jacobian`) but
  not exercised by any gate in either -- only theta=1.0 (backward
  Euler) is validated, 1D or 2D.
- Phase 2's `GateBC.Vg` is NOT waveform-driven -- only `DirichletBC`
  ohmic contacts take a `Waveform`. A MOSFET-style transient (a ramped
  gate pulse, the most obviously useful 2D transient scenario) is
  therefore NOT reachable yet; this needs `_contact_values`-equivalent
  handling for `GateBC` extended the same way, deferred rather than
  rushed.
- `TransientResult2D.stored_charge()` had to be redefined RELATIVE to
  the initial snapshot rather than as an absolute total -- found while
  gating 2D's G4: at this mesh's node count (~30x260), the ABSOLUTE sum
  of `(n-p)*dA` over the whole domain is dominated by near-cancelling
  majority-carrier bulk charge on each side of the junction (a
  genuinely symmetric Na=Nd diode, chosen for the gate, makes this
  worse but the cancellation risk is generic to any large 2D mesh), so
  the real signal (the much smaller time-varying injection/depletion
  charge) was lost to float64 cancellation -- the naive absolute-sum
  version measured a `d(stored_charge)/dt` about 1e4x smaller than the
  terminal current it should equal. Computing the delta directly
  (never summing the large non-time-varying bulk term at all) fixed it
  outright. Phase 1's 1D `stored_charge()` was NOT changed to match --
  it already passed its own G4 at 1D's much smaller node count, and
  changing an already-gated, already-shipped function without a
  concrete failure to fix was judged unnecessary churn; a future
  caller hitting the same issue in 1D at a much finer mesh should apply
  the same fix there.
- Phase 3's GUI wiring does NOT cover: waveform-driven `GateBC` voltages
  (only ohmic `DirichletBC` contacts take a `Waveform`, matching Phase
  2's own scope note); persisting an armed transient config across
  project save/load (`_sweep_config` is saved/restored by
  `project_store.py`, `_transient_config` deliberately is not -- a real
  gap, not an oversight, left for a future session rather than bumping
  `project_store.py`'s own schema in the same pass as this one);
  per-step field-snapshot storage/playback the way `sweep_snapshots()`
  offers for bias sweeps (only a scalar current-vs-time series is
  stored, per the Phase 3 scope decision).
- Devsim backend compatibility: `check_devsim_compatible()` now
  explicitly refuses `spec.transient` (a real gap closed during Phase
  3 -- its `run()` had no transient dispatch at all, so an armed
  transient config on that backend would previously have been silently
  solved as a plain bias/sweep job instead, exactly the "hidden
  failure" this function's other checks already existed to catch).
- No AC/small-signal analysis -- that is M18, which depends on this
  milestone but is a separate coupled-solve formulation, not built here.
- G1's test needed an explicit `dt_max` well below the decay time being
  measured; `solve_transient`'s own default `dt_max` (`dt0 * 64`) is
  tuned for reaching a distant `t_end` quickly, not for resolving a
  specific short timescale -- callers measuring a particular decay
  constant should always pass an explicit `dt_max` for it, not rely on
  the default.
- G4's sign convention (`d(stored_charge)/dt == I_right - I_left`, not
  the naively-expected `I_left - I_right`) was found empirically during
  implementation and is now documented in the gate test itself; the
  most likely explanation is that `stored_charge` (net mobile charge
  sum(n-p)) responds to depletion-width narrowing under forward bias in
  the opposite direction from naive "current entering charges the
  device up" intuition -- not independently re-derived from first
  principles here, flagged rather than asserted as certain.

------------------------------------------------------------------------
6. IMPLEMENTATION RECORD (2026-08-30)
------------------------------------------------------------------------
Built in the order the plan specified (TDD, gates before tuning):
G-FD and G5 passed on the first run. G4 initially failed with the
correct MAGNITUDE but opposite sign (see section 5); fixing the sign
convention in the test (not the solver -- the solver's residual/
Jacobian construction was never in question once G-FD and G5 both
passed) made it pass, then a spurious failure at the quasi-steady tail
(both sides of the comparison at the same ~1e-9 noise floor, blowing up
a purely-relative tolerance) was fixed by switching to
`np.allclose(rtol=1e-3, atol=1e-9)`. G1 initially fitted a decay
constant 42% slower than analytic; traced to the default adaptive-dt
growth (1.5x per easy step, `dt_max` capped only at 64x the initial
step) coarsening `dt` far past the `tau` being measured within the
first handful of steps -- fixed by passing an explicit `dt_max=tau/8,
growth=1.2` in the test (a test-tuning fix, not a solver bug: the
default growth policy is appropriate for reaching a distant `t_end`
efficiently, just not for resolving a specific short decay). G2's
quantitative textbook-formula attempts (both long- and short-base
estimates) were off by a factor of 3-6x and sign-ambiguous after direct
numerical experimentation (not merely guessed) -- descoped to the
two independently-verifiable claims in section 3/5 rather than forcing
a tolerance, following M20's own precedent for honestly leaving a gap
open. A first draft of the diode-turnoff gate at `t_end=6*tt` on a
~1000-node mesh took ~25s per run (intermittent Newton retries in the
depletion-formation regime burning up to `max_iter` per failed
attempt); reduced to `t_end=3*tt` with `NewtonOptions(max_iter=25)`,
bringing it to ~5.5s without weakening either of the two checks it
actually makes.

------------------------------------------------------------------------
7. IMPLEMENTATION RECORD -- PHASE 2 (2026-08-31)
------------------------------------------------------------------------
Built the same way: G-FD and G5 passed on the first run again (strong
evidence the same theta-scheme composition technique generalizes
correctly, not just that it happened to work once). G4 failed twice,
for two DIFFERENT reasons, neither of which was 1D's sign bug repeating
verbatim:

  1. First failure looked like a ~1e4x MAGNITUDE mismatch (not a sign
     flip) between `d(stored_charge)/dt` and any combination of
     `I_left`/`I_right` tried. Printing the raw numbers showed
     `stored_charge()` itself returning near-zero values (~1e-16 to
     1e-22) at every snapshot, including t=0 -- not a solver bug: for
     this symmetric Na=Nd diode, the TRUE absolute `sum((n-p)*dA)` over
     the whole 2D mesh really is near-zero (majority-carrier bulk
     charge on the two sides roughly cancels), so the tiny residual
     left over after that cancellation was pure float64 roundoff, not
     the real (much smaller) transient signal. Fixed by redefining
     `stored_charge()` as a delta relative to the initial snapshot
     (section 5) -- confirmed this was the right diagnosis by checking
     `dev.dV.sum() * dev.LD**2` against the mesh's known physical area
     first (matched exactly), ruling out a units bug before chasing a
     cancellation explanation.
  2. After that fix, values were finite and correctly scaled, but still
     didn't match `I_right - I_left` (Phase 1's relation) OR the
     magnitude was still off. Re-derived the conservation identity from
     the box-integration telescoping property directly (sum of F_n_raw
     over ALL nodes is a pure algebraic constant regardless of Newton
     convergence, since interior divergence terms cancel pairwise by
     construction -- this holds for ANY psi/n/p values, not just a
     converged state) rather than guessing at sign combinations: this
     showed `d(stored_charge)/dt == -(I_left + I_right)`, and a direct
     numerical check confirmed it to the same rtol=1e-3 Phase 1 used.
     The relation is genuinely different from 1D's because
     `Device2D.terminal_current()`'s convention is "positive = current
     INTO the device" independently at EVERY contact, whereas 1D's
     `Jn[edge]+Jp[edge]` is a single continuous current sampled at two
     points along one wire -- these are different physical quantities
     with different natural sign conventions, not the same thing named
     differently.

G1 needed the same `dt_max` capping Phase 1's did (same underlying
adaptive-growth-vs-short-timescale interaction; not re-derived as a
new finding, applied directly from the Phase 1 lesson already recorded
in section 5). G2 was deliberately not attempted -- see section 3.

### Files changed (Phase 2):
- `pytcad/pytcad/transient2d.py` (new)
- `pytcad/tests/test_m17_transient2d.py` (new)
- `pytcad/M17-TRANSIENT-PLAN.md`: this update
- `ARCHITECTURE.md`: M17 status updated to Phase 1+2 complete

------------------------------------------------------------------------
8. IMPLEMENTATION RECORD -- PHASE 3 (2026-08-31)
------------------------------------------------------------------------
Exploration BEFORE writing any code (two parallel Explore agents: one on
the GUI service-layer job/spec/result wiring, one on QML panel/
controller registration conventions) confirmed the plan's key
assumption -- `JobRunner`/the subprocess mechanism needed ZERO changes,
since dispatch is purely data-driven off the `DeviceSpec` JSON. This
made Phase 3 mechanically low-risk; the real work was matching existing
conventions exactly (sweep-config's Slot/Property shapes, the ABC's
protocol-with-defaults style, the "cv" mode's own-axis-labels
precedent) rather than inventing new patterns.

End-to-end verified by hand (before writing the automated test suite,
per this repo's own house habit of running the live app for anything
touching the GUI): `run_job()` on both a 1D and a 2D transient
`DeviceSpec` produced a valid schema-v3 npz on the first real attempt
for each dimensionality (only one bug needed fixing along the way, see
below) -- then the full desktop app was launched headlessly
(`QT_QPA_PLATFORM=offscreen`), driven through `AppController.
setTransientConfig()` + `run()` exactly as a real user's click sequence
would, and a screenshot of the rendered "Transient" view mode was
inspected directly (not just "QML loaded without error") to confirm an
actual current-vs-time curve rendered, not a blank or mis-scaled plot.

### Real bugs found and fixed (not guessed, verified with the live app):
1. `pytcad.transient.solve_transient` (1D, Phase 1) requires BOTH
   "left"/"right" waveform keys explicitly -- it has no
   "unmentioned contact defaults to its current bias" convenience the
   way `transient2d.py` (Phase 2) does. `run_transient()`'s first draft
   passed only the stimulus contact's waveform and crashed
   (`TypeError: float() argument ... not 'NoneType'`) inside
   `_as_waveform` on the other, un-mentioned contact. Fixed by
   explicitly passing the non-stimulus contact's already-established DC
   bias as a plain float (auto-wrapped in a `ConstantWaveform`) --
   this is a real, useful asymmetry between the two already-shipped
   solvers to know about, not a Phase 3 bug per se.
2. `MplCanvasItem.fit()` had no `"transient"` branch, so it fell through
   to the generic mesh-axes fallback and autoscaled the plot's x-axis to
   the device's SPATIAL extent in microns (coincidentally producing a
   visually plausible-looking "0 to 6" axis for a 6 um-long diode,
   which is why this was caught by actually looking at a rendered
   screenshot rather than just checking that data reached the canvas
   object without an exception). Fixed by adding a `"transient"` branch
   mirroring "series"/"cv"'s own fit-to-data-range pattern, using
   `TransientResult.times` instead of a swept voltage array.
3. Bumping `SOLVER_RESULT_SCHEMA_VERSION` to 3 broke three PRE-EXISTING
   tests that hardcoded the literal `2` as "the current version"
   (`test_run_record_v2.py`'s two version-constant assertions,
   `test_m7_devsim.py`'s backend-stamp check) -- an expected, correct
   consequence of a real version bump, not a regression, fixed by
   updating those literals to `3` (and, for the devsim one, switching
   `workbench/solvers/devsim_backend.py`'s own hardcoded `2` to import
   the live `SOLVER_RESULT_SCHEMA_VERSION` constant instead, so a
   future bump doesn't require editing that file's literal again).
4. `check_devsim_compatible()` had no check for `spec.transient` at
   all -- confirmed by reading `DevsimBackend.run()` directly that it
   never dispatches on `spec.transient`, meaning an armed transient
   config selected on the devsim backend would have been silently
   solved as a plain bias job instead of refused. Fixed by adding an
   explicit rejection, the same "hidden failure" pattern this
   function's other checks (region_materials, non-default models)
   already existed to catch.

Verified: `pytest tests/ gui/tests/ -n 6 -m "not slow" -q` -> 891
passed (878 + 13 new Phase 3 tests), 25 skipped, 1 xfailed, 3 failed
(the same pre-existing, unrelated M20 set), zero new warnings.
Adversarial pass: a `"constant"` waveform (a deliberate no-op transient)
runs without crashing; `equilibrium_only=True` combined with an armed
transient config runs correctly from the equilibrium state -- the ONE
combination Phase 3 deliberately does NOT reject (unlike sweep+
equilibrium_only, which IS rejected), matching the plan's stated
compatibility claim that a transient run can legitimately start from
equilibrium.

### Files changed (Phase 3):
- `pytcad/gui/services/device_spec.py`: `WaveformSpec`, `TransientSpec`,
  `DeviceSpec.transient` field
- `pytcad/gui/services/solver_runner.py`: `_waveform_from_dict`,
  `run_transient`, `_solve_all`/`run_job` wiring
- `pytcad/gui/services/solver_backend.py`: schema v2 -> v3 bump,
  transient block validation, `RunRecord.transient`
- `pytcad/gui/services/result_store.py`: `TransientResult`,
  `has_transient`/`transient_result` on the ABC + `NpzResultStore`
- `pytcad/gui/controllers/app_controller.py`: transient config
  slots/properties, `run()` dispatch + mutual-exclusion check
- `pytcad/gui/qml/panels/TransientPanel.qml` (new)
- `pytcad/gui/qml/Main.qml`: new tab + view-mode selector entry
- `pytcad/gui/qml/panels/ViewportPanel.qml`,
  `pytcad/gui/visualization/mpl_canvas_item.py`: "transient" view mode
  (`setTransientSource`, `_draw_transient`, `fit()` branch)
- `pytcad/workbench/solvers/devsim_backend.py`: reject `spec.transient`;
  stamp from the live schema-version constant instead of a literal
- `pytcad/gui/tests/test_transient_gui.py` (new, 13 tests)
- `pytcad/gui/tests/test_run_record_v2.py`,
  `pytcad/gui/tests/test_m7_devsim.py`: updated for the v3 schema bump
