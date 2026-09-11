# M34-S1 — Nonlocal BTBT in Device1D: Reviewed Formulation

Status, 2026-09-11 (final): **S1 LANDED as part of M34 -- the current
record is `M34-PLAN.md`, "Status".** Section 9 below is the second
pass's record (the G4 blocker's real cause, the conservation bug, the
eq (8) transcription error); its open G6 item was closed by the exact
per-segment quadrature M34-PLAN.md section 2 describes. Sections 1-8
are the history of how the design got there.

Original review framing, preserved below: this review was triggered by
an explicit instruction to resolve a named contradiction before any
implementation: the original plan proposed freezing the tunnel window
`[x1, x2]` while also claiming a nonzero
analytic `dG/dpsi` through `F_eff = Eg/(x2-x1)`. If `x1, x2` are frozen,
`F_eff` is a frozen scalar and that derivative is exactly zero. That
claim is retracted below, not patched — the underlying MODEL was wrong,
not just the Jacobian bookkeeping (§1, §2).

## 0. Reference actually checked (per instruction 7 — no invented citation)

**D. Esseni, M. Pala, P. Palestri, C. Alper, T. Rollo, "A review of
selected topics in physics based modeling for tunnel field-effect
transistors," Semicond. Sci. Technol. 32, 083005 (2017),
doi:10.1088/1361-6641/aa6fca.**

Verified directly (fetched 2026-09-11, not assumed): the IOPscience
page states explicitly "Open access" under a **CC-BY 3.0** license — no
paywall, no login. Section 2.1 covers exactly this ground (local vs.
nonlocal direct BTBT) and was the section fetched. What it confirms,
in its own words/structure (paraphrased from the fetch, since the tool
returns prose, not verbatim LaTeX — flagged honestly in §4 as needing
a second, closer read of the primary equations before coding):

- The transmission is a genuine WKB line integral, `T ~ exp(-2 * INT
  kappa(x) dx)`, `kappa(x)` the imaginary wavevector from the Kane
  two-band E-k relation evaluated along the ACTUAL local band profile
  — not a single substituted field.
- The tunnel path endpoints are **classical turning points fixed by
  energy conservation** (zero longitudinal kinetic energy at each
  end) — i.e. a real root-finding condition on the band profile, not
  a free choice.
- Critically, and this directly answers instruction 4: **"G_T ...
  corresponds to a generation of holes at position x_i and a
  generation of electrons at position x_f"** — the SAME total rate is
  deposited at the TWO ENDPOINTS of the path, holes at the start
  (valence-band end), electrons at the end (conduction-band end).
  This is NOT what the original plan assumed. The original plan
  copied the LOCAL model's convention (add `+G` to the electron row
  and `-G` to the hole row at the SAME node `i`) and only replaced `F`
  by `F_eff` — that is a local-model bookkeeping pattern grafted onto
  a nonlocal quantity, and it is the real source of the degenerate
  Jacobian, not a detail to patch afterward.
- The local Kane closed form (already in `btbt.py`, unchanged) is
  confirmed to be the UNIFORM-FIELD LIMIT of this same WKB integral —
  the reduction-identity gate (G2 below) rests on a claim the
  literature actually makes, not an assumption.

This reference is used for STRUCTURE (path integral, turning-point
definition, two-point deposition, uniform-field reduction) — it is
GOOD ENOUGH to fix the model errors instruction 2 flagged, but §4
states plainly what is still unverified (the exact closed-form
`kappa(x)` algebra) rather than presenting a fetch-tool paraphrase as
a pinned constant, which would repeat the M14 "guessed constant"
mistake in a new place.

## 1. Corrected S1 formulation

Homojunction Device1D only (uniform `Eg`, uniform `m_r` — same scope
restriction the local BTBT/II models already carry). Per Newton
iterate, given the current `psi` array:

**Turning points.** For each candidate start node `x_i` where the
local field exceeds a floor (same gating idea as local BTBT), find
`x_f > x_i` such that

    Ec(x_f) = Ev(x_i)      i.e.      psi(x_f) - psi(x_i) = Eg / (q * VT)

(uniform-`Eg` homojunction reduction of the general energy-conservation
turning-point condition — matches what was derived independently
before this review and is UNCHANGED by it; the review found the
deposition/Jacobian treatment wrong, not this part). This is a 1D
root-search on the existing nodal array — no C++, no field-line
tracing, confirming the earlier plan's scope note.

**Transmission / rate.** Evaluate the WKB integral using the LOCAL
band profile between `x_i` and `x_f` (trapezoidal quadrature on the
existing mesh nodes strictly between them):

    T(x_i, x_f) = exp( -2 * sum_k kappa(x_k) * dx_k ),  x_i < x_k < x_f

with `kappa(x)` a function of the LOCAL band bending at `x_k` (not a
single substituted field) — the exact closed algebraic form of
`kappa(x)` is flagged as unverified in §4 and must be pinned from the
primary source before coding, not guessed.

    G_T(x_i, x_f) = nu_attempt * T(x_i, x_f)      [pairs / (area * time)]

`nu_attempt` is an attempt-frequency prefactor (present in every WKB
tunneling rate in this codebase already — TAT's `_update_tat_probabilities`
has the analogous role) — its exact form is the SAME open item as
`kappa(x)`'s, §4.

**Deposition (instruction 4, now answered from the source rather than
assumed):**

    F[hole row at x_i]     -=  G_T * (path cross-section factor)
    F[electron row at x_f] +=  G_T * (path cross-section factor)

The SAME scalar `G_T` at both ends is not an optional design choice —
it IS the conservation law (one tunneling event makes exactly one
electron-hole pair; depositing anything else would fabricate charge).
This replaces the original same-node `+G_local`/`-G_local` pattern
entirely for the nonlocal path term; it does not stack with or
resemble the local model's bookkeeping, so `_residual_jacobian`'s
nonlocal block needs its own insertion, not a small edit to the M16
block. `x_i`/`x_f` will in general NOT coincide with the same node the
local model would have used, so the nonlocal term touches a
DIFFERENT pair of continuity rows than the local term does.

## 2. Jacobian strategy (the contradiction, resolved rather than patched)

Two structurally different sensitivities exist, and conflating them is
what produced the original error:

  (i)  **Interior sensitivity** — `kappa(x_k)` at each node strictly
       inside the window depends on the LOCAL band bending at `x_k`,
       which depends on `psi` there. This is nonzero EVEN IF the
       window endpoints `x_i, x_f` are held fixed. This term was
       MISSING entirely from the original `F_eff = Eg/(x2-x1)`
       proxy — collapsing the whole path integral to a single window-
       length scalar threw away the one dependency that survives
       freezing.
  (ii) **Endpoint sensitivity** — `x_i, x_f` themselves move as `psi`
       evolves (implicit function of the root-finding condition
       above). This is the term that becomes EXACTLY ZERO if the
       endpoints are frozen — the original plan's claim of a nonzero
       `dG/dpsi` "through F_eff" was implicitly relying on this term
       while simultaneously freezing it away. That was the
       inconsistency; there is no version of "freeze x1,x2, keep
       F_eff's derivative nonzero" that is correct, because with
       (i) discarded (as the F_eff proxy did) there is nothing else
       for the derivative to come from.

**Resolution adopted for S1: freeze (ii), keep (i) live.**

- `x_i, x_f` are relocated once per BTBT strength-ladder stage (same
  cadence `_update_tat_probabilities` and the local-BTBT/II ladder
  already use), then held fixed through that stage's Newton
  iterations — precedented, not a new mechanism.
- Within a stage, `kappa(x_k)` for every interior node is evaluated
  LIVE from the current `psi`, and the analytic Jacobian carries
  `dG_T/dpsi_k` for every such `k` via the chain rule through
  `kappa(x_k)`'s dependence on local band bending — a REAL, nonzero,
  well-defined sensitivity, unlike the retracted claim.
- This is a genuinely NEW sparsity pattern for this file: the nonlocal
  block's Jacobian row is DENSE across the (generally multi-node)
  window, not tridiagonal. No existing block in `device.py` needs this
  today; it must be added as its own stamping loop, sized to the
  window width found at that ladder stage (bounded, not unbounded,
  since the window is a finite physical tunnel length).
- Endpoint-motion sensitivity (ii) is dropped, exactly as TAT drops
  `dP/dpsi` for its frozen escape probabilities — same category of
  approximation, same honesty requirement to document it as such and
  gate that it does not stall convergence (G6 below), not silently
  assumed harmless.

This is a different (and more defensible) design than either option in
the original plan: it is not the fully-frozen zero-Jacobian TAT-style
option, and it is not the fully-live implicit-differentiation option —
it is the one that is actually consistent with what "freeze the window"
can honestly mean once the model is the real path integral instead of
the degenerate `F_eff` proxy.

## 3. Revised gates

- **G1 OFF BIT-IDENTITY** — unchanged from the original plan.
- **G2 UNIFORM-FIELD REDUCTION** — for an artificially linear potential
  ramp, `G_T` from the path-integral form must match the EXISTING
  `btbt_generation(F)` local closed form to a stated tolerance. This
  now rests on the literature's own stated claim (§0) rather than an
  assumption, and is a real regression test against `btbt.py` staying
  untouched.
- **G3 HIGH-BIAS SEPARATION** — unchanged in spirit: on a real diode,
  the nonlocal path rate departs upward from the local rate as reverse
  bias grows (the literature-named failure mode of the local model).
- **G4 SPARSITY / FD-JACOBIAN, REDEFINED** — two parts, replacing the
  single (broken) claim in the original plan:
  - (4a) for nodes k STRICTLY INSIDE the frozen window, analytic
    `dG_T/dpsi_k` (via live `kappa(x_k)`) matches an FD probe to the
    house 5e-5 tolerance;
  - (4b) for nodes OUTSIDE the frozen window (including the endpoints
    themselves, per the dropped-term decision in §2), the analytic
    Jacobian contribution is asserted to be EXACTLY zero — this is now
    a true statement of the model as designed, not a gap being hidden.
- **G5 CONSERVATION (NEW — answers instruction 4/5 directly)** — the
  scalar added to the hole row at `x_i` and the scalar added to the
  electron row at `x_f` are asserted equal in magnitude by
  construction (unit-level check on the two `F[]` increments, not just
  an emergent property), and over a bias sweep the cumulative injected
  electron and hole counts from this source match to machine
  precision — the direct test that the two-point deposition in §1
  cannot fabricate charge.
- **G6 LADDER-REFRESH CONVERGENCE** — `solve_bias` with the nonlocal
  flag converges across the same bias range the local-BTBT gate
  already covers despite the endpoint freeze-and-refresh cadence
  (replaces the original "G5 convergence" gate; renamed to make clear
  what specifically is being stressed — the refresh, not just
  "does it converge").
- **G7 STRUCTURAL BENCHMARK** in `test_model_benchmarks.py`: on a
  reverse-biased diode, `x_i != x_f` (the model is exercising genuine
  spatial separation, not degenerating back to a co-located point
  source), cross-checked against the cited review's explicit
  description of two-point deposition (§0) — a structural claim, not
  an absolute-magnitude claim (no calibration constant is being
  asserted here, sidestepping a repeat of the M14 paywall problem).

## 4. Verbatim equations (obtained 2026-09-11 from the actual PDF pages,
read visually, not summarized by a lossy text-fetch tool)

The §0 gap is now closed. Fetching the paraphrase was not enough per
CLAUDE.md's own standard (the `E_SWITCH` mix-up precedent) -- the
actual open-access PDF was downloaded and its pages 4-6 read directly.
Verbatim, from Esseni et al. 2017 section 2.1:

    kappa(x) = (1/hbar) * sqrt( mr * Eg * (1 - alpha(x)^2) )      (9)

    alpha(x) = -m0/(2 mr)
               + 2 * sqrt( (m0/(2 mr)) * ((E - Ev(x))/Eg - 1/2)
                           + m0^2/(16 mr^2) + 1/4 )

    valid for Ev(x) <= E <= Ev(x) + Eg; m0 = free electron rest mass,
    mr = reduced mass = (mc^-1 + mv^-1)^-1.

    G_T(E) = |dEv/dx|_xi * (e / (36 hbar)) * (INT_xi^xf dx/kappa)^-1
             * [1 - exp(-km^2 * INT_xi^xf dx/kappa)]
             * exp(-2 * INT_xi^xf kappa dx) * (fc - fv)          (11)

    km^2 = min( 2 mv (Emax - E)/hbar^2, 2 mc (E - Emin)/hbar^2 )  (12)

Confirmed by hand: at x=xi, delta=(E-Ev(xi))/Eg=0 and at x=xf,
delta=1; for Si (m_n_star=0.26, m_p_star=0.386, mr=0.1554 m0,
u=m0/(2mr)=3.217) both endpoints give alpha=-+1 exactly, hence
kappa=0 at BOTH ends -- the classical-turning-point structure the
paper describes, verified algebraically here, not assumed.

**A finding that changes G2/G3, found by tracing units through eq (8)
(the paper's own closed-form UNIFORM-FIELD reduction of eq 9-11):**

    G_T = (e^2 F^2 sqrt(mr)) / (18 pi hbar^2 sqrt(Eg))
          * exp( -pi * sqrt(mr) * Eg^1.5 / (2 * e * F * hbar) )        (8)

[Corrected 2026-09-11, second pass: this block originally read
`18 pi^2` and `sqrt(2)`; both were transcription errors against the
paper's page 5 and both propagated into `kane_local_fp` -- section 9.]

This is a FIRST-PRINCIPLES construction from bare mr/Eg/hbar. It is
**NOT the same function as `pytcad/btbt.py`'s existing
`btbt_generation(F)`**, whose `KANE_A_SI`/`KANE_B_SI` are Hurkx et
al.'s 1992 EMPIRICAL RECALIBRATION of exactly this Kane theory --
recalibrated precisely because the bare first-principles form (eq 8
above) does not match measured Si BTBT current, which is the
documented historical reason Hurkx redid the theory. Treating them as
interchangeable would silently misrepresent physics as surely as the
retracted `F_eff` shortcut did. Consequence for the gates (§5):

- G2 (reduction) must compare the nonlocal path integral's
  uniform-field limit against a FRESHLY-IMPLEMENTED eq (8), computed
  from the same bare mr/Eg/hbar the nonlocal code uses -- an
  apples-to-apples self-consistency check of the CODE, not a claim
  that `Models(btbt_nonlocal=True)` numerically approximates
  `Models(btbt=True)`.
- `Models(btbt_nonlocal=True)` and `Models(btbt=True)` are documented,
  in the code and here, as two INDEPENDENT, non-comparable BTBT
  mechanisms (first-principles path integral vs. empirical local fit)
  -- not as a local/nonlocal pair of the SAME calibration. Any future
  session must not "fix" an apparent magnitude mismatch between them
  by rescaling one to match the other; that would be inventing a
  fudge factor against a real, cited physical reason they differ.

**Jacobian freezing, finalized (resolves a follow-on question the
original design left open):** in addition to freezing the window
endpoints `xi, xf` once per `solve_bias` call (the SAME cadence
`_update_tat_probabilities` already uses via its `self._Pn is None`
lazy-cache pattern -- not "once per ladder stage" as originally
stated; there is no ladder-stage reset point in the existing code for
TAT's cache, so the precedent this design follows is per-call, and
this plan now matches it exactly), the SCALAR PREFACTOR
`|dEv/dx|_xi`, `km^2`, and `Emin`/`Emax` are ALSO frozen at that same
snapshot. Only `kappa(x_k)` for nodes strictly interior to `(xi, xf)`
stays live every Newton iterate. This keeps the sparsity claim in G4b
literally true (zero Jacobian contribution at and outside the window
boundary, by construction, not by omission) and is justified physically
because the exponential path integral is the term with real
sensitivity to bias, not the polynomial-order prefactor.

**Analytic interior derivative (derived, not FD-only):**

    d(kappa_k)/d(psi_k) = [2 mr alpha_k u / (hbar^2 kappa_k (alpha_k + u))]
                           * (-q * VT)

using `sqrt(inner) = (alpha_k + u)/2` from eq (9)'s own definition to
avoid recomputing the inner sqrt, and `dEv/dpsi = -q*VT` (the same
sign/scale convention `_ii_compute_E_from_state` already uses for
`dE_edge/dpsi`). This is singular only exactly at the turning points
(`kappa -> 0`), which is why they are excluded from the live set
rather than clipped -- consistent with, not a workaround for, the
freezing decision above.

**Remaining, explicitly named simplifications for S1** (kept from the
original plan, now precise rather than approximate):
- Single dominant, zero-transverse-momentum energy channel
  (`E = Ev(xi)` exactly, `k_perp = 0`) rather than eq (11)'s full
  integral over `E` in `[Emin, EMAX]` -- a real scope narrowing versus
  the full reviewed model, stated in the docstring, not silently
  dropped.
- `(fc - fv) = 1` (full occupation-difference driving force) -- the
  same level of approximation the existing empirical local model
  already carries (no separate occupation factor at all).
- Turning point `xf` snapped to the nearest existing mesh node past
  the exact crossing (`psi(xf)-psi(xi) >= Eg/(q VT)`), not
  interpolated -- a mesh-resolution-bounded discretization choice.

## 5. Revised gates (final)

- **G1 OFF BIT-IDENTITY** -- unchanged.
- **G2 UNIFORM-FIELD SELF-CONSISTENCY** -- for an artificial linear
  potential ramp, the path-integral form (eq 9/11) matches a
  freshly-coded eq (8) closed form (same mr/Eg/hbar), NOT
  `btbt_generation`. Documents the eq(8)-vs-Hurkx distinction from
  section 4 inline in the test.
- **G3 HIGH-BIAS DEPARTURE FROM THE UNIFORM-FIELD FORM** -- on a real
  (nonuniform-field) diode, the path-integral rate diverges from eq
  (8) evaluated at the peak local field as reverse bias grows --
  reframed against eq (8), not against `btbt_generation`, for the
  same reason.
- **G4a INTERIOR FD-JACOBIAN** -- for nodes strictly inside the frozen
  window, analytic `dG_T/dpsi_k` (the derivation above) matches an FD
  probe to the house 5e-5 tolerance.
- **G4b EXTERIOR SPARSITY** -- for nodes at or outside the window
  (including `xi`, `xf` themselves), the analytic Jacobian
  contribution is EXACTLY zero -- now literally true given the
  prefactor/km/Emin/Emax freezing decision in section 4, not merely
  asserted.
- **G5 CONSERVATION** -- the scalar subtracted from the hole row at
  `xi` and added to the electron row at `xf` are equal in magnitude by
  construction (unit-level check on the two `F[]` increments), and
  cumulative injected electron/hole counts match over a bias sweep to
  machine precision.
- **G6 LADDER/REFRESH CONVERGENCE** -- `solve_bias` with
  `btbt_nonlocal=True` converges across a real reverse-bias range
  despite the per-call freeze-and-refresh cadence.
- **G7 STRUCTURAL BENCHMARK** (`test_model_benchmarks.py`) -- on a
  reverse-biased diode, `xi != xf` (genuine spatial separation is
  exercised), cross-checked textually against the cited review's
  "generation of holes at position xi and ... electrons at position
  xf" statement -- a structural claim, no calibration constant
  asserted (sidesteps a repeat of the M14 paywall problem, and is
  honest that this mechanism has no empirical calibration at all yet).

## 6. GO / HOLD recommendation (updated after the unit audit)

**HOLD on wiring into `device.py`; the pure-math layer is now
substantially, quantitatively verified.** The unit audit requested
after the earlier GO/HOLD flip found and fixed TWO real, independent
bugs (full detail in `pytcad/btbt.py`'s module-level comment above
`nonlocal_btbt_window`):

1. `kane_local_fp` (eq 8) had a mistranscribed exponent denominator
   (`sqrt(2)` instead of `2`), caught by re-reading the primary
   source's actual equation image at high resolution rather than
   trusting the earlier transcription. Fixed.
2. `nonlocal_btbt_window` (eq 11) double-counted a factor of
   elementary charge, traced to a plausible eV/m vs J/m unit
   convention mismatch for `dEv/dx` between this code and the paper.
   Fixed.

After both fixes:
- The EXPONENTIAL (dominant, exponentially-sensitive) part of the
  nonlocal path integral matches `kane_local_fp`'s exponent EXACTLY
  (5+ significant figures, across a decade of field strengths) --
  the WKB integral itself (eq 9's kappa(x), the turning-point
  structure, the edge-midpoint quadrature) is verified correct.
- The PREFACTOR ratio (nonlocal / eq 8) is not exactly 1, but
  converges cleanly to EXACTLY pi as quadrature resolution increases
  (measured 3.1955 -> 3.1433 for N = 500..512000, monotonically
  approaching 3.14159265 -- the classic slow-convergence signature of
  an integrable inverse-sqrt singularity, not random noise). This is
  attributed to eq (10)'s small-k_perp expansion being a leading-order
  approximation of eq (7)'s exact k_perp dependence -- a clean,
  explicable O(1) factor, not a bug, but NOT YET PROVEN to be exactly
  pi from a from-scratch re-derivation of eq (10)'s own k_perp
  integral (that derivation was not completed in this pass).

This is a much stronger position than the prior HOLD: the model is
verified correct in its dominant term, and the ONE remaining open
question (is the pi factor exact, and should it be applied as a
documented, derived correction or left as a stated approximation
limit) is narrow, well-characterized, and no longer an unexplained
15-19-orders-of-magnitude gap.

**Nothing in `pytcad/device.py` has been touched.** The `btbt.py`
functions remain off any code path (no `Models` flag references them).
Recommended next step, before wiring into `device.py`: either (a)
complete the from-scratch k_perp-integral derivation for eq (10) to
confirm pi is exact (closing the gap with proof, not measurement), or
(b) proceed to wire S1 with the pi ratio EXPLICITLY documented as a
stated limit of the small-k_perp approximation (not silently divided
out) and let G2 gate on "matches eq(8) x pi to 1e-3", a meaningful,
non-arbitrary numeric target either way.

## 7. Golden baseline (recorded before any core edit, per CLAUDE.md)

    diode1d_eq.npz      f78dd28dbd24b39f6995e423d59e24cc
    diode1d_fwd.npz     36662794eb2f849ac6263f23921ebb86
    diode2d_eq.npz      f31b42c7b4cded7d10ff0831d92f8174
    frozen_meshes.npz   ce5850ecaf56ee0db5e05be4d9b17a80
    hetero1d_eq.npz     a2791e63f070ae749ae5bc11fde99ed1
    resistor3d_eq.npz   7b2e8ad51672c9fd66ec26b30d88446e

## 8. FINAL HANDOFF RECORD, 2026-09-11 -- M34-S1 STOPPED, NOT SIGNED OFF

Explicit instruction closing this session's work on M34-S1: **stop
implementation, document, do NOT sign off, carry the FD-Jacobian
failure as the explicit blocker.** This section is that record.

### What was actually built

- `pytcad/pytcad/btbt.py`: `kane_alpha`, `kane_kappa`, `dkappa_ddelta`,
  `kane_local_fp` (eq 8, first-principles uniform-field closed form --
  NOT the empirical `btbt_generation`/`KANE_A_SI`/`KANE_B_SI`, see the
  module docstring), `nonlocal_btbt_window` (eq 11/12, edge-midpoint
  quadrature with a physically-motivated `kappa`-floor exclusion).
- `pytcad/pytcad/device.py`: `Models(btbt_nonlocal=False)` flag;
  `_btbt_nl_window` cache (frozen per `solve_bias` call, same cadence
  as `_Pn`/`_Pp`); a homojunction-only guard in `__init__` reusing
  M33-S2's `_te_edge` detector; `_btbt_nl_find_windows` (candidate
  tunnel-window search over mesh edges, with a field floor and a
  `kappa`-floor-based live/frozen node split); `_btbt_nl_window_
  contribution` (per-window residual value + analytic interior
  Jacobian); a new residual/Jacobian block in `_residual_jacobian`,
  inserted after the M16 local-BTBT block, same ordering-invariant
  convention (after continuity `=`, before Dirichlet stamping).
- `pytcad/tests/test_m34_s1_nonlocal_btbt.py`: three gates.
  `test_g1_off_bit_identity` (PASSES), `test_g2_nonlocal_produces_a_
  real_nonzero_effect` (PASSES, threshold calibrated to the actually-
  measured single-shot effect size, not a round number), and
  `test_g4_fd_jacobian` (**OPENLY FAILS, INTENTIONALLY** -- this is
  the explicit blocker, not xfail'd, per CLAUDE.md's dirty-tree rule:
  "Working tree may be left dirty ONLY with openly-failing tests and a
  precise handoff note").

### Bugs found and fixed along the way (real, not hypothetical)

1. `kane_local_fp`'s (eq 8) exponent denominator was mistranscribed as
   `sqrt(2)*hbar*e*F`; the primary source has `2*hbar*e*F`. Found by
   re-reading the actual equation image at high resolution. Fixed.
2. `nonlocal_btbt_window` (eq 11) double-counted a factor of
   elementary charge (a plausible eV/m vs J/m unit-convention gap
   between the paper's `dEv/dx` and this code's). Found via a
   from-scratch re-derivation of eq (11)'s prefactor using the SAME
   method the paper itself uses for eq (7)->eq (8). Fixed.
3. After both fixes, the nonlocal model's uniform-field prefactor
   limit converges CLEANLY to exactly `pi` times `kane_local_fp` (not
   1.0) as quadrature resolution increases -- attributed to eq (10)'s
   small-`k_perp` expansion being a leading-order approximation of eq
   (7)'s exact form, NOT divided out (unproven exact from a
   from-scratch derivation of eq 10's own k_perp integral -- see
   section 6). This factor is carried, documented, not applied as a
   correction.
4. A degenerate-window NaN on a REAL device (not the synthetic
   uniform-field test that validated finding 3): long near-flat mesh
   regions put MANY interior nodes within float precision of the
   window's turning-point `delta` value, not just the two literal
   endpoints, and `1/kappa^2` exploded there in the Jacobian. Fixed
   with a `kappa`-floor (1.0 /m, many orders below any real tunneling
   `kappa` ~1e8-1e9 /m) that excludes near-turning-point edges from
   the live derivative sum entirely, rather than array-position-based
   exclusion.
5. The SAME bug's twin in the VALUE computation (not just the
   Jacobian): `nonlocal_btbt_window`'s own quadrature had the
   identical issue, silently underflowing `G_T` to ~1e-274 on a real
   device (versus a physically meaningful value) via the same
   long-flat-region mechanism. Fixed with the same `kappa`-floor,
   applied to the quadrature itself, not just the derivative helper.

Findings 4 and 5 are why finding 3's `pi` factor was verified BEFORE
they were found (on a clean synthetic uniform-field profile with no
flat regions) and remains believed-correct; they are a separate,
purely mesh/discretization-driven class of bug.

### The explicit, carried-forward blocker

`test_g4_fd_jacobian` fails: worst-case relative mismatch between the
analytic Jacobian and a finite-difference probe is **7.368e-3 (0.74%)**
on a real diode at -6V, versus this project's house FD-Jacobian
tolerance of 5e-5 used throughout M15/M16/M20's own gates. Measured
directly (60 randomly-sampled `psi` columns, `eps=1e-6`, seed 0),
reproducible, pinned into the test file.

**Leading hypothesis, not yet proven:** the SAME `kappa`-floor that
fixed bugs 4/5 above may be silently dropping a small but genuinely
nonzero FD-visible sensitivity at edges just above the floor (or
misclassifying an edge as "frozen" that FD still sees a gradient
through), rather than the floor being a clean zero/nonzero cut. This
has NOT been verified -- it is the natural next thing to check (e.g.,
sweep the floor value and see if the mismatch tracks it, or compare FD
sensitivity node-by-node against which edges got floor-excluded), not
yet done.

**Other NOT-yet-ruled-out candidates**, for whoever resumes this:
- An error in the `dint_kappa_dpsi`/`dint_invkappa_dpsi` edge-to-node
  scatter (the `0.5` midpoint weighting applied twice, once implicitly
  in `dkappa_mid_dnode` and once in how it is scattered to both of an
  edge's endpoints) has not been independently re-derived/checked
  since finding 4's fix was made under time pressure.
- The `km2`/`bracket`/`Emin`/`Emax` terms are treated as fully frozen
  in the Jacobian (per section 4's design) -- this was not itself
  re-verified against FD after findings 4/5's fixes; it is assumed
  still correct because it was correct before those fixes, but that
  assumption was not re-tested.

### Explicit non-sign-off

**M34-S1 is NOT signed off, NOT landed, and MUST NOT be described as
complete in `ARCHITECTURE.md` or `history.md` beyond "attempted,
blocked, left as an open red gate."** `Models(btbt_nonlocal=True)`
must not be recommended for any real use until `test_g4_fd_jacobian`
passes at house tolerance without the tolerance itself being loosened.
The working tree is left dirty on purpose, matching the M12-S2
precedent CLAUDE.md's workflow section names: openly-failing test
committed to the test suite (not hidden, not xfail'd), full record
here, `history.md` updated with a short pointer to this section.

Goldens (section 7 above) confirmed byte-identical to the pre-M34-S1
baseline at every checkpoint during this work -- the default-off path
was never at risk.

## 9. SECOND PASS, 2026-09-11 -- G4 blocker root-caused and fixed; G6 open

Read this section first when resuming. It supersedes section 8's
diagnosis of the G4 blocker and the "factor of pi" explanation in
sections 6 and 8. Still NOT signed off (see the end of this section).

### What was actually wrong (each measured, not inferred)

1. **G4 (FD Jacobian, 7.4e-3) was not the kappa floor.** Probing EVERY
   psi column at -6V: every bad column was a window START node (worst
   7.4e-3); interior, end and outside columns agreed to ~1e-8. The
   residual reads psi[i0] LIVE -- `delta = VT*(psi - psi[i0])/Eg`, and
   `E = Ev(x_i)` inside km^2 -- while the Jacobian treated psi[i0] as
   frozen and left its column zero. Section 8's leading hypothesis was
   not the cause.
2. **The two-point deposition fabricated charge.** Holes were
   deposited as `g*dV[i0]`, electrons as `g*dV[j0]`. On the graded test
   mesh the per-window ratio dV[j0]/dV[i0] spans 0.33-3.3, and
   device-wide the electron injection was 26% above the hole injection
   at -6V (1.4653e-1 vs 1.1625e-1, scaled). Esseni eq (1) and figure 2:
   an energy bin's hole and electron generation carry the same COUNT,
   so both rows take `g*dV[i0]`. Section 5's G5 would have caught this;
   it had not been written.
3. **The "factor of pi" was a third transcription error in eq (8),**
   not an expansion artifact. The paper's eq (8) (page 5) is
   `e^2 F^2 sqrt(mr) / (18 pi hbar^2 sqrt(Eg)) * exp(-pi sqrt(mr)
   Eg^1.5 / (2 hbar e F))`; `kane_local_fp` had `18 pi^2`. Integrating
   eq (7) over k_perp in eq (3) by hand also gives 18 pi. In a uniform
   field eq (10)'s expansion is exact, and substituting alpha gives
   `int_0^1 d(delta)/kappa = pi hbar / (2 sqrt(mr Eg))` for any
   u = m0/(2 mr) > 1 (Gauss-Chebyshev agrees to 1e-10), so eq (11)/eq
   (8) = 1. Do not re-check this with scipy `quad` on 1/kappa: it
   under-resolves the two inverse-sqrt endpoints and returns 3.188.

### What changed (the user chose fix B over freezing psi[i0])

- `Device1D._btbt_nl_window_contribution`: psi at every node i..j is
  live in the Jacobian, the start node included (it shifts every
  unclipped delta by -s = -VT/Eg and enters km^2 through E); clipped
  nodes carry zero sensitivity. Still frozen per solve_bias call: the
  node span, the mesh path, |dEv/dx|_xi, Emin/Emax. Fix B on its own
  leaves the residual -- and therefore every converged solution --
  unchanged (measured max |dpsi| 3e-14 against the pre-fix solve at
  -6V); the deposition fix in the next bullet is what changes the
  residual. The
  rejected alternative (A: freeze psi[i0] when the window is found)
  also passed the FD probe but moved the converged psi by 0.157.
  Consequence: section 5's G4b ("exactly zero Jacobian at x_i") is no
  longer the design. G4b now asserts that the nonlocal block touches
  only its two deposit rows and psi columns inside [i0, j0].
- `_residual_jacobian`: the electron deposit at j0 is weighted by
  dV[i0], in the residual and the Jacobian.
- `btbt.kane_local_fp`: 18 pi. Comments in btbt.py and device.py that
  carried the old pi explanation or the "do not wire" status corrected.

### Gates now

| gate | where | status |
|---|---|---|
| G1 default-off bit-identity | test_m34 | pass |
| G2 uniform-field reduction: closed-form 1/kappa integral, and `nonlocal_btbt_window` -> `kane_local_fp` (N^-1/2 order + Richardson limit, F = 5e7..3e8 V/m) | test_model_benchmarks.py | pass (red at ratio 3.151 before the 18 pi fix) |
| G4 FD Jacobian at 5e-5: 60 random columns at -6V, and every column at -2/-4/-6V | test_m34 | pass (was 7.4e-3 / 8.5e-4) |
| G4b sparsity | test_m34 | pass |
| G5 pair conservation, -2 and -6V, rel 1e-12 | test_m34 | pass (red before) |
| G6 0 -> -6V ramp, 0.5V steps | test_m34 | **FAILS -- open, below** |
| G3 high-bias departure, G7 structural benchmark | -- | not written |

### Open: G6 -- the edge-midpoint quadrature is not smooth at a turning point

Before this pass the ramp failed at -1.0V; with fix B it fails at
-5.5V (stage 0.35 of the strength ladder). With 0.25V steps it fails at
-1.25V, with 0.1V steps at -1.6V (both stage 0.7): smaller steps do not
help, which points at a non-smooth residual rather than continuation.

Root cause, confirmed at the -1.25V stall: node 46 of window (30, 47)
sits within ~2e-8 of delta = 1, and raising psi[30] by 1e-6 drops that
window's rate from 1.945e-4 to 5.46e-7 (356x). delta is clipped at 1,
so an edge whose true band crosses the turning point partway along it
looks like a whole edge sitting just below delta = 1: its midpoint
kappa is near zero and dx/kappa_mid is huge, until the kappa floor
drops the edge entirely. int dx/kappa -- and so G -- is nearly
discontinuous whenever a node crosses delta = 0 or 1, and Newton stalls
when the solution sits on such a crossing. The 1 /m floor is not
"physically negligible" for this integral: an edge just above it adds
dx/1 ~ 1e-10 m^2 against a typical whole-window integral of ~3e-18 m^2.

Separately, and NOT an M34 defect: a direct solve from equilibrium to
-5V stalls in the ladder's 0.0 stage (no generation active) identically
for Models(btbt=True), Models(impact=True) and Models(btbt_nonlocal=
True) -- err 3.12e-7, backtracking stuck at lambda = 0 with |F| =
1.2e-2, which is not round-off (the plain solver converges there to
9e-14). The stiff_gen backtracking path shared since M15 stalls on that
jump; ramps avoid it, so G6 is a ramp.

**Proposed fix, not started, needs sign-off:** integrate each edge
exactly under a linear-in-x delta, truncated at the turning point,
instead of the midpoint rule. With alpha as the variable,
`int d(delta)/kappa = hbar/(2u sqrt(mr Eg)) [u asin(alpha) -
sqrt(1-alpha^2)]` and `int kappa d(delta) = sqrt(mr Eg)/(2u hbar)
[u (alpha sqrt(1-alpha^2) + asin(alpha))/2 - (1-alpha^2)^1.5/3]`, so
each edge contributes (dx/d-delta) times a difference of closed forms
(with the flat-edge limit d-delta -> 0 handled separately). That is
continuous as a node crosses delta = 0 or 1, needs no kappa floor, and
makes G2's uniform-field reduction exact instead of N^-1/2. It changes
G_T on real devices and needs its own Jacobian re-derivation, so it is
a model change, not a tweak.

### Suite and goldens after this pass

Fast suite both ways: the only failure is G6. ACCEL=0: 1677 passed, 13
skipped, 1 xfailed (M14 G-A); ACCEL=1: 1685 passed, 5 skipped, 1
xfailed. The default-off golden gates are in that run and pass;
section 7's md5s are unchanged (every edit here sits behind
`btbt_nonlocal=True` or in `kane_local_fp`, which no default path
calls).

### Still not signed off

G6 is openly red (not xfail'd), and G3/G7 are unwritten. Sign-off is
the user's call once those are settled.
