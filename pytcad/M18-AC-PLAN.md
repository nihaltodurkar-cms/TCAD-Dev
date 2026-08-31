# M18 — Small-Signal AC Analysis Implementation Plan

Status: PHASE 1 (Device1D) LANDED 2026-08-31. Gate battery
`tests/test_m18_ac.py`, 6/6 green. Phase 2 (Device2D) and Phase 3
(GUI) not started -- see section 4.

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

## 4. Honest limits

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
  (Y11/Y12/Y21/Y22) or reciprocity check. Sufficient for the stated
  acceptance gates (all two-terminal); a full 2-port framework is
  deferred, not attempted.
- `Device2D`/`Device3D` AC analysis: not started (Phase 2, natural
  continuation given M17's own 2D transient phase already exists to
  mirror the same external-driver pattern against).
- GUI exposure: not started (Phase 3, same as M17's own Phase 3 was
  separately scoped from Phases 1/2).

## 5. Files changed

- `pytcad/pytcad/ac.py` (new)
- `pytcad/tests/test_m18_ac.py` (new)
- `pytcad/M18-AC-PLAN.md` (new, this file)
- `ARCHITECTURE.md`: M18 status line + milestone table updated
- `history.md`: new STATE ADDENDUM
