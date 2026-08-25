# DEVSIM impact-ionization coupling -- investigation record (M8)

Status: coupling implemented up to a **frozen-current Jacobian**
limitation; avalanche simulation not yet robust enough to ship.
Analysis-layer model (`workbench/physics/impact_ionization.py`) remains
validated against published values.

## Established facts (all verified empirically this session)

### Equation rewiring recipe -- WORKS
- `delete_equation` both continuity equations, recreate them with
  `edge_volume_model` attached, THEN recreate contact equations
  (`CreateSiliconDriftDiffusionAtContact`) LAST. Contact equations bind
  to region equations by name; wrong order = "Cannot find equation
  index" at solve time.
- With alpha = 0 the rewired system matches baseline exactly through a
  20 V reverse ramp.
- `equation()` with an existing name does NOT truly reinstall (stale
  object stays in charge) -- deletion first is mandatory.

### Sign calibration -- RESOLVED
Both continuity equations take **+II_PairGen** where
`II_PairGen = AlphaN*abs(ElectronCurrent) + AlphaP*abs(HoleCurrent)`
[C/cm^3 s]. Calibrated against a node-model ground truth on a uniform
resistor (constant pair generation G): analytic terminal current is
q*G*L/2 (NOT q*G*L -- carriers split between contacts); node-model
implementation reproduces it, and edge_volume with +/+ signs matches to
<0.5%. An E-negative convention silently acts as recombination.

### alpha formulation -- WORKS
alpha = A*exp(-B/(|E|+1)): additive denominator floor avoids 0*inf NaNs
on neutral-region edges. devsim evaluates BOTH branches of ifelse(), so
branch guards do NOT protect exp(-B/E). Symbolic diff() through nested
edge-model references (abs(ElectricField), abs(ElectronCurrent)) yields
Jacobian entries that limit-cycle Newton -- write derivative models
manually (template in prototype).

### THE REMAINING LIMITATION
With correct signs and manual d(alpha)/d(Psi) Jacobian entries, the
system converges only in a narrow bias/step window (~0.5 V on the
1e19/1e17 junction; smaller steps do NOT help; behavior is
non-monotonic in step size). Diagnosis: the current-dependence of the
generation term is FROZEN out of the Jacobian (devsim's model framework
cannot express d(|J|)/d(n) inside an edge_volume term), leaving a
marginally-stable fixed-point map. Full coupling requires either:
1. upstream guidance on II-style volume terms with carrier-dependent
   edge sources (devsim GitHub discussions), or
2. folding generation into the ElectronCurrent/HoleCurrent edge models
   themselves so its derivatives ride the existing flux Jacobian.

## Reproduce
    ALPHA_DERIVS=0 python3 benchmarks/devsim_ii_edge_volume_prototype.py
    # alpha=0: plumbing check, converges to 20 V
    ALPHA_DERIVS=1 ... # real vOdM chain: converges ~0.5 V, stalls beyond

## When unblocked
Catalog flag + Physics Lab toggle + published-BV gate (ranges already
encoded in tests/test_model_benchmarks.py).
