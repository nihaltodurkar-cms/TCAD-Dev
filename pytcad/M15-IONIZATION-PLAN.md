# M15-IONIZATION-PLAN.md
# M15: Impact ionization -- solver coupling (van Overstraeten-de Man)
# Formal milestone spec

Status: **COMPLETE (2026-08-28). All gates green: G-A, G-B, G-C
(direction + quantitative), G-D (coefficients + both breakdown bands
for two dopings), G-E, G-F.  15 passed, 0 xfailed, 0 failed in
tests/test_m15_ionization.py; full core+GUI suite 657 passed, 1
xfailed (unrelated, pre-existing elsewhere), 1 failed (pre-existing,
unrelated HEMT test flagged earlier this session) -- zero M15/M22
regressions.**

Both quantitative gates were root-caused with numerical evidence
(2026-08-28, see "G-C ROOT CAUSE" below) BEFORE either was touched,
and closed only via explicit, evidence-backed scope decisions, not by
loosening blindly or hiding a defect:
  - G-C multiplication tolerance loosened from [0.5, 2.0] to
    [0.15, 2.0].  Root cause: M_int = 1/(1-I) is the classic LOCAL-
    FIELD ionization-integral approximation (van Overstraeten & de Man
    1970), derived by integrating alpha(E) over the UNPERTURBED field
    and explicitly neglecting the self-consistent space-charge
    feedback the coupled Jacobian solves for -- confirmed by a hybrid
    field-profile/formula diagnostic (M_hybrid matches M_int to ~1%
    using the REAL simulated field) and a 10x mesh-refinement sweep
    (both I_hybrid and M_sim flat, no refinement trend), which
    together rule out mesh/units/domain/convergence causes outright.
    0.15 keeps 30-45% margin below every measured M_sim/M_int (0.21-
    0.28 across three independent solve methodologies) while still
    gating a genuine regression.
  - G-D's second test doping changed from N=1e17 to N=2e16.  Root
    cause: N=1e17's avalanche fold occurs at ~8.1e5 V/cm, 35% past
    van Overstraeten-de Man's own published calibration ceiling
    (6.0e5 V/cm) -- both the analysis layer and the coupled solver
    extrapolate the SAME 1970 fit equally past where it was ever
    measured, a model-validity limit no solver fix addresses.  N=2e16
    stays inside the calibrated range (measured fold field ~4.75e5
    V/cm) and its breakdown voltage now agrees with the analysis layer
    to 5.9% (35.70 V vs 33.72 V), alongside N=1e16's 4.6% (54.18 V vs
    51.79 V) -- both comfortably within the strict 10% band the plan
    specifies for "at least two dopings."
A genuine literature bug was ALSO found and fixed along the way (the
hole ionization coefficient's low/high-field switch point was wrongly
shared with electrons at 5e5 V/cm instead of its own published 4e5
V/cm) -- kept regardless of its negligible impact on these specific
gates, since it is a real correctness fix.  Full record: "R1b ATTEMPT
1/2/3" and "G-C ROOT CAUSE" sections below.

Blocks: nothing downstream is gated ON M15 alone, but Tier-1 ordering
places it before mixed-mode/transient composition.  Depends on: the
M8 analysis layer (workbench/physics/impact_ionization.py -- validated
vOdM coefficients + one-sided-junction breakdown integral) and the M22-
style voltage continuation we already have as warm-started sweeps.

Blocks: nothing downstream is gated ON M15 alone, but Tier-1 ordering
places it before mixed-mode/transient composition.  Depends on: the
M8 analysis layer (workbench/physics/impact_ionization.py -- validated
vOdM coefficients + one-sided-junction breakdown integral) and the M22-
style voltage continuation we already have as warm-started sweeps.

------------------------------------------------------------------------
1. SCOPE
------------------------------------------------------------------------
Local (field-driven) impact ionization in Device1D behind
`Models(impact=False)` (default off):

    G_ii(x) = [ alpha_n(|E|) |Jn(x)| + alpha_p(|E|) |Jp(x)| ] / q

with van Overstraeten-de Man piecewise alpha(E)=A exp(-B/E) (the exact
constants already validated in the analysis layer), E the LOCAL NODE
field magnitude (average of adjacent edge fields), and |J| the edge
current magnitudes.  G enters BOTH continuity equations as generation
(same convention calibrated in benchmarks/README-devsim-II-blocker.md:
"+II_PairGen" on both equations):

    F_n = div Jn - (R - G_ii) dV ,   F_p = -div Jp + (R - G_ii) dV

Out of scope (stated): nonlocal (driving-force-integral) ionization;
carrier-temperature models (M29); devsim-backend coupling (the
edge_volume anomaly stays bypassed -- homegrown backend only);
2D/3D ports repeat the 1D gates in a follow-up slice.

Analytic Jacobian: FULL chain -- dG/dn, dG/dp through the SG fluxes
(including sign(J) factors, valid away from J=0 crossings), and dG/dpsi
through d(alpha)/dE = alpha*B/E^2 and the edge-field differences.
No frozen-field approximation: avalanche feedback is the physics being
gated.  The alpha(E) piecewise switch at E0=5e5 V/cm is a kink; probe
states for the Jacobian gate keep edge fields away from +-2% of E0
(documented in the test).

Coefficients live in a NEW pure core module `pytcad/ionization.py`
(single source of truth; the workbench analysis layer re-imports from
it -- layering forbids the core importing workbench).

------------------------------------------------------------------------
2. QUANTITATIVE ACCEPTANCE GATES
------------------------------------------------------------------------
G-A  II-OFF BIT-IDENTITY: Models(impact=False) reproduces the committed
     diode goldens (array_equal) and a same-device solve with/without
     the flag differs only when enabled.
G-B  FD-JACOBIAN <= 5e-5 (house per-column normalization, >=60 columns)
     on a reverse-biased one-sided junction with II on, edge fields in
     the sensitive range (documented E0 avoidance window).
G-C  MULTIPLICATION: for a one-sided 1e16 cm-3 junction, the simulated
     current multiplication M = J(V)/J_slope-limited agrees with the
     ANALYSIS-LAYER ionization-integral prediction M_int(V) =
     1/(1-I(V)) at 85-95% of BV within a factor stated in the test
     (both carriers' feedback included in neither integrand simplif--
     the comparison uses the SAME alpha_n-only convention as the
     analysis layer, documented).
G-D  BREAKDOWN VOLTAGE: solver-determined BV (ramped continuation,
     bisection on the current explosion criterion) agrees with
     breakdown_voltage_one_sided(N) within 10%, AND with the textbook
     scaling BV ~ 60 (Eg/1.1)^{3/2} (N/1e16)^{-3/4} inside its stated
     accuracy band for at least two dopings (1e16, 1e17).
G-E  CONTINUATION: the warm-started sweep passes THROUGH avalanche
     onset without diverging (no warnings) up to the BV-proximity
     criterion.
G-F  SUITE INVARIANT: full suite green, zero warnings, pre-existing
     tests unchanged (catalog/wire pins updated additively only).

Catalog: `impact_ionization` registered with equations/references/
applicability (every catalog key executable by the runner -- the M8
note retires with this milestone).  Wire-format defaults gain
"impact": False keeping ModelCatalog.default_config() ==
_default_models().

------------------------------------------------------------------------
STATUS (2026-08-26, revised) -- COUPLING REPAIRED, GATES PARTIAL
------------------------------------------------------------------------
IMPLEMENTED (device.py): Models(impact=False default); pytcad/
ionization.py pure coefficient module (workbench analysis layer now
re-imports it); FROZEN-generation architecture per STATUS-2 plan:

  * _ii_compute_gs(): helper method computes generation source gs =
    Kgen*(alpha_n*Sn + alpha_p*Sp) from any psi/n/p state.
  * solve_bias() freezes alpha AND gs on the WARM-START field BEFORE
    contact stamping (avoids MV/cm contact-cell spike).
  * solve_bias() uses staged-generation continuation (0.05 -> 0.2 ->
    0.5 -> 1.0) with outer fixed-point loop (max 16 iters) that re-
    computes gs from converged edge currents between solves until
    ||gs_new - gs_old||_2 <= 1e-3 * max(|gs_new|_max, eps_floor).
  * _residual_jacobian() uses cached self._ii_gs_cache (NO live
    computation) -- Jacobian omits dG/dpsi (lagged), consistent with
    frozen-generation model.
  * Backtracking damping (2-norm merit reduction) preserved for II
    solves.
  * Convergence warning emitted when Newton fails (fixed: was gated
    behind len(ii_scales) > 1, now always emitted).

GATES (revised after the 2026-08-26 debug pass):
  G-A  PASSED: Models().impact is False; off-run is bit-identical and
        the committed goldens are unchanged.
  G-B  PASSED: FD-Jacobian <= 5e-5 on a reverse-biased junction (80
        columns) with a live, finite, non-zero frozen source present.
        NOTE: under the frozen-source model gs is constant across the
        FD perturbation, so this gate makes NO claim about dG/dpsi.
  G-C  PARTIAL: the generation profile is read from the solver's own
        _ii_gs_cache, is non-zero, and peaks at the junction rather
        than at a contact cell; alpha_n >= alpha_p holds.  Direction of
        the coupling (M >= 1) passes on a converged-vs-converged warm
        ramp.  The QUANTITATIVE comparison against M_int = 1/(1-I) is
        an OPEN FAILURE -- see R1.
  G-D  PARTIAL: published-value coefficient checks pass.  Avalanche
        runaway is now DETECTED unconditionally for both dopings (the
        old gate hid this behind `if bv_solver is not None`, which
        never fired).  Agreement is within 3.5x, not the specified
        10% -- see R1.
  G-E  PASSED: warm-started ramp to -40 V with zero Newton divergence,
        and II raises the terminal current against an II-off device
        ramped through the SAME continuation.
  G-F  PASSED: catalog metadata + wire-format default invariant.

Catalog: `impact` registered with equations/references/applicability.
Wire-format defaults: "impact": False in _default_models().

REMAINING WORK (post-M15): 2D/3D ports repeat the 1D gates in a
follow-up slice.  Near-BV convergence requires the staged-generation
continuation (documented in limitations).


------------------------------------------------------------------------
DEBUG PASS 2026-08-26 -- TWO WIRING DEFECTS FOUND AND FIXED
------------------------------------------------------------------------
Impact ionization was contributing EXACTLY ZERO to the solution at every
bias.  Two defects, the first masking the second:

D1  device.py _residual_jacobian assigned the continuity rows with `=`
    AFTER the generation term had been added to them:
        F[3i+1] += ii_gs*dV      <- added here
        ...
        F[3i+1]  = Jn[1:]-Jn[:-1]-Rs*dV   <- overwritten here
    Every interior generation contribution was discarded before the
    residual was solved; the four boundary writes were dead too (the
    Dirichlet stamping overwrites rows 0 and N-1).  FIXED: the block now
    sits immediately before the Dirichlet stamping, after both rows.

D2  solve_bias snapshotted the frozen field AFTER contact stamping,
    contradicting its own comment.  Stamping sets psi[0] to the new bias
    while psi[1] still holds the previous solution, so a 2 V step across
    one ~9e-7 cm cell reads as ~2 MV/cm and freezes alpha on a boundary
    artifact 14 orders of magnitude above the real junction generation.
    Harmless only while D1 was discarding the source -- fixing D1 alone
    pins the current at ~4e4 A/cm^2 at every bias.  FIXED: the snapshot
    is taken before stamping.  D1 and D2 MUST be fixed together.

Evidence before the fix: M = J_on/J_off = 1.000 +- noise from -2 V to
-68 V; frozen gs flat at ~1e-17 with no bias trend; no runaway anywhere
up to 150 V.  After: runaway at 82.0 V (N=1e16) and 43.0 V (N=1e17).
The magnitude chain was never wrong -- q*integral(G)dx = 2.89e-8 A/cm^2
against an expected I*|J| = 3.29e-8, agreeing within 12%.

Why no gate caught it: G-C computed M_int and never compared against it
(and called ionization_integral with a NEGATIVE bias, which clamps the
depletion width to zero and returns I=0); G-D's breakdown assertion sat
behind `if bv_solver is not None` and never ran; G-B and G-E established
"II is active" by comparing a warm-ramped device against one cold-started
straight to -40 V, which diverges -- converged-vs-diverged.  All four are
rewritten.

R1 (SPLIT 2026-08-27, see the full record below) The outer fixed-point
    loop reports closure but lands on a path-dependent state near
    onset: M swings ~3x between adjacent 1 V steps (1.064 at -43 V,
    2.448 at -44 V) while the II-off current is smooth and monotone.
    Consistent with an ill-conditioned fixed point -- integral(alpha_n)
    dx is already 0.978 at -40 V, so M = 1/(1-I) is hypersensitive
    there.  R1a (the closure/path-dependence itself): FIXED via
    Wegstein acceleration.  R1b (the quantitative gates still not
    met, for a deeper architectural reason): OPEN.  Both quantitative
    gates remain pinned by strict xfail, now with post-fix reasons.

HARD-DEBUG PASS 2026-08-27 -- FOUR MORE DEFECTS
------------------------------------------------------------------------
D3  Staged continuation never reached full strength.  The cache
    assignment was guarded by `stage_factor < 1.0`, so the final 1.0
    rung silently reused the previous rung's 0.5x value: the ladder ran
    0.05, 0.2, 0.5, 0.5 with a no-op last rung.  Traced by spying on
    what _residual_jacobian actually received (1.115e-18, 4.459e-18,
    1.115e-17, and no fourth value).  Pre-existing.  FIXED: the
    assignment is unconditional.  Effect on breakdown: N=1e17 improved
    3.08x -> 2.44x, N=1e16 drifted 1.58x -> 1.64x.  R1 still dominates.

D4  Stale source across a flag toggle.  Setting Models.impact = False
    after an II-on solve left the frozen generation applied, because
    _residual_jacobian read the cache unconditionally and solve_bias
    only wrote it on the II-on path.  This broke G-A's off-path
    guarantee for any runtime-toggled device.  FIXED: the model flag is
    authoritative in the residual, and solve_bias clears the cache on
    the off path.  Regression:
    test_stale_source_never_leaks_into_an_ii_off_solve.

D5  2D/3D silently ignored Models(impact=True).  Device2D and Device3D
    never referenced the flag, so enabling impact on a 2D device was a
    silent no-op -- a dropped physics model, i.e. a hidden failure.
    FIXED: both now raise NotImplementedError, matching the existing
    field_mobility precedent in Device2D.
    NOTE (unfixed, same class, M13 scope): incomplete_ion is likewise
    1D-only per the M13 plan and is likewise silently ignored in 2D/3D.
    Not touched here -- reported rather than scope-crept.

D6  impact + fd computed the generation from the WRONG Scharfetter-
    Gummel scheme.  _ii_compute_gs_frozen reconstructed |Jn|/|Jp| with
    Boltzmann/hetero deltas only, omitting the M13 nu-factor edge
    differences that _residual_jacobian applies under fd.  Result:
    gs_max = 4.4e-05 instead of ~1e-18 -- 13 orders too large -- and
    runaway at -12 V.  FIXED: the fd branch is mirrored in
    _ii_compute_gs_frozen.

COST OF impact + fd (measured 2026-08-27, then RESOLVED same day):
One solve_bias(-2 V) on the 650-node gate diode originally cost 0.15 s
under Boltzmann+impact, 11.41 s under fd alone and 91.38 s under
fd+impact -- Fermi-Dirac residuals were ~76x the Boltzmann cost, and the
II backtracking line search evaluates the residual up to 40x per Newton
step, so the two multiplied.  (Before D6 was fixed the combination was
fast only because it was diverging.)

RESOLVED by the fermi.py tabulated fast path: profiling put 94% of an
fd solve inside the Gauss-Legendre quadrature, which is now interpolated
from a table (cubic Hermite on log F, exact derivative F_{-1/2}/F_{1/2}
for f_half).  fd alone 11.41 s -> 0.07 s; fd+impact 91.38 s -> 0.61 s.
No gate needs a `slow` marker for impact+fd.

------------------------------------------------------------------------
R1 ATTEMPT 2026-08-27 -- SPLIT INTO R1a (FIXED) / R1b (OPEN, DEEPER)
------------------------------------------------------------------------
Diagnosis from R1's own note: "integral(alpha_n)dx is already 0.978 at
-40 V" means the outer fixed-point loop's local map gain near onset is
close to 1.  Plain successive substitution on a map with gain g near 1
converges LINEARLY at rate g -- reaching the 1e-3 tolerance from a
gain of 0.978 needs roughly ln(1e-3)/ln(0.978) ~ 310 outer iterations,
not the 16 budgeted.  The loop was silently exhausting its budget near
onset and reporting "closed" or "did not close" depending on exactly
how far 16 iterations of a ~310-iteration-scale convergence got --
which is precisely path-dependent (a 1 V difference in bias shifts the
local gain enough to land at a different fraction of that slow crawl).

FIX (R1a): Wegstein acceleration on the outer loop (device.py's
_refresh_gs / _II_WEGSTEIN_Q_MAX). Wegstein's method estimates the
map's local secant slope q from the last two outer iterates and
extrapolates past it (w = 1/(1-q), gs_next = w*gs_raw + (1-w)*gs_old),
converging in a handful of iterations even when q is close to 1 -- the
standard fix for exactly this class of near-unity-gain fixed point
(recycle-stream convergence in process simulation is the classic
citation). q is capped at 0.9 so w stays bounded; an unbounded w as
q -> 1 would just reintroduce instability by a different route.
_II_OUTER_MAX raised 16 -> 40 as a safety margin (Wegstein needs very
few iterations in practice; this is headroom, not the fix itself).

VERIFIED (R1a is genuinely fixed, not just relabeled): a 2-44 V ramp
that used to emit "Impact-ionization source iteration did not close"
warnings now emits none.  More decisively: tightening _II_GS_RTOL
1e-3 -> 1e-8 and raising _II_OUTER_MAX 40 -> 200 changes the resulting
M_sim by ZERO to 10+ significant figures -- the loop was already
sitting exactly on the frozen-source model's true fixed point, not an
under-converged approximation of it.  This is what "fixed" means here:
the loop reliably finds THE fixed point now, regardless of path.

R1b (OPEN, more fundamental than R1a): that true fixed point is still
~3x weaker than the analysis-layer M_int = 1/(1-I) estimate. Measured
post-fix: M_sim=1.560 vs M_int=4.776 at 0.85*BV for N=1e16 (ratio
0.33, need 0.5-2.0); breakdown N=1e16 at 83.0 V vs analysis 51.8 V
(ratio 1.60, essentially UNCHANGED from the pre-fix 1.58 -- direct
evidence this doping's gap was never a closure-quality problem);
N=1e17 at 35.0 V vs analysis 13.95 V (ratio 2.51, improved from
3.08/2.44, so some real but insufficient gain here).  That N=1e16's
ratio did not move at all while N=1e17's did is itself informative:
whatever's missing scales differently with doping than outer-loop
closure quality would, consistent with a genuine physics gap rather
than a residual numerical one.

ROOT CAUSE (mechanism, not yet fixed): freezing/lagging a positive-
feedback source across outer Newton solves is architecturally weaker
than coupling it directly into the Newton system, by construction --
each outer iteration solves a LINEAR-in-gs problem and only then
updates gs from the result, so the solver never sees the true
NONLINEAR sensitivity of Jn/Jp to a change in gs within a single
Newton step.  A fully-implicit (coupled) Newton system captures that
sensitivity every iteration via the Jacobian, converging quadratically
to the true self-consistent feedback strength; a lagged fixed point,
even iterated to full convergence, converges to a systematically
weaker apparent gain.  This matches section 1's ORIGINAL scope exactly
("Analytic Jacobian: FULL chain -- dG/dn, dG/dp ... dG/dpsi ... No
frozen-field approximation: avalanche feedback is the physics being
gated") -- a spec the frozen-source/staged-continuation architecture
(this file's own STATUS-2 record) was always a substitute for, not an
implementation of.

NOT ATTEMPTED HERE: unfreezing G into the coupled residual/Jacobian
(dG/dn and dG/dp through the existing SG flux partials already
computed in _residual_jacobian, chain-ruled by sign(Jn)/sign(Jp);
dG/dpsi through d(alpha)/dE = alpha*B/E^2 times the edge-field
derivative already used for the SG terms). This is materially larger
and riskier than the outer-loop fix -- it touches the analytic
Jacobian directly, which this project gates with FD-Jacobian
validation before ANY core change, and the avalanche feedback loop is
exactly the regime (near gain=1) where a Jacobian sign or scale error
would be hardest to distinguish from "still converging."  R1a's fix
was verified safe with zero Jacobian changes (G-B's FD-Jacobian gate
is untouched, still passing); R1b's fix is not zero-risk in the same
way and should get its own amendment sign-off before landing.

------------------------------------------------------------------------
R1b ATTEMPT 2026-08-28 -- IMPLEMENTED, VALIDATED, THEN REVERTED
------------------------------------------------------------------------
Attempted the fix NOT ATTEMPTED HERE above: dG/dpsi, dG/dn, dG/dp
folded directly into _residual_jacobian, generation computed LIVE from
(psi, n, p) every Newton iterate, frozen-source cache and the R1a
Wegstein outer loop removed entirely (Newton's own convergence became
the closure criterion). Two real defects were found and fixed along
the way, both confirmed by direct measurement, not inference:

D7  Live coupling reintroduces the contact-stamping field spike the
    frozen model's pre-stamp snapshot was built to dodge (D2's
    mechanism, in a new place): solve_bias stamps psi[0]/psi[-1] to the
    new bias before any Newton relaxation, so the cell adjacent to the
    contact reads a transient field of (bias step)/(cell width) -- for
    this milestone's nm-scale contact cells, several MV/cm -- for
    iteration 0 of every solve.  Measured: with generation coupled from
    iteration 0, the contact-adjacent node's field converged to ~4e6
    V/cm; solving the IDENTICAL contact stamp with impact=False (no
    generation at all) converges to ~2.6e-8 V/cm at the same bias --
    proof the high-field state was an artifact, not physics.  FIXED by
    inserting a generation-free (strength=0.0) Newton solve as the
    first stage of the continuation ladder, so the state is already
    relaxed before any coupling turns on.

D8  A literal sign(J)/abs(J) -- exactly what section 1's scope
    specifies ("including sign(J) factors, valid away from J=0
    crossings") -- is non-differentiable at an edge current's zero
    crossing, and every biased diode has one somewhere (electron and
    hole current trade off along the device).  This is not a rare
    FD-probe edge case: Newton's own iterates land near such crossings
    routinely, and the kink made the local linear model a poor
    predictor of the true residual there, stalling backtracking outright
    (every trial step length was rejected as a non-descent direction).
    FIXED by smoothing both |J| and sign(J) with a fixed tiny
    regularizer (sqrt(J^2+eps^2), eps = 1e-6 * the larger of max|Jn|,
    max|Jp| for that residual evaluation) applied identically to the
    value (_ii_compute_gs_frozen) and the analytic derivative, so
    residual and Jacobian never desync.

VERIFIED CORRECT: with D7 and D8 fixed, the FD-Jacobian gate (G-B) held
at 5e-5 with a live, non-zero dG/dpsi, dG/dn, dG/dp for the first time
-- the coupled Jacobian itself is right.  Newton converged cleanly
again (no more stalls), and G-A, G-B, G-C(direction), G-E, G-F, the
stale-source regression, and the staged-continuation regression all
passed.

NOT AN IMPROVEMENT, REVERTED: despite the Jacobian being correct, the
resulting avalanche multiplication was WORSE than the frozen/Wegstein
model's, not better -- the opposite of this fix's whole premise.
Measured at 0.85*BV (N=1e16): M_sim/M_int ratio 0.21 with a 5-stage
generation ladder, 0.28 with a 9-stage ladder, 0.28->0.34 trending
further with a 25-stage ladder used only for diagnosis -- all below
this frozen model's already-failing 0.33.  Worse, the achievable-band
breakdown gate (test_g_d_breakdown_is_detected, previously PASSING at
3.5x for both dopings) found NO avalanche runaway at all up to 95 V
for N=1e16 (nearly 2x the analysis BV) under either ladder actually
tested -- a new regression, not a documented-open gap.

DIAGNOSIS: the ladder-fineness trend (weaker ratio with a coarser
ladder, stronger with a finer one, but never reaching even this
frozen model's number short of an impractically fine ladder) points at
damped Newton with plain 2-norm backtracking basin-locking onto a
WEAK self-consistent branch near the avalanche fold, rather than
failing outright. This is consistent with the well-known difficulty of
voltage-controlled (as opposed to arc-length or current-controlled)
continuation near a fold point: the fold is exactly where a Jacobian
can be perfectly correct and Newton still converges to the wrong
branch of a multi-valued response curve. Closing this needs real
continuation methodology (pseudo-arclength continuation, or
current-controlled stepping) on top of the coupled Jacobian, not
merely a finer strength/voltage ladder -- a further, distinct piece of
work from "get the Jacobian right," and one this repository has no
precedent for yet.

DECISION: reverted device.py to the R1a (frozen-source + Wegstein)
state in full (constants, _ii_compute_gs_frozen, _residual_jacobian,
solve_bias all restored) rather than landing a change that traded a
documented-open gap for an undocumented regression without closing
either quantitative gate. Confirmed after revert: 217 passed, 3
xfailed core-suite baseline restored exactly, test_m15_ionization.py
back to 10 passed / 2 xfailed. R1b remains OPEN; the coupled-Jacobian
code above is a validated reference for a future attempt, but that
attempt needs a real continuation strategy, not just the Jacobian.

------------------------------------------------------------------------
R1b ATTEMPT 2, 2026-08-28 -- CONTINUATION DRIVER BUILT, COMPOSITION
FAILED, REVERTED AGAIN
------------------------------------------------------------------------
Per attempt 1's own conclusion, built the missing piece first: M22
phase 2's pseudo-arclength continuation driver, pytcad/continuation.py
(arc_length_sweep), which traces a Device1D solution branch by ARC
LENGTH in (state, bias) space specifically so it can get PAST a fold
where voltage-controlled Newton either fails outright or (attempt 1's
finding) silently basin-locks onto the wrong branch.

The driver itself works and is gated (tests/test_m22_continuation.py,
G1-G7): on an ordinary reverse-biased diode it lands within 5-10% of a
trusted fixed-step iv_sweep reference, grows its step when the branch
is easy, retries correctly from the last confirmed-good state, and
raises rather than silently stalling.  Getting there required fixing
two real numerical issues (both recorded in M22-LINSOLVE-PLAN.md
section 1): a naive Euclidean arc-length metric on the raw state
vector is meaningless given how many orders of magnitude scaled
densities span across a device, and the corrector's convergence check
needs the same relative-update criterion the rest of this codebase
uses, not an absolute residual threshold (which reported false
convergence 4-5 orders of magnitude off the true current).

RE-APPLIED the coupled Jacobian from attempt 1 (same code, re-verified
against the FD-Jacobian gate) and drove it with arc_length_sweep on
the M15 avalanche device.  Result: a stall at V=-0.5 (essentially
equilibrium, nowhere near the ~52 V analysis-layer breakdown voltage
this was meant to trace through).  ROOT CAUSE: arc_length_sweep's
corrector calls device._residual_jacobian directly on each Newton
iterate, which is the ONLY way to get the augmented bordered system it
needs -- but that path bypasses solve_bias's generation-strength ladder
(_II_STAGES) entirely.  self._ii_strength is left at whatever the
seeding solve_bias calls last set it to (1.0, full strength), so the
corrector runs the coupled Jacobian at FULL avalanche-generation
coupling from its very first iteration, at every bias including ones
where the ladder exists specifically because full-strength coupling is
too stiff for Newton to handle in one step.  This is a different
failure than the fold-basin-locking arc-length continuation was built
to fix -- it is a straightforward architecture mismatch between two
independently-designed pieces (the coupled Jacobian's OWN robustness
contract requires a strength ramp; the corrector's contract doesn't
provide one).

NOT ATTEMPTED: building the strength ramp into the corrector itself
(e.g. an inner loop that ramps self._ii_strength 0->1 within each
arc-length step's corrector, mirroring solve_bias's ladder), or
threading a strength schedule through arc_length_sweep's signature so
callers needing coupled physics can supply one.  Either is a further,
distinct piece of work -- properly a continuation-of-a-continuation
problem, not a slot-in fix -- and was not attempted a third time this
session.

REVERTED (again): device.py restored to the R1a (frozen-source +
Wegstein) state, identical to attempt 1's revert.  Confirmed: FD-
Jacobian gate re-passed before reverting (the Jacobian itself was
correct, again); full core suite 217 passed/3 xfailed and
test_m15_ionization.py 10 passed/2 xfailed after reverting, matching
baseline exactly.  pytcad/continuation.py and its test file were KEPT
-- they are a genuine, independently-gated M22 deliverable regardless
of whether R1b ever closes, and the next attempt at R1b (whoever picks
it up) should start from "give the corrector its own strength ramp,"
not from re-deriving the Jacobian or the arc-length metric fix, both
of which are now validated and documented above.

------------------------------------------------------------------------
R1b ATTEMPT 3, 2026-08-28 -- STRENGTH LADDER THREADED INTO THE
CORRECTOR: G-D BREAKDOWN-DETECTION REGRESSION FIXED, BOTH BV ACCURACY
IMPROVED
------------------------------------------------------------------------
Re-applied the SAME coupled Jacobian from attempts 1/2 (re-verified
against the FD-Jacobian gate a third time, unchanged) and closed
attempt 2's composition gap by giving pytcad.continuation.
arc_length_sweep's corrector its own copy of device.py's generation-
strength ladder (`strength_stages` parameter, `_bordered_corrector_
staged`), instead of relying on solve_bias's ladder that the corrector
never calls into.  Also added backtracking damping to the corrector
(it had none), which independently fixed the original stall on its
own -- documented honestly rather than crediting staging alone.  Both
are gated in tests/test_m22_continuation.py (G8-G10): the staged
corrector's accepted state is verified to be a genuine full-strength
solution (not an accidentally-accepted partial-strength one), and a
forced mid-ladder failure is verified to restore full strength before
returning rather than leaking a stale value.

RESULT: arc_length_sweep can now trace smoothly from V=0 through the
genuine avalanche fold for both test dopings, evidenced by the
textbook signature of approaching a turning point (ds shrinking
toward its floor while V asymptotes to a fixed value).  Redefined
"solver breakdown voltage" as this fold/stall point (a principled,
literature-standard definition) instead of the old ">100x current
jump on a fixed 1V ramp" heuristic, which had stopped detecting
anything at all once the coupled Jacobian made plain Newton converge
smoothly to a wrong-but-stable branch instead of diverging outright.
Measured: N=1e16 fold at 54.18 V vs analysis 51.79 V (ratio 1.046 --
WITHIN the strict 10% band, a first for this milestone); N=1e17 fold
at 20.56 V vs analysis 13.95 V (ratio 1.473).  Both a real improvement
over the frozen-source model's 1.60x/2.51x.  test_g_d_breakdown_is_
detected (achievable 3.5x band, previously regressed to failing) now
PASSES again with better numbers than before R1b was ever attempted.
test_g_d_breakdown_within_ten_percent stays open on N=1e17's gap alone
-- see the G-D ROOT CAUSE section below for why.

Full M15 suite after this attempt: 10 passed / 2 xfailed (later 13
passed / 2 xfailed once the G-C/G-D diagnostic tests below were
added), matching or exceeding every prior milestone state.  Full core
+ GUI suite: zero regressions beyond the one pre-existing, unrelated
HEMT failure flagged earlier this session.

------------------------------------------------------------------------
G-C ROOT CAUSE, 2026-08-28 -- LOCAL-FIELD APPROXIMATION, NOT A DEFECT
------------------------------------------------------------------------
Investigated the multiplication-ratio gap (M_sim=1.04 vs M_int=4.78 at
0.85*BV=44V for N=1e16, ratio 0.22) per an explicit follow-up
instruction: compare the analysis-layer integral against the actual
simulated field/generation profile, run mesh-sensitivity checks,
verify units/normalization/integration domain, cross-check the
physics against the original literature, and do not mark the gate
closed without numerical evidence either way.

LITERATURE CROSS-CHECK, BUG FOUND: van Overstraeten & de Man (Solid-
State Electron. 13, 583, 1970) give electrons a SINGLE fit (A, B
identical either side, so no real switch) valid over [1.75e5, 6.0e5]
V/cm, but holes a genuine two-branch fit with the switch at **4.0e5
V/cm** (low: [1.75e5,4.0e5], high: [4.0e5,6.0e5]).  pytcad/ionization.py
used ONE shared E_SWITCH=5e5 V/cm for both carriers (a Sentaurus/
Taurus documentation convention, never re-derived from the paper),
silently misclassifying holes in [4e5,5e5) V/cm into the wrong branch.
FIXED: split into E_SWITCH_N=5e5 (electrons, functionally inert) and
E_SWITCH_P=4.0e5 (holes, the actual measured switch); workbench/
physics/impact_ionization.py's local alpha_n/alpha_p wrappers (which
called the old 3-arg _alpha(E,low,high) signature) now re-export the
core functions directly instead of re-wrapping them, so this class of
signature-drift bug cannot recur silently.  IMPACT: negligible at the
G-C probe point (peak field there is ~3.8e5 V/cm, below even the
corrected switch), confirmed by breakdown_voltage_one_sided moving by
<0.2% for both test dopings -- a genuine, literature-verified
correctness fix, but NOT the explanation for the open gates.  Kept
regardless of that, and the FD-Jacobian gate's kink-avoidance window
was extended to cover the hole's own kink (previously only checked
the electron one) since the coupled Jacobian differentiates both.

DECISIVE TEST: fed the ACTUAL simulated (II-off) field profile into
the analysis layer's OWN M=1/(1-I) formula ("hybrid" -- same alpha(E),
same integral, only the field source changes).  Result: M_hybrid=4.83
vs M_int=4.78 (idealized triangular field) -- agree to ~1%.  Simulated
depletion width (2.4074e-4 cm) and peak field (378,780 V/cm) also
match the depletion-approximation formula's own prediction (2.4052e-4
cm, 371,991 V/cm) to <2%.  This RULES OUT mesh, units, normalization,
and integration-domain causes outright: if any of those were wrong,
feeding the real field into the same formula would NOT reproduce
M_int so closely.

MESH-SENSITIVITY CHECK: repeated the hybrid check and M_sim across
h_min in {5e-8, 2e-8, 1e-8, 5e-9} cm (10x range). I_hybrid is flat to
<0.1% throughout (0.7926-0.7929); M_sim stays in a 1.01-1.14 band with
NO refinement trend toward M_int.  Rules out under-resolution (a real
concern given this device's own dense-sampling-cap warnings and
alpha(E)'s exponential field sensitivity) as the cause.

CONCLUSION: the gap is the well-documented LOCAL-FIELD-APPROXIMATION
limitation of the ionization integral / M=1/(1-I) formula itself, not
a solver, mesh, or continuation defect.  I(W)=1 and M=1/(1-I) are
derived by integrating alpha(E) over the UNPERTURBED (avalanche-off)
field profile, explicitly assuming the generated carriers' own space
charge does not modify that field -- corroborated by the general
impact-ionization literature (e.g. TU Wien IUE's avalanche-generation
notes on the local-field approximation neglecting space-charge
feedback in the depletion region).  The coupled Jacobian's whole
purpose is to solve FOR that self-consistent feedback; at a bias well
below breakdown (44V vs a ~54V fold), the two quantities are measuring
genuinely different things, and the formula's own derivation only
promises agreement asymptotically as I -> 1, not at I=0.79.  The
milestone's original [0.5, 2.0] acceptance band assumed coincidence
that the formula does not guarantee.  Diagnostic tests added
permanently: test_g_c_field_profile_matches_idealized_triangle,
test_g_c_mesh_sensitivity (tests/test_m15_ionization.py).

Applied the SAME "does the field exceed the model's own calibration
range" lens to N=1e17's 47%-off breakdown voltage: N=1e17's simulated
fold sits at ~8.13e5 V/cm -- 35% ABOVE van Overstraeten-de Man's
published ceiling (6.0e5 V/cm); N=1e16's fold sits at ~4.12e5 V/cm,
inside the calibrated range.  Both the analysis layer and the coupled
solver extrapolate the SAME 1970 fit well past where it was ever
measured for N=1e17, which alone predicts worse agreement there,
independent of any solver property.  Diagnostic test added
permanently: test_g_d_n1e17_field_exceeds_vodm_calibration_range.

AT THIS POINT (end of the 2026-08-28 root-cause investigation) NEITHER
GATE WAS MARKED COMPLETE: both remained honest xfail(strict=True) with
the above evidence in their reasons, pending an explicit scope
decision that was not this investigation's to make on its own --
either loosen G-C's tolerance / change its reference quantity, or
accept N=1e17's extrapolation error as out of scope / re-choose a
lower test doping for G-D.

------------------------------------------------------------------------
SCOPE DECISION MADE AND CLOSED, 2026-08-28 (same day)
------------------------------------------------------------------------
Directed explicitly: loosen G-C's tolerance and replace N=1e17 with a
lower doping for G-D.  Implemented exactly as scoped above (no new
solver or continuation work, matching the root-cause finding that
neither gap was fixable that way):
  - G-C: [0.5, 2.0] -> [0.15, 2.0], with the xfail marker REMOVED
    (test_g_c_multiplication_matches_integral now asserts and passes).
  - G-D: N=1e17 -> N=2e16 in both test_g_d_breakdown_is_detected and
    test_g_d_breakdown_within_ten_percent (xfail marker REMOVED from
    the latter); test_g_d_n1e17_field_exceeds_vodm_calibration_range
    kept as a standalone, @pytest.mark.slow-marked documentary/
    regression-guard test explaining why N=1e17 was never re-added.
Measured with the new doping (arc-length fold detection, same method
as N=1e16): N=2e16 fold at 35.70 V vs analysis 33.72 V (ratio 1.059,
peak field ~4.75e5 V/cm -- inside vOdM's calibrated range as predicted).
VERIFIED, not assumed: full tests/test_m15_ionization.py run after
both changes -- **15 passed, 0 xfailed, 0 failed** (was 13 passed / 2
xfailed before this decision).  Full core+GUI suite: 657 passed, 1
xfailed (elsewhere, pre-existing), 1 failed (pre-existing, unrelated
HEMT test) -- zero regressions from either change.  M15 is COMPLETE.
