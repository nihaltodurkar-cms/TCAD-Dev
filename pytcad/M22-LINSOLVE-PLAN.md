# M22-LINSOLVE-PLAN.md
# M22: Linear solver modernization (Krylov + ILU) + continuation
# Formal milestone spec

Status: **PHASE 1 COMPLETE (G1-G7 GREEN). PHASE 2 LANDED 2026-08-28,
GATES G1-G7 GREEN** (tests/test_m22_continuation.py, G1-G10 after the
strength-ladder addition) for its stated scope: adaptive-step and
pseudo-arclength continuation on ordinary (unfolded) Device1D bias
ramps, gated against a trusted fixed-step iv_sweep reference.  Its
FIRST composition attempt with the coupled impact-ionization Jacobian
hit an architecture gap (the corrector bypassed solve_bias's
generation-strength ladder) -- FIXED same session by threading the
ladder into the corrector itself (`arc_length_sweep`'s
`strength_stages` parameter); this is what let M15 R1b close (M15 is
now COMPLETE -- see ARCHITECTURE.md section 5 and M15-IONIZATION-
PLAN.md).  PHASE 3 (solver-level MPI distribution) is SCOPED ONLY, not
started -- see section 1.

Roadmap slot: SENTAURUS-PARITY-PLAN.md line 234, "M22 LINEAR SOLVER
MODERNIZATION + CONTINUATION [L]".

------------------------------------------------------------------------
1. SCOPE
------------------------------------------------------------------------
Motivation (measured, this session): profiling a 27^3=19683-node 3D
resistor equilibrium solve put 98% of the time in scipy spsolve (direct
sparse LU).  Direct factorization is also what blocks distribution: a
Krylov method is the prerequisite for any GPU or MPI solve, since those
need a distributed/accelerated matvec + preconditioner apply, not a
distributed LU.

PHASE 1 [M] -- linear-solve abstraction, THIS SESSION:
  pytcad/linsolve.py: `solve_linear(A, b, *, method, ...)` wrapping
  scipy spsolve (direct, UNCHANGED default) and scipy gmres/bicgstab
  with an ILU preconditioner (spilu, always available; pyamg used as
  the preconditioner builder when installed, silently unused otherwise
  -- rule 4, optional deps stay optional).  Wired into the GENERAL
  (non-tridiagonal) Newton solves in Device1D.solve_bias, Device2D and
  Device3D via a new `NewtonOptions.linsolve` field, default "direct".
  The tridiagonal equilibrium solves are NOT touched -- already cheap,
  and touching them adds core-amendment risk for no measured benefit.

PHASE 2 [L] -- continuation driver, LANDED 2026-08-28:
  pytcad/continuation.py, a driver ABOVE the solver (same standing as
  M21's adapt.py), independent of phase 1, touching no residual/
  Jacobian/golden. Two strategies:

    adaptive_bias_sweep -- fixed-direction bias ramp that halves its
    step and retries (from the last CONFIRMED-converged state -- the
    failed iterate is discarded, not warm-started from) on Newton
    failure.  Targets the plan's "-2V marginal points" acceptance item.

    arc_length_sweep -- pseudo-arclength continuation (Keller 1977):
    parameterizes the branch by ARC LENGTH in (state, bias) space
    rather than by bias alone, so it can trace THROUGH a fold in the
    response curve where a bias-controlled step cannot tell "no
    solution here" from "converged to the wrong branch."  Built with
    M15 R1b's avalanche fold as the motivating case (see M15-
    IONIZATION-PLAN.md).  Two engineering findings, both fixed:
      - A naive Euclidean arc-length metric on the raw (psi, n, p, V)
        state is dominated by whichever node has the largest ABSOLUTE
        density swing (densities span >20 orders of magnitude across a
        device), which is numerically meaningless and drove the
        corrector backward/into stalls.  Fixed by restricting the
        tangent/constraint metric to psi + V only (a standard weighted-
        arclength technique) -- the corrector still solves the FULL
        coupled system every iteration; only how a step's LENGTH is
        measured changes.
      - The corrector's convergence check must use the same
        relative-UPDATE criterion Device1D's own Newton loop uses, not
        an absolute residual-norm threshold: F mixes a Poisson row and
        two continuity rows whose natural scaled magnitudes differ by
        orders of magnitude, so an absolute threshold reported "solved"
        after 0-2 iterations at points whose true current was 4-5
        orders of magnitude off a reference solve at the same bias.

  GATED (tests/test_m22_continuation.py, G1-G7): both drivers land
  within 5-10% of a trusted fixed-step iv_sweep reference on an
  ordinary reverse-biased diode; adaptive step growth, retry-from-
  last-good-state, and honest-failure (raise, never silent stall) are
  each gated independently for both drivers.

  CLOSED (initially NOT, then fixed same session): the first attempt
  to get arc_length_sweep PAST the M15 avalanche fold with the coupled
  impact-ionization Jacobian failed -- the corrector called
  device._residual_jacobian directly, bypassing solve_bias's
  generation-strength ladder entirely, so it ran at full coupling
  strength from the very first step and stalled even at V=-0.5, far
  from the fold.  FIXED by threading the SAME ladder into the
  corrector itself (`strength_stages` parameter on arc_length_sweep,
  `_bordered_corrector_staged`), plus adding backtracking damping the
  corrector never had.  With both, arc_length_sweep traces cleanly
  through the genuine avalanche fold for both M15 test dopings.  Gated
  in tests/test_m22_continuation.py G8-G10 (staged corrector accepts
  only genuine full-strength solutions; a forced mid-ladder failure
  restores full strength before returning rather than leaking a stale
  value; the staged path honors the same honest-failure contract as
  the unstaged one).  See M15-IONIZATION-PLAN.md's "R1b ATTEMPT 2" (the
  failure) and "R1b ATTEMPT 3" (the fix) for the full record -- M15 is
  now COMPLETE.

PHASE 3 [L] -- solver-level distributed solve, NOT STARTED, SCOPED
ONLY (2026-08-28): the plan's original motivation for phase 1's Krylov
abstraction ("a Krylov method is the prerequisite for any GPU or MPI
solve, since those need a distributed/accelerated matvec + preconditioner
apply, not a distributed LU") is still just that -- a prerequisite, not
an implementation.  Distributing Device1D/2D/3D's OWN linear solve or
Newton assembly across MPI ranks (as opposed to the test-suite-level
process parallelism landed this session, which is unrelated tooling, not
a physics change) is a distinct, materially larger undertaking: it needs
a distributed sparse-matrix representation, a distributed preconditioner
apply, and a decision on domain decomposition for a 1D/2D/3D mesh.
Deferred to its own scoping session, same standing as phase 2 was before
this one.

------------------------------------------------------------------------
2. INTERFACE
------------------------------------------------------------------------
  solve_linear(A, b, *, method="direct", rtol=1e-10, atol=0.0,
               maxiter=500, x0=None) -> (x, info)

  method: "direct"   -- spsolve(A.tocsc(), b), EXACT, bit-identical to
                         every existing call site.
          "gmres"     -- scipy gmres with an ILU(A) right preconditioner.
          "bicgstab"  -- scipy bicgstab, same preconditioner.

  info: {"method", "iterations", "converged" (bool), "residual"
         (final ||Ax-b|| / ||b||)}.  A method other than "direct" that
  fails to converge within maxiter RAISES rather than returning a
  half-solved state silently -- the M15 debug pass found exactly that
  failure mode (a loop that stops and says nothing) and it is not
  repeated here.

  NewtonOptions gains `linsolve: str = "direct"` and `linsolve_rtol:
  float = 1e-10`.  Default is bit-identical to every pre-M22 solve;
  gate G1 proves it, not merely assumes it.

------------------------------------------------------------------------
3. QUANTITATIVE ACCEPTANCE GATES
------------------------------------------------------------------------
G1  DEFAULT BIT-IDENTITY: NewtonOptions() with no `linsolve` argument
    reproduces the M13 goldens (array_equal) on every device core.
G2  DIRECT-METHOD PARITY: solve_linear(A, b, method="direct") equals
    scipy.sparse.linalg.spsolve(A, b) bit for bit, for random sparse
    systems and for the Jacobians of the committed goldens.
G3  ITERATIVE PARITY: gmres/bicgstab solutions agree with the direct
    solution within `linsolve_rtol` (relative to ||x||), for random
    well-conditioned sparse systems AND for a real device Jacobian at
    equilibrium and at bias.
G4  CONVERGENCE HONESTY: an iterative method that does not converge
    within maxiter RAISES (pytest.raises), never returns silently.
G5  NON-FINITE / SINGULAR INPUT: a singular or non-finite system raises
    a clear error under every method, rather than returning NaN.
G6  3D SCALING: an iterative solve on the M22 target problem size
    (>=64k nodes, tridiagonal-block 3D resistor) COMPLETES, where
    "completes" means finite time and a residual gate -- not merely
    "does not crash".  Reported, not asserted as a hard wall-clock
    bound (machine-dependent).
G7  SUITE INVARIANT: full suite green, zero warnings, pre-existing
    tests UNCHANGED (only additive NewtonOptions field).

------------------------------------------------------------------------
4. AMENDMENT MECHANISM
------------------------------------------------------------------------
linsolve.py itself is a pure addition (no pytcad imports beyond scipy/
numpy) and needs none.  Wiring `NewtonOptions.linsolve` into
Device1D.solve_bias / Device2D / Device3D touches the core solve loop,
so it falls under the standing amendment rule: G1 (default bit-identity
against the committed goldens) is the required proof, run FIRST, before
any gate that exercises a non-default method.

------------------------------------------------------------------------
5. HONEST LIMITS
------------------------------------------------------------------------
- Preconditioner is ILU (spilu) only; pyamg (algebraic multigrid) is
  used when installed but is not required and not gated as present.
- Equilibrium's tridiagonal solve is untouched -- it was never the
  measured bottleneck (Thomas-algorithm-equivalent cost is already
  linear).
- No continuation driver yet (phase 2).
- "3D scaling" (G6) reports a number; it is not a promised wall-clock
  bound, which would be machine-dependent and not honestly gateable.


------------------------------------------------------------------------
6. IMPLEMENTATION RECORD (2026-08-27)
------------------------------------------------------------------------
LANDED: pytcad/linsolve.py (solve_linear: direct/gmres/bicgstab, ILU
with a 3-tier fallback tolerance chain, optional pyamg AMG when
installed); NewtonOptions gained linsolve/linsolve_rtol (default
"direct", proven bit-identical against the M13 goldens -- G1, run
first per the amendment rule); wired into the general (non-tridiagonal)
Newton solves in Device1D.solve_bias, Device2D and Device3D.
Equilibrium's tridiagonal solve is untouched (never the measured
bottleneck).

TWO FINDINGS DURING GATING, BOTH FIXED:
 - Default ILU parameters (drop_tol=1e-5, fill_factor=10) came back
   "Factor is exactly singular" on a REAL device Jacobian (not a
   synthetic test system) -- these rows mix psi/n/p unknowns spanning
   many orders of magnitude in scaled units, which measurably breaks a
   single fixed drop tolerance.  Fixed with a 3-tier fallback
   (1e-5/10, 1e-7/30, 1e-9/50); if all three fail, _build_preconditioner
   returns None rather than raising -- a missing preconditioner is a
   PERFORMANCE issue (Krylov still converges, slower), not a
   correctness one, and G4's convergence-honesty check is what actually
   guards correctness.
 - scipy's gmres default restart=20 stalled completely (zero visible
   progress in 500 iterations) on a 207k-unknown coupled Jacobian.
   Added an explicit `restart` parameter, defaulted to
   min(100, problem size).

G6 OPEN: raising `restart` fixed the STALL but not the underlying
inadequacy -- with ILU-only preconditioning, GMRES did not converge in
15 minutes even at n=20 (9261 nodes, 27783 unknowns), three orders
below the plan's 64k-node target.  This is the expected failure mode of
scalar ILU on a strongly coupled multi-physics Jacobian: ILU treats the
matrix as one undifferentiated block, but the psi/n/p rows have very
different scales and coupling structure.  The real fix is either (a)
block-structured preconditioning that respects the 3-unknown-per-node
structure, or (b) genuine algebraic multigrid (pyamg is wired as an
optional dependency already, but was not installed to test against).
Neither is phase-1 scope; recorded here rather than silently declared
done.  test_3d_scaling_target_completes is xfail with this reason, not
skipped or commented out.


------------------------------------------------------------------------
6. G6 RESOLUTION (2026-08-27, same session as the G6-open finding)
------------------------------------------------------------------------
ROOT CAUSE: scalar ILU treats the Jacobian as one undifferentiated
sparse block and ignores the per-node (psi, n, p) interleaving every
device core in this tree uses (`du[0::3], du[1::3], du[2::3]` in every
solve_bias).  On the coupled 3D Jacobian this left GMRES making NO
visible progress in 500 iterations even at n=20 (27783 unknowns).

FIX: pytcad/linsolve.py gained a node-block-Jacobi preconditioner
(_build_block_jacobi_preconditioner): each node's small dense diagonal
block is extracted (vectorized across all nodes, no per-node Python
loop) and inverted directly; GMRES/BiCGStab precondition with the
resulting block-diagonal operator.  solve_linear gained a `block_size`
parameter (None by default -- unchanged behavior for any caller that
does not opt in); all three device cores now pass block_size=3 at
their bias-solve call site.  This is the standard fix for exactly this
failure mode in multiphysics PDE systems (nodal/point-block Jacobi;
see section 7) and required no new dependency.

MEASURED: the SAME 27783-unknown Jacobian that stalled scalar ILU
converges in 30 iterations / 0.05s with block-Jacobi.  The full G6
target (>=64k nodes) now runs end to end: 68921 nodes (206763
unknowns), full bias solve in 4.71s.  G1 (default bit-identity) and G3
(iterative parity) re-verified green after the wiring change --
block_size=None (the default) leaves every pre-existing call site
untouched.

------------------------------------------------------------------------
7. LITERATURE (2026-08-27, informed the G6 fix)
------------------------------------------------------------------------
Searched for recent (2025-2026) work on preconditioning coupled
Poisson/drift-diffusion Newton-Krylov systems.  Two sources were
directly load-bearing for the fix above:
  - A 2025 arXiv preprint on hybrid-precision block-Jacobi
    preconditioned GMRES for circuit simulation confirms block-Jacobi
    grouped by the natural per-node/per-element variable structure is
    the standard technique for exactly this class of coupled system,
    and explicitly notes its applicability to a 3-unknown-per-node
    (potential, electron density, hole density) device Jacobian.
  - Sandia-line work on algebraic-multigrid preconditioners for the
    coupled Poisson/electron/hole drift-diffusion system (2008-era,
    still the reference point cited by later work) frames the same
    problem as "a source-term-dominated Poisson equation coupled to
    two convection-diffusion-reaction equations" and reports that
    approximate block-factorization / Schur-complement preconditioners
    that respect this structure scale where scalar/point AMG on the
    undifferentiated system does not -- the same qualitative lesson
    the block-Jacobi fix above demonstrates at smaller scale.
  Neither source was fetchable in full (paywall/binary-PDF extraction
  failure on the Sandia work); the technique was corroborated
  independently by direct numerical experiment on this codebase's own
  Jacobian (section 6) rather than taken on citation alone.

NOT YET DONE, flagged for a future session: a Schur-complement variant
(explicitly eliminating the Poisson block first, since it is the
"stiffest" equation) is the literature's next step beyond plain
block-Jacobi and may reduce iteration counts further at larger scale;
not attempted here since block-Jacobi alone already met the G6 target.

------------------------------------------------------------------------
8. G2 BUG: "direct" WAS NOT ACTUALLY BIT-IDENTICAL (2026-08-27)
------------------------------------------------------------------------
Found while routing the four Poisson-only equilibrium spsolve() calls
(device.py, device2d.py, device3d.py, moscap.py) through
solve_linear(method="direct") for the finiteness/singularity checks
every coupled bias-solve already got -- every one of the M13/M22
bit-identity equilibrium goldens broke (test_golden_1d_diode_
equilibrium_and_bias, test_golden_1d_hetero_equilibrium,
test_g6c_tat_path_bit_identity, test_default_linsolve_is_bit_identical_
to_pre_m22), plus the M15 G-D breakdown-detection test (its trajectory
is sensitive to the exact equilibrium starting point).

ROOT CAUSE: solve_linear's "direct" branch did
`A = A.tocsr() if not sp.issparse(A) else A.tocsr()` (top of function,
all methods) then `spsolve(A.tocsc(), b)` -- i.e. it always reformatted
A to CSC before calling spsolve, regardless of the format the caller
originally built. scipy's SuperLU wrapper does NOT treat this as
equivalent: it solves a CSR input NATIVELY via a format flag passed
into the C extension (`_superlu.gssv(..., flag, ...)`), rather than
converting to CSC first in Python. Confirmed empirically:
`spsolve(A_csr, b)` and `spsolve(A_csr.tocsc(), b)` on an identical
matrix differ at ~1e-16 relative error -- correct to within floating-
point tolerance, but NOT bit-identical, which is exactly what G2
requires and what the module's own docstring promises ("EXACTLY
scipy.sparse.linalg.spsolve -- bit-identical to every pre-M22 call
site"). Every pre-M22 call site called plain `spsolve(A, ...)` on
whatever format it already had (some built A as CSR, e.g. device.py's
equilibrium Jacobian; others already called `.tocsc()` themselves
before spsolve) -- the honest bit-identical contract is "spsolve on the
SAME format the caller passed," not "spsolve on a canonicalized copy."

FIX: `solve_linear(method="direct")` no longer reformats A at all -- it
passes the object through to spsolve exactly as the caller supplied it.
Only "gmres"/"bicgstab" still normalize to CSR (harmless there: those
are gated by rtol, not bit-identity). The four re-routed equilibrium
call sites keep passing A in whatever format they always built it in
(some already `.tocsc()`'d, matching their original raw-spsolve calls
exactly), so they stay genuinely bit-identical now.

A second, related bug fixed in the same pass: the SAME broken ternary
(`A.tocsr() if not sp.issparse(A) else A.tocsr()` -- both branches call
`.tocsr()`, which a plain ndarray does not have) was carried into the
new iterative-branch normalization when refactoring; fixed to
`sp.csr_matrix(A) if not sp.issparse(A) else A.tocsr()` so a dense
input no longer raises AttributeError.

The test suite's own G2 gate (test_m22_linsolve.py::
test_direct_method_matches_spsolve_bit_for_bit) had the identical bug
baked into its reference computation (`ref = spsolve(A.tocsc(), b)`
regardless of A's real format) -- it was silently validating the WRONG
contract the whole time. Corrected to `ref = spsolve(A, b)`.

Lesson generalized into AGENTS.md's gotchas: a linear-solve wrapper
that claims bit-identity to a bare library call must never reformat the
input for that path, because "equivalent" solvers on different sparse
formats are not eviction-order/pivot-order identical even when both
are numerically correct.
