# DEVSIM impact-ionization coupling -- investigation record (M8)

Status: BLOCKED on a devsim-build quirk. Analysis-layer model
(`workbench/physics/impact_ionization.py`) is validated against
published values; solver coupling is implemented up to the point
documented here and must not ship until resolved.

## What works (verified)
- Equation rewiring recipe: `delete_equation` both continuity equations,
  recreate them with `edge_volume_model` attached, THEN recreate contact
  equations (`CreateSiliconDriftDiffusionAtContact`) LAST -- they bind to
  region equations by name and fail with "Cannot find equation index"
  otherwise.
- With alpha = 0 the rewired system is byte-identical to baseline
  (reverse ramp to 20 V, same currents).
- NaN-safe alpha formulation: alpha = A*exp(-B/(|E|+1)); the additive
  floor avoids 0*inf in derivatives on neutral-region edges.
  NOTE: devsim evaluates BOTH branches of ifelse(), so branch guards do
  NOT protect exp(-B/E).
- Symbolic diff() through nested edge-model references
  (abs(ElectricField), abs(ElectronCurrent)) produced Jacobian entries
  that limit-cycled Newton; manual derivative expressions are the way
  (template in the prototype script).

## The blocker
ANY nonzero edge_volume source -- even scaled to 1e-14 of its physical
value, sign-independent, Jacobian-independent -- destabilizes Newton at
reverse bias >= ~1 V on a 1e19/1e17 one-sided junction (50 iterations,
RelError oscillating ~1e0..1e2), while alpha=0 converges to 20 V.
Scaling bisection shows the failure boundary tracks the source
magnitude: the assembled residual contribution appears amplified by
~1e12..1e19 versus its physical C/cm^3 s interpretation, i.e. the
edge_volume slot in this build (devsim 2.11.0) does not integrate
volumetric edge sources in the units its documentation implies.

## Reproduce
    python3 benchmarks/devsim_ii_edge_volume_prototype.py   # alpha=0, works
    E_SCALE=1 ALPHA_DERIVS=0 python3 ...                    # fails at 1 V

## Next steps for whoever picks this up
1. Confirm the intended units of edge_volume_model with upstream
   (devsim GitHub discussions; Juan Sanchez has answered exactly this
   class of question).
2. Alternative discretization: fold generation into the current EDGE
   models themselves (modify ElectronCurrent/HoleCurrent expressions)
   instead of the edge_volume slot.
3. Only then: catalog flag + Physics Lab toggle + published-BV gate
   (ranges already encoded in tests/test_model_benchmarks.py).
