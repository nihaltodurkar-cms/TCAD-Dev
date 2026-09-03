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
PLAN.md).  **PHASE 3 LANDED 2026-09-02** as MPI Schwarz domain
decomposition (a different design than this section's original
"distributed matrix" sketch -- see section 9 for the full record,
including a real regression found and gated against before it shipped)
-- plus, in the same session, two GPU/CPU preconditioner wins for the
GUI's own 3D solve path that section 9 also covers: pyamg-backed AMG
for the equilibrium Poisson solve, and a CUDA (CuPy/cuSOLVER) direct
solve for the bias/sweep Newton loop. **GENERALIZED 2026-09-02** (same
day, section 10) from an x-only split to picking whichever mesh axis
(x/y/z) a device's doping is actually safe to split along -- this is
what brought pn_junction_3d (previously refused outright) onto the
MPI path via a z-split, 1.5x over its single-process AMG+GPU baseline.

Roadmap slot: ARCHITECTURE.md section 4b.2, "M22 LINEAR SOLVER
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

PHASE 3 [L] -- solver-level distributed solve, LANDED 2026-09-02 as
MPI SCHWARZ DOMAIN DECOMPOSITION, not the distributed-matrix design
this section originally sketched: this plan's original motivation for
phase 1's Krylov abstraction ("a Krylov method is the prerequisite for
any GPU or MPI solve, since those need a distributed/accelerated
matvec + preconditioner apply, not a distributed LU") turned out not
to be the path actually taken. A genuine distributed sparse matrix
(PETSc-style) was ruled out as a materially larger undertaking than
this session's time warranted; overlapping ADDITIVE SCHWARZ -- split
the mesh into N overlapping subdomains, solve each with the ordinary
(already-fast) direct solve, exchange one interior column of state
with each neighbor, repeat until the core region stops changing -- is
a real, working alternative that needed no distributed-matrix
machinery at all, just a new boundary-condition type (Device3D.PinnedBC)
to pin an artificial Schwarz interface to a neighbor's current state.
See section 9 for the full record: what was measured, a real
regression this caught before it shipped, and where it's gated in
gui/services/solver_runner.py. Distributing Device1D/2D/3D's OWN
linear solve/Newton assembly via a genuinely distributed matrix (as
opposed to Schwarz's independent-subdomain-solves design, or the
test-suite-level process parallelism landed 2026-08-28, which is
unrelated tooling, not a physics change) remains undone and would
still be the larger undertaking this section always said it was, if a
future session wants that different design instead.

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

--> LANDED 2026-08-29 (session noted "implement M22 and complete it"):
pytcad/linsolve.py gained `_build_schur_preconditioner` +
`solve_linear(precond="schur")`.  Design: permute the interleaved
(psi,n,p) unknowns to equation-major order, factor the block-LOWER-
TRIANGULAR approximation M = [[A_pp,0,0],[A_np,D_nn,0],[A_qp,0,D_qq]]
-- A_pp (Poisson, the stiffest equation) applied via spilu on the
permuted Poisson block alone (far better conditioned than the coupled
matrix), D_nn/D_qq the per-node density diagonals; the (n,p) cross-
couplings are dropped (the outer Krylov absorbs them), which is the
standard price of an approximate block factorization.  `precond`
defaults to "auto" = the exact M22 phase-1 node block-Jacobi behavior,
unchanged -- every existing call site and the G6 gate are untouched;
"schur" is strictly opt-in per call.  Invalid `precond` raises
ValueError (a typo must not silently fall through to ILU).  Gates
appended to tests/test_m22_linsolve.py: exact-apply check against a
dense assembly of M itself (diagonal A_pp so the ILU is exact and the
comparison closed-form), parity vs direct on a real Device1D Jacobian,
convergence on the 27783-unknown coupled 3D Jacobian (budget 150
iterations vs block-Jacobi's 100), default-is-unchanged operator
identity (auto == block_jacobi, and both differ from schur), and
structural refusal (block_size != 3 returns None, caller falls through
the chain).  NOT wired into NewtonOptions/the device cores: that would
be a core-touching change under the amendment rule for a performance
option whose benefit over block-Jacobi is not yet measured on this
codebase -- a future session can add `NewtonOptions.linsolve_precond`
once the iteration-count comparison is actually run.  SUITE NOT RUN
THIS SESSION (user explicitly deferred test execution); the gates are
written but UNVERIFIED -- treat M22-Schur as landed-pending-verification,
same standing M16 had in Addendum 16.

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

------------------------------------------------------------------------
9. PHASE 3 LANDED + TWO GPU/CPU PRECONDITIONER WINS (2026-09-02)
------------------------------------------------------------------------
Three separate additions to the GUI's 3D solve path
(gui/services/solver_runner.py's run_job(), pytcad/linsolve.py,
pytcad/device3d.py), each gated by measurement, none touching any
existing call site's default behavior:

A. EQUILIBRIUM: AMG-preconditioned bicgstab. Device3D.solve_equilibrium
   previously hardcoded method="direct" -- opts.linsolve reached
   solve_bias but never equilibrium at all. Wired through, with a
   try/fall-back-to-direct wrapper on LinearSolveError (mirrors
   solve_bias's own contract exactly). MEASURED on real 3D examples:
   bicgstab+pyamg cuts bjt_3d's equilibrium from 43.4s to 1.0s (44x),
   pn_junction_3d 31.1s to 0.8s (39x), finfet_3d 33.1s to 4.0s (8x) --
   all agreeing with the direct solve to ~1e-17 relative error. But the
   SAME setting made a SMALLER mesh slower: mosfet_3d's ~15.8k-node
   equilibrium went 2.1s -> 21.4s (AMG hierarchy setup cost that only
   pays for itself once direct factorization is already expensive).
   20,000 nodes (mosfet_3d below, bjt_3d/finfet_3d/pn_junction_3d
   above) is the measured switch. Also gated on pyamg actually being
   installed: bicgstab with only ILU (no pyamg) does NOT reliably
   converge across a full equilibrium trajectory -- confirmed directly,
   it made bjt_3d's equilibrium SLOWER (79-83s) than plain direct
   (41s) by repeatedly trying and failing before the fallback kicked
   in. Separately, installing pyamg alone (no code change) broke a
   PRE-EXISTING test (test_iterative_methods_on_a_real_device_jacobian):
   pyamg's Ruge-Stuben coarsening can succeed (no exception) while
   producing a degenerate hierarchy for a matrix it isn't suited to
   (an interleaved multi-physics system with no block_size given),
   which only surfaced as NaN later when the preconditioner was
   actually applied -- past this function's own try/except. Fixed by
   probing the built preconditioner with one matvec on an all-ones
   vector before ever returning it (_build_preconditioner in
   linsolve.py), falling through to ILU on a non-finite result exactly
   like a construction-time exception already did.

B. BIAS/SWEEP: GPU direct solve (cuSOLVER via CuPy). solve_bias's
   block-Jacobi-preconditioned iterative path (gmres/bicgstab) does
   NOT reliably converge on the coupled psi/n/p Jacobian -- confirmed
   directly, tried block-Jacobi, Schur (_build_schur_preconditioner
   REFUSES to build at all on bjt_3d's Jacobian: RuntimeError "Factor
   is exactly singular" factoring the isolated Poisson block, in
   ~1s -- a structural refusal, not a slow convergence), and AMG (also
   fails to converge on the full coupled system, and in one attempt
   hung for 17+ minutes rather than erroring out) -- so there is no
   iterative bias solver worth defaulting to. A DIRECT solve run on
   the GPU sidesteps the convergence question entirely: added
   method="gpu_direct" to linsolve.py (cupyx.scipy.sparse.linalg.spsolve),
   same LinearSolveError/fallback contract as everything else.
   MEASURED on bjt_3d's real 121,824-unknown bias Jacobian, full
   multi-iteration solve_bias trajectory (not one sample matrix): 2.8x
   faster than scipy spsolve (128.3s -> 46.1s), agreeing with the CPU
   result to ~1e-17 relative error. But GPU transfer/kernel-launch
   overhead doesn't amortize on a small matrix: measured 0.4x-0.7x
   (SLOWER) on resistor_3d/moscap_3d/jfet_3d's few-thousand-unknown
   Jacobians, ~1.1x (break-even) at mosfet_3d's 47,304, a clear win
   from pn_junction_3d's 99,360 up -- the SAME 20,000-node threshold as
   (A) happens to land in the right place for this too, so it is
   reused rather than inventing a second unvalidated constant. Also
   gated on cupy being installed (requirements.txt documents the
   install command; it is deliberately NOT an unconditional line
   there, since the package name is CUDA-toolkit-version-specific and
   `pip install -r requirements.txt` must not fail on a machine with
   no matching wheel).

C. PHASE 3 ITSELF: MPI Schwarz domain decomposition
   (gui/services/mpi_schwarz_runner.py). Splits the mesh into 4
   overlapping x-slabs, each rank solves its own slab with the
   ordinary direct solve, ranks exchange one interior column of
   psi/n/p with their neighbor via mpi4py after each local solve,
   repeats until the core region stops changing. A NEW boundary-
   condition type was needed and added: Device3D.PinnedBC (device3d.py)
   pins psi/n/p directly to given per-node values -- unlike the
   existing DirichletBC, which derives them from a contact voltage via
   the equilibrium ohmic relations -- for the artificial interior
   interface a Schwarz split creates. Purely additive: wired into both
   _residual_jacobian_poisson and _residual_jacobian's existing
   contact-row-replacement code paths (same treatment as DirichletBC),
   and into solve_bias's initial-guess setup; nothing else changes
   when no PinnedBC exists in a device's bcs dict.

   A SECOND core addition, caught by careful checking BEFORE any
   correctness testing, not discovered by a failure: Device3D derives
   its ENTIRE dimensionless scaling (Ns, LD, J0, and even the mesh
   coordinates themselves -- xs = mesh.x / LD) from max(|doping|) of
   whatever array it's built with. Two ranks seeing different SLICES
   of a device whose doping varies along the split axis would derive
   DIFFERENT LD/Ns and silently disagree on units -- every downstream
   quantity, not just the obviously-doping-dependent ones. Fixed by
   adding Device3D(..., Ns_override=None): every rank's local device is
   built with Ns_override pinned to the FULL device's own
   max(|doping|), computed once from the complete array. Default None
   is bit-identical to every existing construction site.

   MEASURED on bjt_3d (a genuinely different geometry+contact layout
   than the M22 gates above were validated on -- three ohmic contacts,
   each spanning the FULL x-extent, vs. those gates' simpler
   two-terminal test devices): 4 ranks, 2 Schwarz sweeps to
   convergence, 31.09s vs. this same job's 158.6s single-process
   baseline (5.1x) -- and FASTER than that job's own GPU-accelerated
   single-process result (48.0s) -- exact to a relative L2 error of
   1.56e-17 against the plain single-process reference. Verified
   through the REAL gui/services/job_runner.py-equivalent CLI path
   (`python -m gui.services.solver_runner job.json out.npz`), not just
   a standalone script: run_job() spawns `mpirun -np 4 ... -m
   gui.services.mpi_schwarz_runner` as a subprocess and relays rank 0's
   stdout through its own, so JobRunner's existing PYTCAD_STAGE regex
   parsing sees the same markers live and neither JobRunner nor
   AppController needed to change at all. Also checked 6 ranks (18.1s,
   same 2-sweep/machine-precision result) -- capped at 4 by explicit
   decision, not a technical limit.

   A REAL REGRESSION, FOUND AND GATED AGAINST BEFORE SHIPPING, not
   merely "unverified": bjt_3d's clean 2-sweep result is specific to
   its doping being CONSTANT along x (the split axis) -- every rank's
   subdomain is a near-identical copy of the others. Tried the same
   split on pn_junction_3d, whose doping IS the thing varying along x
   (the junction itself): a middle rank's per-sweep bias solve took
   39-45s (vs. bjt_3d's ~5s), and the run had not converged after 2
   sweeps at the point bjt_3d always finishes by -- killed rather than
   let run to an unknown, possibly multi-minute completion, which would
   have been dramatically WORSE than that job's already-working ~34s
   single-process AMG+GPU result. run_job() now computes, directly on
   the real doping array (not a device-name list), whether doping
   varies by more than 1% of its own range along x, and refuses the
   MPI path entirely otherwise -- confirmed bjt_3d still routes to MPI
   (safe, ratio 0.0) and pn_junction_3d correctly falls through to the
   single-process AMG+GPU path instead (safe fallback, ratio 1.001,
   completes in 33.6s as expected). mosfet_3d/finfet_3d's source-
   channel-drain doping profile would fail the same check for the same
   reason and has not been separately tried.

   v1 SCOPE, NOT YET DONE: equilibrium + a single bias point only --
   spec.sweep/spec.transient both fall back to the plain single-process
   path regardless of mesh size (a sweep re-runs the whole Newton
   trajectory at many points; re-running the ENTIRE Schwarz loop that
   many times is a distinct, unexercised cost/convergence question).
   Terminal current correctness for the MPI path is NOT computed via
   any per-rank summation -- deliberately avoided as a likely source of
   double-counting bugs at the overlap -- instead the reassembled
   global psi/n/p is loaded onto one final, ordinary (unsplit)
   Device3D and extract_result() runs on it completely unchanged,
   which is also why terminal__<contact>__value came out correct
   (verified against the reference) without any new summation logic to
   audit.

   ONE MORE BUG, CAUGHT BY RUNNING THE FULL SUITE BEFORE CALLING THIS
   DONE (not by inspection): the x-doping-variation safety check above
   computed `doping.max(axis=2)` unconditionally, before checking
   dimensionality -- broke EVERY 1D/2D gui/tests job (AxisError: a 1D
   doping array has no axis 2 at all), which is most of the suite.
   Fixed by moving the computation inside the `if is_large_3d:` guard,
   which already implies dimensionality == 3. gui/tests: 590 passed
   after the fix (none passed silently-wrong before it -- the bug
   crashed every affected job outright, which is why it surfaced
   immediately rather than needing separate scrutiny).

------------------------------------------------------------------------
10. PHASE 3 GENERALIZED PAST X-ONLY: PICK THE SAFE AXIS (2026-09-02)
------------------------------------------------------------------------
Section 9C's safety check refused the WHOLE MPI path for any device
whose doping varies along x -- correct as a safety gate, but it meant
mosfet_3d/finfet_3d (S/D/gate localized along x) and, worse,
pn_junction_3d (the junction itself sits on x) got NO speedup at all,
even though several of these devices are perfectly uniform along a
DIFFERENT axis (device width, typically z or y). Generalized rather
than hard-coded to x:

- solver_runner.py's new _pick_mpi_split_axis(doping) checks all
  three array axes (x=2, y=1, z=0) with the SAME <=1%-of-range
  variation test section 9C already validated, and a minimum-node-
  count floor (2 per rank) so a degenerate axis can't be picked just
  because it happens to be flat. Among the axes that pass, picks the
  one with the most nodes (best parallelization headroom). Returns
  (None, None) -- same as before -- when no axis is safe.
- The chosen axis name is threaded through as a THIRD CLI arg to
  mpi_schwarz_runner.py (`... job.json out.npz <axis>`), rather than
  re-derived per rank: every rank must agree on the same choice, and
  _pick_mpi_split_axis's node-count tie-break must run exactly once.
- mpi_schwarz_runner.py's split/exchange/reassembly logic (previously
  hard-coded to array axis 2 / contact key "i") is now parameterized
  on (array_axis, key): _split_x -> _split_axis_range, _face_nodes and
  the psi/n/p exchange use a generic _take(arr, axis, index) helper,
  and _build_local_device slices whichever mesh axis (x/y/z) and
  ContactSpec node key (i/j/k) the chosen split axis corresponds to.
  record__meta.numerics now also carries "mpi_split_axis".

MEASURED, both regression and new-capability checks, through the real
CLI (`python -m gui.services.solver_runner job.json out.npz`), not a
standalone script:

- bjt_3d (still picks x, same as section 9C): unchanged, 32.5s,
  identical result -- confirms the generalization is a no-op for the
  one case already shipped.
- pn_junction_3d: _pick_mpi_split_axis now finds z safe (the junction
  varies along x and y, but this device's mesh is uniform along z) --
  previously REFUSED entirely by the x-only check. MPI z-split: 21.8s
  vs. a 32.6s single-process (AMG+GPU) reference, 1.5x, agreeing to a
  relative L2 error of 5.0e-18 (potential), 2.9e-19 (electrons),
  4.6e-17 (holes) -- no runaway convergence like the x-split attempt
  in section 9C, because z genuinely has none of the doping gradient
  the junction sits on.
- finfet_3d also newly qualifies (z-safe) at its current mesh size,
  though it sits below the 20,000-node is_large_3d gate at the
  reduced example size chosen for interactive runtime, so it does not
  currently route through MPI at all regardless of axis -- checked via
  _pick_mpi_split_axis directly, not run end-to-end.
- mosfet_3d/moscap_3d/jfet_3d also produce a valid split-axis choice
  (moscap_3d: y; jfet_3d: x; mosfet_3d: z) but all three sit below the
  20,000-node gate at their current example sizes, so this is a
  latent capability (correct if/when a larger mesh crosses that
  threshold), not something exercised end-to-end here.

Full regression check: tests/ (365 passed, 1 xfailed -- pre-existing,
unrelated) and gui/tests (590 passed) both green after this change,
same totals as section 9C's own verification.

------------------------------------------------------------------------
11. MPI SCHWARZ SWEEP SUPPORT LANDED (2026-09-04)
------------------------------------------------------------------------
Section 9C's MPI Schwarz path was v1-scoped to equilibrium + a single
bias point only; a voltage sweep always fell back to the plain single-
process path regardless of mesh size. Extended run_job()'s gate to also
route a sweep through MPI Schwarz (transient remains excluded --
Device3D has no transient module at all, so there is nothing to
parallelize there).

DESIGN: gui/services/mpi_schwarz_runner.py's per-rank exchange/
convergence loop was factored into a reusable _schwarz_loop(solve_fn)
helper (byte-identical behavior verified on bjt_3d's single-bias-point
path both before and after this refactor -- 0.0 diff, same 32.5s wall
time), then reused for a new _run_sweep(): a pure-equilibrium Schwarz
solve establishes the warm-start baseline, then each sweep point re-
runs the Schwarz loop with a bias-only solve_fn that SKIPS
solve_equilibrium entirely and starts Newton from the PREVIOUS point's
converged per-rank psi/n/p (Device3D.solve_bias already warm-starts
from self.psi/n/p when set) -- the same warm-started-ramp idea
solver_runner.run_sweep()'s single-process path already uses, just
applied per rank. Terminal currents and 3D snapshot fields (the sweep-
playback dock) are computed per point via the SAME reassemble-to-one-
global-Device3D-and-call-extract_result() design the single-bias-point
path always used -- no new current-summation logic to audit.

MEASURED on bjt_3d (a 3-point collector sweep, 0.0/0.1/0.2 V, base held
at 0V, x-split -- the same geometry section 9C validated), through the
real CLI end to end: MPI Schwarz sweep 258.1s vs. a 699.3s single-
process reference (2.7x). Correctness: sweep__voltage and
sweep__converged (all 3 points) match exactly; 3D snapshot fields
(potential/electron_density/hole_density) for ALL THREE points agree
to ~1.1e-16 absolute (machine precision) between the two paths.
Terminal collector current shows large RELATIVE error at low bias
(158% at V=0.0) but the absolute difference is 5.4e-21 A -- both
values are sub-attoamp noise-floor numbers, expected physics for an
unbiased base junction, not a correctness signal; relative error on a
quantity whose true value is ~0 is not a meaningful metric. At V=0.2
(the largest current in this sweep) the values agree to 1.4e-5
relative error.

No automated regression test exists for this path specifically (same
as section 9C's single-bias-point path) -- verified the same way that
one was, by direct comparison through the real CLI against a genuine
single-process reference, not just inspection.

------------------------------------------------------------------------
12. A GENUINE CORRECTNESS BUG FOUND BY EXERCISING THE LATENT AXIS
    CHOICES END TO END (2026-09-04)
------------------------------------------------------------------------
Section 10 noted finfet_3d/mosfet_3d/moscap_3d/jfet_3d all now produce
a valid non-x split-axis choice but were never run end to end -- only
checked via _pick_mpi_split_axis() directly. finfet_3d actually sits
ABOVE the 20,000-node is_large_3d gate (38,976 nodes; the earlier
section 10 note that it "sits below" the gate was WRONG -- corrected
here), so it was ALREADY silently routing through MPI Schwarz in
production, unverified, via a z-split.

Ran it end to end through the real CLI: MPI Schwarz took 157s vs. a
38.3s single-process (AMG+GPU) reference -- a REAL REGRESSION (4.1x
SLOWER), not just unverified. Worse: the result was also WRONG, not
merely slow -- 1.4e-3 relative L2 error on potential, 7.1e-4 on
electron density, vs. the ~1e-17 machine-precision agreement bjt_3d/
pn_junction_3d's verified MPI paths always show. This would have
shipped a silently-wrong, silently-slower result for any FinFET-shaped
device above the size gate.

ROOT CAUSE, confirmed directly: finfet_3d's side gates have
`normal_axis="z"` -- the exact axis _pick_mpi_split_axis() chose,
because that axis genuinely passed the DOPING-uniformity test (the
device really is doping-uniform along z). But a GateBC's Robin/oxide-
coupling term runs along its own normal_axis regardless of doping --
this is a field-curvature mechanism from geometric/electrostatic gate
confinement, structurally different from a doping gradient, and the
doping-only check has no way to see it. bjt_3d/pn_junction_3d have no
gates at all, which is why their MPI paths were never exposed to this
failure mode.

FIX: _pick_mpi_split_axis(doping, spec) now also excludes any axis
matching a registered GateBC's normal_axis, regardless of that axis's
doping-variation score. Re-checked every 3D example after the fix:
bjt_3d still picks x (no gates, unaffected, still 30.3s/exact match),
pn_junction_3d still picks z (no gates, unaffected), finfet_3d now
correctly returns (None, None) -- gate normal_axes {y, z} exclude two
candidates outright and x fails the doping-variation test on its own,
leaving no safe axis -- and falls back to the single-process AMG+GPU
path: re-run end to end, 43.3s, EXACT match (0.0 max abs diff) against
the single-process reference. mosfet_3d/moscap_3d (both have a y-axis
gate) and jfet_3d (its "gate" is modeled as a plain ohmic contact, no
GateBC, so unaffected by this fix) all re-checked directly via
_pick_mpi_split_axis() too, though none currently cross the 20,000-
node gate at their example sizes so this is not exercised end to end
for them.

Full regression check: gui/tests 608 passed (unchanged from before
this fix) -- the fix only removes candidate axes, it adds no new code
path any existing test could have exercised differently.

Lesson generalized into this section's own record (not yet promoted to
AGENTS.md, since this is still local to MPI Schwarz's axis-selection
logic specifically): a safety gate built from ONE physical mechanism
(here, doping gradients) does not automatically cover a DIFFERENT
mechanism that happens to correlate with the same axis (here, gate
electrostatics) -- each new hazard needs its own explicit check, not
an assumption that the existing one already covers it.
