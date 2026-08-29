# M20-DENSITY-GRADIENT-PLAN.md
# M20: Density-gradient quantum correction (= M12-S3, folded)
# Formal milestone spec

Status: **VERIFIED 2026-08-29, PARTIALLY GREEN, LEFT OPEN BY USER
DECISION.** tests/test_m20_dg.py run for the first time this session:
14/17 original gates green plus 3 new regression tests, after a
hard-debug pass found and fixed a real outer-fixed-point non-
convergence bug (section 6). G-A, G-B, G-E, G-F all green. G-C and G-D
(3 tests) remain OPEN -- not the convergence bug, a gamma-calibration
gap (section 6's "SEPARATE ISSUE" + "FOLLOW-UP INVESTIGATION"
paragraphs: three further hypotheses tested and ruled out; the real
fix is either a coupled-Newton reformulation of the DG term or a
published, pre-calibrated gamma, both explicitly deferred). Do not
treat M20 as complete, and do not spend further effort on the lagged-
iteration scheme itself, until one of those two is actually decided.

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
- LAMBDA_MAX = 20*VT clamp is a numerical guard, not physics.  It was
  ASSUMED to engage only in the deep-bulk minority tail; measured
  (2026-08-29 hard-debug pass, section 6) to be FALSE -- it engages
  hard at the strong-inversion surface node, the primary physics of
  interest, and is load-bearing there (removing it diverges the outer
  loop rather than revealing a larger physical answer).

------------------------------------------------------------------------
6. HARD-DEBUG PASS (2026-08-29): OUTER FIXED-POINT NON-CONVERGENCE
------------------------------------------------------------------------
BUG FOUND AND FIXED.  The outer fixed-point loop (MOSCapacitor.solve_psi
and Device1D.solve_equilibrium, both dg=True) computed each pass's
target Lambda from the DG-CORRECTED density
(n_classical * exp(-Lambda_old/VT)) rather than the classical density.
This closes a 1-node self-reference at the node next to the Lambda=0
boundary: Lambda[1] enters n[1] via the exponential, and
quantum_potential's 3-point curvature stencil at node 1 reads n[1]
straight back out. Instrumenting the loop (PARAMS from
tests/test_m20_dg.py, Vg = Vth+1V strong inversion) showed a RIGID
period-2 oscillation: Lambda[1] flipping between exactly
+LAMBDA_MAX*VT and -LAMBDA_MAX*VT every single outer pass, forever --
immune to under-relaxation at every damping factor tried from 1.0 down
to 0.02 over up to 400 passes, and immune to ramping gamma via
continuation (the instability just relocated to a different node as
gamma grew). `warnings.warn("... did not converge ...")` fired on
every dg=True solve; the returned Lambda/psi were whichever phase of
the 2-cycle the loop happened to stop on, not a converged answer (this
is what produced test_gc_dg_centroid_within_factor2_of_sp's 188 nm
centroid against a ~4 nm Schrodinger-Poisson reference -- a 48x error
from an oscillation artifact, not a calibration gap).

FIX: source the outer loop's target Lambda from the CLASSICAL
(psi-only) density instead of the DG-corrected one. Verified to
converge in as few as 4 outer passes with NO damping at all, and to
the SAME converged Lambda across every damping factor from 1.0 down to
0.3 -- the signature of a genuine fixed point, unlike the old scheme
which never had one. Regression tests added:
test_gr_moscap_outer_fixed_point_converges_without_warning,
test_gr_device1d_dg_outer_fixed_point_converges_without_warning,
test_gr_outer_fixed_point_is_deterministic.

SEPARATE ISSUE SURFACED, NOT YET FIXED: with the oscillation gone, the
CONVERGED answer at gamma=1 (PARAMS: Nsub=1e17, tox=20nm) lands exactly
at the LAMBDA_MAX=20*VT clamp and gives a centroid of 0.168 nm --
smaller than the CLASSICAL (dg=False) centroid of 0.631 nm, inverting
the required "DG pushes charge OFF the interface" direction (G-C, G-D).
This is NOT the same bug: a gamma sweep (0.001 to 3.0) shows the
converged centroid jumps discontinuously from ~0.55-0.63 nm (gamma
<=0.01, negligible DG effect, clamp not engaged) to a clamp-saturated
~0.02-0.29 nm regime (gamma >=0.03) with NO intermediate gamma giving a
stable answer anywhere near the ~2-8 nm band G-C's factor-2-of-S-P gate
needs. Raising the clamp in this regime does not help -- it makes the
(now non-oscillating) fixed point diverge outright instead (measured:
clamp=200*VT overflows). In short: gamma=1 (explicitly documented above
as uncalibrated) does not have a stable operating point that reproduces
Schrodinger-Poisson-scale physics on this device/mesh; three gates
(test_gc_dg_centroid_within_factor2_of_sp,
test_gc_classical_centroid_is_the_sub_debye_tail,
test_gd_dg_changes_the_physics_in_every_required_direction) still fail
after this fix, but now for an understood, correctly-diagnosed reason
(gamma calibration / possibly the curvature evaluation needing a
coarser length scale than MOSCapacitor's classical-Poisson mesh
provides) rather than a broken fixed point.

FOLLOW-UP INVESTIGATION (same session, immediately after): three
further hypotheses tested and RULED OUT, each with numbers, before
concluding this needs a design decision rather than another patch.

1. BOUNDARY-CONDITION MISMATCH.  Noticed dg.schrodinger_poisson (the
   REFERENCE solver these gates check against) treats the Si/SiO2
   interface as a hard wall (psi(0)=0 Dirichlet, hard_wall_left=True),
   while quantum_potential treats every boundary as Neumann
   (Lambda=0) -- a genuine internal inconsistency between the model
   and its own reference. Tested a hard-wall variant of
   quantum_potential (odd-extension ghost node enforcing sqrt(n)->0 at
   the oxide interface, matching schrodinger_poisson's convention
   exactly). RESULT: Lambda[0] itself changes (no longer pinned at 0),
   but the interior curvature at node 1 -- where the pathology lives --
   is untouched: same discontinuous gamma-jump, same 0.02-0.25 nm
   clamp-saturated centroid range. Worth fixing on its own honesty
   grounds (the BC inconsistency is real) but it is NOT the cause of
   the calibration gap.

2. SUB-PHYSICAL MESH RESOLUTION.  The Bohm/DG gradient expansion is
   only valid for a density envelope varying slowly relative to a
   quantum coherence length (~1 nm scale); MOSCapacitor's classical-
   Poisson mesh reaches h[0] ~ 2.5e-9 cm (0.025 nm), two orders of
   magnitude finer. Tested evaluating the curvature stencil using
   neighbours at least h_min_phys away (0.1-3.0 nm, walking past
   adjacent mesh nodes as needed) instead of the raw mesh spacing.
   RESULT: centroid improves mildly at h_min_phys=1nm (0.168 -> 0.23
   nm) then gets WORSE again at 2-3 nm (non-monotonic) -- still an
   order of magnitude short of the ~4 nm S-P reference in every case.
   Not the fix either.

3. FORMULA/UNITS BUG.  Ruled out earlier in the same investigation: a
   smooth Gaussian test density (5 nm width, no mesh pathology) gives
   quantum_potential ~90 meV (~3.5 VT) -- the correct order of
   magnitude for a real inversion-layer confinement energy. The
   discretization and SI prefactor are correct; the pathology is
   specific to feeding this machinery the classical MOSCapacitor's
   strong-inversion profile.

DIAGNOSIS: sweeping gamma (0.001 to 3.0) shows a HARD BIFURCATION, not
a smooth calibration curve -- negligible effect below ~0.01, clamp-
saturated above ~0.03, no gamma in between and no BC/stencil variant
that produces an intermediate, S-P-matching regime. Combined with
"raising the clamp diverges rather than revealing a larger physical
answer" (section 6 above), this is the signature of a LAGGED (Gummel-
style) fixed point that does not reliably find self-consistent DG-
Poisson solutions for this device -- a documented weakness of exactly
this scheme in the DG literature, and the reason production TCAD tools
solve the quantum potential COUPLED into the same Newton system as psi
rather than lagging it. Fixing that properly means deriving and
assembling the DG term's Jacobian contribution directly (a core-
physics amendment on the scale of M11-S3/M13, needing the same sign-
off + FD-Jacobian process), not a numerics patch on the lagged scheme.

DECISION (user, 2026-08-29): LEAVE M20 FLAGGED OPEN.  Do not invest
further this session in either a coupled-Newton reformulation or
sourcing a calibrated gamma -- both are legitimately separate, larger
pieces of work. The three open gates
(test_gc_dg_centroid_within_factor2_of_sp,
test_gc_classical_centroid_is_the_sub_debye_tail,
test_gd_dg_changes_the_physics_in_every_required_direction) stay red,
openly, with this record explaining exactly why and what was already
ruled out -- so a future session does not have to re-derive any of
this before deciding which of the two real fixes to pursue.
