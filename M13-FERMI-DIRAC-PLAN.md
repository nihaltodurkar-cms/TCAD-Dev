
------------------------------------------------------------------------
5. GATE-TO-TEST MAP (red tests written on approval, in this order)
------------------------------------------------------------------------
  G1  test_fermi_half_vs_quadrature
      test_fermi_half_smoothness
      test_fermi_half_published_spot_values
  G2  test_fermi_half_boltzmann_limit
      test_fd_on_boltzmann_regime_equivalence
  G3  test_fermi_half_sommerfeld_asymptotics
      test_fd_degenerate_neutrality_root
  G4  test_fd_uniform_neutrality_vs_independent_root
      test_fd_generalized_mass_action
      test_fd_built_in_potential_degenerate_junction
  G5  test_fd_jacobian_1d_degenerate_step
      test_fd_jacobian_1d_heterointerface
      test_fd_jacobian_incomplete_ionization
      test_fermi_inverse_derivative
  G6  test_fd_off_bit_identical_goldens_1d   (+ _2d, _3d at port time)
      test_fd_on_nondegenerate_density_agreement
      test_fd_off_tat_hetero_bit_identity
  G7  test_fd_degenerate_concentration_vs_published
      test_incomplete_ionization_boron_vs_literature
      test_freeze_out_directional_gate
      test_fd_degenerate_cv_max_direction
  G8  full-suite run (the standing invariant)

Ordering inside the list is the implementation order: fermi.py (G1-G3)
is independently mergeable BEFORE any core edit; the solver gates
(G4-G6) follow; G7's published benchmarks may be written red at any
time (they only need fermi.py + the solver once it exists).

------------------------------------------------------------------------
6. AMENDMENT MECHANISM (unchanged from M11-S3 precedent)
------------------------------------------------------------------------
M13 modifies the residual/Jacobian of all three device cores.  Per the
standing rule this requires explicit user sign-off recorded in this
file before the first core edit, with:
  - goldens committed BEFORE the edit (G6a),
  - FD-Jacobian gate run FIRST on the new physics (G5),
  - bit-identity proven for the off-path (G6a/c) before any feature
    composes with it.
fermi.py itself is a pure addition and needs no amendment.

------------------------------------------------------------------------
7. DEPENDENCY CLEANLINESS (explicit)
------------------------------------------------------------------------
- M13 depends on: nothing outside the current tree.
- M13 blocks: M15 (impact ionization coupling), M16 (BTBT), M17
  (transient), M18 (AC), M19 (self-heating), M20 (DG) -- none of
  these may START (not even red tests that assume FD internals)
  until every gate in section 4 is green and the suite invariant
  holds.  M11-S4/S5 and the M12-S2 closeout are independent and may
  proceed in parallel.
- M13 must not change: defaults, scalings, tolerances, DeviceSpec,
  the subprocess contract, or any GUI data path.

------------------------------------------------------------------------
8. HONEST LIMITS TO SHIP WITH THE MILESTONE
------------------------------------------------------------------------
- Parabolic-band statistics; degenerate wide-gap or strained-Si
  bandstructure is out.
- BGN composition convention is pinned as: FD applies to the
  (Nc, Nv) of the material object; Slotboom BGN continues to enter
  through nie_eff exactly as today; their product is an
  APPROXIMATION of the true heavily-doped density of states and is
  labeled as such in the catalog.
- Frozen-field TAT + FD is untested territory until composed; the
  composition gets its own bit-identity + Jacobian test at M15/M16
  time, not now.
- No claim of Sentaurus numerical-method parity (their FD-SG scheme
  details are proprietary); we gate on the physics properties, not
  on matching their discretization.
