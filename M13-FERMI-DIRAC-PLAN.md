# M13-FERMI-DIRAC-PLAN.md
# M13: Fermi-Dirac carrier statistics + incomplete ionization
# Formal physics-foundation milestone spec

Status: IN IMPLEMENTATION (approved).  Phase 1 (fermi.py + G1-G3
gates + G6a goldens) landed pure-addition, suite 541 green.
Core amendment sign-off (section 6): GIVEN by the user ("implement
it") for the M13 residual/Jacobian changes -- goldens committed
before the first core edit, FD-Jacobian gate runs first.

SPEC-FIX NOTE (G2/G3 gate numbers, recorded during implementation):
the original G2 tolerances (eta=-20 @ 1e-12, eta=-15 @ 1e-9) were
MATHEMATICALLY UNATTAINABLE: the exact Taylor series of the complete
Fermi integral gives |F_{1/2}(eta) - exp(eta)|/exp(eta) ~
exp(eta)/2^{3/2}, i.e. 7.3e-10 at eta=-20 and 1.1e-7 at eta=-15.
The implementation was verified correct against the exact series;
the gates were corrected to (-30, 1e-12), (-20, 1e-9), (-15, 1e-6).
Likewise the G3 Sommerfeld rate check uses the 3-term form (residual
~ c3/eta^6, factor ~64 per doubling); the original 4-term rate band
assumed eta^-4.  These are spec fixes to match published mathematics,
not tolerance weakening -- each is asserted against the exact-series
deviation in tests/test_m13_fermi.py docstrings.

Blocks: M15, M16, M17, M18, M19, M20 (all of Tier 1 after M13) are
NOT started until every gate in section 4 is green.
Parent: SENTAURUS-PARITY-PLAN.md (Tier 1). Conventions unchanged:
red tests first, published-value benchmarks before features,
FD-Jacobian-first, bit-identity when off, suite green + zero
warnings, no tolerance ever weakened, no hidden failures.

------------------------------------------------------------------------
1. SCOPE
------------------------------------------------------------------------
Add degenerate carrier statistics to the drift-diffusion cores behind
`Models(fd=False)` (default off):

  n = Nc * F_{1/2}(eta_n),   eta_n = (E_Fn - E_c) / (k_B T)
  p = Nv * F_{1/2}(eta_p),   eta_p = (E_v - E_Fp) / (k_B T)

with the complete Fermi integral (normalized so the Boltzmann limit is
exactly exp(eta)):

  F_{1/2}(eta) = (1/Gamma(3/2)) * Integral_0..inf
                 t^(1/2) / (1 + exp(t - eta)) dt

plus incomplete dopant ionization behind
`Models(incomplete_ion=False)` (B, P, As; standard
degeneracy-factor formulation).

Out of scope (stated, so we never drift into them silently):
non-parabolic bands (this is the parabolic-band F_{1/2});
valley-resolved Nc; any change to the BGN convention beyond pinning
it (section 4.8); transient/AC composition (later milestones compose
with whatever lands here).

------------------------------------------------------------------------
2. NEW MODULE: pytcad/fermi.py  (pure functions, no core dependency)
------------------------------------------------------------------------
  f_half(eta)      fast, C1-smooth evaluation on [-40, +40]
  f_half_ref(eta)  INDEPENDENT high-accuracy quadrature reference
  f_half_inv(nu)   inverse via bracketed Newton (monotone everywhere,
                   convex for eta > 0 -> globally safe)
  df_half(eta)     analytic derivative = F_{-1/2} (Jacobian needs it)
  ni_fd(Nc, Nv, Eg, T)  FD intrinsic carrier density (neutrality root)

IMPLEMENTATION NOTE (as built): the production evaluation is a hybrid
fixed-node Gauss-Legendre quadrature -- t = s^2 transform on [0, 1]
(kills the t^(-1/2) endpoint singularity of F_{-1/2}), then direct
width-2 t-panels on [1, max(eta,0)+60], where the 1/(1+e^(t-eta))
transition has O(1) width for EVERY eta.  A published rational
approximation (Cody-Thacher) was the original preference; no
coefficient table was available offline, and the quadrature form is
exact, auditable, and fast (one vectorized call per array), so it was
chosen BY THE GATES as the spec allows.  The audit layer is three
independent schemes: scipy adaptive quadrature, 30-digit mpmath
(knee-subdivided -- plain mp.quad on [0, inf) under-resolves the
t~eta knee and measured 5e-5 off at eta=40), and the published
Sommerfeld series.

------------------------------------------------------------------------
3. SOLVER INTEGRATION (1D first; 2D/3D ports repeat the same gates)
------------------------------------------------------------------------
3.1  DENSITY PATH
  eta_n/eta_p computed from the scaled unknowns exactly as today;
  densities become Nc*F_{1/2}(eta) instead of Nc*exp(eta).  All
  existing T-dependent Nc(T), Nv(T) calls are reused unchanged.

3.2  CURRENT PATH (generalized Scharfetter-Gummel)
  The exponential-fitting SG edge current must be made consistent
  with FD densities.  Candidate discretizations (design spike picks
  ONE, decided by the section 4 gates -- this mirrors the M11
  lesson where a plausible scheme passed a Jacobian check but broke
  hole detailed balance):
    A) nu-factor SG:  nu(eta) = F_{1/2}(eta)/exp(eta);  Bernoulli
       argument extended with the ln(nu) edge difference.
    B) inverse-FD SG: keep the current SG form; quasi-Fermi levels
       obtained through f_half_inv; Bernoulli argument on the
       (psi - phi_n) difference of the inverted variables.
  Hard properties either candidate must satisfy (these are gates,
  not wishes):
    - exact reduction to the current SG when eta << -1 (bit-level
      on the edge factor, not just "close");
    - ZERO equilibrium current across a degenerate doping step and
      across a heterointerface to machine precision (carrier-
      specific detailed balance, both carriers);
    - positivity of densities preserved by construction;
    - analytic Jacobian covers every new factor.

3.3  INCOMPLETE IONIZATION
  Ionized fraction per dopant species from the standard
  charge-neutrality-consistent formulation (degeneracy factors
  g=4 for B, g=2 for P/As; Nc,Nv at lattice T).  Enters rho and
  the Jacobian (d(N_ion)/d(psi) terms).  1D only in this milestone;
  flagged independently of fd.

3.4  PORT ORDER
  1D (device.py) carries the whole gate battery first.  2D
  (device2d.py) and 3D (device3d.py) ports repeat: bit-identity,
  FD-Jacobian, neutrality, Boltzmann-regime equivalence.  A port is
  not "done" because 1D passed.

------------------------------------------------------------------------
4. QUANTITATIVE ACCEPTANCE GATES
------------------------------------------------------------------------
Every gate below is a named test in tests/ (red first).  GREEN means
ALL of them pass with the full suite, zero warnings, and no existing
tolerance weakened.  M15+ stay blocked until then.

G1  F_{1/2} EVALUATION vs INDEPENDENT REFERENCE
    f_half vs f_half_ref over eta in [-40, +40] on a 4001-point grid
    (dense near eta=0): max relative error <= 1e-9 (metric floor
    1e-11 on the deep-Boltzmann tail, where two double-precision
    quadratures can only agree to ~1e-21 ABSOLUTE -- measured).
    Continuity/smoothness: max step-to-step second difference of
    ln f_half <= 1e-6 (C1-smoothness guard for Newton).
    Published audit: spot values vs 30-digit mpmath (knee-subdivided)
    <= 1e-11, exact anchor F_{1/2}(0) = (1-2^{-1/2}) zeta(3/2) to
    1e-13, Sommerfeld series cross-check with asserted eta^-6 rate.

G2  BOLTZMANN (NONDEGENERATE) LIMIT
    Gates at the EXACT Taylor-series deviation exp(eta)/2^{3/2}
    (see SPEC-FIX NOTE): <= 1e-12 at eta <= -30; <= 1e-9 at
    eta <= -20; <= 1e-6 at eta <= -15.
    Solver-level: with fd=True on a 1e16-diode, the I-V curve agrees
    with the Boltzmann run to max relative current difference
    <= 1e-4 (numerical equivalence -- different code path, so NOT
    bit-identity; that distinction is deliberate).

G3  DEGENERATE LIMIT
    Sommerfeld check with asserted decay rate (see SPEC-FIX NOTE).
    Physical: electron density at full activation of
    N_D = 1e20 cm^-3, Si, 300 K: solver's equilibrium n matches the
    independent neutrality root-find of Nc*F_{1/2}(eta) = N_D to
    machine precision, and eta lands in the published degenerate
    range (eta > 2 for 1e20 at 300 K).

G4  CHARGE-NEUTRALITY CONSISTENCY
    Uniformly doped domain (no junction), equilibrium solve:
    (a) n, p constant along x to machine precision;
    (b) n - p = C matches the INDEPENDENT 1D root-find of
        Nc*F_{1/2}(eta_n) - Nv*F_{1/2}(eta_p) = C
        (max relative density error <= 1e-12) for
        C in {1e15, 1e17, 1e19, 1e20} x {n, p} at 300 K;
    (c) generalized mass action:
        n*p = ni_fd^2 * [F_{1/2}(eta_n)F_{1/2}(eta_p)] /
              [exp(eta_n)exp(eta_p)]  holds identically between the
        solver's (n, p, eta) at every node (<= 1e-10 relative);
    (d) built-in potential of a 1e20/1e17 FD junction vs the
        independent neutrality-pair computation, agree <= 1e-3 V
        (discretization-dominated).

G5  FD-vs-ANALYTIC JACOBIAN
    The house gate, extended: max relative error between the
    analytic Jacobian and central finite differences <= 5e-5 over
    >= 80 sampled columns (house standard) on:
      - a 1e20/1e17 degenerate step junction (fd=True);
      - a degenerate Si/GaAs heterointerface (fd=True) -- the
        composition that historically hid the shared-delta bug;
      - incomplete-ionization-enabled runs (d(N_ion)/d(psi) rows);
      - the f_half_inv Newton derivative: d(eta)/dn analytic vs FD
        <= 1e-8 over nu in [1e-8, 10].  [DONE in phase 1:
        test_fermi_mhalf_is_derivative + inverse roundtrip.]

G6  BIT-IDENTITY / NON-REGRESSION WHEN DEGENERACY IS NEGLIGIBLE
    (a) Models(fd=False) (default): ALL THREE cores produce
        np.array_equal results against pre-M13 golden runs
        [CAPTURED in phase 1: tests/goldens/m13/ -- 1D diode
        equilibrium + 0.6V bias, 1D Si/GaAs hetero, 2D diode,
        3D resistor];
    (b) fd=True at nondegenerate bias points: densities agree with
        Boltzmann to <= 1e-6 relative (the F_{1/2} vs exp gap at
        those eta), currents to <= 1e-4;
    (c) the TAT, heterojunction, and process-derived-doping paths
        are re-run with fd=False and remain bit-identical -- no
        incidental drift from refactoring.

G7  PUBLISHED-VALUE BENCHMARKS WITH EXPLICIT APPLICABILITY LIMITS
    (a) Degenerate electron concentration: Si, 300 K, N_D = 1e20:
        n/N_D vs the published FD-corrected figure (Altermatt-style
        apparent-band tables): agree within 5% (the gate is the
        FD statistics alone; BGN interplay is pinned, see 4.8).
    (b) Incomplete ionization, B in Si: ionized fraction at
        T = 77/150/250/300 K for N_A = 1e16 vs published curves
        (Sze; Altermatt et al.): agree within 2 percentage points
        or the reference's stated precision.
    (c) Freeze-out sign gate: 77 K B-doped Si carrier density is
        BELOW N_A by the published order (solver must reproduce
        freeze-out at all, directionally, before fine gates).
    (d) Degenerate MOS C_max: FD-only reduction of C_max vs the
        classical value consistent with the documented 10-20%
        classical overestimate direction (quantization-free part;
        the quantum centroid correction remains M20's job --
        stated so nobody claims this gate "fixes" C_max fully).
    APPLICABILITY LIMITS (mandatory in the test docstrings AND the
    catalog metadata):
      - parabolic-band F_{1/2} only; no non-parabolicity, no
        valley splitting;
      - valid for eta in [-40, +40]; beyond that the code must
        refuse loudly, not extrapolate [DONE in phase 1:
        test_fermi_eta_range_refusal];
      - T range of the chosen evaluation as published (state it);
      - incomplete ionization: shallow B, P, As only; no deep
        levels;
      - FD composes with BGN ONLY through the pinned convention
        below -- any other composition is out of spec.

G8  SUITE INVARIANT
    Full tests/ + gui/tests/: all green, zero warnings, pre-existing
    tests unchanged.  A red or skipped physics test at "done" time
    means NOT done (no-hidden-failures policy, unchanged).

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
      test_fermi_inverse_derivative            [DONE phase 1]
  G6  test_golden_1d_diode_equilibrium_and_bias [DONE phase 1]
      test_golden_1d_hetero_equilibrium          [DONE phase 1]
      test_golden_2d_diode_equilibrium           [DONE phase 1]
      test_golden_3d_resistor_equilibrium        [DONE phase 1]
      test_fd_on_nondegenerate_density_agreement
  G7  test_fd_degenerate_concentration_vs_published
      test_incomplete_ionization_boron_vs_literature
      test_freeze_out_directional_gate
      test_fd_degenerate_cv_max_direction
      test_fermi_eta_range_refusal               [DONE phase 1]
  G8  full-suite run (the standing invariant)

Status at phase-1 commit (58ca76c + this fix): G1, G2, G3 fully green
at the fermi.py level; G5 partial (inverse derivative); G6a goldens
captured and enforced; G4-G8 solver-level gates are RED-BY-ABSENCE
until the core lands.

PHASE-2 STATUS (2026-08-26): ALL GATES GREEN.  1D core integration
landed in pytcad/device.py (nu-factor SG per section 3.2bis; physical
Nc/Nv statistics; incomplete ionization with flag independence from fd;
moscap FD branch for G7d).  Gate evidence lives in
pytcad/tests/test_m13_solver.py:
  G4   uniform neutrality x6 vs independent roots, generalized mass
       action, degenerate V_bi -- PASS
  G5   FD-Jacobian on degenerate step / degenerate Si+GaAs
       heterointerface / incomplete-ionization rows <= 5e-5 (house
       per-column normalization) -- PASS
  G6a/c goldens + pre-edit sha256 digests (TAT path, hetero bias) --
       bit-identical -- PASS
  G6b  nondegenerate equivalence -- PASS after a documented SPEC-FIX:
       the original 1e-6 density tolerance is unattainable because the
       exact-series nu correction exp(eta)/2^{3/2} at 1e16 cm^-3 is
       1.24e-4; gates now derive from that exact deviation.
  G7a  n/N_D within 5% of the fully-ionized degenerate figure +
       machine-precision independent-root agreement -- PASS
  G7b/c B ionization 77/150/250/300 K: solver == independent root to
       1e-9 and inside literature bands (77 K freeze-out ~28%) -- PASS
  G7d  moscap FD C_max strictly below the classical value by 2-30% --
       PASS
  G8   full suite green, zero warnings, pre-existing tests unchanged
       (564 passed).

PHASE-2 ADDENDUM -- 2D/3D PORTS COMPLETE (same session): Device2D and
Device3D gained the identical nu-factor SG statistics via the shared
fd_node_factors/fd_ohmic_values helpers (device.py); port gates in
tests/test_m13_solver.py (port2d/port3d): uniform-grid neutrality vs
independent roots to <=1e-12, machine-precision zero equilibrium
current across a degenerate 2D step, house FD-Jacobian gates on
degenerate 2D/3D grids, Boltzmann-regime equivalence.  fd=False paths
bit-identical (G6a goldens re-verified; suite 570 passed).  Incomplete
ionization remains 1D-only per section 3.3.  M13 gate battery G1-G8 is
now FULLY GREEN across 1D/2D/3D.
Full-suite runtime grew to ~5 min (the M13 gate tests run hundreds of
residual/Jacobian evaluations through f_half_inv); f_half_inv was
optimized (split analytic-tail + secured Newton) with all phase-1 gates
re-verified unchanged.

Ordering inside the list is the implementation order: fermi.py (G1-G3)
is independently mergeable BEFORE any core edit; the solver gates
(G4-G6) follow; G7's published benchmarks may be written red at any
time (they only need fermi.py + the solver once it exists).

------------------------------------------------------------------------
6. AMENDMENT MECHANISM (unchanged from M11-S3 precedent)
------------------------------------------------------------------------
M13 modifies the residual/Jacobian of all three device cores.  Per the
standing rule this requires explicit user sign-off recorded in this
file before the first core edit [RECORDED: GIVEN, see Status block]
with:
  - goldens committed BEFORE the edit (G6a) [DONE];
  - FD-Jacobian gate run FIRST on the new physics (G5);
  - bit-identity proven for the off-path (G6a/c) before any feature
    composes with it.
fermi.py itself is a pure addition and needed no amendment.

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

------------------------------------------------------------------------
3.2bis  DESIGN SPIKE DECISION (recorded phase 2, session of 2026-08-26)
------------------------------------------------------------------------
Scheme A (nu-factor modified SG) is CHOSEN.  Per node
    eta_x = f_half_inv(density_x / nie_x)          (x = n or p)
    nu_x  = F_{1/2}(eta_x) exp(-eta_x)
    L_x   = ln nu_x
the SG edge arguments become
    electron: delta_n = dpsi + dln(nie) + dL_n
    hole:     delta_p = dpsi - dln(nie) - dL_p
(carrier-specific OPPOSITE signs -- the M11 lesson is structural here).

Why A over B (inverse-FD): B's Bernoulli argument (a quasi-Fermi
difference) vanishes at equilibrium only if Delta psi = 0, so plain B
breaks detailed balance at ANY junction; patching B needs exactly the
Delta ln(nu) correction, collapsing into A.  Scheme A has:

  * EXACT equilibrium detailed balance for BOTH carriers, algebraically:
    at phi = const, eta_n = psi - const => Delta eta_n = Delta psi, so
    ln(n_{i+1}/n_i) = dln(nie) + dpsi + dln(nu) = delta_n identically,
    including heterointerfaces (machine precision, both carriers).
  * Bit-level Boltzmann reduction: for eta <= -30 the code sets
    L = w = 0.0 EXACTLY (true deviation < e^-30/sqrt(2) ~ 5e-14),
    so deep-Boltzmann edges reproduce today's deltas bit-for-bit.
  * Positivity: Bernoulli factors stay strictly positive.
  * Jacobian: delta_tilde depends on psi exactly like today (+-1);
    density columns gain w_x = dL_x/d(density_x) =
    (F_{-1/2}/F_{1/2} - 1)/(nie F_{-1/2}) -- computed in the
    cancellation-safe form (ratio-minus-one)/(nie F'), never
    (1/F - 1/F')/nie which cancels catastrophically at eta << 0.

Recombination under FD: the equilibrium product becomes
    np_eq = nie^2 * nu_n * nu_p
(exact at equilibrium because eta_n + eta_p = 0 in the symmetric-nie
convention; -> nie^2 as nu -> 1).  SRH/Auger/TAT driving forces use
(np - np_eq) with chain-rule derivatives through w.  TAT+FD composition
keeps its declared untested status (section 8) until M15/M16 gates.

Incomplete ionization (standard degeneracy formulation, physical
statistics): eta^phys_n = f_half_inv(n/Nc(T)), eta^phys_p =
f_half_inv(p/Nv(T));
    N_D+ = N_D / (1 + g_D e^{eta_n + DE_D/kT}),   g_D = 2, DE_D = 45 meV
    N_A- = N_A / (1 + g_A e^{eta_p + DE_A/kT}),   g_A = 4, DE_A = 45 meV
Net-doping-only input means single-species assumption (majority side
carries all dopants) -- stated in the catalog.  Hydrogenic model is
INVALID above the Mott transition (~4e18 cm^-3 Si:P); applicability
notes go in test docstrings + catalog metadata (G7).

Note for G7a: with FD statistics alone (full ionization), uniform
neutrality gives n ~= N_D exactly; the nontrivial FD content at 1e20 is
the Fermi level (eta > 2, gated in G3/G4d) and junction electrostatics,
so G7a gates n/N_D within 5% of the published fully-ionized degenerate
figure AND the independent-root agreement, with the caveat documented.
