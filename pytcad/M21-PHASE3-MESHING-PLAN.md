# M21-PHASE3-MESHING-PLAN.md
# M21 Phase 3: General unstructured 2D + Delaunay FV assembly
# Formal milestone spec

Status: **NOT STARTED.** Phases 1-2 (1D/2D/3D separable adaptive h-refinement)
SHIPPED. Phase 3 geometry foundation VALIDATED (gmsh conformality check in
examples/debug_geometry_gmsh_conformality.py). This plan covers Phase 3 only.

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

(End of file - total 283 lines)
