# M12 -- Tunneling & Quantum Corrections -- Milestone Plan

Status: PLANNING (no code).  Follows the M11 pattern: staged slices,
published-value gates before anything ships, catalog metadata required,
honest limits documented.

Depends on: nothing in M11 (oxide tunneling is MOS-side; quantum
corrections touch Device1D separately).  Can proceed in parallel.

------------------------------------------------------------------------
1. SCOPE -- the four items
------------------------------------------------------------------------
T-A  DIRECT TUNNELING through thin dielectrics
     Physics: WKB transmission through the truncated barrier,
     T ~ exp(-2 integral kappa dx), kappa(x)=sqrt(2 m*(phi(x)-E))/hbar;
     current from thermionic supply function times T.
     Where it lives FIRST: analysis layer (workbench/physics/) as a
     post-processing diagnostic on any solved MOS structure -- no Newton
     changes needed because the oxide field comes from the solved
     potential drop across the oxide.
GATE S1a: WKB decay constant kappa for SiO2 (m* = 0.42 m0, barrier
     3.1 eV) must land in the published 0.55-0.65 inverse-angstrom
     band; direct-tunnel current density at (tox=2 nm, Vox=2.5 V)
     within the widely reproduced ~0.1-1 A/cm^2 band (multiple
     independent experimental sources).
GATE S1b: FN plot linearity -- ln(J/E^2) vs 1/E must be straight with
     slope -B*phi^1.5 recovered to <1% (the defining FN signature).

T-B  FOWLER-NORDHEIM (high-field limit of T-A)
     J = (A E^2 / phi) exp(-B phi^{3/2} / E), universal constants
     A = 1.541e-6 [A eV V^-2], B = 6.831e9 [eV^-3/2 V m^-1].
     GATE S1c: constants verified against their physical definitions
     (A from free-electron supply function, B = 4 sqrt(2 m0)/(3 q hbar));
     extracted slope/intercept round-trip.
S1 SHIPS TOGETHER: workbench/physics/tunneling.py +
     tests/test_model_benchmarks.py gates + catalog entries.

T-C  TRAP-ASSISTED TUNNELING (S2)
     SRH-style trap kinetics with capture cross-sections PLUS a
     tunnelling probability to/from the trap (WKB over part of the
     gap).  This is a RECOMBINATION-MODEL extension -- it enters the
     Newton assembly (device cores), so it follows the M8/M11-S3 rule:
     finite-difference Jacobian extension FIRST, homojunction
     regression second, published TAT-benchmark third.
GATE S2: lifetime-extraction consistency (effective lifetime vs trap
     depth/position matches published SILC-style dependencies).

T-D  OPTIONAL QUANTUM CORRECTIONS (S3)
     Density-gradient (DG) quantum correction term added to Poisson as
     a selectable ModelCatalog flag (default OFF -- zero behavior
     change until enabled).  Validated against the standard DG
     benchmark: inversion-layer charge centroid shift reproducing the
     ~1 nm offset and Cmax reduction quoted in README section 1.
GATE S3: DG-off runs bit-identical (flag default); DG-on centroid
     shift within published range; Jacobian FD-verified.

------------------------------------------------------------------------
2. ORDER & EFFORT
------------------------------------------------------------------------
S1 (T-A+T-B): SMALL -- pure functions, no solver coupling, immediately
   actionable next session.
S2 (TAT): MEDIUM-LARGE -- touches cores; same discipline as M11-S3.
S3 (DG): LARGE -- modifies Poisson assembly; only after S2 proves the
   core-extension playbook again.

------------------------------------------------------------------------
3. HONEST LIMITS FROM DAY ONE
------------------------------------------------------------------------
- Analysis-layer S1 numbers are DIagnostics, not self-consistent
  solver currents: they tell you what the oxide leakage IS at the
  solved field, not a coupled boundary condition.
- No quantum-mechanical solver (Schrodinger/Poisson) is planned;
  DG is a moment correction, not QM.
- Gate materials other than poly-Si need work-function handling that
  already exists (flatband_voltage).

------------------------------------------------------------------------
4. RULE AMENDMENT
------------------------------------------------------------------------
S2/S3 modify device cores -> requires the same explicit sign-off
mechanism as M11-S3 (HETEROSTRUCTURE-PLAN.md section 4).  S1 needs
nothing and can start immediately.

------------------------------------------------------------------------
5. S2/S3 DESIGN NOTES (from the code audit -- implement directly)
------------------------------------------------------------------------
S2 TRAP-ASSISTED (core extension; needs section-4 sign-off):
- Injection point: pytcad/device.py `_residual_jacobian`, extending the
  recombination block exactly like M11-S3 extended Poisson/continuity.
  Model: trap level E_t (default mid-gap); capture rates
      c_n = sigma_n * v_th * n(x), c_p likewise;
  occupancy N_t from steady-state balance including the tunneling
  escape/addition probabilities
      P_n(x->surface) = exp(-2 int kappa dx)  [WKB over the barrier
      portion between trap and contact/oxide].
- Residual contribution enters BOTH continuity equations as
  R_TAT - G_TAT with the SAME sign conventions as SRH (verified
  against test_global_charge_neutrality-style checks).
- Jacobian: analytic w.r.t. n/p; the WKB factors are fixed wrt psi
  ONLY if the field is frozen -- for self-consistent fields include
  d(kappa)/d(psi) or accept frozen-field first slice (document!).
- FIRST RED TEST: extend tests/test_validation.py FD-Jacobian to a
  device with traps enabled; homojunction-without-traps must remain
  bit-identical.
- Benchmark gate: SILC-style effective-lifetime vs trap-position curve
  against published dependencies.

S3 DENSITY-GRADIENT (core extension):
- Add quantum potential Lambda^2 * grad^2(sqrt(n)) / sqrt(n) term to
  the electron/hole continuity equilibrium expressions as a Model-
  Catalog flag `density_gradient` (default False -> bit-identical).
- Lambda^2 = hbar^2/(12 m* q) material property -> Semiconductor gains
  an m* field (conductivity-band and valence-band effective masses).
- FD-Jacobian extension first (the grad^2(sqrt n) stencil is wide --
  five-point); then centroid-shift benchmark (~1 nm inversion offset,
  Cmax reduction quoted in README section 1).

BOTH SLICES: catalog entries with equations/references/applicability;
honesty notes that TAT trap densities are fitting parameters unless
measured; DG is a moment correction, not QM.
