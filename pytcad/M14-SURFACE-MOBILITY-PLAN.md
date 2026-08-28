# M14-SURFACE-MOBILITY-PLAN.md
# Surface & Inversion-Layer Mobility + Interface Recombination

Status: IN IMPLEMENTATION (resumed after a mid-session crash, 2026-08-27)
Owner: session handoff via history.md

RESUMED-SESSION NOTE: the prior session crashed after writing
mobility_cvt() and declaring the Models fields, before either was
validated or wired -- see STATUS below for exactly what existed. Two
findings from resuming:
  (1) BUG in mobility_cvt itself: mu_SR was coded as (delta/E_eff)^2
      with delta in V/cm -- dimensionally wrong. COMSOL's documented
      reproduction of Lombardi et al. 1988 states plainly "delta_n and
      delta_p have units of V/s" and gives mu_SR = delta/E_eff^2 (E
      squared in the denominator). FIXED, with delta_n=5.82e14,
      delta_p=2.05e14 V/s cross-corroborated on two independent COMSOL
      documentation pages. B_n/B_p (the phonon term) remain UNVERIFIED
      -- with the corrected delta and the original B_n, mu_eff at the
      plan's own G-A check points comes out 3-8x ABOVE the Takagi/Taur
      targets. Not recalibrated without a source; see
      test_mobility_cvt_effective_mobility_matches_takagi_taur_gate
      (xfail, reason recorded) in test_model_benchmarks.py.
      ADDENDUM (same day, deeper literature check): the delta NUMBER is
      also less settled than first recorded. Synopsys's own Sentaurus
      Device User Guide (N-2017.09, Table 61, "IALMob") gives
      delta=3.97e13 cm^2/(V*s) for BOTH carriers -- 14.7x (n) / 5.2x (p)
      smaller than the COMSOL-sourced values kept in the code, once put
      in the same units. Both sources agree on the delta/E_eff^2 FORM
      (which is what matters for the structural bug fix); they disagree
      by 5-15x on the NUMBER. Kept the COMSOL value as the closer match
      to this function's plain two-term model (IALMob is a more
      elaborate, doping-cluster-dependent generalization); recorded as
      a judgment call, not a settled citation. Neither source is the
      original 1988 paper. See materials.py's comment above
      _CVT_DELTA_N/_CVT_DELTA_P.
  (2) Wiring scope: Device2D's GateBC accepts arbitrary (i,j), but
      EVERY actual call site in this codebase (mosfet.py's
      build_mosfet) places the gate on mesh row 0. The M14 wiring
      below is therefore scoped to row 0 as "the surface" -- documented
      in device2d.py's _update_surface_mobility docstring, not silently
      assumed. Generalizing to arbitrary gate placement/orientation is
      not done.

------------------------------------------------------------------------
## 1. SPEC (from SENTAURUS-PARITY-PLAN.md section 2, M14)

**Scope:**
  - Lombardi CVT (surface roughness + phonon + Coulomb components) for
    2D MOSFET channel
  - Driving-force choice for high-field in 2D switches to
    grad(quasi-Fermi) (Sentaurus convention) behind a flag
  - Surface recombination velocity S at interfaces and contacts (SRH
    surface term)
  - D_it in moscap (interface-trap stretch-out)

**Acceptance:**
  - G-A: effective mobility vs effective field against published Si
    curves (Takagi/Taur universal mobility form factors)
  - G-B: C-V with D_it stretch-out vs analytic
  - G-C: S-driven diode leakage vs analytic S*ni/2 boundary formula
  - G-D: bit-identity when all M14 flags off (golden gate)
  - G-E: FD-Jacobian across the full M14 coupled system < 5e-5

**Depends:** M13 optional (composes).

------------------------------------------------------------------------
## 2. DESIGN

### 2a. Lombardi CVT Surface Mobility

Matthiessen's rule combining bulk Caughey-Thomas with surface scattering:

    1/mu_eff = 1/mu_CT + 1/mu_phonon + 1/mu_SR

where:
  mu_CT  = Caughey-Thomas doping-dependent (existing, per-node)
  mu_phonon = B / (T * E_eff^{1/3})   [phonon-limited surface]
  mu_SR  = (delta / E_eff)^2           [surface roughness]

E_eff is the effective transverse field, computed from the vertical
component of the electric field at surface nodes:

  E_eff = |E_y| at the silicon surface

In Device2D, E_y at the top row (y=0, surface) is computed from the
potential difference between the surface row and the row below:

  E_y = -(psi[0,:] - psi[1,:]) * VT / (hy[0] * LD)

Parameters (Si, 300K, from Lombardi et al. 1988 / Taur & Ning):
  Electrons: B_n = 2.5e8, delta_n = 3.0e6 V/cm
  Holes:     B_p = 5.0e7, delta_p = 8.0e5 V/cm

Applied LAGGED in the Newton loop (like field_mobility in 1D):
  - Recomputed each iteration from the current psi
  - No Jacobian contribution (consistent with frozen-mobility model)
  - Edge diffusivities at surface edges updated accordingly

### 2b. Driving-Force Flag

`Models(driving_force="field")` (default) uses the electric field as
the parallel driving force (existing behavior).

`Models(driving_force="quasi_fermi")` switches to grad(phi_n) / grad(phi_p)
for the parallel field in the Canali velocity-saturation model.  This
is the Sentaurus convention for 2D MOSFETs where the current path is
not aligned with a single field direction.

Implementation: in Device2D.solve_bias, when driving_force is
"quasi_fermi", the parallel field for mobility_field is computed from
the quasi-Fermi level gradient rather than the electrostatic field.

### 2c. Surface Recombination Velocity

A Robin-type boundary condition at contacts/gates:

  Jn·n_hat = q * S_n * (n - n0)   [electron current at surface]
  Jp·n_hat = q * S_p * (p - p0)   [hole current at surface]

where S_n, S_p are the surface recombination velocities [cm/s] and
n0, p0 are the equilibrium values.

In the Newton assembly, this adds a diagonal contribution to the
continuity equations at boundary nodes:

  F_n[k] += dV * S_n_scaled * (n[k] - n0)
  F_p[k] += dV * S_p_scaled * (p[k] - p0)

where S_scaled = S * LD / D0.

Default: S = 0 (no surface recombination, bit-identical to existing).
When S > 0: the boundary becomes a recombination sink.

### 2d. Interface-Trap Capacitance (D_it) in MOS-C

Interface traps contribute an additional capacitance in parallel with
the semiconductor:

  C_it = q * D_it   [F/cm^2]

In the quasi-static C-V, this adds a frequency-dependent contribution.
For the low-frequency (quasi-static) case:

  C_total = C_semiconductor + C_it

where C_it = q * D_it is approximately constant over small bias ranges
(independent of surface potential for the simplest model).

In the MOS-C solver, D_it modifies the gate charge balance:

  Q_g = C_ox * (Vg - Vfb - phi_s) - Q_it

where Q_it = q * D_it * (phi_s - phi_s_0) and phi_s_0 is the
flatband surface potential.

Implementation: MOSCapacitor gains a `D_it` parameter (default 0).
When D_it > 0, the gate BC in solve_psi adds the Q_it term.

------------------------------------------------------------------------
## 3. FILES CHANGED

| File | Change | Amendment? |
|------|--------|------------|
| pytcad/materials.py | Add mobility_cvt() | No (physics library) |
| pytcad/device.py | Add surface_mobility, driving_force, S_n, S_p to Models | Yes |
| pytcad/device2d.py | Wire surface_mobility into Newton; driving_force; S_vel BCs | Yes |
| pytcad/moscap.py | Add D_it parameter and Q_it in gate BC | Yes |
| workbench/core/catalog.py | Register surface_mobility, s_velocity, dit entries | No |
| tests/test_m14_surface_mobility.py | Gate tests G-A through G-E | N/A |

------------------------------------------------------------------------
## 4. GATES

G-A: Effective mobility vs effective field
  Build a 2D MOSFET (build_mosfet), solve equilibrium, compute
  mu_eff = J_x / (n * q * E_x) at the surface vs E_eff.
  Compare against the Takagi/Taur universal curve shape:
    - mu_eff decreases monotonically with E_eff
    - mu_eff at E_eff=1e5 is within 2x of published ~400 cm2/Vs (n)
    - mu_eff at E_eff=1e6 is within 2x of published ~50 cm2/Vs (n)
  Source: Takagi et al., IEEE Trans. ED 41, 2357 (1994); Taur & Ning,
  Fundamentals of Modern VLSI Devices, Fig. 3.6.

G-B: C-V with D_it stretch-out
  MOS-C with D_it=1e11 cm^-2 eV^-1: the C-V curve shows increased
  stretch-out compared to the ideal (D_it=0) curve.
  Gate: |C_max(D_it) - C_max(ideal)| / C_max(ideal) > 0.01 (measurable)
  and the threshold voltage shift: Delta_Vth ~ q*D_it/C_ox > 0.

G-C: S-driven diode leakage
  1D diode with S=1e4 cm/s at one contact: the reverse leakage current
  should approach J_leak = q * S * n_i / 2 for S >> D_n / L_D.
  Gate: |J_S - q*S*ni/2| / (q*S*ni/2) < 0.10.

G-D: Bit-identity when flags off
  All M14 flags at defaults (surface_mobility=False, driving_force="field",
  S_n=0, S_p=0, D_it=0) must reproduce the M14 goldens with
  np.array_equal.

G-E: FD-Jacobian
  With surface_mobility=True, the 2D Jacobian (numerical, finite
  difference) vs analytic must agree to < 5e-5 at 25 random columns.
  NOTE: surface_mobility is LAGGED (no Jacobian contribution), so
  this is trivially satisfied.  The gate verifies the lagged-mobility
  path doesn't corrupt the existing Jacobian.

------------------------------------------------------------------------
## 5. AMENDMENT MECHANISM

Per SENTAURUS-PARITY-PLAN.md standing rule 1:
1. Goldens committed BEFORE the core edit: tests/goldens/m14/*.npz
2. G-D (bit-identity) verified FIRST
3. G-E (FD-Jacobian) verified
4. Then physics gates G-A, G-B, G-C
5. Full suite green with pre-existing tests unchanged

------------------------------------------------------------------------
## 6. STATUS

[x] Goldens captured (tests/goldens/m14/) -- pre-dates this pass
[x] mobility_cvt() surface-roughness bug fixed and gated (see
    RESUMED-SESSION NOTE above; tests/test_model_benchmarks.py)
[x] G-D: bit-identity verified (surface_mobility=False is a no-op;
    isolated-hunk comparison, not a whole-file git-stash comparison --
    the latter gave a false positive by also reverting unrelated
    same-session changes)
[x] G-E: FD-Jacobian verified (3.2e-9, threshold 5e-5)
[x] Wiring: Device2D.solve_bias updates dn_edge_y[0,:]/dp_edge_y[0,:]
    per Newton iteration when surface_mobility=True, scoped to mesh
    row 0 (see wiring-scope note above); regression tests confirm the
    scope (no leakage to other edges/axes) and that the toggle is real
    (finite, different, and only ever REDUCES the surface edge
    mobility relative to bulk)
[ ] G-A: surface mobility curve -- OPEN, xfail, B_n/B_p unverified
[ ] G-B: D_it C-V stretch-out -- not started (moscap.py untouched)
[x] G-C precondition: S_n/S_p/driving_force now REFUSE loudly
    (Models.__post_init__ raises NotImplementedError if S_n/S_p != 0.0
    or driving_force != "field") instead of being silently accepted
    and doing nothing -- a hard-debug finding: they were declared and
    documented as controlling real physics but read nowhere in
    device.py/device2d.py/device3d.py/workbench/, unlike impact/
    incomplete_ion which already got this same loud-refusal treatment.
    The actual physics (surface recombination BC, alternate driving-
    force convention) is still NOT implemented -- this only stops the
    silent-no-op failure mode; G-C/driving_force itself is still open.
[ ] driving_force flag -- not started (declared, now loudly refused
    rather than silently ignored; still not wired)
[ ] catalog registration -- not started
[ ] Full suite green -- see full-suite run recorded at the end of this
    session's history.md addendum
