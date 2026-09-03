# M14-SURFACE-MOBILITY-PLAN.md
# Surface & Inversion-Layer Mobility + Interface Recombination

Status: MOSTLY COMPLETE (2026-08-31). G-B (D_it), G-C (S_n/S_p in
Device1D AND, as of this session, Device2D), G-D, G-E, and catalog
registration are all green. G-A remains OPEN, blocked on a paywalled
primary source -- re-searched fresh this session (Darwish-model
alternative, DEVSIM/MINIMOS-NT source code, academia.edu mirrors) with
no new result; see "G-A LITERATURE SEARCH" and its 2026-08-31 addendum
below. G-C at Device2D: the first attempt (2026-08-28) was a no-op,
reverted to an explicit NotImplementedError; THIS session found a
different approach (reuse the already-computed box-integration
residual instead of deriving per-edge boundary stamps) that works and
generalizes to arbitrary contact shapes with no per-shape logic -- see
"G-C, DEVICE2D, TAKE 2" below. One honest limitation found and left
open: Newton convergence for this Robin BC can be non-monotonic for a
DEEP MINORITY-carrier contact under reverse bias (majority-carrier
convergence is clean); see that section for the full investigation.
2026-09-04 FOLLOW-UP: re-investigated systematically; the original
density-floor-masking explanation was disproven (residual is already
tiny at the declared-converged point), along with two further
hypotheses (cold-start trapping, recombination contamination) -- see
"G-C, DEVICE2D, TAKE 2"'s follow-up paragraph. Root cause narrowed but
STILL NOT FIXED (leading candidate: 2D-specific lateral current
coupling with no 1D analog); still an open, now more precisely
characterized, limitation.
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
## 1. SPEC (from ARCHITECTURE.md section 4b.2, M14)

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

Per ARCHITECTURE.md section 4b.4 standing rule 1:
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
[ ] G-A: surface mobility curve -- OPEN, xfail, B_n/B_p unverified.
    2026-08-28 research pass (see "G-A LITERATURE SEARCH" addendum
    below): confirmed the primary source is paywalled with zero open-
    access copies; found the correct multi-term equation FORM via a
    citation-grade secondary source, but not the numeric constants.
    Blocked pending a primary-source PDF from the user.
[x] G-B: D_it C-V stretch-out -- LANDED 2026-08-28 in moscap.py.
    Q_it = q*D_it*phi_s (see "G-B/G-C IMPLEMENTATION" below for a
    correction to this formula's derivation and to which D_it value
    actually clears the plan's own gate). D_it=0.0 bit-identical
    (test_g_b_dit_zero_is_bit_identical_to_no_dit).
[x] G-C: S_n/S_p surface recombination velocity -- LANDED 2026-08-28 in
    Device1D ONLY (see "G-B/G-C IMPLEMENTATION" below for the physics
    derivation, the initial no-op bug it corrects, and why Device2D was
    reverted rather than shipped broken). S_n=S_p=0.0 bit-identical
    (test_g_d_bit_identity_when_s_off_1d). Device2D/Device3D raise
    NotImplementedError (test_s_n_s_p_raise_in_device2d_and_device3d).
[x] driving_force flag -- DESCOPED (user decision, 2026-08-28): its
    only consumer would be Canali/mobility_field(), which is
    unconditionally NotImplementedError in Device2D/Device3D -- there
    is nothing for "quasi_fermi" to switch. Left exactly as it was
    (Models.__post_init__ still raises for anything but "field").
    Revisit only once/if Canali is ported to 2D.
[x] catalog registration -- "surface_mobility" added to
    workbench/core/catalog.py and gui/services/device_spec.py's
    _default_models() (2026-08-28). S_n/S_p and D_it deliberately NOT
    added as catalog boolean toggles -- they are continuous physical
    magnitudes (cm/s, cm^-2 eV^-1), and forcing them into the
    {model_key: bool} wire-format contract would mean inventing a
    scientifically arbitrary "canonical enabled value." They stay
    Python-API parameters (Models(S_n=...), MOSCapacitor(D_it=...)),
    same framing M12-S2 already uses for TAT.
[x] Full suite green: 696 passed, 1 xfailed (G-A only), 0 failed --
    688 baseline + 8 new tests, zero regressions.

## G-B/G-C IMPLEMENTATION, 2026-08-28

Both features hit a real error along the way, each caught by actually
running the numbers rather than trusting a formula (the same discipline
this repo's standing rules already demand for every other milestone).

**G-B (D_it):** a first pass "corrected" the plan's own `Q_it =
q*D_it*phi_s` to `q^2*D_it*phi_s`, citing a half-remembered textbook
heuristic without re-deriving it. Implemented, then found NUMERICALLY
to be a no-op (~1e-21x the scale of the existing `kappa` term -- see
moscap.py's own diagnostic in its module docstring). Re-derived from
first principles instead: D_it [cm^-2 eV^-1] times a band-bending shift
of dphi_s VOLTS is a dphi_s-eV energy shift numerically (eV = q*volts,
by definition), giving dN_it = D_it*dphi_s and dQ_it = q*dN_it -- ONE
factor of q. The plan's original text was right; the "correction" was
wrong. Implemented as `q*D_it`; verified a real, monotonic C-V
stretch-out. Separately, the plan's own D_it=1e11 test point does NOT
clear its own >1% C_max gate for this MOSCapacitor's parameters
(measured 0.1%, not >1%) -- D_it=1e12 does (1.07% C_max shift, +0.2V
threshold shift), so the gate test uses 1e12 instead (still a realistic
"poor interface" density; real D_it spans ~1e10-1e12 cm^-2 eV^-1).

**G-C (S_n/S_p):** the FIRST wiring attempt (both Device1D and
Device2D) used `F_n[node] = (n[node]-n0)*(1+S_scaled)` -- an algebraic
generalization chosen because it reduces to the exact existing Dirichlet
bits at S=0 with no branching. This is a NO-OP: multiplying an
already-zero-at-convergence residual by any nonzero constant does not
change its root, so n stayed pinned to n0 EXACTLY regardless of S --
confirmed numerically (n[0] identical across 4 orders of magnitude of
S_n). Caught before writing any test around it. Redone as a genuine
Robin flux-balance, derived from steady-state particle conservation in
the boundary half-box (not assumed from an external convention): the
one SG edge current touching the boundary node equals the recombination
sink S*(n-n0)/S*(p-p0). This does NOT reduce to Dirichlet at S=0 (S=0
there means zero current, a different boundary condition), so S=0 is
handled as an explicit branch back to the original Dirichlet code, not
an algebraic limit. Verified: FD-Jacobian < 5e-5 (both electron and
hole rows, both contacts), and the physically correct signature -- as
S_n increases from near-zero to very large, the boundary electron
density converges MONOTONICALLY to the S=0/Dirichlet ("ideal ohmic
contact") value (measured S=1e-2 -> 7.4e-2 cm^-3; S=1e10 -> 1.139e4
cm^-3, matching S=0's value to 4 digits), matching the textbook
qualitative behavior of a finite surface recombination velocity. The
plan's own G-C target formula (`J_leak ~ q*S*ni/2`) turned out not to
apply to this boundary condition at all -- that is the classic MOS
DEPLETION-REGION surface-generation-current formula (n~p~ni at a
depleted/intrinsic surface, e.g. Grove's Si surface-generation-velocity
theory), a different physical scenario from an ohmic contact's
Jn.n_hat=q*Sn*(n-n0) where n0/p0 are full equilibrium values -- so the
test validates the monotonic-convergence signature instead.

**G-C, DEVICE2D:** porting the (corrected) Device1D fix to Device2D hit
the same no-op bug the first Device1D attempt had (confirmed
numerically: n[0,0] identical across 7 orders of magnitude of S_n in a
2D diode). Fixing it properly requires the same flux-balance approach,
generalized to find, per contact node, WHICH neighbor is "into the
bulk" and whether the relevant SG edge is x- or y-directed -- trivial
for 1D's two fixed endpoints, genuinely harder for an arbitrary 2D
contact shape (add_contact accepts any i,j list, not just a domain
edge). Not implemented this pass. Device2D.__init__ now raises
NotImplementedError for S_n/S_p != 0.0 with the full explanation inline,
matching the existing per-dimension-guard convention (field_mobility,
impact). Device3D was never in this feature's scope either way.

## HARD-DEBUG PASS, 2026-08-28 (post-implementation)

A dedicated adversarial pass over the newly-landed G-B/G-C code,
targeting interactions with OTHER models rather than re-confirming what
the landing tests already covered. Checked S_n/S_p (Device1D) against
every other Models flag that can be combined with it: tat, incomplete_ion,
impact, bgn all measured clean (boundary FD-Jacobian error 1e-9 to 1e-10,
both at equilibrium and at a biased/impact-active operating point).

**fd=True + S_n/S_p != 0.0 was NOT clean**: boundary FD-Jacobian error of
~1.2e-3 (25x over the 5e-5 gate), found by restricting the FD-Jacobian
probe to just the 6 boundary columns rather than random full-matrix
sampling (a handful of boundary columns among thousands is easy for
random sampling to miss entirely -- every other M14 test that passed
FD-Jacobian used fd=False, so this gap was invisible to them by
construction). Root cause: M13's Fermi-Dirac statistics add a
doping/density-dependent chain-rule correction to the SG edge-current
Jacobian (the `wn`/`wp`-weighted terms the INTERIOR electron/hole
continuity rows already apply when fd=True) that the new boundary Robin
rows reused the base an*Bm/an*Bp terms from but never extended with.
Fixed by adding the identical correction (mirrored for holes, opposite
sign, same convention the interior rows already use) to the boundary
stamps; verified error drops to ~7.7e-9, and the fd=False case is
unaffected (regression-checked). New test:
test_g_e_fd_jacobian_with_surface_recombination_and_fd_statistics.

MOSCapacitor's own fd=True + D_it>0 combination was also checked
(different code, no shared risk with the Device1D fix above, but the
same "does this Newton loop even converge" question applies) --
converges cleanly, finite, and produces a real D_it-dependent C-V
difference from the fd=True/D_it=0 baseline.

## G-A LITERATURE SEARCH, 2026-08-28 (blocked, materials.py NOT touched)

User asked to research online/published sources for the correct Lombardi
acoustic-phonon constants (B_n/B_p, or whatever the real parameter set
turns out to be) rather than continue leaving G-A unverified indefinitely.

FOUND: COMSOL's "Lombardi Surface Mobility" application-note PDF
transcribes the 1988 paper's equations directly (not a paraphrase --
its own model source uses these exact symbols), and gives the
acoustic-phonon term as a TWO-part expression, not the single term
mobility_cvt() currently implements:

    mu_ac,n = mu1,n / (E_perp,n / E_ref)
              + [mu2,n * (N/N_ref)^beta_n] / [(E_perp,n/E_ref)^(1/3) * (T/T_ref)]

    (mu_sr,n = delta_n / E_perp,n^2 -- unchanged, already verified)

    N = Na- + Nd+

This means the code's current `B / (T * E_eff^(1/3))` is missing an
entire additive term (mu1/(E/E_ref)) AND the doping-dependence factor
(N/N_ref)^beta -- a structural gap, not just a wrong constant. This is
new, useful information even without new numbers: no single
recalibrated B_n could ever reproduce the real curve shape, because
the real model has doping dependence this one doesn't.

NOT FOUND, despite an extensive search: the actual numeric values of
mu1,n, mu2,n, beta_n, E_ref, N_ref, T_ref (and the hole equivalents).
Checked and exhausted:
  - COMSOL's own docs (equations only, defers numbers to Ref. 1)
  - Synopsys Sentaurus Device User Guide and Silvaco ATLAS User's
    Manual (both reference a full "Lombardi model" / CVT parameter
    table by section title -- Sentaurus calls it "Named Parameter Sets
    for Lombardi Model" -- but the freely-crawlable web versions never
    expose the numbers themselves; the full ATLAS manual PDF is too
    large (>10MB) to fetch whole, and a direct curl download timed out
    from this sandbox)
  - Stanford's old Prophet TCAD docs, which explicitly claim to have a
    "Table 3" with these values -- server unreachable (connection
    refused), and web.archive.org is blocked from this environment
  - A TU Wien PhD thesis chapter dedicated to inversion-layer mobility
    models -- discusses Lombardi by name and gives full equations for
    the related Darwish model, but no Lombardi numbers
  - A CERN detector-simulation TCAD parameter compilation, a general
    mobility-modeling course PDF (Vasileska, ASU), and a
    ResearchGate-hosted table figure (blocked, HTTP 403)
  - The original paper itself: confirmed via a direct Unpaywall API
    query (DOI 10.1109/43.9186) that it is_oa=false with ZERO
    oa_locations -- there is no legal open-access copy anywhere, not
    just none this search happened to find.

CONCLUSION: this is genuinely blocked on external material, not on
search effort. Flagged as a spawned background task (dismissed/tracked
outside this file) asking the user for either the original 1988 paper
(institutional IEEE Xplore access) or a Sentaurus/Silvaco manual PDF
they may already have, since both almost certainly contain the table.
materials.py is UNCHANGED -- implementing the two-term form now with
guessed mu1/E_ref/N_ref would replace one unverified constant with
several, which is worse, not better, than the current honest xfail.

## G-A LITERATURE SEARCH ADDENDUM, 2026-08-31 (still blocked)

Re-ran the search fresh at the start of a new session, from different
angles than 2026-08-28's exhaustive pass, before concluding the same
thing again: (1) a Darwish (1997) "improved electron and hole mobility
model" was checked as a possible ALTERNATIVE published model for the
same transverse-field physics (DEVSIM itself uses Darwish, not
Lombardi, for exactly this purpose) -- found its title/venue (IEEE
TED, 1997, vol 44 issue 9) but no accessible numeric parameter table
either (academia.edu copy returned HTTP 403; a TU Wien PhD thesis
gives Darwish's EQUATIONS, same as the 2026-08-28 finding, but
explicitly states it omits the numeric coefficients). (2) Checked
whether MINIMOS-NT's or DEVSIM's own source/docs expose a usable
parameter set -- no. (3) Re-tried the Stanford Prophet docs URL
directly and via web.archive.org -- same as 2026-08-28, unreachable
(connection refused / archive.org blocked from this environment).
CONCLUSION UNCHANGED: this stays genuinely blocked on external
material. Adopting Darwish instead of Lombardi is a real, legitimate
option in principle (it's what an actual production simulator uses),
but swapping the underlying model is a bigger decision than filling in
a missing constant and was not made unilaterally here -- flagged for
the user rather than assumed.

------------------------------------------------------------------------
## G-C, DEVICE2D, TAKE 2 (2026-08-31) -- IMPLEMENTED

The first attempt (see "G-C, DEVICE2D" above) failed because it tried
to derive, per contact node, "which single edge is into the bulk" --
genuinely hard for an arbitrary 2D contact shape (a node can touch 1-4
edges, unlike 1D's two fixed single-edge endpoints).

**The insight**: `Device2D._residual_jacobian` already computes the
correct multi-edge box-integration continuity residual (`F_n`, `F_p`)
at EVERY node uniformly, contact or not, before the Dirichlet overwrite
discards it -- exactly what `terminal_current()` already reuses as "the
net current the contact must supply" (see its own docstring). That
residual is the 2D generalization of what 1D calls "the one SG edge
current touching the boundary node" (1D's boundary residual reduces to
a single edge only because a 1D endpoint happens to have exactly one).
So the Robin BC (`Jn.n_hat = q*Sn*(n-n0)`, mirrored for holes)
generalizes to: keep the already-computed `F_n[contact_node]` (don't
overwrite it), then ADD `S_n_s*(n[node]-n0)` to it -- instead of the
old code's unconditional overwrite-with-Dirichlet + strip-every-
Jacobian-entry-in-the-row-to-identity. Every OTHER Jacobian entry
already in that row (from the general box-assembly pass earlier in the
same function) stays exactly as computed, which is what makes this
generalize to any number of edges per contact node with zero new
"which edge" logic -- confirmed, not just claimed: a genuine multi-edge
test (an L-shaped patch spanning a domain corner plus several top-row
nodes, where individual nodes touch 2 or 3 non-contact edges) passes
FD-Jacobian at the same tolerance as an ordinary single-edge contact.

**Bonus finding**: because this approach reuses the interior-style
Jacobian entries wholesale rather than hand-deriving new boundary
stamps, the M13 Fermi-Dirac `wn`/`wp` chain-rule correction (which 1D's
hand-derived boundary stamps needed a SEPARATE fix for, found in a
2026-08-28 hard-debug pass) came along automatically -- verified
directly with an `fd=True` FD-Jacobian check restricted to the
boundary columns (same "random sampling can miss a handful of boundary
columns" lesson 1D's own hard-debug pass recorded), not assumed.

**Real limitation found, not hidden**: sweeping S_n from near-zero to
very large at a DEEP MINORITY-carrier contact under reverse bias (the
same scenario Device1D's own G-C test uses) is NOT monotonic in
Device2D the way it is in Device1D -- it collapses to spurious
near-zero values across several decades of S before recovering near
the Dirichlet limit at very large S. Traced (not just observed) to
Newton's own convergence-update criterion: `solve_bias`'s relative-
update check floors the denominator at `1e-10` (scaled) for EVERY node
(a deliberate M11-S5 safeguard against deep-minority AlGaAs-barrier
nodes stalling the whole solve) — Device1D's own analogous check floors
at `1e-300` instead, i.e. effectively no floor. For a target density
below that `1e-10` floor, changes there stop counting toward the
convergence criterion at all, so Newton can (and, empirically, does)
declare "converged" while this new Robin-BC row is still drifting via
the per-iteration 0.1x/10x density clamp, landing on a residual that is
"small" only because both terms in the equation are independently near
zero at that point -- not because the true self-consistent root was
found. This is NOT a sign error or a wrong formula (the SAME equation
converges cleanly, and monotonically, for a MAJORITY-carrier contact,
and the FD-Jacobian is clean everywhere it was checked, including this
exact deep-minority regime) -- it is a genuine interaction between a
pre-existing, deliberately-added convergence safeguard (M11-S5) and a
new feature that, for the first time, puts a NON-Dirichlet unknown at a
node whose target value can legitimately sit below that safeguard's
floor. Not fixed this pass (changing M11-S5's floor is a separate,
wider-blast-radius decision affecting every 2D solve, not just S_n/S_p)
-- left as an honest, investigated limitation. The shipped gates
therefore cover: bit-identity (S=0), FD-Jacobian (single-edge,
multi-edge corner, and fd=True combinations), majority-carrier
monotonic convergence, and combination with bgn/auger/surface_mobility
-- NOT a minority-carrier monotonic-convergence gate, which would be
gating something not actually reliable yet.

**FOLLOW-UP INVESTIGATION (2026-09-04): the mechanism above is
INCOMPLETE.** A later session's systematic re-investigation reproduced
the collapse (confirmed: `S_n=S_p` swept 1e-2..1e10 at a reverse-biased
p-side contact, `n[left]` plateaus near 1e-19..1e-20 for S in
[1e1, 1e5] before recovering to the correct ~1.14e-14 Dirichlet-limit
value at S>=1e6) and tested the density-floor-masking explanation
above directly by instrumenting the residual at the declared-converged
point: `max(|F|)` is already ~1e-12 to 1e-17 there, i.e. genuinely
tiny by any reasonable absolute standard -- NOT merely "small because
the update-criterion floor stopped counting it." That rules out the
convergence-CHECK being the proximate cause. Two further hypotheses
were tested and also ruled out:
  - Cold-start trapping (Newton's per-iteration 0.1x/10x multiplicative
    clamp getting stuck traversing many decades from a fresh
    equilibrium guess): warm-starting each S from the previous
    (smaller) S's converged state produces the IDENTICAL collapse --
    not a starting-point artifact.
  - SRH/Auger recombination contamination (2D's box-residual-reuse
    design pulls the full nodal G-R term into the Robin-BC row, unlike
    1D's boundary treatment which is PURELY `Jn[edge] + S_n_s*(n-n0)`
    with no recombination term at all -- see device.py's own boundary
    block): running the identical sweep with `srh=False, auger=False`
    reproduces the SAME collapse to within roundoff. Recombination is
    not the differentiator either.
The sharpest new evidence: re-solving the pathological case
(S_n=S_p=1e3) with `tol_update` tightened from 1e-8 down to 1e-16 does
NOT converge more precisely to a stable value -- `n[left]` keeps
shrinking (1.07e-19 -> 1.07e-23 -> 1.07e-25 -> underflow and
divergence). This is not Newton settling on a stable-but-wrong root;
the computed Newton step for this one unknown behaves like noise, with
apparently NO genuine nearby fixed point for intermediate S. The
remaining, untested candidate: Device2D's box residual at this node
also carries LATERAL (y-direction) current-divergence terms coupling
to neighboring nodes along the contact face (visible directly in the
assembled Jacobian row: an off-diagonal entry of magnitude ~79,
compatible with a y-neighbor coupling) that 1D's two-fixed-endpoint
boundary treatment structurally cannot have at all, since 1D has no
lateral dimension. This was flagged, not confirmed -- pinning it down
and designing a fix (if one exists that doesn't touch the M11-S5 floor
globally) is real numerical-methods work, not a quick patch, and was
deferred rather than attempted speculatively against gated physics
code. Still an honest, investigated (now MORE precisely than before)
limitation, not a fix.

### Files changed:
- `pytcad/pytcad/device2d.py`: removed the S_n/S_p `NotImplementedError`
  guard; `_residual_jacobian`'s Dirichlet-BC block now branches per
  contact/carrier on S_n_s/S_p_s (0 -> exact prior behavior; nonzero ->
  Robin flux-balance reusing the existing box residual)
- `pytcad/tests/test_m14_2d_surface_recombination.py` (new, 6 tests)
- `pytcad/tests/test_m14_surface_mobility.py`: updated
  `test_s_n_s_p_raise_in_device2d_and_device3d` ->
  `test_s_n_s_p_works_in_device2d_raises_in_device3d` (Device2D no
  longer raises; Device3D still does, unchanged)
- `M14-SURFACE-MOBILITY-PLAN.md`, `ARCHITECTURE.md`, `history.md`:
  status updates
