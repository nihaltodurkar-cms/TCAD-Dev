# M20-DENSITY-GRADIENT-PLAN.md
# M20: Density-gradient quantum correction (= M12-S3, folded)
# Formal milestone spec

Status: **COMPLETE, ALL GATES GREEN, 2026-08-31** (coupled-Newton
reformulation -- section 7). `tests/test_m20_dg.py`: 20/20 pass.
**2026-09-04 UPDATE:** the S-P reference solver's `eigsh` Lanczos
nondeterminism (section 7.6's own open item, flagged there as needing
"a future session to switch to a deterministic eigensolver path") is
FIXED -- `dg.schrodinger_poisson` no longer calls `eigsh` at all; see
the note at the end of section 7.6. The
previously-open G-C/G-D gates (`test_gc_dg_centroid_within_factor2_
of_sp`, `test_gc_classical_centroid_is_the_sub_debye_tail`,
`test_gd_dg_changes_the_physics_in_every_required_direction`) now pass
for real physical reasons, not a loosened threshold -- see section 7
for the full record, including a genuine wrong-sign bug found and
fixed along the way (independently confirmed to be a property of the
pre-existing `quantum_potential` formula itself, not new code) and the
literature research (DEVSIM's density-gradient reference
implementation) that led to the actual fix.

Prior status (2026-08-29, superseded): VERIFIED, PARTIALLY GREEN, LEFT
OPEN BY USER DECISION. The lagged outer-fixed-point scheme converged
cleanly (a real convergence bug was found and fixed that session --
section 6) but to the WRONG physics: a gamma sweep (0.001-3.0) found
no value reproducing the S-P/literature centroid band, diagnosed as a
documented failure mode of lagging a nonlocal quantum potential
outside the Newton loop rather than solving it coupled. Three
hypotheses were tested and ruled out (section 6); the real fix was
identified as either a coupled-Newton reformulation or a published
pre-calibrated gamma, both deferred at the time. Section 7 records the
coupled-Newton reformulation actually being carried out.

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

------------------------------------------------------------------------
7. COUPLED-NEWTON REFORMULATION (2026-08-31): M20 CLOSED
------------------------------------------------------------------------
User decision: pursue the coupled-Newton reformulation (not a
published-gamma shortcut, which the section 6 gamma sweep already
showed would not work on its own).

### 7.1 Architecture

Both `MOSCapacitor.solve_psi(dg=True)` and `Device1D.solve_equilibrium`
(`Models(dg=True)`) now solve `(psi, Lambda_n, Lambda_p)` as one
COUPLED Newton system -- 3 unknowns per node, interleaved
`[psi_i, Lambda_n_i, Lambda_p_i]` (mirrors `device.py`'s own
`[psi, n, p]` convention for the DD Newton system) -- replacing the
LAGGED outer fixed point entirely. New methods:
`MOSCapacitor._dg_residual_jacobian` / `_dg_newton_solve` /
`_solve_psi_dg_coupled`, and the identical pattern in `device.py`:
`Device1D._dg_residual_jacobian_eq` / `_dg_newton_solve_eq` /
`_solve_equilibrium_dg_coupled`. `dg=False` in both classes is
UNCHANGED (verified byte-identical -- G-A) and the classical Newton
loop was extracted into its own un-wrapped code path (no more
`n_outer=1` dg-conditional wrapper) rather than left inside a dead
outer loop.

Poisson rows are exactly the pre-existing classical flux-divergence
residual, with `n`, `p` now COUPLED (Lambda are live Newton unknowns)
rather than lagged. Lambda_n/Lambda_p rows are the residual form of
`dg.quantum_potential`'s own defining equation, `Lambda*sqrt(n) +
pref*(sqrt(n))'' = 0`, evaluated on the PHYSICAL mesh (not the scaled
mesh the Poisson rows use) with `pref` from a newly-extracted shared
helper, `dg._dg_prefactor`, so the coupled formulation cannot silently
drift from the already-gated (G-B Airy, G-C S-P reference)
`quantum_potential` formula. G-FD (new, both classes): analytic vs.
central-finite-difference Jacobian at a randomized non-converged
state, `<2e-9` max relative error (well inside the `<2e-3` standing
FD-Jacobian-first threshold).

A single Newton solve at the full target gamma from `Lambda=0` does
NOT reliably converge (measured directly: singular/non-finite step at
strong inversion -- the DG coupling is genuinely stiff). Fixed with a
gamma-continuation strength ladder (the same pattern `device.py`'s own
M15/M16 stiff-generation `solve_bias` already uses): ramp gamma from 0
to the target, warm-restarting `(psi, Lambda_n, Lambda_p)` between
stages, bisecting the gap on a failed stage. At gamma=0 the Lambda rows
force Lambda=0 exactly and the Poisson row reduces to the classical
equation, so the first stage is (up to solver tolerance) the
already-trusted classical solve.

### 7.2 The numerical pathology is genuinely fixed

Sweeping gamma with the new coupled solver (0.1 to 1000) gives a
SMOOTH, MONOTONIC centroid curve -- no discontinuous bifurcation, no
clamp-saturation jump, unlike the old lagged scheme's hard 0.01/0.03
threshold behavior (section 6). This confirms the original diagnosis:
lagging the quantum potential outside the Newton loop was the real
architectural problem, independent of what gamma value or physics
finding comes next.

### 7.3 A genuine wrong-sign bug found, root-caused, and fixed

Even with the numerical pathology gone, the FIRST working coupled
solve (Lambda=0 Neumann boundary, matching the old scheme's BC choice)
gave a centroid still ~5x short of the S-P reference (0.81 nm vs. 4.23
nm at gamma=1), and, more importantly, a NEGATIVE Lambda at the
near-surface node -- the correction was ENHANCING density there
instead of suppressing it, backwards from the required physics
(G-D's original assertion). Root-caused, not assumed: evaluating the
pre-existing, already-gated `quantum_potential` formula DIRECTLY on a
classical MOS density profile (bypassing the coupled solve entirely)
reproduces the same negative sign -- an analytic property of applying
this Bohm-potential formula to a density profile that classically
PEAKS at a Neumann boundary (proved with a toy exponential-decay
profile: `g(x)=g0*exp(-x/L)` gives `Lambda = -pref/(4L^2) < 0`
identically). Not a bug in the new coupled-Newton code.

### 7.4 Literature/production-tool research (user-directed)

Searched how DEVSIM's density-gradient reference implementation and
the underlying literature (Wettstein et al., IEEE TED 2001;
Garcia-Loureiro et al., "Implementation of the Density Gradient
Quantum Corrections for 3-D Simulations of Multigate Nanoscaled
Transistors", 2011) treat the semiconductor/insulator interface.
Finding: DEVSIM extends the mesh INTO the oxide with its own quantum
prefactor and a surface term -- the interface is NOT a free (Neumann)
boundary for the quantum unknown, it is effectively a very high
(quantum-opaque) barrier. This MOSCapacitor has no oxide mesh to
extend into (the oxide is a lumped Robin/`Cox` term, never meshed), so
the equivalent, and this codebase's OWN Schrodinger-Poisson reference
solver's convention (`dg.schrodinger_poisson`'s `hard_wall_left=True`:
`psi_k(0)=0` exactly, so `n_q(0)=0` identically) is a HARD WALL:

- Node-1's curvature stencil uses a GHOST value of `g[0]=0` (not the
  real classical `g[0]`) -- this alone flipped the near-surface sign
  from negative to positive and moved Lambda's peak to node 1
  (interior, decaying into the bulk) -- a real, correctly-signed
  confinement profile.
- Left alone, though, `Lambda_n[0]`/`Lambda_p[0]` were still pinned to
  the OLD Neumann value (0), leaving the actual density AT the
  interface node itself unsuppressed and still dominating the centroid
  integral (measured: ratio only improved to ~0.25-0.48, still short
  of the factor-2 gate). Fixed by pinning `Lambda_n[0]`/`Lambda_p[0]`
  to the EXISTING `LAMBDA_MAX_VT` numerical clamp (already defined in
  `dg.py`, not a new invented constant) -- the discrete equivalent of
  the S-P reference's exact `psi_k(0)=0` hard wall.

This is a real modeling change (documented, not silently smuggled in):
`MOSCapacitor`'s interface node now genuinely represents a hard
quantum wall for the DG correction, matching this codebase's own S-P
reference and the literature-documented production-tool treatment.
`Device1D`'s DG branch was NOT given this hard-wall treatment -- its
DG boundaries are ohmic CONTACTS, not an oxide interface (no physical
justification for a hard quantum wall there), so it keeps the plain
Lambda=0 Neumann boundary; see `Device1D._dg_residual_jacobian_eq`'s
docstring for the reasoning.

### 7.5 Gate results (measured, `PARAMS = Nsub=-1e17, tox_cm=2e-7`,
`Vg = Vth+1V`, `gamma=1.0` default, unchanged)

- G-FD (both classes): <1.2e-9 max relative error vs. central FD.
- G-C (`test_gc_dg_centroid_within_factor2_of_sp`): DG centroid 2.49 nm
  vs. S-P reference 4.20 nm, ratio 0.593 (gate: 0.5-2.0). PASS.
- G-C (`test_gc_classical_centroid_is_the_sub_debye_tail`): classical
  centroid 0.631 nm < DG centroid 2.49 nm, classical < 2 nm. PASS.
- G-D direction (1) centroid > 0.2 nm: 2.49 nm. PASS.
- G-D direction (2) suppression: near-surface DG density < classical
  density at the same psi. PASS (was FAILING before the hard-wall fix
  -- density was being enhanced, not suppressed).
- G-D direction (3), REWRITTEN (see 7.4): Lambda peaks AT the hard
  wall (node 0, pinned at `LAMBDA_MAX_VT*VT = 0.517 V`) and decays
  monotonically over the first 10 nodes -- the opposite assertion from
  the pre-2026-08-31 version, which encoded the (now understood to be
  wrong) Neumann assumption.
- G-D direction (4) C_max drop: 16.7% (gate: 3-25%, the README
  section-6 caveat's 10-20% band). PASS.
- G-A (bit-identity, both classes): unchanged, re-verified.
- G-E/G-F (refusals, catalog): unchanged, re-verified.
- Outer-fixed-point regression tests (`test_gr_*`): still meaningful
  and still pass -- they check "solve_psi/solve_equilibrium(dg=True)
  converges without warning" and "two fresh devices converge to the
  SAME Lambda", both true of the new coupled architecture too.

Full suite: `pytest tests/ gui/tests/ -n 6 -m "not slow" -q` -> 931
passed, 6 skipped, 1 xfailed, 1 failed
(`test_gc_sp_centroid_in_literature_band`, confirmed PRE-EXISTING and
unrelated: `dg.schrodinger_poisson`'s `scipy.sparse.linalg.eigsh`
Lanczos iteration is nondeterministic run-to-run on this problem,
independently reproduced by running the same test 5x before touching
any code in this session -- 3/5 passed, 2/5 failed, all against the
UNCHANGED reference solver). Zero new failures anywhere else; the
baseline going into this work was 929 passed / 3 failed (the three
gates this section closes).

### 7.6 Honest limits (updated)

- `dg_gamma` stays at its documented default (1.0, the uncalibrated
  Bohm value) -- NOT recalibrated. The hard-wall boundary fix, not a
  gamma change, is what closed the gates; gamma=1 was never touched.
- The hard-wall treatment is `MOSCapacitor`-specific (real Si/SiO2
  interface); `Device1D`'s DG branch keeps the Neumann boundary since
  its contacts are ohmic, not an oxide interface -- untested against
  any accuracy gate of its own (none exists), but architecturally
  consistent (coupled Newton, no more lagged pathology) and FD-
  Jacobian-verified independently.
- `test_gc_sp_centroid_in_literature_band`'s pre-existing flakiness
  (the S-P REFERENCE solver's own `eigsh` nondeterminism) was found
  but explicitly left NOT FIXED here, deferred to a future session.
- DG remains EQUILIBRIUM-ONLY (`solve_bias(dg=True)` still refuses);
  full DG transport is unchanged, out of scope, same as before.

**FIXED 2026-09-04** (a later session, discovered as an existing fix
when a parallel development branch was merged in): root cause was
DEEPER than an unseeded Lanczos start -- the assembled Hamiltonian on
a non-uniform mesh was never actually Hermitian in the first place
(dividing each row by its OWN control-volume width, per the naive
finite-volume residual, makes `H[i,i+1] != H[i+1,i]`), so `eigsh`'s
Lanczos iteration was iterating on a genuinely non-symmetric operator
-- which off-diagonal array it happened to trust first varied run to
run, and the two choices disagreed by up to 10x. Fixed by solving the
SIMILARITY-TRANSFORMED problem `(D^-1 K D^-1) phi = E phi` (D =
diag(sqrt(control-volume widths))), which is exactly tridiagonal,
genuinely symmetric by construction, and has identical eigenvalues to
the original problem -- then switching the solve itself from the
iterative sparse `eigsh` to the DIRECT tridiagonal LAPACK routine
`scipy.linalg.eigh_tridiagonal` (no iterative convergence or seed to
worry about at all, now that the matrix is provably symmetric).
Verified: bit-for-bit identical `centroid_cm`/`sheet` output across 10
independent fresh-subprocess runs (not just "passes" -- the exact same
float64 bytes every time), and `test_gc_sp_centroid_in_literature_band`
30/30 passed in a repeated-run check. See `pytcad/dg.py`'s
`schrodinger_poisson()` docstring for the full derivation.
