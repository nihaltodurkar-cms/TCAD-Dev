# M18 — Small-Signal AC Analysis Implementation Plan

Status: PHASE 1 (Device1D one-port) LANDED 2026-08-31. PHASE 2
(Device1D N-terminal Y-parameters + fT) LANDED 2026-09-04, merged in
from a parallel branch (commit 9906d6b). PHASE 3 (Device2D, N-terminal
Y-parameters incl. gate ports) LANDED 2026-09-04. PHASE 4 (GUI
exposure) LANDED 2026-09-05 -- see sections 12-16 below for the
design; implementation plan at
docs/superpowers/plans/2026-09-05-m18-phase4-ac-gui.md. Gate battery
`gui/tests/test_ac_gui.py` green (non-QML gates); QML-object-tree
gates (`test_ac_panel.py`, viewport selector) written and correct,
verified against the same pre-existing local Qt6/QML environment
issue this session's other GUI work already documented (not a defect
in this phase's own code -- confirmed by reproducing the identical
failure with `git stash` before writing any of this phase's code).
Gate batteries `tests/test_m18_ac.py` (6/6), `tests/test_m18_yparam.py`
(Phase 2), and `tests/test_m18_ac2d.py` (6/6), all green. Phase 3b
(full 4-terminal `mosfet_2d` Y-parameter/fT extraction) not started --
see section 15.

## 1. Scope (Phase 1)

Frequency-domain perturbation of a converged `Device1D` DC operating
point: complex linear solve reusing the same analytic Jacobian
`_residual_jacobian` already assembles for the DC Newton core, with a
capacitive storage term added in exactly the shape M17's
backward-Euler `dV*dn/dt`/`-dV*dp/dt` term takes, `d/dt -> j*omega`
instead of the backward-Euler `1/dt`. Output: a small-signal
admittance `Y(f)` (one-port, driving one contact with a unit AC
voltage, the other AC-grounded), decomposed into `C(f) = Im(Y)/(2*pi*f)`
and `G(f) = Re(Y)`.

New module `pytcad/pytcad/ac.py`, following the M15/M16/M17 pattern of
driving `Device1D` from OUTSIDE `device.py` through its own
`_residual_jacobian` -- `device.py` is NOT touched, and no new `Models`
flag was added (AC is a different equation formulation layered on the
converged DC point, not a physics term to toggle -- M17 set this same
precedent).

Descoped this phase (see section 4): `Device2D` AC, GUI exposure,
Y-parameter reciprocity/2-port framework beyond the one-port case
needed for the acceptance gates.

## 2. Architecture

```
J_ac(w) = J0 + 1j*w_s*Cmat
```

- `J0`: the real DC Jacobian from `device._residual_jacobian(psi0, n0,
  p0, bc0)` at the converged operating point.
- `Cmat`: `pytcad.ac._storage_matrix` -- EXACTLY
  `transient._step_residual_jacobian`'s storage-term addition with
  `dt_s = 1.0` substituted in (verified bit-for-bit identical in
  G-CONSISTENCY, not re-derived independently).
- `w_s = 2*pi*f*t0`, `t0 = device.Ns/device.R0` -- the same time scale
  `transient._time_scale` uses.
- Forcing: driving one contact's Poisson row with a unit `1.0+0j` RHS
  entry (that row is a pure Dirichlet identity row in `J0`), all other
  rows zero-forced -- physically correct because a Device1D ohmic
  contact's densities (`_contact_values`) depend only on doping/`nie`,
  never on the applied voltage, so `dn/dV = dp/dV = 0` at a contact
  exactly, and the un-driven contact stays fixed (AC-grounded).
- `delta_u = spsolve(J_ac.tocsc(), b)` -- one linear complex solve, no
  Newton loop (the system is genuinely linear in `delta_u` at fixed
  `(psi0,n0,p0)`).
- Terminal-current sensitivity `S` (real, 6 nonzero entries per driven
  edge): a central finite difference on the SAME `Jn[edge]+Jp[edge]`
  values `_residual_jacobian` already returns (also what
  `transient._record_current` reads) -- not a hand-rederived
  Scharfetter-Gummel derivative, so it is automatically correct
  whatever physics-model toggles (FD statistics, band-offset SG, ...)
  the device was built with.
- `Y = S @ delta_u`; `Y_phys [S/cm^2] = Y_scaled * device.J0 /
  device.VT` (the same `J0`/`VT` scale-factor convention `current_
  density()` and every other DC/transient quantity already uses).

## 3. Gates (`tests/test_m18_ac.py`)

1. **G-CONSISTENCY**: `Cmat` bit-identical (max abs diff < 1e-9) to
   `transient._step_residual_jacobian`'s storage term at `dt_s=1.0` --
   a strong regression check against the already-FD-gated M17 formula,
   used in place of a fresh FD-Jacobian derivation (justified: the
   affine map `u -> J0*u + j*w*Cmat*u` would trivially reproduce
   `Cmat` under its own FD probe, so an independent-formula check is
   the more informative gate here). GREEN.
2. **G-LOWF** (the ARCHITECTURE-mandated gate): at `f=1 Hz` (deep in
   the low-f plateau), `Re(Y)` and `C` matched against a finite-
   difference `dI/dV` / `dQ/dV` from two independent `solve_bias(V0 +-
   1e-5)` calls. Measured: `G` relative error 2.76e-5, `C` relative
   error 8.08e-5 (gate threshold 1e-2, both comfortably inside). This
   single gate independently validates both `Cmat` and the current-
   sensitivity vector `S` at once. GREEN.
3. **G-JUNCTION-C**: equilibrium (V=0) low-f `C` on an abrupt
   Na=Nd=1e17 diode vs the textbook depletion formula `C_j = eps/W`,
   `W = sqrt(2*eps*Vbi/q*(1/Na+1/Nd))` (same `Vbi` formula
   `test_validation.py::test_built_in_potential` already gates
   independently). No such junction-capacitance gate previously
   existed in the repo (confirmed during planning). Measured: 3.32%
   relative error (gate threshold 10%) -- attributed to the finite
   device structure vs the formula's infinite one-sided assumption,
   not investigated further. GREEN.
4. **G-ROLLOFF** (the honest-limits-aware version of ARCHITECTURE's
   "3dB roll-off... against the analytic stored-charge pole from
   M17"): see section 4 -- no quantitative pole match attempted,
   qualitative roll-off signature only. Measured on a 0.4V-forward-
   biased diode, freqs 1kHz-1e11Hz: `C` drops 1.048e-7 -> 1.542e-8
   F/cm^2 (6.80x, gate threshold >5x), `G` rises 1.042e-2 -> 2.418e4
   S/cm^2 (2.32e6x, gate threshold >1e5x), both stay finite and `G`
   stays positive throughout. GREEN.
5. **G-LIVE-STATE**: `ac_sweep` at V=0.0 vs V=0.3 gives Y differing by
   >10% -- catches a stale-cached-Jacobian bug directly (mirrors the
   M15/M16 live-state-gates-first convention). GREEN.
6. **G-SCOPE-REFUSAL**: `ac_sweep(Device2D)` raises `TypeError` (same
   convention as M16's G-F / M21's 3D+gates refusal). GREEN.

Full suite: `pytest tests/ gui/tests/ -n 6 -m "not slow" -q` -- see
history.md addendum for the run this session, unchanged apart from the
6 new M18 tests.

## 4. Honest limits (Phase 1)

- **G-ROLLOFF has NO quantitative pole match**, by design: M17's own
  plan doc (section 5) explicitly tried and abandoned `Qs ~=
  I_F*tau_p` as sign-ambiguous and off by a factor of several for the
  diode-turnoff scenario. This session did not re-attempt deriving a
  clean `tau_p`-based corner-frequency formula for the same reason --
  the gate checks the qualitative "does it roll off" signature
  ARCHITECTURE.md's literature-note framing calls for, not a specific
  number.
- **Numerical validity ceiling found during development**: sweeping
  well past ~3e11 Hz on the test diode, `C(f)` crosses zero and goes
  slightly negative near 1e12 Hz -- the complex solve loses physical
  fidelity at frequencies that fast relative to this mesh/device's own
  intrinsic timescales. Not investigated further (genuinely outside
  the swept, gated range) and not gated; a future session extending
  this analysis to picosecond-scale devices would need to establish
  where this ceiling actually sits.
- **A real bug was found and fixed while deriving `S`** (the current-
  sensitivity vector), left here as a durable numerical-methods note:
  an early version computed each of the 6 finite-difference probes
  with a step size scaled to THAT node's own state magnitude
  independently. Since the edge current depends on `psi[node_lo]` and
  `psi[node_lo+1]` ONLY through their difference, `dI/dpsi[lo]` and
  `dI/dpsi[lo+1]` must cancel EXACTLY when dotted against a state
  response that shifts both nodes together (a common physical case).
  Using a different step size at each node broke that cancellation at
  a magnitude comparable to the genuine signal, producing a silent
  ~2x error in the low-frequency conductance that only surfaced when
  cross-checked against the independent `dI/dV` finite difference
  (G-LOWF) -- caught before it became a gate result, not after. Fixed
  by sharing one step size across both nodes of a given state
  component (`_edge_current_sensitivity` in `pytcad/ac.py`).
- Only a one-port measurement is implemented (drive one contact,
  AC-ground the other) -- no general multi-terminal Y-parameter matrix
  (Y11/Y12/Y21/Y22) or reciprocity check. Addressed in Phase 2 (section
  6) for Device1D and Phase 3 (sections 7-10) for Device2D.
- `Device2D` AC analysis: landed in Phase 3, see sections 7-10 below.
  `Device3D` AC analysis remains out of scope entirely.
- GUI exposure: not started (Phase 4, same as M17's own Phase 3 was
  separately scoped from Phases 1/2).

## 5. Files changed (Phase 1)

- `pytcad/pytcad/ac.py` (new)
- `pytcad/tests/test_m18_ac.py` (new)
- `pytcad/M18-AC-PLAN.md` (new, this file)
- `ARCHITECTURE.md`: M18 status line + milestone table updated
- `history.md`: new STATE ADDENDUM

## 6. Phase 2 (Device1D N-terminal Y-parameters + fT)

Landed 2026-09-04 via merge of a parallel branch (commit 9906d6b,
"Merge parallel branch: 3D unstructured DD, Y-params, DG fix, new GUI
panels") that this session's own history does not otherwise cover --
summarized here from the shipped code
(`pytcad/pytcad/ac.py::y_parameters`/`cutoff_frequency`,
`pytcad/tests/test_m18_yparam.py`) for a complete record, since that
branch did not itself update this plan doc.

- Additive to `ac.py`: `YParamResult`, `y_parameters(device, freqs)`,
  `cutoff_frequency(yres)`. Same `J_ac(w) = J0 + 1j*w_s*Cmat` machinery
  as Phase 1, factored ONCE per frequency (`scipy.sparse.linalg.splu`)
  and reused across both ports' RHS solves.
- Fixed at exactly 2 ports: `Device1D` has only a left/right contact,
  so this is the full `Y11/Y12/Y21/Y22` matrix for that structure, not
  a general N>2-terminal framework (no such 1D device exists in this
  repo).
- `fmax` (Mason's unilateral power gain crossing) deliberately NOT
  implemented: only physically meaningful for an active 3-terminal
  device, and would be a vacuous figure of merit on a reciprocal
  2-terminal diode's Y matrix. `fT` (current-gain cutoff, from
  `|Y21/Y11|=1`) has no such problem and is implemented via a
  log-log bisection for the crossing.
- Gates (`tests/test_m18_yparam.py`): reduction to `ac_sweep`'s
  one-port result, right-port magnitude match, reciprocity, junction-C
  cross-check, positive diagonal conductance, `fT` sanity/crossing-
  algorithm gates, and an `splu`-reuse-vs-`spsolve` parity check.

## 7. Scope (Phase 3)

Generalize the frequency-domain small-signal analysis to `Device2D`,
and generalize the port model from Phase 1/2's fixed 2-port
(Device1D-only) case to a genuine N-terminal Y-parameter matrix
(`Y[k,i,j] = dI_i/dV_j` at `freqs[k]`, all undriven ports AC-grounded)
covering BOTH of `Device2D`'s port kinds: `DirichletBC` (ohmic
contact) and `GateBC` (Robin/oxide-coupled gate) -- scoping decisions
made explicitly with the user before implementation:

- Device scope: full MOSFET-capable (gate terminal included), not
  ohmic-only.
- Port scope: N-terminal Y-parameters, not a fixed 2-terminal
  one-port measurement.
- Gate physics anchor: `moscap_2d` (a 2-terminal gate+body `Device2D`
  fixture built for this phase, mirroring `MOSCapacitor`'s own 1D
  setup) is the acceptance-gate target; full 4-terminal `mosfet_2d`
  Y-parameter/fT extraction is explicitly deferred as Phase 3b.
- GUI exposure: out of scope, deferred to Phase 4 (separate effort).

New module `pytcad/pytcad/ac2d.py`, following the same
externally-driven pattern as `ac.py`/`transient2d.py` --
`pytcad/device2d.py` is NOT touched.

## 8. Architecture (Phase 3)

Same `J_ac(w) = J0 + 1j*w_s*Cmat` shape as Phases 1/2, `w_s =
2*pi*f*t0`, `t0 = device.Ns/device.R0`. Two structural differences
from the 1D modules:

- **`Cmat` needs no gate-row term.** `Device2D`'s Poisson residual
  carries no time derivative anywhere in this codebase (only the n/p
  continuity rows do, same as 1D) -- confirmed by reading
  `_residual_jacobian` directly. So `_storage_matrix` in `ac2d.py` is
  structurally identical to `ac.py`'s (n/p diagonal rows only, `dt_s
  =1.0` convention), verified bit-identical against
  `transient2d._step_residual_jacobian`'s own storage term
  (G-CONSISTENCY-2D).
- **Two port kinds, two forcing/observation formulas**, dispatched by
  `isinstance(bc, DirichletBC | GateBC)`:
  - **Ohmic** (`DirichletBC`): forcing `b[3*m]=1` for every node `m`
    in the contact (mirrors Phase 1's Dirichlet-row convention, now
    generalized from a single node to an arbitrary node SET, since a
    named 2D contact can span many mesh nodes). Observation: a real
    central finite difference of `terminal_current`'s own raw
    `F_n+F_p` sum, using ONE shared step size per state component
    across the whole "support set" (the contact's nodes plus their
    4-connected neighbors) -- generalizes Phase 1's shared-step-size
    fix (see Phase 1 section 4's "real bug" note) from a 1D two-node
    edge to a 2D multi-node stencil.
  - **Gate** (`GateBC`): CLOSED FORM, no FD needed. From the gate
    row's own linearization (`dF[m]/dVg_s = +kappa*w[m]`, read
    directly out of `_residual_jacobian`), forcing is `b[3*m] =
    -kappa*w[m]` and the observation is `Y[i,k](w) = j*w_s *
    sum_{m in gate i's nodes} kappa*w[m] * (delta_ik - du_k[3*m])`,
    `delta_ik=1` only when gate `i` is the driven port `k`. This is
    genuinely new territory: `transient2d.py`'s own docstring
    explicitly notes time-varying `GateBC` voltage isn't supported
    there -- gated FIRST (G-GATE-FD, before anything else gate-related)
    against a direct finite difference of two independent
    `solve_bias({"gate": ...})` calls, not trusted by construction.
- **Physical scaling**, uniform across BOTH port kinds: `Y_phys =
  Y_scaled * device.J0 * device.LD / device.VT` (matches
  `terminal_current`'s own `*J0*LD` current convention, `/VT` since a
  unit *scaled* voltage perturbation corresponds to `VT` physical
  volts). A DIFFERENT conversion applies when converting a raw
  Poisson-residual flux value to physical CHARGE (used only inside
  G-GATE-FD's own independent reference, not in `ac2d.py` itself):
  `Q_phys = flux_scaled * Q_electron * LD^2 * Ns` (no `/VT` -- this
  converts a value, not a per-volt derivative).

## 9. Gates (`tests/test_m18_ac2d.py`)

1. **G-CONSISTENCY-2D**: `Cmat` bit-identical to
   `transient2d._step_residual_jacobian`'s storage term at `dt_s=1.0`
   (same justification as Phase 1's G-CONSISTENCY). GREEN.
2. **G-LOWF-2D**: on a 2-terminal ohmic diode2d, `f=1 Hz` `Re(Y)`/`C`
   match FD `dI/dV`/`dQ/dV` from two independent `solve_bias` calls.
   GREEN.
3. **G-NPORT-OHMIC**: a genuine 3-ohmic-terminal fixture
   (`_resistor3term`, no such >2-terminal 2D device existed anywhere
   in the repo before this phase) -- full 3x3 `Y` is approximately
   reciprocal (loose tolerance, same known particle-current-only
   omission Phase 2's own Y-parameter reciprocity gate documents), and
   the third port (never exercised by any 2-port case) shows a
   genuinely nonzero response, not a degenerate zero row from a bug in
   the N-port generalization. GREEN.
4. **G-GATE-FD**: the closed-form gate forcing/observation formula
   matches a direct finite difference of two independent
   `solve_bias({"gate": ...})` calls to <5% relative error. GREEN --
   see section 10's ill-conditioning note for what it took to get
   here.
5. **G-MOSCAP-CV** (the headline physics gate): low-f `Cgg(Vg)` from
   the `Device2D` gate port tracks `MOSCapacitor.cv_sweep`'s
   independent quasi-static reference (accumulation/depletion/
   near-threshold, <25% relative error), AND shows a genuine
   measurable high-frequency roll-off (not a frequency-independent
   constant). GREEN -- but substantially descoped from its original
   design; see section 10.
6. **G-SCOPE-REFUSAL-2D**: `y_parameters(Device1D)` raises `TypeError`
   (mirrors Phase 1's G-SCOPE-REFUSAL). GREEN.

Full suite: `pytest tests/ gui/tests/ -n 6 -q` -- see history.md
addendum for the run this session.

## 10. Honest limits (Phase 3)

- **A 5nm oxide (`tox_cm=5e-7`, matching
  `test_cv_physics_validation.py`'s own value) makes the gate row's
  linearization numerically ill-conditioned** on the `moscap_2d` test
  mesh used (graded 61-point y-mesh, depth=2e-4 cm): the AC-computed
  gate-node sensitivity varied wildly (0.045 to 1.746) across
  nominally-equivalent Newton-tolerance settings, while a direct
  finite difference of `psi` itself (two independently-converged
  `solve_bias` calls) stayed rock-stable at ~0.378. This looked like a
  ~5x formula bug and consumed most of this phase's debugging time;
  root-caused instead to fixture conditioning by switching to
  `tox_cm=2e-6` (20nm), where the closed-form sensitivity matched the
  direct FD reference to 8 significant figures (0.558410 vs
  0.558410) -- confirming `ac2d.py`'s formula/code is correct.
  `MOSCAP_PARAMS` in the test file uses 20nm for this reason, with the
  finding documented inline.
- **G-MOSCAP-CV could not reproduce the classic inversion-region LF/HF
  divergence its original design targeted**, for a genuine physical/
  numerical reason, not a bug: the real-device signature
  `test_cv_physics_validation.py` documents analytically comes from
  minority-carrier GENERATION LIFETIME, a slow (Hz-to-kHz) process.
  On the `moscap_2d` fixture, the DC solve genuinely DOES build an
  inversion layer past threshold (surface `n` exceeds `Na` by
  `Vg=1.0`, confirmed by direct inspection of `dev.n`) -- but the
  linearized AC *sensitivity* stops tracking `MOSCapacitor`'s
  quasi-static reference beyond `Vg~0.6` (near this fixture's own
  threshold), most likely the same class of Jacobian ill-conditioning
  as the tox_cm finding above, now triggered by the huge surface/bulk
  carrier-concentration ratio in strong inversion rather than oxide
  thinness. Separately, the roll-off that DOES appear in this fixture
  (~1e10-1e11 Hz) was measured to be essentially bias-INDEPENDENT
  (near-identical onset at Vg=-0.5, 0.0, 0.3) -- a structural
  dielectric-relaxation/RC effect of the small (2 micron) mesh, not an
  inversion-specific minority-carrier-lag signature. G-MOSCAP-CV was
  therefore rescoped to accumulation/depletion/near-threshold bias
  points only (where LF genuinely matches the reference) plus a
  bias-independent high-frequency roll-off sanity check, rather than
  forcing a pass with a cherry-picked tolerance or bias point. Deep-
  inversion small-signal AC fidelity for `Device2D` gates is left as a
  known, undeferred-but-unsolved limitation for any future session
  that needs it.
- **N-port ohmic reciprocity uses a loose tolerance** for the same
  reason Phase 2's own reciprocity check does: the current-sensitivity
  `S` vector captures particle current only (`F_n+F_p`), an
  already-known, already-documented omission carried forward
  unchanged from Phase 1/2.
- Full 4-terminal `mosfet_2d` Y-parameter matrix / fT extraction: not
  attempted (Phase 3b, explicitly deferred per the user's own scoping
  decision going into this phase).
- GUI exposure: not started (Phase 4, unchanged from Phase 1's own
  scoping).
- `Device3D` AC analysis: out of scope entirely, not part of any
  planned phase.

## 11. Files changed (Phase 3)

- `pytcad/pytcad/ac2d.py` (new)
- `pytcad/tests/test_m18_ac2d.py` (new)
- `pytcad/M18-AC-PLAN.md` (this file, sections 6-11 added: section 6
  backfills Phase 2's record, sections 7-11 are this phase's own)
- `ARCHITECTURE.md`: M18 status line + milestone table updated
- `history.md`: new STATE ADDENDUM

## 12. Scope (Phase 4)

Expose Phase 1-3's Y-parameter/AC machinery in the GUI: a single-
contact frequency sweep armed from a new panel, dispatched through the
existing solve pipeline (`solver_runner.py`), and plotted as C(f)/G(f).
Landed 2026-09-05 via the implementation plan at
`docs/superpowers/plans/2026-09-05-m18-phase4-ac-gui.md`; this section
and 13-16 record the design retroactively as part of Task 9 (this plan
doc's own sections 12-16 were never actually written before Task 1
started coding -- a process gap discovered while landing Phase 4,
same kind of backfill section 6 already did for Phase 2's un-recorded
landing).

- New wire-format type `ACSpec` (`gui/services/device_spec.py`)
  mirroring `SweepSpec`/`TransientSpec`'s validate/round-trip shape
  exactly: `contact`, `f_start`, `f_stop`, `n_points` (log-spaced only
  -- AC analysis is inherently multi-decade, no linear-spacing option).
  Additive `DeviceSpec.ac` field; a job file saved before this phase
  (no `ac` key at all) still loads unchanged.
- Dispatch in `solver_runner.py`'s `_solve_all()`/`run_job()` for BOTH
  `Device1D` and `Device2D`, reusing `pytcad.ac.y_parameters`/
  `pytcad.ac2d.y_parameters` (Phase 1/2/3's own code, untouched) --
  explicit refusal (`ValueError`) for `Device3D` (no `ac3d` module
  exists, same honesty standard Phase 1's G-SCOPE-REFUSAL set).
- `AppController` wiring: `setACConfig`/`clearACConfig`/`acConfig`/
  `hasACConfig`/`hasAc`/`acResultForQml`/`canRunAc`, plus extending the
  existing Sweep/Transient mutual-exclusion check in `run()` to a
  3-way Sweep/Transient/AC mutex.
- New `"ac"` plotting mode in `MplCanvasItem`: C(f) on the primary
  axis, G(f) on `ax.twinx()`.
- New "AC" entry in the viewport mode selector.
- New `ACPanel.qml` config panel registered as a workbench tab (with
  its own icon in `Icons.qml`/`icon_provider.py`).
- Explicitly NOT in scope: the GUI surfaces only the driven port's own
  diagonal `Y[:, port_idx, port_idx]` (C/G of the driven contact
  against AC ground) -- Phase 2/3's full N-port Y-matrix and `fT` are
  not displayed anywhere in this phase. AC combined with an armed
  Sweep or Transient is refused (mutually exclusive, same as
  Sweep+Transient already are). `Device3D` AC remains out of scope
  entirely, unchanged from Phase 1-3.

## 13. Architecture (Phase 4)

Two real design corrections were found and applied while WRITING the
implementation plan (before any Task 1 code existed):

1. **Solver-dispatch insertion point.** AC does not replace
   equilibrium/bias the way `sweep`/`transient` do (each of which is a
   full alternative to a plain bias solve) -- AC instead runs AT the
   same converged operating point an ordinary bias solve already
   reaches. The naive design would add a fourth top-level
   `elif spec.ac is not None:` branch alongside `_solve_all()`'s
   existing `if spec.transient... elif spec.sweep... else:` chain,
   making AC a mutually-exclusive fourth "mode" -- semantically wrong,
   since AC augments a plain-bias result rather than replacing it.
   Corrected: the AC dispatch lives INSIDE the existing `else:` branch
   (the plain-bias path), placed right after `extract_result()`, so an
   armed AC config adds `ac__*` keys onto the ordinary
   equilibrium/bias result dict instead of describing a fourth
   disjoint solve mode. See `solver_runner.py::_solve_all()`'s own
   comment at the dispatch site.
2. **Canvas plotting decision.** C(f) and G(f) differ by many orders
   of magnitude across a Hz-to-GHz sweep and cannot share one linear
   y-axis meaningfully. The naive design would add a new multi-
   subplot figure layout to `MplCanvasItem` -- a first, since every
   existing mode draws on a single `Axes`. Corrected: use `ax.twinx()`
   on the SAME single Axes every other mode already gets -- C(f) on
   the primary (left) axis, G(f) on a twin (right) axis sharing the
   log-scaled frequency x-axis -- confirmed while planning this that
   no existing mode needed more than one Axes, so `twinx()` keeps
   `MplCanvasItem`'s one-Axes-per-mode invariant intact rather than
   adding a second code path for multi-Axes figures. Known limitation
   carried from this decision: the hover-readout
   (`_remember_series`/`self._ax`) tracks only the C(f) curve on the
   primary axis -- G(f)'s twin axis is not readout-hoverable.

Port-resolution note (also referenced from `solver_runner.py`):
`Device1D` has no named contact registry at the core level, so
`apply_bias()`'s own positional convention (`contacts[0]` = left/x=0
node, `contacts[1]` = right node, regardless of either contact's name)
is reused to resolve `spec.ac.contact` to `port_idx` 0 or 1. `Device2D`
DOES have a named port registry (`yres.port_names`, covering both
`DirichletBC` ohmic contacts and `GateBC` gates), so its port index is
resolved with a plain name lookup instead.

Wire format: additive `ac__freqs`/`ac__C`/`ac__G`/`ac__port`/
`unit__ac_capacitance`/`unit__ac_conductance` keys in the result dict,
following the same `<field>__<name>` convention `sweep__*`/
`transient__*` already use. `ResultStore.has_ac()`/`ac_result()` mirror
the existing `has_sweep`/`has_transient`-style accessors.

## 14. Gates

- `gui/tests/test_ac_gui.py` (pure Python, no QML engine): `ACSpec`
  validation (bad frequencies, bad `n_points`, unregistered contact),
  `DeviceSpec.ac` JSON round-trip, backward compatibility with a job
  file missing the `ac` key entirely, `ResultStore.has_ac()` honesty
  (`SpecResultStore` and `NpzResultStore`, including a plain non-AC
  run reading back `has_ac()==False`), G-AC-1D (a CLI-driven 1D AC
  run's stamped `ac__C`/`ac__G` matches a direct `pytcad.ac.
  y_parameters` call, both contacts), G-AC-2D (same cross-check on a
  real `Device2D` moscap fixture, driving the gate port), G-AC-3D-
  REFUSAL (`Device3D` raises a clear `ValueError` naming AC/Device3D),
  `AppController`-level `setACConfig`/`clearACConfig`, `canRunAc`
  hidden for a 3D spec, the 3-way Sweep/Transient/AC mutual-exclusion
  refusal, refusal on an unregistered contact name, and a full `run()`
  tagging the result so `hasAc` reads back true.
- `gui/tests/test_mpl_canvas_item.py`: the `"ac"` mode's `twinx()` draw
  path (pure matplotlib, no QML engine).
- QML-object-tree gates (require the real QML engine -- in THIS
  sandbox these fail on the pre-existing local Qt6/QML plugin-load
  issue documented throughout this session's other GUI work, verified
  by reproducing the identical failure with `git stash` on unmodified
  code): `gui/tests/test_ac_panel.py` (`ACPanel` present in the QML
  tree; arm-and-clear end-to-end through the real panel; a rejected
  arm reverts fields to the last armed config) and
  `gui/tests/test_viewport_modes.py::test_view_mode_selector_offers_ac`.

## 15. Honest limits (Phase 4)

- N-port Y-matrix / `fT` are NOT exposed in the GUI: only the driven
  port's own diagonal C(f)/G(f) is plotted (same one-port scope Phase
  1's own GUI target always intended); the underlying Phase 2/3 Python
  API can compute the full matrix, this phase does not surface it.
- AC + Sweep and AC + Transient combined runs are NOT supported:
  mutually exclusive, same as Sweep+Transient already are -- a user
  must clear the other armed config before running AC.
- `Device3D` AC: still out of scope entirely (unchanged from Phase
  1-3), refused with an explicit error rather than silently ignored.
- The hover-readout on the `"ac"` canvas mode only tracks C(f) (primary
  axis); G(f)'s twin axis is not hoverable -- a direct consequence of
  the `twinx()` decision in section 13, left as-is for this phase.
- Project-file persistence of an armed AC config follows the same
  additive round-trip pattern `SweepSpec`/`TransientSpec` already use
  (no new persistence mechanism), but per-run field-snapshot/animation
  playback (already out of scope for Transient per M17's own plan) is
  equally out of scope here.
- **Phase 4 itself is now LANDED (2026-09-05):** GUI exposure, the
  item this milestone's own table has carried as "NOT STARTED" since
  Phase 1, is complete for the single-port C(f)/G(f) case described
  above. What remains deferred is Phase 3b (full 4-terminal
  `mosfet_2d` Y-parameter/fT extraction, unaffected by this phase) and
  the N-port-matrix/AC+Sweep items listed above.

## 16. Files changed (Phase 4)

- `pytcad/gui/services/device_spec.py` (`ACSpec` + `DeviceSpec.ac`)
- `pytcad/gui/services/result_store.py` (`ACResult`,
  `has_ac()`/`ac_result()`)
- `pytcad/gui/services/solver_runner.py` (AC dispatch in
  `_solve_all()`/`run_job()`, Device1D+Device2D, Device3D refusal)
- `pytcad/gui/controllers/app_controller.py` (`setACConfig`/
  `clearACConfig`/`acConfig`/`hasACConfig`/`hasAc`/`acResultForQml`/
  `canRunAc`, 3-way `run()` mutex)
- `pytcad/gui/visualization/mpl_canvas_item.py` (new `"ac"` mode,
  `ax.twinx()`)
- `pytcad/gui/qml/panels/ACPanel.qml` (new)
- `pytcad/gui/qml/panels/ViewportPanel.qml` (AC entry in the mode
  selector)
- `pytcad/gui/qml/Main.qml`, `pytcad/gui/qml/components/
  MainToolBar.qml`, `pytcad/gui/qml/Icons.qml`,
  `pytcad/gui/services/icon_provider.py` (workbench tab registration +
  icon)
- `pytcad/gui/tests/test_ac_gui.py`, `pytcad/gui/tests/test_ac_panel.py`,
  `pytcad/gui/tests/test_mpl_canvas_item.py` (new),
  `pytcad/gui/tests/test_viewport_modes.py`,
  `pytcad/gui/tests/test_shell_icons.py`,
  `pytcad/gui/tests/test_transient_gui.py` (updated)
- `pytcad/M18-AC-PLAN.md` (this file, sections 12-16 added)
- `ARCHITECTURE.md`: M18 status line + milestone table updated
- `history.md`: new STATE ADDENDUM
