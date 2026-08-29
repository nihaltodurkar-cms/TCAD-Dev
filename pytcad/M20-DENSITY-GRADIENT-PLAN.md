# M20-DENSITY-GRADIENT-PLAN.md
# M20: Density-gradient quantum correction (= M12-S3, folded)
# Formal milestone spec

Status: **IMPLEMENTED 2026-08-29, LANDED-PENDING-VERIFICATION** (same
session standing as M16/M22-Schur: the user directed implementation
without test execution; every gate below is written but NOT run.  The
next session MUST run tests/test_m20_dg.py, the two M16 gate files,
test_m22_linsolve.py, and the full suite before treating this as
complete).

Gate-writing cross-check self-caught defects (all fixed in dg.py):
1. The 2D-DOS occupation multiplied by kT twice (dos = m*kT/(pi*hbar^2)
   is ALREADY m^-2); occupations came out ~1e-4 m^-2 and the N_total
   bisection bracket could never reach its target.
2. E_band in schrodinger_poisson_mos had the WRONG SIGN (+(psi-psi_b)*VT
   instead of -): the inversion well landed in the bulk.  Correct law:
   E_c - E_F = Eg/2 - (psi - psi_b)*VT.
3. The Hamiltonian's far-boundary diagonal was never assigned
   (`main[-1] = main[-1]` on np.empty garbage) -- nondeterministic
   eigensolve.  Now an explicit Dirichlet far wall (the states decay
   long before the bulk end).

Roadmap slot: ARCHITECTURE.md section 4b.2, "M20 DENSITY-GRADIENT
QUANTUM CORRECTION (= M12-S3, folded) [M]".

------------------------------------------------------------------------
1. MODEL (and its provenance, honestly stated)
------------------------------------------------------------------------
Density-gradient (DG) theory (Ancona & Stafford, IEEE TED-46, 1999;
Ancona, Superlattices & Microstructures 27, 2000 -- the standard
macroscopic quantum correction for drift-diffusion): the carrier
chemical potential gains the Bohm-type quantum potential

    Q_n(x) = -(gamma_n * hbar^2 / (2 m_n*)) * d2(sqrt(n))/dx2 / sqrt(n)   [J]

and the equilibrium density law becomes

    n = n_classical * exp(-Q_n / (k_B T))
    p = p_classical * exp(-Q_p / (k_B T))        (Q_p same form on p)

with gamma a calibration factor (Ancona's gamma; gamma=1 is the
uncalibrated Bohm value).  Published Si inversion-layer work calibrates
gamma per carrier to match full Schroedinger-Poisson; this
implementation exposes `dg_gamma` (default 1.0) and GATES the result
against the codebase's own self-consistent Schroedinger-Poisson solve
(dg.py) plus the literature ~1 nm centroid figure, rather than silently
assuming a calibration.

PROVENANCE CAVEAT (recorded, not hidden): the exact prefactor above is
the Bohm/Ancona form as commonly transcribed in TCAD literature.  The
web literature search could not be run this session, so the prefactor
is from model knowledge; the Airy-analytic gate (G-B) pins the
Schrödinger side, and the DG-vs-SP gate (G-C) pins the composition --
if either fails review, fix the constant deliberately, never silently.

PHYSICS SIGN CHECK (the reason the sign below is right): the ground
state of the triangular inversion well is psi ~ x*exp(-x/2*lambda), so
psi''/psi ~ -1/(lambda*x) < 0 near the interface, hence Q_n > 0 there
and n < n_classical: charge is PUSHED OFF the interface, the
physically-required direction.  A naive exp(-x/2*lambda) shape (no
node at the hard wall) would give the wrong sign -- the sign was
chosen from the ground-state shape, not from algebra convenience.

BOUNDARY CONDITIONS (deliberate, per ARCHITECTURE.md's M20 literature
note): Neumann on the quantum potential -- Lambda = 0 at both boundary
nodes of every 1D domain (ohmic contacts in Device1D, the Si/SiO2
interface + bulk contact in MOSCapacitor).  The literature note warns
the Dirichlet choice at ohmic contacts is less stable and physically
worse; Lambda=0 (Neumann-equivalent for the 3-point stencil used) is
the published-recommended choice and is gated by construction (G-D
peaks the correction OFF the boundary nodes).

------------------------------------------------------------------------
2. SCOPE
------------------------------------------------------------------------
S1 (analysis layer, pure): pytcad/dg.py
   - `quantum_potential(x, n, m_star, gamma)`: the Lambda(x) [V]
     discretization above (3-point second difference on the
     NON-uniform mesh, evaluated in physical cm with the SI hbar^2/2mq
     prefactor converted; Lambda clamped to +-LAMBDA_MAX=20*VT --
     deep-bulk minority densities make sqrt(n)''/sqrt(n) numerically
     wild and the clamp keeps the exponential finite).
   - `airy_triangular_well(F_V_cm, m_star)`: analytic Airy subband
     energies E_k and centroids <x>_k of a uniform-field well (the
     published-value reference).
   - `schrodinger_poisson(...)`: self-consistent 1D Schroedinger-Poisson
     inversion-layer solver (finite-difference Hamiltonian on the same
     non-uniform mesh, lowest states via scipy eigsh, 2D-DOS Boltzmann
     subband occupations, outer Poisson fixed point).  This is the
     published-value gate the milestone text requires.

S2 (MOSCapacitor, the milestone's own vehicle): `dg=False` flag.
   solve_psi gains a DG branch: Lambda_n/Lambda_p computed from the
   CURRENT density iterate (LAGGED inside the Newton loop -- same
   frozen-source architecture class as M12-S2 TAT), densities
   n*exp(-Lambda/VT) in rho, and an OUTER fixed-point loop rerunning
   the Newton solve until Lambda closes to 1e-6 scaled.  dg=False
   (default) is the EXACT prior code path -- bit-identity gate G-A.
   New accessor `inversion_centroid(Vg)`: the charge-weighted centroid
   of the DG-corrected inversion charge, the quantity the README
   section-6 caveat is about.

S3 (Device1D, amendment-rule core edit): Models(dg=False).
   - solve_equilibrium: DG slaved densities (same lagged-Lambda outer
     fixed point), Boltzmann path only (dg+fd composes by refusing --
     see limits).
   - solve_bias + Device2D/Device3D: raise NotImplementedError for
     dg=True (DG transport / higher-D is out of M20 scope; refusing
     loudly beats silently ignoring the flag, the standing rule since
     M13's incomplete_ion guard).

------------------------------------------------------------------------
3. ACCEPTANCE GATES (tests/test_m20_dg.py)
------------------------------------------------------------------------
G-A BIT-IDENTITY OFF: MOSCapacitor(dg=False) C-V arrays bit-identical
    to the pre-M20 constructor call; Models().dg is False; Device1D
    equilibrium psi/n/p bit-identical with and without the dg flag's
    off-path (two fresh devices, array_equal).
G-B AIRY ANALYTIC: dg.schrodinger_poisson on a pure triangular well
    reproduces the Airy E_1 and <x>_1 within 5% (uniform mesh, hard
    wall at x=0) -- the S-P solver itself is validated against
    closed-form physics before it is used as anybody's reference.
G-C CENTROID vs S-P + literature: at strong inversion the
    self-consistent S-P electron centroid is 0.5-4 nm (literature ~1
    nm at ~1 MV/cm surface field); the DG MOSCapacitor centroid is
    within a factor of 2 of the S-P value at the same bias.
G-D DG-OFF vs DG-ON PHYSICS DIRECTION: with dg=True the centroid is
    STRICTLY POSITIVE (>0.2 nm, charge pushed off the interface), the
    surface electron density is reduced, and Lambda is largest at
    the first INTERIOR node (not the boundary node -- the Neumann
    choice), and C_max drops by 3-25% relative to classical (the
    README section-6 caveat's 10-20% band).
G-E REFUSALS: Device2D/3D and Device1D.solve_bias raise
    NotImplementedError on dg=True; non-finite gamma / gamma <= 0
    raises ValueError.
G-F CATALOG: "dg" registered in ModelCatalog (equations/references/
    applicability, default OFF) and the wire-format invariant
    ModelCatalog.default_config() == _default_models() holds (the
    three key-set pin tests updated per the M14/M16 precedent --
    corrected, not weakened).

------------------------------------------------------------------------
4. AMENDMENT RECORD (device.py touch)
------------------------------------------------------------------------
Device1D.solve_equilibrium is the only core method edited.  dg=False
(default) adds zero floating-point operations to the existing path
(the DG block sits behind `if dg:` AFTER the classical density
computation, before F assembly).  The M13 goldens (frozen meshes,
array_equal) pin the off-path; the G-A gate re-proves it.  No
residual/Jacobian path is touched (DG is equilibrium-only in S3), so
no FD-Jacobian gate is required -- solve_bias refuses instead.

------------------------------------------------------------------------
5. HONEST LIMITS
------------------------------------------------------------------------
- DG is EQUILIBRIUM-ONLY here: Device1D.solve_bias(dg=True) refuses.
  Full DG transport (quantum potential inside the SG currents) is a
  different, larger milestone (the currents are where DG gets hard).
- dg+fd composition is refused in MOSCapacitor (the FD branch's
  density law and the DG exponential correction would need a joint
  derivation; refusing beats composing two corrections nobody
  validated together -- M15's lesson).
- gamma=1.0 default is UNCALIBRATED; the gates bound the error against
  the codebase's own S-P solve, which is itself gated against Airy
  analytics (G-B).  A future session may calibrate gamma per carrier
  against published S-P curves -- deliberately, with the gate updated.
- LAMBDA_MAX = 20*VT clamp is a numerical guard, not physics; it
  engages only in the deep-bulk minority tail where sqrt(n) underflows.
