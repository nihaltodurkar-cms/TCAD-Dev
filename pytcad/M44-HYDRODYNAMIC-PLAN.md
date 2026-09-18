# M44 -- Hydrodynamic transport: coupled 1D, then compiled, then 2D/3D

Status: Slice 0 (literature confirmation) DONE 2026-09-19. Slice 1
(1D coupled Tn in Device1D) IN PROGRESS.

## Slice 0 -- literature confirmation (done before any code)

Primary source: T. Grasser, T.-W. Tang, H. Kosina, S. Selberherr,
"A Review of Hydrodynamic and Energy-Transport Models for Semiconductor
Device Simulation," Proceedings of the IEEE, vol. 91, no. 2, Feb 2003,
pp. 251-274 (open PDF: iue.tuwien.ac.at/pdf/ib_2003/JB2003_Grasser_1.pdf,
fetched and read directly this session, pages 1-3 and 7-12).

**Finding 1 -- the existing M29 local closure is independently
confirmed correct.** The paper's Eq. (5):

    Tn = TL + (2/3)(q/kB)*tau_E*mu*E^2 = TL*(1 + (E/Ec)^2)

is EXACTLY `hydrodynamic.carrier_temperature()`'s formula (module
already cites Selberherr for `TAU_W_N`; this is now doubly confirmed
against a second, independent published source, same coefficients, no
discrepancy). No change needed to hydrodynamic.py's existing local
closure.

**Finding 2 -- the coupled model to implement is the standard
"three-moment energy-transport" (ET) model**, the paper's Eqs.
(56)-(59) (Fourier-law closure of Bloetkjaer's moment equations, the
"typical" ET model per the paper's own text):

    grad.J        = q * dn/dt                                   (56)
    J             = mu*kB*grad(n*Tn) + q*n*mu*E                 (57)
    grad.(n*S)    = -(3/2)*kB*d(n*Tn)/dt + E.J
                    - n*(3/2)*kB*(Tn - TL)/tau_E                (58)
    n*S           = -(5*kB*Tn)/(2*q)*J - kappa(Tn)*grad(Tn)     (59)

Read: (58) is the electron energy-balance equation (the new PDE M44
adds); (59) is the energy flux S -- a convective term (5/2)(kB*Tn/q)*J
plus a Fourier conductive term -kappa(Tn)*grad(Tn); (57) generalizes
the electron current to include a temperature-gradient driving force
(mu*kB*grad(n*Tn) replaces the isothermal mu*kB*Tn*grad(n) drift-
diffusion term) -- this is the ONLY change needed to Jn in
`_residual_jacobian`, and is the mechanism that actually produces
overshoot (current no longer depends on the LOCAL field alone).
kappa(Tn), the carrier thermal conductivity, is closed via a
Wiedemann-Franz-type relation standard to this model family; for the
STEADY-STATE bias solve (`solve_bias`, no `d/dt` terms), (58) reduces to

    d(n*S)/dx = E.J - n*(3/2)*kB*(Tn - TL)/tau_E

which is the actual equation to discretize (Slice 1 has no transient
coupling -- that is out of scope here, same as M17's own device.py-
untouched pattern for now; a future slice could extend this to
transient3d.py-style external driving if ever needed).

**Finding 3 -- mobility feedback: REUSE existing gated code, invent
nothing new.** Searched for a standard closed-form `mu_n(Tn)` (the
often-cited "Baccarani-Wordeman" form); no single clean formula is
retrievable/verifiable from accessible sources -- the Grasser review's
own Section IV shows mobility-vs-Tn closures in this model family are
either fit to Monte Carlo data (Thoma/Tang/Chen models, Section
IV.A-D) or left as `mu*(T*)` with `T*` a fitted function, not one
universal law. Rather than invent/attribute an unverified formula,
Slice 1 uses two pieces ALREADY published and ALREADY gated in this
codebase:
  1. `hydrodynamic.effective_field_from_temperature(Tn, mu, tau_w, TL)`
     -- M29's own already-gated inverse of the local closure, maps a
     carrier temperature back to the field consistent with it.
  2. `materials.mobility_field(mu0, E, mat, carrier)` -- the Canali
     velocity-saturation model, ALREADY used in Device1D today (see
     `Models.field_mobility`, device.py:2451-2468) with a LAGGED
     per-Newton-iterate field value `E_node`. `Models.field_mobility`'s
     existing lagged-update code is the exact mechanism to extend: when
     `energy_balance=True`, `E_node` is computed from the current Tn
     iterate via (1) instead of (or supplementing) the local field, fed
     into the SAME `mobility_field()` call. This is a much
     lower-risk mobility coupling than inventing a new law, and gives
     an honest, disclosed simplification consistent with this module's
     own existing honesty-clause style.

**Finding 4 -- benchmark gate, honestly scoped.** The Grasser paper's
Fig. 1(a)/(b) show the QUALITATIVE overshoot shape (Tn bump then decay
near a junction; velocity overshoot above v_sat that decays into the
bulk) from Monte Carlo reference data, for n+-n-n+ structures of
varying channel length. No raw digitized data is available from this
fetch (only rendered figure images), so a QUANTITATIVE curve-matching
gate (repo's usual "vs published, +/-X%" gate style) is NOT achievable
here without digitizing a printed figure by eye, which is exactly the
kind of imprecision M14 G-A already refused to do with a paywalled
source. HONEST GATE SCOPE (mirrors the M14 G-A precedent -- disclosed
gap, not fabricated precision):
  - G4 (qualitative): Tn(x) and Jn(x)/v(x) show the bump-then-decay
    shape near a field gradient that the LOCAL closure (M29) cannot
    produce -- this is directly checkable and is the real capability
    this milestone buys.
  - G4b (quantitative, XFAIL/disclosed gap): matching Fig. 1's actual
    digitized curve values is not attempted -- no accessible digitized
    dataset, same class of gap as M14's G-A.

**Scope note carried into Slice 1:** hole energy balance (Tp) is
explicitly deferred (see main plan's "Scope decision" section) --
consistent with the wider ET literature itself, which treats electron
energy balance as the dominant effect for n-channel/n+-n-n+ overshoot.

## Slice 1 -- golden baseline (recorded BEFORE any device.py edit, 2026-09-19)

Per CLAUDE.md's reconstruct-and-compare protocol. `Models.energy_balance`
defaults to `False` and the change is additive-only (new DOF branch
gated behind the flag, existing 3*N code path untouched) -- these
should all come back byte-identical after the edit; if any moves,
that's a defect to explain, not a re-baseline.

```
ce5850ecaf56ee0db5e05be4d9b17a80  tests/goldens/m13/frozen_meshes.npz
a2791e63f070ae749ae5bc11fde99ed1  tests/goldens/m13/hetero1d_eq.npz
f78dd28dbd24b39f6995e423d59e24cc  tests/goldens/m13/diode1d_eq.npz
f31b42c7b4cded7d10ff0831d92f8174  tests/goldens/m13/diode2d_eq.npz
36662794eb2f849ac6263f23921ebb86  tests/goldens/m13/diode1d_fwd.npz
7b2e8ad51672c9fd66ec26b30d88446e  tests/goldens/m13/resistor3d_eq.npz
```

(TAT_EQ_DIGEST/TAT_FW_DIGEST/HETERO_FW_DIGEST hardcoded hex digests in
`tests/test_m13_solver.py` are the other bit-identity gate covered by
the same rule -- checked via that file's own test run, not re-copied
here.)

## Slice 1 -- implementation notes and bugs found (2026-09-19)

Implemented in `pytcad/device.py`: `Models.energy_balance` (appended
4th DOF block, indices `3*N..4*N-1`, NOT interleaved with psi/n/p --
the existing 3*N block's code and indices are completely unchanged);
`_residual_jacobian(..., theta=None, n_lag=None, Jn_lag=None,
Qheat_lag=None)`; wiring in `solve_bias`/`_newton()` (theta warm-start,
Tn-consistent mobility via `hydrodynamic.effective_field_from_temperature`
+ `materials.mobility_field`, lagged coefficients recomputed each outer
Newton iterate); `solve_equilibrium` sets `Tn = TL` exactly (zero
current => zero Joule heating => theta==1 is the EXACT solution, not
an approximation -- no new equation solved there).

**Two real bugs found by direct testing, not by inspection:**

1. **Wrong Jacobian diagonal term** (algebra slip in the hand
   derivation, transposed which edge's left/right derivative feeds the
   diagonal). Caught immediately by the FD-Jacobian gate -- exactly
   what that gate exists for.

2. **Negative carrier temperature (Tn < TL) under forward bias** --
   caught by direct execution (a smoke test showing `Tn.min() < 300`)
   BEFORE the formal gate was even written. Root cause: the Joule-
   heating source term `E.Jn` used the raw electrostatic field
   `E = -grad(psi)`. This is EXACTLY the same pathology M19 self-
   heating already found and fixed (`thermal.joule_heating_density`'s
   own docstring: "an earlier version of this function used
   device.E_field directly ... In a diode's diffusion-dominated
   depletion region that formula gives spurious, thermodynamically-
   impossible LOCAL NEGATIVE heat"). Fixed the same way: Wachutka
   (1990)'s electron quasi-Fermi-potential gradient,
   `E_n = -grad(phi_n)`, `phi_n = psi - ln(n/nie)`, with the product
   `Jn*E_n` formed PER EDGE first and box-averaged to nodes after
   (not averaged-then-multiplied) -- the same convention
   `joule_heating_density` uses, reused rather than re-derived.

**FD-Jacobian gate methodology note:** the first version of G1 used a
fixed absolute error threshold and a large fixed perturbation step,
which failed even on the UNTOUCHED pre-existing 3*N block (confirmed
by running the same probe with `theta=None` -- identical failure,
proving it was a test artifact, not a regression). Fixed by adopting
`test_m13_solver.py`'s own established `_jacobian_probe` convention
exactly: a relative (`1e-7 * |value|`) finite-difference step, and
per-column error normalized by that column's own max magnitude (an
absolute threshold is meaningless across rows spanning many orders of
magnitude). All 5 gates plus the disclosed G4b xfail pass after this
fix (`tests/test_m44_hydrodynamic_coupled.py`, 0.29s).

**Combination refused (disclosed, not silently ignored):**
`energy_balance=True` with `impact`/`btbt`/`btbt_nonlocal` raises
`NotImplementedError` in `Models.__post_init__` -- those flags drive
`solve_bias`'s stiff-generation strength ladder and backtracking line
search, which does not yet know about the theta unknown (its merit
function is evaluated via a 3*N-only `_residual_jacobian` call).
Deferred, not attempted here.

Golden baseline reconstruct-and-compare: confirmed byte-identical
after the full Slice 1 edit (`energy_balance` defaults False and the
3*N code path is untouched) -- all 6 `tests/goldens/m13/*.npz` md5sums
match the Slice-1-start baseline recorded above.

**Regression check (targeted, per this milestone's own instruction not
to run the full suite until M44 fully lands):**
`OPENBLAS_NUM_THREADS=1 python3 -m pytest tests/test_m13_solver.py
tests/test_m15_ionization.py tests/test_m16_btbt.py
tests/test_m34_s1_nonlocal_btbt.py tests/test_m34_s2_nonlocal_ii.py
tests/test_m34_s6_impact_2d3d.py tests/test_m44_hydrodynamic_coupled.py
-q -n 6` -> **93 passed, 1 xfailed in 564.75s** (2026-09-19). No
regressions in any physics that shares `_residual_jacobian`/`Models`
with M44's changes (M13 Fermi-Dirac/incomplete-ionization, M15 impact
ionization, M16 BTBT, M34 nonlocal BTBT/II) -- the 4th-DOF append
design's "existing 3*N block is untouched" claim is now regression-
tested, not just asserted.

**Slice 1 status: DONE.** Next: Slice 2 (benchmark before touching
C++ at all) or a review pause -- see chat for which was chosen.

## Slice 2 -- benchmark results (2026-09-19)

`benchmarks/m44_s2_hydro_measure.py` (one-off decision script, same
shape as the existing `p4_diffusion_remeasure.py` precedent -- not a
permanent B1-B9 dashboard case). Warm run discarded, best of 5,
`OPENBLAS_NUM_THREADS=1`, `V=[0, 0.6]` diode:

| N | off (s) | on (s) | overhead | assembly-only off (s) | assembly-only on (s) | assembly overhead |
|---|---|---|---|---|---|---|
| 41 | 0.0085 | 0.0361 | 4.24x | 0.000257 | 0.000574 | 2.23x |
| 161 | 0.0120 | 0.0869 | 7.27x | 0.000304 | 0.001510 | 4.97x |
| 641 | 0.0197 | 0.2466 | 12.50x | 0.000461 | 0.005151 | 11.17x |
| 2561 | 0.0553 | 1.1202 | 20.25x | 0.001131 | 0.021207 | 18.75x |

**This CONTRADICTS the plan's own stated a-priori expectation**
("assembly is O(N) ... almost certainly dominated by the sparse solve,
so a compile is likely NOT justified here" -- written before
measuring, exactly the kind of guess CLAUDE.md's M32 rule exists to
override with a real number). The overhead is large AND GROWS with N
(4x at N=41, 20x at N=2561), and tracks the "assembly-only" column
closely -- so the new Tn-row cost, not the larger linear solve, is the
dominant and worsening cost.

**Root cause, found by reading the code the numbers pointed at (not by
guessing):** the new Tn-block assembly in `_residual_jacobian` is a
plain Python `for i in range(1, N-1):` loop -- one Python-level
iteration per interior node, appending to `rows/cols/vals` lists --
while every OTHER term in `_residual_jacobian` (including this exact
same tridiagonal shape for psi's own Poisson row) is vectorized numpy.
This is an ordinary Python-loop-vs-vectorized-numpy performance bug,
not a case for C++: the loop has no genuine serial dependency (node i's
computation only reads neighbor values, all already computed
up front as `w_edge`/`dw_dthetaL`/`dw_dthetaR`/`Q_src` arrays) and
vectorizes directly.

**Decision:** vectorize the Tn-block assembly in pure numpy FIRST (an
ordinary correctness-preserving refactor, re-gated by the existing FD-
Jacobian + regression tests, zero new dependencies) before any C++ is
considered anywhere in this milestone. This is not a deviation from
the plan's C++ scoping (Slice 3 was always the earliest C++ could be
justified, on the structured 2D/3D grid) -- it is fixing a plain
Python inefficiency that should never have reached the "compile it"
question in the first place. Re-measure after vectorizing before
deciding whether Slice 3's C++ step is still warranted at all.

## Slices 3-4

See the approved plan (design phase) for the full slice breakdown
(Slice 1: 4*N DOF coupling in Device1D; Slice 2: benchmark before any
C++; Slice 3: compile the 2D/3D structured-grid assembly, mirroring
`thermal_grid.py`; Slice 4: dimensional lift). This file is updated as
each slice lands with: golden-baseline md5sums (before/after), FD-
Jacobian gate results, and any further honest findings.
