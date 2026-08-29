# M16 — Band-to-Band Tunneling (Local Kane) Implementation Plan

Status: implementation landed 2026-08-29; gate battery
`tests/test_m16_btbt.py` + coefficient pins in
`tests/test_model_benchmarks.py`.

## 1. Scope

Local Kane BTBT generation coupled into the Device1D Newton core:

    G(F) = A * F^2 * exp(-B / F)      [cm^-3 s^-1],  F = |E| [V/cm]
    A = 3.5e21 cm^-3 s^-1,  B = 1.03e8 V/cm   (Si, Hurkx 1992 Table I)

Out of scope (deferred): nonlocal line-integral BTBT (Tier 3 — needs
general meshes), the Modified-Hurkx dynamic local correction, 2D/3D
ports (Device2D/Device3D raise NotImplementedError on `btbt=True`).

## 2. Architecture (follows M15 R1b exactly)

- `pytcad/btbt.py` — pure coefficient module (mirrors
  `pytcad/ionization.py`): `KANE_A_SI`/`KANE_B_SI` published-table
  constants, `btbt_generation(F)`, `dbtbt_dF(F)`. Vectorized, no
  cross-module dependencies.
- `Models(btbt=False)` — default OFF => bit-identical to the plain
  solver (G-A goldens).
- `_residual_jacobian`: a live-coupled generation block placed AFTER
  both continuity-row `=` assignments and BEFORE Dirichlet stamping
  (the M15 D1 ordering invariant — now gated first, see below).
  G depends on the state through E(psi) alone, so the chain rule runs
  only through the node field (the same `E_i = 0.5*(e_mag[i-1] +
  e_mag[i])` and `dE_i/dpsi_{L,M,R}` chain the II block validated).
  Residual: `F[3i+1] += G/R0*dV`, `F[3i+2] -= G/R0*dV`, interior
  nodes only. Jacobian: dG/dpsi on both continuity rows via
  `dG/dF / R0 * dE_i/dpsi_j`.
- `solve_bias`: BTBT shares the II strength ladder (`_II_STAGES`) and
  the backtracking merit test (`stiff_gen = impact or btbt`). A Zener
  source is stiffer than avalanche onset (G ~ exp(-1e8/F)), so the
  leading 0.0 generation-free relaxation stage matters just as much.
- `self._btbt_gs_cache`: the live source the residual last integrated
  (introspection/gates only; None whenever `Models.btbt` is False —
  the M15 D4 stale-source protection, mirrored).
- Catalog: `"btbt"` ModelInfo in `workbench/core/catalog.py`, wire
  default `"btbt": False` in `gui/services/device_spec.py`
  (`default_config() == _default_models()` invariant kept).

## 3. Gates (ordering gates FIRST — the explicit M16 lesson)

1. **Residual-ordering invariant** — probing the residual directly at
   a fixed state: BTBT-on minus BTBT-off is zero in Poisson rows, zero
   at both contact nodes, antisymmetric (+g/-g) between the electron
   and hole rows of each interior node, and non-zero somewhere.  This
   is the gate that would have caught M15's inert generation term.
2. **Live-state invariant** (the frozen-snapshot lesson) — two
   residual calls at different states must cache different sources.
3. **Stale-source regression** (M15 D4 mirror) — flag off after an
   on-solve leaves no generation; a simulated cache residue cannot
   enter a `btbt=False` residual.
4. **Ladder completeness** (M15 D3 mirror) — the strength ladder
   reaches 1.0x for BTBT (spy on the cached source's spread).
5. **G-A BTBT-off bit-identity**.
6. **G-B FD-Jacobian** with BTBT on, <= 5e-5 (no kink windows: Kane's
   G(F) is smooth for F > 0, unlike ionization's piecewise alpha).
7. **G-C generation profile** — non-zero, finite, peaked at the
   metallurgical junction, read from `_btbt_gs_cache` (the array the
   residual consumed, not test-side arithmetic).
8. **G-C coupling direction** — BTBT raises the reverse current
   (both devices warm-ramped through the same sequence).
9. **G-D coefficients** — published-table exact pin
   (`test_model_benchmarks.py`) + module sanity + dG/dF vs central FD.
10. **G-E Zener onset Kane slope** — ln(J) vs 1/E_peak strongly
    linear with negative slope of order -B (the published Kane-form
    behavior the milestone acceptance requires).
11. **G-E high-bias non-plateau** — the M16 LITERATURE NOTE gate:
    plain local Kane/Hurkx is known to underestimate leakage at large
    reverse bias vs nonlocal BTBT; the gated failure mode is a
    PLATEAU.  The gate asserts strictly monotone growth and that the
    late-ramp log-slope does not collapse relative to onset.
12. **G-F catalog/wire format + 2D/3D refusal**.

## 4. Known limitations (honest)

- Local model: single node field stands in for the whole tunneling
  path — underestimates leakage at large reverse bias relative to
  nonlocal BTBT (gated, not hidden; see gate 11).
- Degenerately doped test device relies on Boltzmann statistics
  (fd=False) in the contacts; FD+BTBT composition is untested (same
  declared-untested status as TAT+FD, M15/M16 plans).
- GIDL proper needs a gate (2D); the 1D gate battery validates the
  Zener-tunneling physics of the same Kane source term.
