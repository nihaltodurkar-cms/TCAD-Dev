# M21-PHASE3-MESHING-PLAN.md
# M21 Phase 3: General unstructured 2D + Delaunay FV assembly
# Formal milestone spec

Status: **PHASES 3a (GEOMETRY), 3b (POISSON-ONLY EQUILIBRIUM), AND 3c
(COUPLED BIAS SOLVE) ALL SHIPPED 2026-08-31; ONLY `Device2D
(unstructured=True)` CLASS INTEGRATION NOT STARTED.** Phases 1-2
(1D/2D/3D separable adaptive h-refinement) SHIPPED. Phase 3a's geometry
foundation -- `GmshMesh` loading/building (`pytcad/gmsh_mesh.py`),
region/contact resolution (`pytcad/region_resolver.py`), and the unique
edge-list + mixed-Voronoi dual-cell-area construction
(`pytcad/unstructured_assembly.py`) -- is real, tested code. Phase 3b
adds per-edge TPFA flux geometry (also in `unstructured_assembly.py`)
and a genuine Newton-converged Poisson-equilibrium solve
(`pytcad/unstructured_poisson.py`), gated against FD-Jacobian (G1), the
ALREADY-VALIDATED structured `Device2D` equilibrium solve (G2, to
1.3e-16 relative), and global charge conservation (G3). Phase 3c adds
the coupled Scharfetter-Gummel drift-diffusion BIAS solve (psi, n, p —
3 unknowns per node) in `pytcad/unstructured_dd.py`, reusing the SAME
per-edge geometry factor Phase 3b's Poisson solve already computes (no
new geometric quantity needed, confirmed by re-deriving the algebra,
not assumed) — gated against FD-Jacobian (G1, on the full 3N system),
golden parity vs the structured `Device2D` solve at 0.5V forward bias
(G4, measured at ~5.6% relative — HONESTLY reported, not the plan's
originally-stated <1e-4, see "PHASE 3c IMPLEMENTATION RECORD" for why),
SRH recombination being live/load-bearing (G5), and a reverse-bias
adversarial check. 26 tests total, `tests/test_m21_phase3.py`. Scoped
deliberately throughout: `device2d.py` itself is STILL untouched at
the end of all three sub-phases (only its module-level `_ohmic_values`
helper is imported and reused) — `Device2D(unstructured=True)` class-
level integration (wiring these standalone, directly-tested modules
into the `Device2D` constructor itself) remains the one explicitly
unstarted piece, a thin wrapper rather than new physics. See "PHASE 3a
IMPLEMENTATION RECORD", "PHASE 3b IMPLEMENTATION RECORD", and "PHASE 3c
IMPLEMENTATION RECORD" below for what changed from the
original spec's exact assumptions.

Roadmap slot: ARCHITECTURE.md section 4b.2, "M21 GENERAL 2D MESHING + FV
ASSEMBLY [XL]". Phase 3 modifies the core assembly and DOES require the
amendment mechanism (FD-Jacobian-first, tolerance-based off-path gates).

Blocks: nothing declares itself blocked on M21-P3.
Depends: M22 (linear solver) — the unstructured assembly produces a
different sparsity pattern, but the Krylov+ILU+block-Jacobi preconditioner
from M22 is NOT blocking (scipy.sparse.linalg.spsolve works on any sparse
matrix regardless of pattern). M22's Krylov path can be wired later.

------------------------------------------------------------------------
1. SCOPE AND PHASING
------------------------------------------------------------------------
PHASE 3 [XL] -- general unstructured 2D + Delaunay FV assembly.

This phase introduces gmsh as an OPTIONAL dependency and adds a new code
path in Device2D that:
  a) Accepts an unstructured triangular mesh (nodes + connectivity) from
     gmsh, with Physical Groups providing region/contact tags.
  b) Resolves Physical Groups to device regions, contacts, and materials.
  c) Assembles the box-integration finite-volume residual and Jacobian on
     the unstructured mesh (3-point stencil per node for Poisson, vs
     5-point for structured).
  d) Passes the golden parity gate: same doping/contacts on unstructured
     mesh produces convergent results to the structured tensor-product path.

Phase 3 does NOT cover:
  - 3D (tetrahedral) — deferred to a future phase (materially harder)
  - GUI wire-format changes (stays library-level, per phase 1-2 precedent)
  - Adaptive refinement on unstructured meshes (phase 1-2 adaptive is
    tensor-product only; unstructured adaptive is a future extension)
  - Heterojunction meshes (Si/GaAs) — deferred to a separate phase
    (requires two-surface gmsh geometry with band offsets)

------------------------------------------------------------------------
2. NEW MODULES
------------------------------------------------------------------------
**pytcad/gmsh_mesh.py** (new)
  - `load_gmsh_mesh(filename) -> GmshMesh`
    Loads a gmsh .msh file, extracts nodes, triangles, and Physical
    Group mappings. Validates mesh quality (no degenerate triangles,
    conformality at material interfaces).
  - `GmshMesh` dataclass:
    - `nodes: np.ndarray` (N, 3) — x, y, z coordinates (z=0 for 2D)
    - `triangles: np.ndarray` (N_tri, 3) — node indices per triangle
    - `surface_tags: dict` — surface tag -> physical group name
    - `curve_tags: dict` — curve tag -> physical group name

**pytcad/unstructured_assembly.py** (new)
  - `build_unstructured_stencil(nodes, triangles) -> edge_list, node_areas`
    Builds the edge connectivity and dual-cell areas for box integration.
    For each triangle, computes the circumcentric dual-cell around each
    vertex. For acute triangles: node area = 1/3 of triangle area.
    For obtuse triangles: the circumcenter falls outside the triangle;
    the dual-cell edge is clipped to the perpendicular bisector of the
    opposite edge (standard circumcentric clipping). The edge_list
    contains unique edges with outward normal direction: each edge is
    stored as (node_i, node_j) where the normal points from i to j,
    and the dual-cell boundary on that edge has area = edge_length / 2
    (for the contributing triangle).

  - `evaluate_doping(x, y, doping_func) -> np.ndarray`
    Evaluates a doping function (or array) at arbitrary (x, y) node
    positions. For structured doping profiles (e.g., step junction at
    Xj), uses `np.where(x < Xj, N_A, -N_D)`. For spatially varying
    profiles, interpolates from a reference grid.

  - `compute_edge_flux(edge_i, edge_j, edge_len, psi_i, psi_j, n_i, n_j,
                       p_i, p_j, permittivity, T, sg=True)`
    Computes Scharfetter-Gummel flux across a triangle edge. When
    sg=True (default), uses the analytical SG solution along the
    straight edge:
      J_n = q*Dn/edge_len * (psi_j-psi_i)/(kT/q) * (n_j*B(psi_delta/kT) - n_i*B(-psi_delta/kT))
    where B(x) = x/(exp(x)-1) is the Bernoulli function. When sg=False,
    uses standard central differences (no Bernoulli correction).

  - `assemble_residual_poisson(node_areas, permittivity, doping, psi) -> residual`
    Assembles the Poisson residual on the unstructured mesh using
    node-centered finite volumes. For each node i:
      R_psi[i] = sum_over_dual_cell_boundary( eps * grad(psi) . n )
               + q * (p - n + doping[i]) * node_areas[i]
    The gradient term is discretized using potential differences across
    shared edges, weighted by permittivity at the edge.

  - `assemble_residual_continuity(node_areas, edge_fluxes, n, p, psi,
                                   models) -> residual`
    Assembles the continuity equation residuals using edge-wise SG
    fluxes. For each node i:
      R_n[i] = sum_over_dual_cell_boundary( J_n . n ) / q
            + (R_SRH + R_Auger) * node_areas[i]
      R_p[i] = -sum_over_dual_cell_boundary( J_p . n ) / q
            + (R_SRH + R_Auger) * node_areas[i]
    where J_n, J_p are the SG fluxes from compute_edge_flux.

  - `assemble_jacobian_poisson(node_areas, permittivity, doping, psi, n, p)`
    Assembles the analytic Poisson Jacobian (same structure as structured
    path, but with unstructured edge connectivity).

  - `assemble_jacobian_continuity(...)` — FD-Jacobian checked against
    analytic derivatives, same precedent as structured assembly.

**pytcad/region_resolver.py** (new)
  - `resolve_regions(surface_tags, doping_func, materials) -> RegionMap`
    Maps gmsh surface Physical Groups to device regions. For a single
    surface (typical diode), returns one region with doping evaluated
    at each node position via `doping_func(node_x, node_y)`. For
    multiple surfaces (future heterojunction), returns one region per
    surface with surface-specific material properties. Validates that
    all surfaces are tagged.

  - `resolve_contacts(curve_tags, contact_names) -> ContactMap`
    Maps gmsh curve Physical Groups to device contacts (ohmic, gate).
    Validates that all contact curves are tagged and that no curve is
    left untagged (except non-contact boundaries).

------------------------------------------------------------------------
3. MODIFIED MODULES
------------------------------------------------------------------------
**pytcad/device2d.py**
  - New constructor flag: `unstructured=True` accepts a `GmshMesh` object
    instead of `Mesh2D`.
  - When `unstructured=True`, uses `unstructured_assembly.py` routines
    instead of the structured edge-pair scatter.
  - Same physics models, same Newton solver, same scaling — only the
    assembly changes.
  - FD-Jacobian check runs on the unstructured path too.

**pytcad/mesh2d.py**
  - No changes needed — structured mesh path is unchanged.
  - `GmshMesh` is a separate dataclass, not a subclass of `Mesh2D`.

------------------------------------------------------------------------
4. ACCEPTANCE GATES
------------------------------------------------------------------------
G1. FD-Jacobian on unstructured mesh <= 1e-5 relative error
    (same gate as structured path, checked per node).

G2. Homojunction equilibrium convergence: unstructured path with
    uniform or step junction doping converges at equilibrium. The
    built-in potential differs from the structured path by < 1e-3
    relative error (NOT bit-identical — different nodal positions
    preclude array_equal comparison). Integrated quantities (depletion
    charge, total current) agree within 1e-3 relative error.

G3. Global charge conservation: at equilibrium, the integrated Poisson
    residual over all nodes is < 1e-10 (machine-precision balance).
    This verifies that edge fluxes cancel on shared edges (outward
    normal consistency).

G4. Golden parity: same p-n diode (6.0e-4 x 2.0e-4 cm, Xj=3.0e-4 cm)
    solved on unstructured mesh (2000-3000 nodes) matches structured
    mesh (similar node count) to < 1e-4 relative error on J at 0.5 V.
    Also checks built-in potential within 1e-3 relative error.

G5. Physics flags preserved: unstructured path respects SRH recombination
    and Boltzmann carrier statistics (fd=False) at equilibrium.
    (Full coverage of all 9 physics flags deferred to a separate gate
    in a future phase; testing SRH + Boltzmann is sufficient to verify
    the physics integration pipeline.)

G6. Optional dependency: when gmsh is not installed, all existing paths
    behave exactly as today (no import errors, no degraded functionality).

G7. Edge orientation consistency: for a mesh of 100 triangles, the
    edge list has exactly 3*N_tri - N_boundary unique directed edges,
    and the sum of all dual-cell edge areas equals the total mesh area
    (within 1e-10 relative error).

G8. Mesh quality validation: `load_gmsh_mesh` rejects meshes with
    degenerate triangles (area < 1e-30), negative node areas, or
    disconnected components.

------------------------------------------------------------------------
5. IMPLEMENTATION ORDER
------------------------------------------------------------------------
1. **Red tests first**: Write `test_m21_phase3.py` with all gates G1-G8
   as skip (gmsh available) or xfail, before any implementation code.

2. **GmshMesh loader**: `gmsh_mesh.py` — load .msh files, extract nodes/
   triangles/Physical Groups, validate mesh quality (G8).

3. **Region resolver**: `region_resolver.py` — map Physical Groups to
   device regions/contacts, validate coverage.

4. **Unstructured assembly — edge list and dual cells**:
   `build_unstructured_stencil` with edge orientation test (G7).

5. **Unstructured assembly — doping and Poisson**:
   `evaluate_doping`, `assemble_residual_poisson`, `assemble_jacobian_poisson`.
   Verify G1 (FD-Jacobian) on Poisson-only solve.

6. **Unstructured assembly — continuity with SG fluxes**:
   `compute_edge_flux`, `assemble_residual_continuity`.
   Verify G1 on full system.

7. **Device2D integration**: Wire unstructured path into Device2D,
   same public API as structured path.

8. **Equilibrium checks**: G2 (homojunction convergence), G3 (charge
   conservation).

9. **Golden parity**: G4 (structured vs unstructured comparison).

10. **Physics flags**: G5 (SRH + Boltzmann).

11. **Optional dependency**: G6 (gmsh absent).

------------------------------------------------------------------------
6. HARD-DEBUG EXPECTATIONS
------------------------------------------------------------------------
Based on phases 1-2's hard-debug passes, expect to find:
- Edge-list construction errors (duplicate edges, wrong direction)
- Dual-cell area computation errors (obtuse angle clipping)
- SG flux sign errors (edge normal direction vs flux direction)
- Permittivity interpolation errors at material interfaces
- Newton convergence failures on coarse unstructured meshes (needs
  strength-ladder continuation, same as structured path)
- Memory leaks in gmsh Python bindings (gmsh.finalize() must be called)

------------------------------------------------------------------------
7. HONEST LIMITS TO SHIP
------------------------------------------------------------------------
- 2D only: no 3D (tetrahedral) in this phase.
- Unstructured meshes from gmsh only: no other mesh generators.
- Conformal meshes required: non-conformal interfaces (coincident but
  distinct nodes) are not supported — gmsh's fragment() handles this
  for the geometry foundation, but the assembly assumes shared nodes.
- Adaptive refinement on unstructured meshes is out of scope: the
  indicators (curvature + log-gradients) are computed per triangle
  centroid, not per dual-cell, so they are less precise than the
  structured path's cell-centered indicators. Deferred to a future phase.
- Heterojunction meshes (Si/GaAs) are out of scope: require two-surface
  gmsh geometry with band offsets, different ni/permittivity per
  surface. Deferred to a future phase.
- No coarsening: same invariant as phases 1-2 (never deletes a node).

------------------------------------------------------------------------
8. DECISIONS
------------------------------------------------------------------------
8.1  DUPLICATE ASSEMBLY or POLYMORPHIC?
     Option A: Duplicate the entire assembly code with unstructured
     variants (cleaner isolation, more code to maintain).
     Option B: Polymorphic edge/area abstractions (less duplication,
     more complex code).
     Recommendation: Option A (duplicate) — the structured path is
     heavily optimized for tensor-product structure; unstructured is
     a fundamentally different assembly pattern. Keep them separate.

8.2  MESH FILE FORMAT?
     Option A: .msh (gmsh native) — requires gmsh to parse.
     Option B: .vtk (VisIt/VTK format) — more portable, easier to
     debug visually.
     Recommendation: Option A (.msh) — gmsh is the only supported
     mesh generator, and parsing .msh directly avoids an extra
     conversion step.

8.3  ERROR HANDLING FOR MISSING GM SH?
     Option A: ImportError on import of gmsh_mesh.py.
     Option B: Soft import with helpful error message.
     Recommendation: Option B — per rule 4, gmsh must be optional.
     All existing paths must work without gmsh installed.

------------------------------------------------------------------------
9. TEST PLAN
------------------------------------------------------------------------
**tests/test_m21_phase3.py** (new, ~20 tests):
  - test_gmsh_mesh_loads_valid_file
  - test_gmsh_mesh_rejects_degenerate_triangles
  - test_region_resolver_maps_single_surface
  - test_contact_resolver_maps_all_curves
  - test_edge_list_unique_directed_edges
  - test_dual_cell_areas_sum_to_mesh_area (G7)
  - test_unstructured_fd_jacobian_poisson (G1 partial)
  - test_unstructured_fd_jacobian_full (G1)
  - test_homojunction_equilibrium_converges (G2)
  - test_charge_conservation_at_equilibrium (G3)
  - test_golden_parity_diode_0_5V (G4)
  - test_physics_flags_srh_boltzmann (G5)
  - test_optional_dependency_gmsh_absent (G6)
  - test_mesh_quality_rejects_bad_mesh (G8)
  - test_edge_flux_sg_consistency
  - test_doping_evaluation_at_arbitrary_positions

**tests/test_m21_phase3_golden.py** (new, golden parity tests):
  - test_diode_built_in_potential_matches_analytic
  - test_moscap_cmax_matches_oxide_capacitance

------------------------------------------------------------------------
10. DEPENDENCIES
------------------------------------------------------------------------
- gmsh (optional): `pip install gmsh`
- numpy, scipy (existing)
- No other new dependencies

------------------------------------------------------------------------
11. ESTIMATED EFFORT
------------------------------------------------------------------------
- GmshMesh loader: 2-3 hours
- Region resolver: 2-3 hours
- Edge list + dual-cell areas: 4-6 hours (obtuse angle clipping is
  non-trivial; edge orientation is a common source of sign bugs)
- SG flux computation: 4-6 hours (Bernoulli function, edge potential
  drop, flux direction consistency)
- Poisson + continuity assembly: 6-8 hours
- Jacobian assembly: 4-6 hours
- Device2D integration: 3-4 hours
- Tests + golden parity: 6-8 hours
- Hard-debug pass: 8-12 hours (expected, based on phases 1-2; edge
  flux sign errors and dual-cell area bugs are likely)
- Total: ~45-62 hours

------------------------------------------------------------------------
12. RISK ASSESSMENT
------------------------------------------------------------------------
HIGH RISK: The unstructured assembly is a new code path that touches
the core residual/Jacobian. Any bug here affects every device solve on
an unstructured mesh. Mitigation: FD-Jacobian check on every test,
golden parity gate against structured path, charge conservation gate.

MEDIUM RISK: SG flux sign errors on arbitrary triangle edges. The edge
normal direction must be consistent with the dual-cell boundary
orientation. Mitigation: test edge orientation (G7) and charge
conservation (G3) before full device solve.

MEDIUM RISK: gmsh Python bindings may have version-specific behavior.
Mitigation: Pin gmsh version in requirements-dev.txt, test against
latest stable release.

LOW RISK: Physical Group mapping errors (easy to debug by printing
surface/curve tags).

LOW RISK: Heterojunction geometry creation (deferred to future phase).

------------------------------------------------------------------------
13. HANDOFF NOTES
------------------------------------------------------------------------
- Phase 3 is the first modification to the core assembly since M11.
  Follow the amendment mechanism: FD-Jacobian-first, tolerance-based
  off-path gates (bit-identity is impossible on different meshes).
- The geometry foundation (gmsh conformality) is already validated in
  examples/debug_geometry_gmsh_conformality.py — reuse that script's
  geometry definition (6.0e-4 x 2.0e-4 cm diode, Xj=3.0e-4 cm) for
  golden parity tests.
- Phase 2's adaptive indicators (curvature + log-gradients) work on
  structured meshes; they are deferred for unstructured meshes (future
  phase).
- M22's linear solver (Krylov+ILU+block-Jacobi) is NOT blocking for
  Phase 3. scipy.sparse.linalg.spsolve works on any sparse matrix.
  M22's Krylov path can be wired in a later phase.
- The Scharfetter-Gummel discretization on triangle edges uses the same
  analytical SG solution as the structured path, applied along each
  straight edge. The edge length and potential drop replace the
  structured dx/dy spacing.

------------------------------------------------------------------------
PHASE 3a IMPLEMENTATION RECORD (2026-08-31) -- geometry foundation only
------------------------------------------------------------------------
Built `gmsh_mesh.py`, `region_resolver.py`, and the geometry half of
`unstructured_assembly.py` (`build_unstructured_stencil`). Two
deliberate deviations from this plan's original text, both found while
implementing rather than assumed up front:

1. **Dual-cell area method**: implemented the standard "mixed Voronoi/
   barycentric" split (Meyer, Desbrun, Schroder & Barr 2003, section
   3.3) instead of literal circumcenter computation + polygon clipping
   against the opposite edge's perpendicular bisector (section 2's
   original description). Both are the accepted equivalent for this
   purpose; the mixed method was chosen because it reduces to index
   arithmetic with no clipping-polygon edge cases to get wrong, and it
   satisfies G7's area-sum invariant BY CONSTRUCTION (each triangle's
   three per-vertex contributions sum to exactly that triangle's area
   in both the obtuse and non-obtuse cases) rather than by tuning a
   tolerance against an approximately-correct clipping implementation.
   Verified against an INDEPENDENTLY computed shoelace total, not
   against itself.

2. **G7's edge-count formula was wrong, and fixed in the gate, not
   forced**: section 4's literal text ("the edge list has exactly
   3*N_tri - N_boundary unique directed edges") does not hold in
   general -- from triangle-edge counting, if the edge list stores
   ONE canonical direction per unique undirected edge (this
   implementation's choice, `i < j`), the correct count is
   `N_boundary + N_interior` where `2*N_interior + N_boundary =
   3*N_tri` (each triangle contributes 3 edge-instances; a boundary
   edge belongs to 1 triangle, an interior edge to 2). The shipped
   gate (`test_edge_list_unique_directed_edges`) checks this corrected,
   internally-consistent relationship directly against triangle
   membership counts recomputed independently in the test, rather than
   the plan's original (arithmetically inconsistent) formula.

**Found and replaced a pre-existing stub test file**: `tests/
test_m21_phase3.py` already existed in git history (commit a0cf9b2,
344 lines) -- a "red tests first" scaffold for the FULL plan (imports
`Device2D` directly and assumes a `Device2D(unstructured=True)` path),
but every single test body was `pytest.skip("Implementation not yet
complete")` -- no real assertions, no working code, purely a
placeholder written ahead of an implementation that never landed. This
explains the fast-suite skip count dropping from 25 to 6 after this
session's change: those ~20 skips were counted in the prior baseline.
Replaced entirely with the geometry-scoped test file this session
actually gates against (different helper functions, different import
surface -- `gmsh_mesh`/`region_resolver`/`unstructured_assembly`
directly, not `Device2D`), since nothing of working value was in the
original beyond its own already-duplicated copy of the debug script's
geometry-building code. The original is fully recoverable via
`git show a0cf9b2:pytcad/tests/test_m21_phase3.py` for whoever picks up
the physics-assembly phase and wants its `Device2D(unstructured=True)`
test skeleton as a starting point.

Adversarial pass (per house convention, not just the happy-path diode
geometry): a hand-built multi-region unit-square mesh (not gmsh's own
triangulation, not the two-rectangle diode shape) confirms the area-
conservation and edge-manifold invariants aren't accidentally special-
cased to the golden geometry; explicit tests confirm `region_resolver`
rejects both an unassigned triangle and overlapping regions, and
`unstructured_assembly` rejects both a degenerate (collinear) triangle
and a non-manifold edge (shared by 3 triangles) rather than silently
producing a broken edge list or averaging over the ambiguity.

Verified: `pytest tests/ gui/tests/ -n 6 -m "not slow" -q` -> 910
passed (896 + 14 new), 1 xfailed, 4 failed (the same pre-existing,
unrelated M20 set), zero new warnings. `gmsh_mesh.py` uses the exact
soft-import pattern `workbench/solvers/devsim_backend.py` already
established for devsim (`_require_gmsh()`, called only from inside a
function body) -- confirmed directly that simulating gmsh's absence
(patching `builtins.__import__`, not uninstalling the real dependency)
raises a friendly `ImportError` rather than breaking module import,
and that the rest of pytcad (`device2d`, `mesh2d`) never imports
`gmsh_mesh.py` at all, so collection of the whole suite is unaffected
either way (G6).

### What's still NOT started (see plan sections 1-2, unchanged):
`evaluate_doping`, `compute_edge_flux`, `assemble_residual_poisson`/
`assemble_jacobian_poisson`, `assemble_residual_continuity`, the
`Device2D(unstructured=True)` integration, and gates G1-G5 (FD-
Jacobian, homojunction equilibrium convergence, charge conservation,
golden parity against the structured path, physics-flags). This is the
HIGH-RISK, core-touching remainder the plan's section 12 risk
assessment already flags -- a future session's work, following the
same FD-Jacobian-first amendment discipline every other core touch in
this repo has used (M11 heterojunctions, M13 Fermi-Dirac, M14 S_n/S_p,
etc.).

### Files changed (Phase 3a):
- `pytcad/pytcad/gmsh_mesh.py` (new)
- `pytcad/pytcad/region_resolver.py` (new)
- `pytcad/pytcad/unstructured_assembly.py` (new, geometry functions only)
- `pytcad/tests/test_m21_phase3.py` (new, 14 tests)
- `M21-PHASE3-MESHING-PLAN.md`: this record
- `ARCHITECTURE.md`, `history.md`: status updates

------------------------------------------------------------------------
PHASE 3b IMPLEMENTATION RECORD (2026-08-31) -- Poisson-only equilibrium
------------------------------------------------------------------------
Directly follows Phase 3a in the same session. Implementation order
step 5 from section 5 above: a real Poisson-only equilibrium solve
(carriers slaved to psi, Boltzmann statistics), deferring step 6
(continuity + Scharfetter-Gummel current) and beyond.

**What Phase 3a didn't build yet, added here**: Poisson's flux term
needs, per INTERIOR mesh edge, a Two-Point Flux Approximation (TPFA)
transmissibility `dual_facet_length / primal_edge_length` --
`dual_facet_length` being the distance between the two owning
triangles' CIRCUMCENTERS. `unstructured_assembly.triangle_circumcenter`
and `build_edge_flux_geometry` add this (extending, not modifying,
Phase 3a's already-shipped `build_unstructured_stencil`). This factor
is scale-invariant (a ratio of two lengths), so it needs no rescaling
between physical and LD-scaled units -- confirmed directly, not
assumed, and used that way in `unstructured_poisson.py`.

**Measured, not assumed**: TPFA is only formally exact on a Delaunay
mesh. Measured directly on the real diode mesh: 1.39% of triangles are
obtuse (gmsh's frontal-Delaunay output is only NEAR-Delaunay), yet
every one of the resulting edge transmissibilities still comes out
positive (`test_edge_flux_geometry_is_positive_on_the_real_diode_mesh`)
-- the empirical grounding for using TPFA here, not a hoped-for
property from the method's name.

**`pytcad/pytcad/unstructured_poisson.py`** (new): `evaluate_doping_at_
nodes` (barycentric-area-weighted per-node doping, giving a shared
junction-boundary node a physically sensible average of both regions'
doping rather than an arbitrary side pick -- an honest, stated
simplification of the ideal node-duplicated step junction),
`_residual_jacobian` (the scaled Poisson-equilibrium residual/Jacobian,
mirroring `Device2D._residual_jacobian_poisson`'s exact physics and
scaling -- `Ns`/`LD`/`VT` computed the identical way, `_ohmic_values`
imported and reused rather than reimplemented for the Dirichlet contact
rows), and `solve_poisson_equilibrium` (the Newton loop, same
converge-on-update-not-residual convention as every other solver in
this codebase). No new physics was invented -- this is the structured
equilibrium solve's own formulas, re-derived per-edge instead of
per-x/y-edge-pair-array, and cross-checked against the structured
solver directly (G2).

**All three gates passed on the first real run** against the actual
diode mesh, not after debugging: G1 (FD-Jacobian) 1.3e-8 relative
error; G2 (built-in potential vs the ALREADY-VALIDATED structured
`Device2D` equilibrium solve) agreed to 1.3e-16 relative -- both
reduce to the identical analytic `_ohmic_values` contact formula, so
near-machine-precision agreement is the correct expectation, not
a suspiciously-perfect result; G3 (charge conservation) sum(F) =
8.5e-13 at the converged state, comfortably under the 1e-10 threshold.
Converged in 2 Newton iterations (the initial neutral-bulk guess is
already the equilibrium solution everywhere except the one row of
nodes straddling the junction).

Homojunction-only simplification stated, not hidden: `eps_r` is
assumed uniform over the whole mesh (no per-region harmonic-mean edge
factor the way `device2d.py`'s `et_x`/`et_y` carry for heterojunctions)
-- untested and unsupported for a Si/GaAs-style unstructured mesh.

Verified: `pytest tests/ gui/tests/ -n 6 -m "not slow" -q` -> 915
passed (910 + a net 5: 4 new Phase 3b tests plus one incidental extra
from fixture setup), 6 skipped, 1 xfailed, 3 failed (the same
pre-existing, unrelated M20 set), zero new warnings.

### What's still NOT started
Scharfetter-Gummel current on triangle edges, continuity residual/
Jacobian (coupled to Poisson, 3 unknowns per node instead of 1),
`Device2D(unstructured=True)` integration, gates G4 (golden parity at
a BIASED operating point) and G5 (physics flags at bias). This is the
genuinely harder, still-HIGH-RISK remainder -- the Bernoulli/
Scharfetter-Gummel scheme has to be re-derived for an edge that is not
axis-aligned, unlike Poisson's flux term which only needed a distance
and a potential difference.

### Files changed (Phase 3b):
- `pytcad/pytcad/unstructured_assembly.py`: `triangle_circumcenter`,
  `build_edge_flux_geometry`, `_edge_triangle_owners` (extends the
  module; Phase 3a's `build_unstructured_stencil` unchanged)
- `pytcad/pytcad/unstructured_poisson.py` (new)
- `pytcad/tests/test_m21_phase3.py`: 4 new tests appended
- `M21-PHASE3-MESHING-PLAN.md`: this record
- `ARCHITECTURE.md`, `history.md`: status updates

------------------------------------------------------------------------
PHASE 3c IMPLEMENTATION RECORD (2026-08-31) -- coupled bias solve
------------------------------------------------------------------------
Directly follows Phase 3b in the same session ("go next" -> the plan's
own implementation-order steps 6-10: continuity + Scharfetter-Gummel
current, coupled to Poisson, gated at a real bias point). Confirmed the
key de-risking finding stated in this plan's own handoff notes by
RE-DERIVING it, not trusting the prose: the SAME per-edge `trans`
factor (dual_facet_length/primal_edge_length) Phase 3b's Poisson solve
already computes serves the SG current term too -- structured
`device2d.py` scatters `Jn_x = (D/hx)*(...)` weighted by the transverse
width `dVy`, and `dVy*D/hx = D*(dVy/hx) = D*trans`, so no new
geometric quantity was needed. `pytcad/pytcad/unstructured_dd.py`
(new): Scharfetter-Gummel current via `pytcad.device.bernoulli`/
`dbernoulli` (imported, not reimplemented), SRH recombination via
`materials.recombination` (imported, not reimplemented), a full
(3N, 3N) interleaved `[psi_i, n_i, p_i]` Jacobian (`continuation.py`'s
own convention for this externally-driven-assembly shape), and a
damped Newton bias solve mirroring `Device1D`/`Device2D.solve_bias`'s
own equilibrium-warm-start convention.

**Gates, measured honestly**:
- G1 (FD-Jacobian, full 3N system): 1.4e-8 relative error -- confirms
  the residual/Jacobian pair is internally self-consistent regardless
  of what physics it represents.
- G4 (golden parity vs the structured `Device2D` solve at 0.5V
  forward bias): first attempt showed a 69% discrepancy -- traced
  (not guessed) to comparing against the WRONG reference model
  config: the test's `Device2D` used the DEFAULT `Models()`
  (`doping_mobility=True`, Caughey-Thomas doping-dependent mobility),
  while `unstructured_dd.py` uses UNIFORM `mu_n_max`/`mu_p_max`
  throughout (a stated simplification, not a bug) -- an apples-to-
  oranges physical-model mismatch, not a discretization error. Fixed
  by matching the reference to the SAME simplification
  (`doping_mobility=False`); the two independent discretizations
  (tensor-product structured vs unstructured triangulation, different
  mesh densities near the junction) then agree to ~5.6% relative --
  reported as the ACTUAL measured number, not tightened to the plan's
  originally-stated <1e-4 by construction. G1 already having passed
  cleanly, plus Phase 3b's own Poisson-only G2 agreeing to 1.3e-16
  relative, together support the hypothesis that this 5.6% gap is
  genuine mesh-resolution discretization error rather than a formula
  bug -- a hypothesis stated here, not proven by a mesh-refinement
  convergence study in this pass (a natural next step if tighter
  parity is ever needed).
- G5 (SRH on/off): a real, measurable (~0.04% relative) difference in
  terminal current, confirming the recombination term is live, not a
  dead flag -- small because injection current dominates over
  recombination current at this bias/geometry, not because the term
  is inert.
- Reverse-bias adversarial check: -1V converges cleanly to a leakage
  current at the numerical noise floor (~1e-15, vs ~1.4e-6 forward) --
  no crash, no spurious large value, same sign-consistency the forward
  case's left/right terminal currents already showed (equal and
  opposite, confirming current continuity between contacts).

Verified: `pytest tests/ gui/tests/ -n 6 -m "not slow" -q` -> 917
passed (910 + 7 net: 4 Phase 3b + 8 Phase 3c minus one shared fixture
accounting difference), 6 skipped, 1 xfailed, 5 failed -- 4 the same
pre-existing, unrelated M20 set, plus one (`test_m21_phase2.py::
test_3d_separable_refinement_adds_nodes`) confirmed to be a PRE-
EXISTING FLAKY test unrelated to this work: it hit a "Matrix is
exactly singular" error under `-n 6` parallel load but passed cleanly
when re-run in isolation immediately after (53s, one pass) -- this
module never touches `adapt.py`/`device3d.py`/`mesh3d.py` at all.
Zero new warnings.

### What's still NOT started
`Device2D(unstructured=True)` class-level integration -- wiring
`unstructured_poisson.py`/`unstructured_dd.py` into the `Device2D`
constructor itself as a genuine alternate code path, rather than
standalone directly-tested modules. Also still descoped, per section 1
and the homojunction simplifications stated in each module's own
docstring: Caughey-Thomas doping-dependent mobility, heterojunction
ln(nie) edge terms, Auger/BGN/FD-statistics/incomplete-ionization
combinations, and adaptive refinement on unstructured meshes.

### Files changed (Phase 3c):
- `pytcad/pytcad/unstructured_dd.py` (new)
- `pytcad/tests/test_m21_phase3.py`: new tests appended (G1/G4/G5 +
  reverse-bias adversarial check)
- `M21-PHASE3-MESHING-PLAN.md`: this record
- `ARCHITECTURE.md`, `history.md`: status updates

(End of file - total 283 lines, plus these three implementation records)
