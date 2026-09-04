# M21-MESHING-PLAN.md
# M21: Solution-driven adaptive meshing (h-refinement)
# Formal milestone spec

Status: **PHASES 1-2 IMPLEMENTED, GATES GREEN.**  pytcad/adapt.py plus
tests/test_m21_adapt.py (17 tests, phase 1) and tests/test_m21_phase2.py
(25 tests, phase 2, 2026-08-28).  Phase 3's geometry foundation shipped
2026-08-31 (gmsh_mesh.py/region_resolver.py/unstructured_assembly.py,
14 tests). [Update, same day: the coupled-physics assembly (3b Poisson
equilibrium G1-G3, 3c coupled bias solve G1/G4/G5, 3d
`Device2D(unstructured=True)` integration) also SHIPPED 2026-08-31 --
M21 Phase 3 is now COMPLETE end to end; see
M21-PHASE3-MESHING-PLAN.md's own status line, which supersedes the
"not started" note this sentence originally made.]  Section 10
records the decisions taken; section 11 records what phase 1's
implementation changed about the design and what it found; section 13
records phase 2's hard-debug pass -- six real bugs found and fixed,
including one that had been silently breaking phase 1 too.

Roadmap slot: ARCHITECTURE.md section 4b.2, "M21 GENERAL 2D
MESHING + FV ASSEMBLY [XL]".  That entry bundles four separable pieces
(optional-dependency meshers; Delaunay FV assembly; solution-driven
adaptive refinement; tensor-product-as-special-case).  This plan
PHASES them (section 1) so the refinement machinery -- the part that
delivers user-visible value -- can land as a pure addition, well before
the unstructured-geometry work.

Blocks: nothing declares itself blocked on M21.
Depends: parity plan says "nothing hard, but do AFTER Tier 1 (physics
first)".  See section 9 for the rule-4b position, which is a decision
for the user, not for this document.

------------------------------------------------------------------------
1. SCOPE AND PHASING
------------------------------------------------------------------------
PHASE 1 [S] -- 1D solution-driven h-refinement on structured meshes.
  A refinement DRIVER that: solves on a starting mesh, computes per-cell
  error indicators from the converged solution, marks and bisects cells,
  rebuilds the mesh under the existing grading invariant, constructs a
  NEW Device1D, and re-solves -- iterating to a convergence criterion on
  a scalar quantity of interest.
  CRITICAL PROPERTY: this touches NO residual and NO Jacobian.  It is a
  pure addition (new module + driver) that consumes the existing solver
  through its public interface.  No amendment is required (section 6).

PHASE 2 [M] -- 2D/3D separable refinement on tensor-product meshes.
  The same indicators reduced onto each axis; x and y (and z) node sets
  refined independently.  Still tensor-product, still the existing
  Device2D/Device3D.  Also a pure addition.
  Its honest limitation is structural and must ship stated: refining one
  cell refines an entire row/column, so a localised 2D feature costs
  O(N) nodes it does not need.  That waste is precisely the motivation
  for phase 3 and must not be hidden.

PHASE 3 [XL] -- general unstructured 2D + Delaunay FV assembly.
  M21 as originally written: optional-dependency meshers (triangle /
  gmsh), box integration on general meshes, tensor-product assembly
  demoted to a special case.  This DOES modify the core assembly and DOES
  require the amendment mechanism.  Out of scope for this plan beyond
  section 8's statement of what it will need; it gets its own spec.

Out of scope for all phases: p-refinement; r-refinement (node motion);
moving boundaries / process simulation (M23); a posteriori error
estimators with proven effectivity bounds -- our indicators are
heuristic and are gated as heuristics (section 4, G4).

------------------------------------------------------------------------
2. NEW MODULE: pytcad/adapt.py  (pure functions, no core dependency)
------------------------------------------------------------------------
Layering: adapt.py may import mesh.py and numpy.  It MUST NOT be
imported BY device.py / device2d.py / device3d.py -- the dependency
points one way, driver -> core, exactly as workbench -> pytcad.

  indicator_debye(x, doping, T)        -> per-cell h / L_D
  indicator_curvature(x, u)            -> per-cell |second difference|
                                          of a nodal field, scaled
  indicator_log_density(x, n, p)       -> per-cell |d ln n|, |d ln p|
                                          (densities span ~20 decades;
                                          linear gradients are useless)
  indicator_rate(x, rate, dV)          -> per-cell share of a volumetric
                                          rate (SRH R, or the M15 II
                                          generation gs) -- resolves the
                                          generation peak that M15's own
                                          debug pass showed sits within
                                          a few cells of the junction
  combine(indicators, weights)         -> normalised per-cell scalar
  mark_dorfler(eta, theta=0.5)         -> indices carrying theta of the
                                          total indicator mass
  refine_1d(x, marked, ratio=1.2,
            max_nodes=None)            -> bisected, grading-limited mesh

All pure: array in, array out, no solver state, no I/O.

------------------------------------------------------------------------
3. DRIVER
------------------------------------------------------------------------
  adapt_solve_1d(build_device, x0, *, qoi, max_passes=6, tol=1e-3,
                 theta=0.5, max_nodes=20000, weights=None)

`build_device(x) -> Device1D` is supplied by the caller, so the driver
never owns doping, materials or Models -- it cannot silently drop a
physics flag (gate G7).  Returns (device, mesh, history) where history
records per pass: node count, QoI, indicator mass, and the marked
fraction.  History is the evidence the convergence gate reads; it is
part of the contract, not debug output.

Termination: |QoI_k - QoI_{k-1}| / |QoI_k| <= tol, OR max_passes, OR
max_nodes reached.  Which one fired is RECORDED in history and, if it
is not the tolerance, WARNED -- a budget-limited result must never be
presented as a converged one.  (This is the same discipline the M15
debug pass had to retrofit: a loop that stops early and says nothing
is a hidden failure.)

------------------------------------------------------------------------
4. QUANTITATIVE ACCEPTANCE GATES
------------------------------------------------------------------------
Every gate is a named test in tests/test_m21_adapt.py, written RED
first.  "Mostly green" is not green (standing rule 4b).

G1  INDICATOR CORRECTNESS: each indicator is verified against an
    analytic case -- curvature on a known cubic recovers the exact
    second derivative to <= 1e-10 relative; log-density on an
    exponential profile recovers the exact decay constant; debye
    reproduces check_mesh's ratio exactly (array_equal).

G2  NO-OP BIT-IDENTITY: on a mesh that already satisfies every
    criterion, the driver returns the SAME mesh (array_equal) and the
    SAME solution (array_equal) as a direct solve.  Adaptive machinery
    must be inert when there is nothing to do.

G3  GOLDEN PARITY (standing rule 3): the adapted solution of the
    committed 1D diode agrees with the committed graded-mesh golden
    within stated discretisation error, on BOTH terminal current and
    the depletion-edge potential.  Rule 3 requires this before anything
    downstream uses adaptive meshes.

G4  MONOTONE CONVERGENCE: for the 1D diode at equilibrium and at
    forward bias, |QoI_k - QoI_{k-1}| is strictly decreasing across
    passes, and the sequence is Cauchy to `tol`.  The parity plan names
    this explicitly ("refinement converges monotonically").

G5  ORDER OF ACCURACY: on a case with an analytic solution (uniform
    resistor), the error against the analytic value falls at the
    box-scheme's second-order rate within a stated band, under uniform
    bisection.  This is what distinguishes a working indicator from one
    that merely adds nodes.

G6  INVARIANTS UNDER FUZZ: over >= 200 randomised doping profiles and
    starting meshes, every output mesh satisfies (a) grading ratio
    <= 1.2, (b) strictly increasing nodes, (c) endpoints preserved
    exactly, (d) node count <= max_nodes, (e) every input node retained
    (refinement never deletes -- see 10.2 on coarsening).

G7  COMPOSITION, NO SILENT DROPS: the driver reproduces the physics it
    was handed -- fd, srh, tat, impact, incomplete_ion and a
    heterostructure each solve through the driver and the resulting
    device reports the same Models as build_device produced.  Motivated
    directly by the M15 hard-debug finding that Device2D/Device3D were
    silently ignoring Models(impact=True).

G8  BUDGET HONESTY: a deliberately under-budgeted run (max_nodes small)
    warns, and history records the termination cause.  Asserted with
    pytest.warns -- not merely observed.

G9  SUITE INVARIANT: full suite green, zero warnings, pre-existing
    tests UNCHANGED.

------------------------------------------------------------------------
5. GATE-TO-TEST MAP  (red tests written on approval, in this order)
------------------------------------------------------------------------
  G1  test_indicators_match_analytic_forms
  G2  test_adequate_mesh_is_returned_unchanged
  G6  test_refinement_invariants_under_fuzz
  G5  test_second_order_convergence_on_analytic_resistor
  G4  test_qoi_converges_monotonically
  G3  test_adapted_diode_matches_committed_golden
  G7  test_driver_preserves_every_physics_flag
  G8  test_node_budget_warns_and_records_cause
  G9  (runner, not a test)

Order matters: the pure-function gates (G1, G6) and the inert-path gate
(G2) come before anything that needs a solve, so a failure localises to
the indicator arithmetic rather than to the physics.

------------------------------------------------------------------------
6. AMENDMENT MECHANISM
------------------------------------------------------------------------
Phases 1 and 2 require NO amendment: adapt.py is a pure addition and the
driver consumes Device1D/2D/3D through their public interface.  No
residual, no Jacobian, no existing golden is touched.  This is the same
standing as fermi.py, which "itself is a pure addition and needed no
amendment" (M13 plan section 6).

Phase 3 DOES modify the core assembly and requires the full mechanism:
sign-off recorded in its own plan file before the first core edit,
goldens committed before the edit, FD-Jacobian gate first, bit-identity
proven for the tensor-product path.

------------------------------------------------------------------------
7. DEPENDENCY CLEANLINESS
------------------------------------------------------------------------
- Phases 1-2 depend on nothing outside the current tree; numpy only.
- Phase 3 introduces triangle / gmsh as OPTIONAL dependencies -- absent,
  every existing path must behave exactly as today (standing rule 4).
- adapt.py must not import workbench or gui.  The GUI reaches it, if at
  all, through the existing QML -> controllers -> services -> subprocess
  layering; see 10.4.

------------------------------------------------------------------------
8. HONEST LIMITS TO SHIP WITH THE MILESTONE
------------------------------------------------------------------------
- h-refinement only: no p-refinement, no node motion.
- Indicators are HEURISTIC.  They are gated for self-consistency (G1)
  and for the convergence they produce (G4, G5), NOT for a proven
  effectivity bound.  The documentation must say so; calling a
  heuristic indicator an "error estimator" would be a false claim.
- Phase 2's tensor-product refinement is separable and therefore wasteful
  on localised 2D features -- stated, measured, and quoted in the docs
  as the reason phase 3 exists.
- Phase 1-2 refine only; they never coarsen (see 10.2).
- A converged mesh is converged FOR THE STATED QoI at the stated bias.
  It carries no guarantee for a different terminal quantity or a
  different operating point, and the API must not imply otherwise.

------------------------------------------------------------------------
9. RULE 4b POSITION  (user decision, stated not assumed)
------------------------------------------------------------------------
Standing rule 4b blocks a milestone's declared dependents until every
gate of the blocking milestone is green.  At the time of this decision,
M15 had two OPEN gates, pinned as strict xfail (M15-IONIZATION-PLAN.md,
R1); M15 is now COMPLETE (2026-08-28, all gates green -- see
ARCHITECTURE.md section 5), so this section is a record of the
reasoning that let phases 1-2 proceed while it was still open, not a
statement of current blocking status.

Reading: M21 is not declared blocked BY M15.  The parity plan gives
M21 "Depends: nothing hard, but do AFTER Tier 1 (physics first)" -- an
ORDERING PREFERENCE, not a gate dependency.  Phases 1-2 additionally
touch no core code and so cannot regress M15 or any Tier-1 physics.

On that reading phases 1-2 may proceed with M15 open.  It is a reading,
not a ruling: if the intent of "physics first" is that no Tier-2 work
starts until Tier 1 is green, then this milestone waits.  The user
decides; this plan does not proceed on an assumption either way.

------------------------------------------------------------------------
10. DECISIONS NEEDED BEFORE IMPLEMENTATION
------------------------------------------------------------------------
10.1  PHASE SCOPE.  Phase 1 alone, or phases 1+2 together?  Phase 1 is
      small and self-contained; phase 2 doubles the gate battery
      (2D and 3D each repeat G2-G7) for a mechanism that is structurally
      wasteful and superseded by phase 3.

10.2  COARSENING.  In or out?  Out is simpler and keeps G6(e) as a
      clean invariant ("never deletes a node").  In is needed for real
      sweep efficiency -- a mesh refined for -50 V is over-resolved at
      0 V -- but it breaks monotone node growth and needs its own
      hysteresis gate to avoid refine/coarsen oscillation.

10.3  QoI DEFAULT.  Terminal current is the obvious default.  It is also
      the quantity the M15 pass showed to be noisy near avalanche onset,
      where the convergence criterion would then be measuring solver
      scatter rather than discretisation error.  Alternative: converge
      on total depletion charge (smoother), and report current.

10.4  WIRE FORMAT.  Does the GUI expose adaptive meshing?  If yes,
      DeviceSpec gains adaptive settings -- a wire-format change with
      the usual pins (ModelCatalog.default_config() invariant,
      round-trip equality).  If no, phase 1 stays a library-level
      feature and the GUI keeps its explicit meshes.

10.5  STARTING MESH.  Does the driver start from the caller's mesh
      as-is, or first impose h/L_D <= 1 via graded_mesh?  The latter is
      friendlier and the former is more honest about what the caller
      asked for.


------------------------------------------------------------------------
11. IMPLEMENTATION RECORD -- PHASE 1 (2026-08-27)
------------------------------------------------------------------------
DECISIONS TAKEN (section 10, resolved by implementation):
 10.1  Phase 1 only.  Phases 2-3 not started.
 10.2  No coarsening.  G6 keeps "every input node survives" as a clean
       invariant.
 10.3  QoI is caller-supplied and mandatory; the gates use depletion
       charge, not terminal current, for the reason 10.3 anticipated.
 10.4  No wire-format change.  adapt.py is library-level; the GUI keeps
       explicit meshes.
 10.5  The caller's mesh is taken as handed over, unmodified.

TWO DESIGN ERRORS FOUND BY THE GATES, BOTH CORRECTED:

E1  h/L_D IS A CONSTRAINT, NOT AN ERROR INDICATOR.  The first
    default_indicator folded the Debye ratio into the Doerfler mass
    criterion.  On a uniform mesh h/L_D is very nearly constant, so it
    contributed a flat floor that dominated the selection and turned
    refinement into near-uniform bisection: the "adaptive" mesh spanned
    only 2x end to end and LOST to a uniform mesh at equal node count
    (7.53e-4 vs 2.58e-4).  Corrected: the error indicator is curvature
    + carrier log-gradients, and h/L_D is enforced separately as an
    absolute constraint (`debye_target`, every violating cell marked
    unconditionally).

E2  BISECTION CANNOT DELIVER AN ARBITRARY GRADING RATIO.  The original
    default ratio=1.2 is unreachable: a bisected cell abuts an
    unbisected one at exactly 2.  The repair loop spun to its sweep cap
    and returned a mesh that quietly failed the request (measured 3.0).
    Corrected: ratio=2.0, the standard 2:1 balance condition of adaptive
    mesh refinement, and ratio < 2 now RAISES rather than being silently
    approximated.

WHAT ADAPTIVITY IS AND IS NOT WORTH (measured, and gated both ways):
  Adaptivity pays only under SCALE SEPARATION.  On a 1e18/1e15 junction
  (L_D ratio ~32) the adaptive mesh is 5.9x more accurate than a uniform
  mesh at the same node count, with a 16x spacing span; at 1e19/1e15
  over 20 um it is 24x more accurate.  On the 1e16/1e17 diode, where
  L_D differs by only 3.2x, a uniform mesh is already near-optimal and
  the driver correctly produces a near-uniform one (8x span).  BOTH
  directions are gated (test_refinement_beats_uniform_under_scale_
  separation and test_scale_uniform_device_yields_a_near_uniform_mesh):
  claiming an adaptive win on a scale-uniform device would be claiming
  something untrue of the physics.

HARD-DEBUG FINDINGS (adversarial pass, all fixed + regression-tested):
  - Non-finite solution state propagated silently: a NaN in psi gave a
    NaN indicator, argsort placed it arbitrarily, and refinement
    proceeded on nonsense.  Now refused loudly at three points (QoI,
    indicator, marking).
  - theta <= 0 marked one cell; the empty set already satisfies a
    zero-mass criterion.  Now marks nothing.
  - Verified clean: determinism (identical mesh and psi across repeat
    runs), degenerate meshes (1, 2, 3 nodes), duplicate/out-of-range/
    negative marked indices, max_nodes below the current size, ragged
    and all-zero combine() inputs, wrong-length indicator returns.

DEFECT FOUND IN EXISTING CODE, REPORTED NOT FIXED:
  mesh.graded_mesh violates its OWN documented grading guarantee at the
  final cell.  Its docstring states "adjacent cells never differ by more
  than `ratio`" (default 1.15); measured output reaches 4.47x and, for
  L=2e-4/h_max=5e-7, 11.06x -- because the last step is truncated by
  `min(x + h, L)` and then snapped with `nodes[-1] = L`.  The jump lands
  on the ohmic contact cell, and the same docstring warns that grading
  degrades the box scheme's second-order accuracy.
  NOT FIXED HERE: graded_mesh builds the meshes behind the committed
  M13 goldens, so changing it breaks bit-identity and requires the
  amendment mechanism plus golden regeneration.  M21's G6 accommodates
  it by asserting refinement never makes grading WORSE than the input,
  rather than asserting an absolute bound the inputs do not provide.

  SUBSEQUENTLY FIXED (2026-08-27, separate session): the amendment was
  done -- goldens decoupled into frozen pre-fix mesh arrays
  (tests/goldens/m13/frozen_meshes.npz) so the bit-identity gates stay
  green against a snapshot rather than a live graded_mesh() call, then
  graded_mesh rewritten to an arc-length construction (place nodes at
  equal increments of integral dx/s(x), never truncating a step) plus a
  log-space gradient-limiter with a scale-invariant rescale, run
  iteratively to hit the documented ratio bound EXACTLY (fuzzed over
  2000 random geometries: worst ratio 1.000000000001, 0 violations,
  down from up to 11.06x). See tests/test_mesh_grading.py.

  A NEW, narrower degradation surfaced from that rewrite and was fixed
  in the same later hard-debug pass: the arc-length construction's
  dense sampling resolution is capped at 2,000,001 points (needed to
  keep memory/time bounded); above L/h_min ~ 40,000 the dense grid near
  a focus point becomes coarser than h_min itself, so the trapezoidal
  arc-length integral under-counts the sharp peak in 1/s(x) there and
  the realised minimum spacing silently ends up ~2-2.4x above the
  requested h_min -- a different documented guarantee ("spacing is
  h_min at a focus point") failing silently, this time from the fix
  rather than the original bug. Fixed by warning (not silently
  proceeding) whenever the cap actually engages, naming the achieved-
  vs-requested discrepancy explicitly.

------------------------------------------------------------------------
12. GEOMETRY FOUNDATION DECISION (2026-08-27) -- PHASE 3'S MESHER
------------------------------------------------------------------------
Phase 3 ("optional-dependency meshers (triangle / gmsh)", section 1)
needed one of those two names picked, plus a decision on whether a CAD
kernel (OpenCASCADE, FreeCAD) belongs underneath it for freeform 2D/3D
device geometry.  Full comparison against the actual repo (mesh2d.py,
workbench/adapters/spec.py, the Matplotlib-raster-to-QQuickPaintedItem
render stack, workbench/solvers/devsim_backend.py) recorded in
ARCHITECTURE.md section 4b; summary here.

DECIDED: gmsh is the foundation.  It is the one open project bundling
an OCC-based CAD kernel (boxes, polygons, extrusions, booleans),
unstructured 2D/3D meshing, and Physical-Group region tagging in a
single Python-importable package -- and DEVSIM (already a backend in
this repo) documents importing gmsh triangular/tetrahedral meshes
directly.  Physical Groups map onto exactly what
DeviceSpec.region_materials already does for rectilinear regions,
generalized from boxes to arbitrary shapes.  build123d (parametric
CAD on OCP/OCCT) is queued behind it for if/when freeform sketch-and-
drag authoring is actually asked for -- it is not a mesher and would
still hand off to gmsh.  Raw OCCT/pythonocc-core and FreeCAD were
considered and set aside: OCCT is the kernel underneath both gmsh and
build123d already, and FreeCAD is a desktop application with a Python
console, not a library -- embedding it fights the pure-QML
architecture the same way a second Qt Widgets stack would.

VALIDATED, NOT MERELY DECIDED.  examples/debug_geometry_gmsh_
conformality.py builds the same p-n diode geometry as the pytcad
Device2D goldens (6.0e-4 x 2.0e-4 cm, junction at 3.0e-4 cm) through
gmsh's OCC kernel and checks the property phase-3 box-integration FV
assembly actually needs: a CONFORMAL mesh across the material
interface (a shared node at the junction on both sides, not two
independently-meshed regions with coincident-but-distinct nodes,
which would break every SG edge-flux calculation that assumes a
shared node).  Result: occ.fragment() delivers it exactly -- 99 shared
node tags, every one at x = Xj to the bit, region areas matching the
analytic rectangle areas to 1e-16 relative, zero degenerate or
inverted triangles, both contact Physical Groups resolving to real
boundary elements.  This is the load-bearing claim behind choosing
gmsh, and it is now measured, not assumed.

HARD-DEBUG FINDING, kept in the script rather than smoothed over: the
first attempt sized the near-junction mesh with an ungrounded distance
field (DistMin=1e-5 cm, SizeMin=5e-7 cm) and produced 21344 nodes for
two rectangles -- gmsh's Threshold field refines uniformly along the
ENTIRE junction curve, so an arbitrary DistMin makes the fine corridor
far wider than the physics needs.  Regrounding DistMin/SizeMin in
pytcad.mesh.debye_length -- the SAME quantity M21 phase 1's own
h/L_D constraint uses, not a new number invented for gmsh -- cut this
to ~2100 nodes (comparable in scale to the existing Device2D goldens'
tensor-product resolution) with area error tightening from 1e-14 to
1e-16 relative.  The lesson is the same one phase 1 already learned
from the opposite direction (adapt.py's own docstring: h/L_D is a
CONSTRAINT, not a thing to bury inside a generic error indicator) --
a mesh size field is not a substitute for physics-grounded sizing
whichever tool is generating the mesh.

NOT YET DONE (this was a conformality/tagging PROBE, not phase 3
itself): the region-tag -> material/doping/contact resolver: box
integration assembly on the gmsh mesh; the golden parity gate against
the tensor-product path (standing rule 3); 3D (tetrahedral) repeat of
the same conformality check across a solid-solid interface, which is
a materially harder case than the 2D curve-curve interface tested
here.  See ARCHITECTURE.md section 7 for where this sits in the queue.

------------------------------------------------------------------------
13. IMPLEMENTATION RECORD -- PHASE 2 HARD-DEBUG PASS (2026-08-28)
------------------------------------------------------------------------
Phase 2 (reduce_x/y/z, default_indicator_2d/3d, refine_2d/3d,
adapt_solve_2d/3d in pytcad/adapt.py; the 25-test gate battery in
tests/test_m21_phase2.py) was already present in the tree when this
pass started, but had never been run to a clean, memory-safe green --
running it the first time drove the host to tens of GB of resident
memory. An adversarial pass over the whole file found and fixed SIX
real bugs, none of them subtle physics mistakes -- the kind that crash
or silently disable a check rather than produce a slightly-wrong
number:

D1  STALE IMPORT NAME BROKE PHASE 1 TOO.  adapt.py's import was
    `from .mesh import debye_length as _debye_length` (renamed for
    phase 2's own debye checks, which correctly use `_debye_length`),
    but `indicator_debye` -- PHASE 1 code, called on every single pass
    of `adapt_solve_1d` -- still called the old bare name `debye_length`.
    This raised `NameError` unconditionally, and had been doing so the
    whole time phase 2 code sat in the tree: 10 of test_m21_adapt.py's
    17 tests were failing before this pass touched anything. Fixed by
    updating the one stale call site to `_debye_length`.

D2  3D DEBYE-CONSTRAINT BROADCASTING BUG.  `adapt_solve_3d`'s per-axis
    Debye check built `debye_y` as
    `np.diff(mesh.y)[:, None, None] / minimum(LD[:, :-1, :], LD[:, 1:, :])`
    -- putting the `Ny-1` axis in position 0, but `LD[:, :-1, :]` has
    shape `(Nz, Ny-1, Nx)` and needs it in position 1. Raises
    `ValueError` on any mesh where `Nz != Ny-1` (i.e. essentially
    always). Fixed to `[None, :, None]`.

D3  3D DRIVER CALLED THE 2D-ONLY REDUCERS.  `adapt_solve_3d` called
    `reduce_x(eta_x)` / `reduce_y(eta_y)` where `eta_x`/`eta_y` from
    `default_indicator_3d` are 3-D arrays; `reduce_x`/`reduce_y` raised
    `ValueError` on anything but a 2-D array. This meant the 3D driver's
    main refinement path -- as opposed to its degenerate empty-indicator
    branch -- had never actually completed once. Fixed by generalising
    `reduce_x`/`reduce_y` to accept a 3-D indicator too (mean over the
    two axes perpendicular to the target axis, matching `reduce_z`'s
    existing 3-D convention), rather than writing separate 3D-only
    reducers.

D4  `prev_q` NEVER UPDATED -- THE TOL-BASED CONVERGENCE CHECK WAS DEAD
    CODE.  `adapt_solve_1d` sets `prev_q = q` unconditionally every pass
    (right after the Debye-adequacy check), so `delta` is meaningful on
    every subsequent pass regardless of whether cells get marked.
    `adapt_solve_2d`/`3d` copied the surrounding structure but the
    `prev_q = q` line ended up ONLY inside the degenerate
    empty-indicator branch, which real (non-trivial) indicator data
    essentially never takes. Net effect: `delta` stayed `inf` forever
    in the normal path, so the `tol` parameter was silently ignored and
    every real run terminated via "nothing left to mark" or a resource
    limit, never via measured QoI convergence. Fixed by restructuring
    both drivers to check Debye adequacy (not indicator emptiness) for
    the tol-gated exit and to set `prev_q = q` unconditionally per pass,
    mirroring `adapt_solve_1d`'s placement exactly.

D5  DEFAULT `qoi` FUNCTIONS WERE THEMSELVES BROKEN.  `adapt_solve_2d`/
    `3d`'s own fallback `_qoi_2d`/`_qoi_3d` (used when a caller passes
    `qoi=None`) computed `rho * dev.mesh.dV` without `.ravel()`ing
    `rho` first -- `rho` is `(Ny,Nx)`/`(Nz,Ny,Nx)`-shaped but `mesh.dV`
    is flat, so this raises on any real device. Invisible in this
    file's own test suite because every test supplies its own
    (correctly raveled) `qoi`. Fixed both.

D6  TEST-HELPER DOPING ARRAY SILENTLY SCRAMBLED (the headline bug).
    `_build_2d`/`_build_3d` built doping via
    `np.meshgrid(x, y, [z,] indexing='ij')` giving shape `(Nx, Ny, [Nz])`,
    then passed it to `Device2D`/`Device3D`, which reshape their
    `doping` argument to `(Ny, Nx)` / `(Nz, Ny, Nx)` -- a FLAT reshape,
    not a transpose. Whenever `Nx != Ny` (2D) or the full triple isn't
    symmetric (3D) -- true of virtually every mesh in this file,
    adaptive or not -- this reinterprets the flat buffer with the wrong
    axis order. Measured: ~49% of doping nodes ended up with the wrong
    value for their position. Because doping only ever takes one of two
    values (-na or nd), the array's CONTENTS looked completely normal
    under inspection; only the spatial PLACEMENT was corrupted, so this
    was invisible short of checking node-by-node against the intended
    step function. Every 3D test in the file had therefore been
    exercising a scrambled, non-physical doping profile, not a clean
    p-n junction along x -- which explains the otherwise-mysterious
    z-axis Debye violations, non-monotonic convergence, and generally
    "off" agreement numbers seen while diagnosing D1-D5. Fixed by
    building the doping array directly in the correct (Ny,Nx) /
    (Nz,Ny,Nx) order via a 1-D broadcast (doping depends only on x; no
    meshgrid needed at all).

TEST-DATA FIXES, DOWNSTREAM OF D6.  Once the doping was no longer
scrambled, several tests' own mesh/domain choices turned out to be
wrong on their own terms, independent of any adapt.py bug:

  - Two G3 "resolved reference" tests (2D and 3D) and two other tests
    (`test_adequate_3d_mesh_is_returned_unchanged`,
    `test_driver_3d_preserves_physics_flag`) reused phase 1's 1D-only
    `graded_mesh(h_min=5e-9, h_max=5e-8)`/`(h_min=2e-8, h_max=2e-7)`
    recipes, tensor-producted across a second or third axis and pushed
    through Device2D/3D's DIRECT sparse solve. That is safe as a 1D
    node count (12020/3020) but not once multiplied out: the 3D cases
    reached 3.6-4.8 MILLION nodes, and Device3D's `spsolve` tried to
    allocate hundreds of MB just for the Jacobian's index arrays --
    this is what drove the host to tens of GB resident. Fixed by
    picking coarser, still-meaningfully-finer references (verified
    debye-adequate at ~5,600-65,000 nodes for the affected 3D cases,
    using W=D=1.0e-5 cm Debye-scale domains rather than the diode's
    usual 2.0e-4/1.0e-4 cm width -- at this doping (1e16/1e17,
    L_D_min ~ 1.29e-6 cm) a uniform y/z mesh across the wider domain
    violates the h/L_D<=1 constraint on EVERY cell, so "already
    adequate" or "converges in a handful of passes" is only actually
    achievable at Debye scale).

  - `test_qoi_3d_converges_monotonically` and
    `test_2d_separable_refinement_adds_nodes` asserted `cause ==
    "converged"` at node budgets (100000 / 200000) that, against the
    now-correct doping, are genuinely too small: the wide-domain 3D
    case needs the Debye constraint resolved across the FULL y/z
    extent (per-axis checks average over the other two axes, so
    locality doesn't help), which forces near-uniform bisection of all
    three axes every pass (~7x node growth per pass) -- reaching
    tol=1e-2 that way needs millions of nodes, and a DIRECT 3D solve
    cannot fit that in memory (measured: SuperLU's `gssv` runs out of
    memory around ~240,000 nodes on this host). Fixed the 3D case the
    same way as the mesh-size fixes above (Debye-scale domain; measured
    to converge cleanly at 65,648 nodes) and raised the 2D case's
    budget to 700,000 nodes (measured to converge at ~559,000 -- large
    but a direct 2D solve handles it in well under a minute).

VERIFICATION.  All fixes applied with `ulimit -v` memory caps during
development so a recurrence would fail loudly (`MemoryError`) rather
than exhaust the host again. Final state: tests/test_m21_adapt.py 17/17
passed, tests/test_m21_phase2.py 25/25 passed, full suite (`tests/
gui/tests/`, `-n 6`) 722 passed / 1 xfailed (M14 G-A, unrelated) / 0
failed -- zero regressions elsewhere in the tree.
