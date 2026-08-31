# M16 — Band-to-Band Tunneling (Local Kane) Implementation Plan

Status: implementation landed 2026-08-29; gate battery
`tests/test_m16_btbt.py` + coefficient pins in
`tests/test_model_benchmarks.py`. VERIFIED GREEN 2026-08-31 (the
gates were written but never actually run before this date -- see
"Gate verification, 2026-08-31" at the end of section 3).

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

### Gate verification, 2026-08-31

`tests/test_m16_btbt.py` was actually executed for the first time this
date (ARCHITECTURE.md had flagged the whole file
LANDED-PENDING-VERIFICATION since 2026-08-29 -- the authoring
session's shell was blocked). 11/13 tests passed immediately; the two
G-E ("Zener onset Kane slope" and "high-bias non-plateau") tests
failed. Root-caused all three failures to bugs in the TEST code, not
the `pytcad/btbt.py` physics or its Newton-core coupling -- none of
gates 1-9 above needed any change:

- `test_g_e_high_bias_does_not_plateau` sorted its ramp records
  ascending by V (most-negative-first, largest |V|/largest J first)
  but then asserted `np.diff(Js) > 0` -- i.e. it asserted J increases
  going FROM the largest-bias point TO the smallest-bias point, the
  reverse of the intended trend. Fixed: sort with `reverse=True` so
  the list runs from least to most reverse bias.
- The same test's "log-slope must not collapse" check compared
  `late > early / 25.0` on two NEGATIVE slopes (J grows as V
  decreases, so d(lnJ)/dV < 0 by construction) -- for negative
  numbers, dividing by 25 moves the bound toward zero, so the
  inequality asserted the opposite of "the magnitude didn't shrink."
  Fixed: compare `abs(late) > abs(early) / 25.0`.
- `test_g_e_zener_onset_has_kane_slope` asserted the ln(J)-vs-1/E_peak
  correlation `r > 0.98`, but a genuine Kane fit (ln J = -B/E + const)
  has slope < 0 and therefore r near -1, never near +1. Fixed:
  `abs(r) > 0.98`. Measured r = -0.99999.
- Also found (not a bug, a too-narrow test window): the onset test's
  original -0.2V..-1.2V ramp only achieves ~262x current growth in the
  V <= -0.5 window it filters to, short of the gate's own >1000x
  threshold. Measured directly rather than adjusting the threshold
  blind: the V in [-0.5, -1.5] window (matching the high-bias test's
  own range) achieves ~1425x. Fixed by ramping to -1.5V instead of
  -1.2V, not by loosening the threshold.

After these test-only fixes, all 13 tests pass
(`pytest tests/test_m16_btbt.py -q` -> 13 passed, ~45s). Coefficient
pins (`test_model_benchmarks.py::test_btbt_coefficients_match_
published_table`) independently pass unchanged. M16 is now genuinely
VERIFIED, not just landed.

## 4. Known limitations (honest)

- Local model: single node field stands in for the whole tunneling
  path — underestimates leakage at large reverse bias relative to
  nonlocal BTBT (gated, not hidden; see gate 11).
- Degenerately doped test device relies on Boltzmann statistics
  (fd=False) in the contacts; FD+BTBT composition is untested (same
  declared-untested status as TAT+FD, M15/M16 plans).
- GIDL proper needs a gate (2D); the 1D gate battery validates the
  Zener-tunneling physics of the same Kane source term.
