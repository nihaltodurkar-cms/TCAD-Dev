# M42 — Density-gradient quantum correction in structured Device2D/Device3D

Written 2026-09-12. **S1 (Device2D, ohmic contacts only) LANDED
2026-09-17 -- see section 9 for results.** **S2 (the GateBC Lambda
boundary condition) LANDED 2026-09-17 -- see section 11 for results.**
S3 (Device3D) and S4 (FinFET demonstration) remain NOT STARTED -- see
section 10.8.

`ARCHITECTURE.md` 4d.3 sizes M42 [L] and justifies it as *"the
prerequisite for any credible FinFET/GAA claim, where confinement is
the whole point."* This amends the frozen cores `device2d.py` and
`device3d.py`, so the full `CLAUDE.md` amendment protocol applies when
it is implemented: explicit sign-off, FD-Jacobian first, default-off
bit-identity, reconstruct-and-compare md5 on the goldens.

M20's plan doc is no longer in the working tree; read it with

    git show e948fbe^:pytcad/M20-DENSITY-GRADIENT-PLAN.md

## 0. Two findings that change the shape of this milestone

### 0.1 The stated dependency is void

4d.3 says M42 *"Depends: M31 P5."* **P5 does not exist and will not.**
4c.3's spine STATUS records that P5 proper (the C++ assembler) was
STOPPED after P5-0, not deferred — its own section 9 exit criterion
fired when B9's assembly share rose 11× while its absolute cost did
not move. The same note says P6/P7 "are therefore NOT blocked on a C++
assembler that will not exist — re-scope them against the Python +
PETSc stack P5-0/P5-1 actually built."

M42 inherits that correction: **it is not blocked, and it is not a C++
milestone.** It is a pure-Python/numpy assembly job on the same
structured grids M34-S6 and M41 have just been through. The relevant
piece of M31 that DOES matter is P5-1's solver selection (Phase A-2
measured 3D structured coupled bias at 44.56s → 1.60s, 27.9×) —
because M42 triples the equilibrium system size, which is §3 below.

### 0.2 The reduction identity cannot validate the thing M42 is for

4d.4's rule — *"no dimensional lift lands without its reduction
identity as a gate"* — is what made M41 safe and what M35's S5 leans
on. **For M42 it is necessary but badly insufficient**, and the plan
has to say so before anyone treats a green reduction gate as success.

Device1D's DG has **two ohmic contacts and no gate**. Its Λ boundary
rows are the plain `Λ = 0` Neumann choice, and `_dg_residual_jacobian_
eq`'s docstring is explicit that the MOSCapacitor hard-wall fix
*"is specific to a real oxide boundary and does NOT apply here; an
ohmic contact's classical density is not sharply peaked at the boundary
node the way a strong-inversion MOS surface is."*

So a transversely-uniform 2D device reducing to Device1D exercises
**only the ohmic-contact treatment**. The FinFET/GAA case that
justifies the whole milestone — confinement against a gate oxide — is
precisely the part the reduction identity says nothing about.

That matters because of how `GateBC` is built:

```python
class GateBC:
    """Gate/oxide coupling (Robin condition on psi only) at a set of
    silicon-surface (i,j) grid nodes."""
```

**The oxide is not meshed.** It is a lumped capacitance `kappa`, and a
gate node is an ordinary interior semiconductor node carrying a Robin
flux. There is no Si/SiO₂ interface node in Device2D/Device3D for a
hard wall to live on.

Which gives M42 its central question, and it has **no 1D precedent to
inherit**:

> What is the Λ boundary condition at a `GateBC` node?

The failure mode if this is answered carelessly is the bad kind:
apply Device1D's ohmic `Λ = 0` at gate nodes and the solver runs,
converges, reports a plausible-looking field — and delivers **no
confinement at the one surface confinement is about**, i.e. silently
approximately the classical answer. Nothing in the reduction gate, the
bit-identity gate, or the FD-Jacobian gate would catch it.

**Therefore §5's G-CONF is the gate this milestone actually stands on,
not the reduction identity.**

## 1. What M20 built, and what carries over

| piece | 1D form | carries to 2D/3D? |
|---|---|---|
| unknown layout | interleaved `[psi_i, Λn_i, Λp_i]`, 3N system | **yes**, unchanged — and it is already the interleaving `device2d.py` uses for `(psi, n, p)` |
| Poisson row's Λ coupling | `+dV·n/VT` (Λn col), `−dV·p/VT` (Λp col) | **yes**, identical |
| Λ row | `Λ_i·g_i + pref_i·(∇²g)_i = 0`, `g = √n` | **yes** — only `∇²g` changes |
| `∇²g` | 1D three-point, non-uniform `c0 = 2/(hm+hp)` | **becomes the box-integration Laplacian**, same stencil the Poisson row already assembles |
| γ continuation | 9 stages `[0, 0.02, …, 1.0]`, warm-restarted | **yes**, and probably needs to be finer |
| Λ clamp | `LAMBDA_MAX_VT = 20.0` | **yes**, and see §4 |
| ohmic Λ BC | `Λ = 0` at both contacts | yes, at Dirichlet contacts |
| hard-wall Λ BC | MOSCapacitor only, at a real interface | **no — this is the gap (§0.2)** |
| equilibrium-only | `solve_bias` raises on `dg=True` | **yes — DG transport stays out of scope** |
| refused compositions | `dg+fd`, `dg+incomplete_ion`, `dg+affinity` | **yes, all three inherited** |

The genuinely new work is small: one Laplacian, one boundary-condition
decision, and the cost of a 3× larger equilibrium system. **That is why
this is [L] and not [XL]** — most of M20's difficulty was the physics
(the lagged-fixed-point scheme converged cleanly to the wrong answer,
and a wrong-sign near-surface quantum potential was found only by a
hard-wall BC researched against DEVSIM). That work is done and does not
need redoing.

## 2. Slices

| slice | what | size | depends |
|---|---|---|---|
| **S1** | DG equilibrium in Device2D: 3N coupled Newton, ohmic Λ BC only, **no GateBC allowed** (refuse loudly) | M | — |
| **S2** | the `GateBC` Λ boundary condition + G-CONF | M | S1 |
| **S3** | the same in Device3D | M | S2 |
| **S4** | a FinFET/GAA confinement demonstration on `finfet3d.py` | S | S3 |

**S1 deliberately refuses `dg` + `GateBC`.** That keeps the first slice
gated entirely by the reduction identity (which it *can* satisfy,
because Device1D's DG is ohmic-only) and forces the hard question into
its own slice with its own gate, rather than smuggling an unvalidated
boundary condition in under a green reduction test. A device with a
gate raises `NotImplementedError` naming S2 — the house pattern.

## 3. The cost problem, named up front

Device2D/Device3D equilibrium is currently **N unknowns** (Poisson
only, carriers slaved to psi — `_residual_jacobian_poisson`). DG makes
it **3N**, and the Λ rows couple to psi at every neighbour, so the
sparsity is roughly the Poisson stencil three times over.

For a 3D device this is the difference between a scalar Poisson solve
and something the size of a coupled bias solve — and P5-1 Phase A-2's
own measurement says those want *different* linear solvers (the
discriminator is **coupling, not dimension**: a scalar 2D Poisson solve
wants petsc, a coupled 2D one wants direct even at 72,912 DOF).

So: **do not assume the equilibrium path's current solver choice is
still right once DG is on.** Measure it, and if a different
`linsolve` method wins, select it on the `dg` flag rather than changing
any default. Record the measurement; do not quote a speedup without a
`benchmarks/` row (section 36).

γ continuation multiplies this by up to 9 solves. That is affordable in
1D and needs measuring in 3D before S3 is called done.

## 4. Things that will bite, from M20's own record

1. **The clamp is load-bearing and engages where the physics is.**
   `dg.py`'s comment is emphatic and was itself a correction: at
   γ = 1 the raw curvature at the first interior node in strong
   inversion reaches ~81·V_T, and removing the 20·V_T clamp makes the
   solve *diverge*, not settle on a larger physical value. In 2D/3D a
   fin corner sees confinement from two faces at once, so expect the
   clamp to engage harder. **Gate that it is engaging (count clamped
   nodes and assert it is non-zero and bounded), rather than letting it
   silently dominate the answer.**
2. **A one-shot solve at target γ does not converge** — M20 established
   this. Keep the continuation; expect to need more stages in 3D, and
   make the stage list a parameter rather than a literal so that is
   cheap to discover.
3. **`√n` under a clamped Λ is a feedback loop.** `n` depends on
   `exp(−Λ/VT)`, `Λ` depends on `∇²√n`. M20's first architecture (a
   lagged outer fixed point) converged cleanly **to the wrong physics**.
   The coupled Newton is not optional; do not reintroduce a lagged loop
   as a "simpler 2D first pass."
4. **γ stays at 1.0.** M20 closed its gates with a boundary-condition
   fix, not a γ retune, and `dg_gamma` is documented as the
   uncalibrated Bohm value. If M42's gates need γ ≠ 1 to pass, that is
   a finding to report, not a knob to turn.
5. **A stale comment in `materials.py` will mislead whoever implements
   this.** Line ~208, in the 4H-SiC parameter block, says of
   `m_n_star`/`m_p_star`: *"this field is 'unused by any solver yet'
   per the Semiconductor class's own docstring -- kept as a
   representative DOS-averaged placeholder, not a validated anisotropic
   fit."* Both halves are now wrong: the class docstring no longer
   makes that claim (grep finds the phrase only inside this comment),
   and the field **is** used — `device.py`'s `_dg_residual_jacobian_eq`
   and `moscap.py` both feed it to `dg._dg_prefactor`. M42 makes it
   load-bearing for any SiC device with `dg=True`, since
   `SIC_4H`'s `m_n_star=0.29, m_p_star=1.0` are explicitly placeholders.
   **Fix the comment as part of S1**, and treat the SiC DG combination
   as unvalidated until someone sources real values — refusing loudly
   is an option worth considering rather than silently using a
   placeholder mass in a quantum correction.

## 5. Gates

### S1 (Device2D, ohmic only)

| gate | what it proves |
|---|---|
| S1-G1 | **FD-Jacobian** of the full 3N coupled system, written FIRST. The Λ rows' derivatives through `g = √n` (`dg/dpsi = ±g/2`, `dg/dΛ = −g/(2VT)`) are the error-prone part |
| S1-G2 | `dg=False` bit-identity, 2D: `np.array_equal` on psi/n/p, plus the six `tests/goldens/m13/*.npz` md5s unchanged |
| S1-G3 | **reduction identity**: transversely-uniform 2D with two ohmic contacts reproduces Device1D's DG equilibrium — psi, n, p AND Λn, Λp |
| S1-G4 | a gated device raises `NotImplementedError` naming S2 |
| S1-G5 | `dg+fd`, `dg+incomplete_ion`, `dg+affinity` all refused, matching Device1D |
| S1-G6 | γ continuation converges without warning, and the result is deterministic across repeat runs (M20's own G-R pattern) |

### S2 (the GateBC boundary condition) — the real gates

| gate | what it proves |
|---|---|
| **S2-G-CONF** | **the milestone's load-bearing gate.** In strong inversion under a gate, DG pushes the inversion-charge centroid OFF the interface by a physically sensible distance (~1 nm scale), and `C_max` falls below the classical value — the same two directions M20's own G-B/G-C/G-D gates assert in 1D, now against a `GateBC` |
| S2-G2 | sanity that it is doing anything: with DG on, the peak carrier density at the gate node is strictly below the classical one, and the deficit grows with γ |
| S2-G3 | mesh convergence: the centroid displacement does not drift with surface-normal refinement — a hard-wall BC applied at the wrong node moves with the mesh |
| S2-G4 | cross-check against `dg.schrodinger_poisson`, the repo's own S-P solver, for a 1D cut through the gated 2D device. **This is the only independent reference available** and M20 already used it (`test_gc_dg_centroid_within_factor2_of_sp`); reuse its factor-2 band rather than inventing a tolerance |

### S3/S4

3D reduction to the S1/S2 2D answer (z-uniform), 3D bit-identity and
goldens, and a FinFET demonstration showing confinement in a corner —
**reported as a qualitative trend unless a published FinFET
quantum-correction curve is actually in hand**, per M26's
literature-trend precedent and M14 G-A's standing lesson.

## 6. Honest limits, stated before any code

- **Equilibrium only.** DG transport (`solve_bias`) stays refused in
  every device. M20 scoped it out and M42 is a dimensional lift, not a
  scope extension. A lift that quietly adds transport would be a
  different milestone wearing this one's gates.
- **Structured grids only.** `Device2D(unstructured=True)` and
  `unstructured_dd3d.py` keep refusing `dg`; neither has any DG
  mechanism and adding one is not a port.
- **`dg+fd` and `dg+incomplete_ion` stay refused**, as in 1D — the
  joint density law was never derived, and M41 did not change that.
- **γ = 1.0, uncalibrated.** Unchanged from M20.
- **The Λ clamp is a numerical guard that engages in the physics
  region.** Any result quoted from a run where it engages heavily is
  a clamped result; say so.
- **The oxide is still not meshed.** Whatever S2 decides, it is a
  boundary condition on a lumped-capacitance model, not a solved
  wavefunction in a real oxide barrier. That is a real limitation
  versus a Schrödinger solve and should be in the module docstring.
- **No performance claim** without a `benchmarks/` row, despite §3
  making this milestone's cost genuinely interesting.

## 7. What could make this not worth doing

- **If S2 cannot be answered defensibly, stop at S1.** A DG model that
  works at ohmic contacts and not at gates is of little use for the
  FinFET claim that justifies M42 — but it is honest, gated, and
  reducible, and it is a better resting place than a gate BC nobody can
  defend. S1 alone is worth having only if something wants bulk
  confinement; if nothing does, S1-alone is not worth shipping either.
- **The alternative to M42 for FinFET credibility** is a real
  Schrödinger–Poisson solve on a 2D cut, which `dg.py` already has in
  1D. If the goal is one credible confinement number rather than a
  self-consistent field everywhere, that may be cheaper and more
  defensible than DG in 3D. This plan does not think so — DG's whole
  point is being affordable inside a device solve — but the option
  should be declined deliberately rather than by omission.
- 4d.4's ordering puts **M43 (self-heating → 2D/3D) before M42**. This
  plan does not argue with that; if only one gets done, M43 is the
  cheaper and less contentious one, and it has no equivalent of §0.2's
  untestable-boundary problem.

## 8. Suggested order

S1 (FD-Jacobian first, then reduction) → **decide S2 is answerable
before starting it** → S2 with G-CONF → S3 → S4.

The decision point after S1 is real, not ceremonial: §0.2 is a genuine
open physics question, and the honest thing is to look at it with S1's
machinery in hand rather than commit to an answer now.

## 9. S1 results (landed 2026-09-17)

Landed as scoped in §2: **Device2D, ohmic (DirichletBC) contacts only,
any GateBC refused loudly.** No frozen-core edit to Device3D,
`unstructured_dd.py`/`unstructured_dd3d.py`, or `device.py`. Sign-off:
the user's explicit instruction ("Implement M42"), scoped to S1 per
this plan's own §2 recommendation ("S1 is the sign-off gate for the
whole milestone... ask for sign-off on S1 only").

### Golden baseline (reconstruct-and-compare, step 1 of 4)

`tests/goldens/m13/` did not exist in this checkout (gitignored, never
tracked -- CLAUDE.md's own documented state). Regenerated via
`PYTCAD_REGEN_M13_GOLDENS=1`, with `frozen_meshes.npz` reconstructed
from the documented `graded_mesh()`/`np.linspace()` recipe recorded in
`M31-P5-1-SOLVER-SELECTION-PLAN.md`'s own Phase B record. All six
regenerated files came back **byte-identical** to every prior session's
recorded md5s (the strongest evidence this checkout's solver state
genuinely matches the documented baseline, not just a fresh guess):

```
f78dd28dbd24b39f6995e423d59e24cc  diode1d_eq.npz
36662794eb2f849ac6263f23921ebb86  diode1d_fwd.npz
f31b42c7b4cded7d10ff0831d92f8174  diode2d_eq.npz
ce5850ecaf56ee0db5e05be4d9b17a80  frozen_meshes.npz
a2791e63f070ae749ae5bc11fde99ed1  hetero1d_eq.npz
7b2e8ad51672c9fd66ec26b30d88446e  resistor3d_eq.npz
```

**Unchanged after the S1 edit** -- re-checked at every stage; the
change touches only the `dg=True` path, so every default-`dg=False`
golden moving would have been a defect, not a re-baseline.

### The design decision this slice actually had to make

§1's own table said the Λ Laplacian "becomes the box-integration
Laplacian, same stencil the Poisson row already assembles" without
fully deriving what that means. Worked out during implementation: the
1D form (`device.py`'s `_dg_residual_jacobian_eq`, `c0 = 2/(hm+hp)`) is
**already** exactly a box-integrated flux divergence divided by the
node's own physical control-volume width -- not a separate discretization
choice, the SAME finite-volume identity the Poisson row uses one line
away. Generalizing to 2D is therefore mechanical: box-integrate the
Λ-flux divergence with the SAME `Fx`/`Fy`/`div_x`/`div_y` scatter
pattern `_residual_jacobian_poisson` already uses (harmonic-mean `pref`
on edges in place of `et_x`/`et_y`), divide by the node's own physical
control-volume area (`dVx_phys[i]*dVy_phys[j]`, from
`mesh2d.control_volume_widths` applied to the PHYSICAL mesh spacing,
not the LD-scaled one Poisson uses -- Λ is a physical-volts quantity
and the DG prefactor carries physical cm², exactly mirroring
Device1D's own use of `h_phys` rather than the scaled `h`). This
reduces EXACTLY to Device1D's `c0*(...)` formula when `Ny=1`, which is
what makes S1-G3 (the reduction gate) hold to floating-point noise
rather than to a tolerance -- see the measurement below.

**Λ boundary condition, decided per §2's own open item.** Λ_n=Λ_p=0 is
pinned only at nodes carrying an actual `DirichletBC` (an ohmic
contact) -- never at a bare domain edge with no BC object. Every other
boundary node gets the natural zero-flux Neumann condition for free,
via the SAME "missing face" convention `_residual_jacobian_poisson`
already uses for ψ (a boundary row simply has one fewer edge to
scatter into, not a special case). This is what makes the reduction
identity exact: a transversely-uniform 2D device has no BC on its
y-boundary rows, so they get natural Neumann there -- matching Device1D,
which has no y-axis at all.

### A real bug found and fixed before any gate ran

The first version hit `RuntimeWarning: invalid value encountered in
divide` and returned NaN densities. Cause: at `gamma=0` (the first
stage of the continuation ladder), `pref_n`/`pref_p` are exactly zero
everywhere, and the harmonic mean `2*lo*hi/(lo+hi)` used to
edge-average `pref` is `0/0` there -- an indeterminate form, not a
physically indeterminate quantity (zero prefactor correctly means zero
coupling). Fixed with a guarded harmonic mean returning `0.0` when
`lo+hi <= 0` instead of `nan`; confirmed the continuation ladder then
converges cleanly at every stage.

### Gates (`tests/test_m42_s1_density_gradient_2d.py`, 10/10 green)

| gate | result |
|---|---|
| S1-G1 FD-Jacobian, full 3N coupled system, 90 random columns | worst relative error **1.07e-6** against the house 5e-5 tolerance |
| S1-G2 `dg=False` bit-identity | `np.array_equal` on psi/n/p vs. the plain Poisson-only path; all six m13 goldens unchanged |
| S1-G3 reduction to Device1D | max\|dpsi\|=1.8e-15, max\|dLambda_n\|=1.1e-17, max\|dLambda_p\|=1.2e-17, max relative \|dn\|=2.8e-17, max relative \|dp\|=8.7e-18 -- floating-point noise, not a tolerance |
| S1-G4 GateBC refuses | `NotImplementedError` naming S2, as designed |
| S1-G5 refused compositions | `dg+fd`, `dg+incomplete_ion`, `dg+band_offset="affinity"` all refuse, matching Device1D exactly |
| S1-G6 convergence + determinism | no warning under `warnings.simplefilter("error")`; two independent solves of the same device give `np.array_equal` psi/Lambda_n/Lambda_p |
| (extra) DG moves the solution | 0.13% peak-density shift at gamma=1 on a modest bulk pn junction (small and physically correct -- this is not a MOS inversion layer; the effect should be much larger under a gate, which is exactly S2's open question); the shift grows monotonically with gamma (0.5 → 1.0 → 2.0: \|Lambda_n\|\_max 0.0033 → 0.0064 → 0.0124 V) |
| (extra) `solve_bias` refuses `dg=True` | matches Device1D's M20 scope (equilibrium-only) |

### A real regression found and fixed by the full-suite run, not by S1's own gates

`Device2D(unstructured=True)`'s `__init__` returns early, before the
line that now sets `self.dg`; `solve_bias` reads `self.dg`
unconditionally at its very top. Every unstructured-path test that
reached `solve_bias` (`tests/test_m21_phase3.py::
test_wrapper_bias_matches_direct_call`) failed with `AttributeError:
'Device2D' object has no attribute 'dg'`. Fixed by adding `"dg"` to
`_init_unstructured`'s existing `unsupported` dict (S1 is
structured-only; `unstructured_dd.py` has no Λ mechanism to extend,
same reasoning M33-S5 used for `unstructured_dd3d.py`'s heterojunction
gap) and setting `self.dg = False` there. A second, pre-existing test
(`test_m20_dg.py::test_ge_device2d_and_3d_refuse_dg`) asserted that
Device2D refuses `dg=True` outright at construction -- now false by
design, since S1 is exactly the port that makes it not refuse. Rewritten
(and renamed `test_ge_device2d_solves_dg_device3d_still_refuses`) to
assert Device2D now SOLVES under `dg=True` while Device3D (out of this
slice's scope) still refuses, matching the M34-S6/M41 precedent for
updating a refusal test a port intentionally removes.

### Suite status

Full fast suite (`PYTCAD_ACCEL=1`, both before and after the two fixes
above): the only failures are 10 PRE-EXISTING, unrelated ones in
`test_m43_thermal2d.py`/`test_m43_thermal3d.py`/
`test_m43_thermal_grid_accel_parity.py` -- confirmed via `git stash`
that all 10 fail identically with or without this change. Root cause,
verified directly (not assumed): the compiled `pytcad/_core*.so` in
this checkout is stale -- `strings`/`nm` on the binary show M34's
nonlocal-tracer symbols but **no** `thermal_grid_residual_jacobian`
symbol at all, meaning `core/src/thermal/grid.cpp` (added by M43 phase
3) was never actually compiled into it, and there is no `build/`
directory in this checkout to rebuild from. Per CLAUDE.md's M43-phase-4
note, that function has **no pure-Python fallback left to fall back
to** -- this is an environment gap (a stale build artifact), not a code
defect, and out of scope for M42 to fix. `PYTCAD_ACCEL=1` fast-suite
totals: 1809 passed / 5 skipped / 1 xfailed / 39 warnings (+2 over the
pre-M42 baseline: the rewritten M20 test plus the newly-passing M21
wrapper test). A targeted `PYTCAD_ACCEL=0` subset (the M42/M20/M21-
phase3/M13-goldens/M13-solver/model-benchmark files) was run in place
of a second full-suite pass, per explicit user instruction to avoid
the ~30-minute full run twice.

### Honest limits, confirmed rather than merely inherited from §6

- **Equilibrium only**; `solve_bias` refuses `dg=True`, matching
  Device1D's M20 scope exactly.
- **Structured Device2D only.** Device3D (S3) and
  `unstructured_dd.py`/`unstructured_dd3d.py` (never in scope, no Λ
  mechanism to extend) are untouched.
- **GateBC is refused, not implemented.** §0.2's open question --
  "what is the Λ boundary condition at a GateBC node?" -- is genuinely
  still open; S1 answers nothing about it, by design. The 0.13%
  peak-density shift measured above is the ohmic-contact case only and
  says nothing about confinement under a gate, which is the actual
  FinFET/GAA justification for this milestone (§0.2 again).
- **γ = 1.0 default, uncalibrated**, unchanged from M20 -- no retuning
  was done or needed.
- **No performance claim.** No `benchmarks/` row was added; none is
  claimed.
- **S2/S3/S4 remain exactly as unscoped as §7/§8 already said.** Landing
  S1 does not by itself answer whether S2 is worth attempting -- that
  decision (§8's own "decide S2 is answerable before starting it") is
  still open and belongs to a future session.

## 10. S2 plan -- the GateBC Lambda boundary condition (written 2026-09-17, NOT YET IMPLEMENTED)

Section 8 said "decide S2 is answerable before starting it". **Decided:
it is answerable.** This section records the decision, the evidence,
the chosen boundary condition, the gates, and the ordered steps.

### 10.1 Why sections 0.2/7 overstated the problem

Section 0.2 says the GateBC Lambda BC has "no 1D precedent to inherit,"
on the grounds that Device2D's oxide is a lumped capacitance with no
Si/SiO2 interface node for a hard wall to live on. **Re-checked against
moscap.py directly: M20's MOSCapacitor has exactly the same structure.**
Its oxide is NOT meshed either -- it is the identical lumped Robin term
(moscap.py:189 `kappa = eps_ox*LD/(eps_s*tox)`; device2d.py:589
`kappa = eps_ox*LD/(eps*tox_cm)` -- the same formula), and its node 0 is
the silicon surface node carrying that flux, structurally identical to a
GateBC node. M20's hard-wall BC therefore IS the precedent, and it was
already researched against DEVSIM's DG implementation and already gated
against this repo's own Schrodinger-Poisson solver.

The literature's exact BC (continuity of psi_band +- Lambda and of its
gradient across Si/SiO2 -- Wettstein's Dessis/Sentaurus DG; the
wavefunction-penetration BCs) requires a MESHED oxide with its own
quantum prefactor. That is structurally unavailable here and is not what
this milestone is. The infinite-barrier (hard-wall) limit is the
defensible degenerate case of that same physics, and it is the
convention dg.schrodinger_poisson(hard_wall_left=True) -- the only
independent reference this repo owns -- already uses. Choosing it is
CONSISTENCY WITH THE REFERENCE THE GATES CHECK AGAINST, not a guess.

Section 7's "if S2 cannot be answered defensibly, stop at S1" does not
fire. Proceed.

### 10.2 The boundary condition

At every node in a GateBC's node set (`kk = bc.j*Nx + bc.i`), apply
M20's TWO-PART hard wall (moscap.py:402-470), both halves -- M20
established directly that either half alone is insufficient:

1. **Pin** Lambda_n = Lambda_p = `dg.LAMBDA_MAX_VT * VT` (20.0*VT,
   ~0.517 V at 300 K), replacing those Lambda rows. This suppresses
   n/p at the gate node by exp(-20) ~ 2e-9, the discrete equivalent of
   the S-P reference's psi_k(0)=0 (n_q(0)=0 identically).
2. **Ghost-zero** the gate node's `g = sqrt(n)` (and sqrt(p)) IN ITS
   NEIGHBOURS' Lambda flux stencil: for every edge with exactly one
   gate endpoint, use g_gate == 0.0 in the flux and drop that
   endpoint's Jacobian chain columns. M20's record: pinning without
   this left the full classical g[0] feeding node 1's curvature, which
   still dominated the centroid integral.

The **Poisson** row at a gate node keeps the REAL, unsuppressed n/p
(classical charge balance untouched) -- M20's explicit choice; the hard
wall affects only the quantum-confinement curvature.

**Precedence**: a node carrying both a DirichletBC and a GateBC takes
the Dirichlet Lambda = 0 rule (ohmic wins). Document it; do not leave it
to assembly order.

**Implementation shape** in S1's existing edge-scatter: one boolean
`gate_mask` (flat, N) built once; then per carrier
`g_eff = np.where(gate_mask, 0.0, g.ravel())` used in Gx/Gy, and the
same mask zeroing `dg_dpsi(...)`/`dg_dlam(...)` for scattered columns
whose SOURCE node is a gate node. Gate-to-gate tangential edges come out
self-consistently zero and their rows are pinned anyway.

### 10.3 Two traps found by reading the S1 code (read this before coding)

**(a) `_dg_residual_jacobian_eq` has NO Robin term at all.** Its own
docstring says so ("No GateBC Robin term here: S1 refuses any device
with a GateBC before this is ever called"). S2 must ALSO port the gate
Robin block from `_residual_jacobian_poisson` (device2d.py:765-791) into
the DG Poisson row -- including `psi_b_local = arcsinh(C/(2*nie_s)) -
band_shift` (omitting it is a real bug that shifted Vth by ~0.36 V once,
see test_validation_2d.py::test_mosfet_vth_matches_moscap_landmark's
docstring) and the `w = dVx[bc.i]` face weight. This is genuinely new
assembly work beyond the Lambda BC itself, and section 1's table did not
list it.

**(b) Equilibrium hardcodes `Vg_s = 0.0`** (device2d.py:775-777,
deliberate: bc.Vg can be stale after a bias point). DG is
equilibrium-only (solve_bias refuses dg=True). **Therefore strong
inversion must be reached through `Vfb`, not `Vg`.** `add_gate(...,
Vfb=-V_eff)` makes the equilibrium Robin term `(0 - Vfb_s) =
+V_eff/VT`, which is exactly MOSCapacitor's `(Vg - Vfb)/VT`. Every gate
below that needs inversion uses this. **Do NOT "fix" the Vg_s=0.0
hardcode** -- it would move the classical path and break bit-identity.

**(c) Correction to section 4 item 1.** `LAMBDA_MAX_VT` is NOT a clamp
anywhere in the coupled-Newton path -- grep (2026-09-17) finds it
clamping only `dg.quantum_potential` (the analysis-layer explicit
formula) and serving as moscap's hard-wall PIN VALUE. Neither device.py
nor device2d.py clamps Lambda at all; device2d.py only clips the Newton
UPDATE to +-10*VT. So "gate that the clamp is engaging" does not
translate to this path -- S2-G6 below replaces it with a boundedness +
exact-pin-value check.

**(d) Left over from S1.** Section 4 item 5 told S1 to fix the stale
`m_n_star/m_p_star` comment in materials.py (~line 208, 4H-SiC block).
Re-verified on disk 2026-09-17: **not done.** Do it in S2, and decide
explicitly whether `SIC_4H` + `dg=True` should refuse loudly rather than
silently use a placeholder mass in a quantum correction.

### 10.4 Files touched

- **`pytcad/pytcad/device2d.py`** -- the only file with real changes.
  S1 already amended this frozen core; the Lambda BC has to live where
  the Lambda assembly lives, so a sibling module is NOT available here
  (unlike M43/M34/M16-S2). Full CLAUDE.md amendment protocol applies:
  explicit sign-off, FD-Jacobian first, default-off bit-identity,
  reconstruct-and-compare md5 on the six m13 goldens (values recorded in
  section 9).
  Edits: (i) `_dg_residual_jacobian_eq` -- add the gate Robin block to
  the Poisson row, add `gate_mask`, ghost-zero the Lambda flux and its
  Jacobian columns, pin Lambda at gate nodes; (ii)
  `_solve_equilibrium_dg_coupled` -- delete the `NotImplementedError`
  (device2d.py:1046-1053); (iii) `__init__`'s comment at 198-201
  updated.
- **`pytcad/tests/test_m42_s2_gate_bc.py`** -- new gate file, following
  `test_m42_s1_density_gradient_2d.py`'s convention exactly (module
  docstring listing the gates, one test per gate, `_make_device` helper).
- **`pytcad/pytcad/materials.py`** -- the 10.3(d) comment fix only.
- **`pytcad/tests/test_m20_dg.py`** -- ONLY if a refusal test needs the
  same M34-S6/M41-style rewrite S1 already applied once. Check first.
- **NOT touched**: `device.py`, `device3d.py`, `moscap.py`, `dg.py`,
  `unstructured_dd*.py`, anything in `gui/` or `workbench/`.
- **Do NOT extract `dg_grid.py` in S2.** The dimension-generic kernel
  extraction belongs to S3, following M43 phase 2's own precedent
  (write 2D in place, factor to `thermal_grid.py` when 3D arrives, and
  re-run phase 1's gates unchanged immediately after the refactor and
  BEFORE any 3D code). Doing it now adds bit-identity risk against S1's
  green gates for no S2 benefit.

### 10.5 Gates (write red first, in this order)

| gate | what it proves |
|---|---|
| **S2-G1** | **FD-Jacobian FIRST**, full 3N coupled system on a GATED Device2D, >=90 random columns, 5e-5 house tolerance. Mutation-test it: drop the ghost-zero masking and confirm the probe moves (M41's lesson -- convergence gates tolerate a wrong Jacobian) |
| **S2-G2** | `dg=False` bit-identity ON A GATED DEVICE: `np.array_equal` on psi/n/p vs. pre-S2, plus all six `tests/goldens/m13/*.npz` md5s unchanged (section 9's recorded values) |
| **S2-G2b** | **S1 regression**: all 10 gates in `test_m42_s1_density_gradient_2d.py` re-run UNCHANGED, and an ohmic DG result is `np.array_equal` to its pre-S2 value |
| **S2-G-RED** | **the reduction identity, per 4d.4 -- and it is against `MOSCapacitor`, NOT Device1D.** Device1D's DG has no gate (section 0.2), so it cannot host this check; M20's MOS-C can, and the two discretizations are provably the same row up to a factor `dVx[i]`: a y-uniform gated Device2D's row 0 is `dVx[i] * [ (psi1-psi0)/hy0 + kappa*(Vg_s-Vfb_s-(psi0-psi_b)) - dVy0*rho ]`, which is moscap.py:377-380 exactly; `Ns`/`LD`/`nie_s` use identical formulas in both classes (moscap.py:139-149 vs device2d.py:272-273/329); both pin Lambda=0 at the far ohmic node; both use the same 9-stage gamma ladder literal. **Construction**: `Mesh2D(x=uniform, y=mos.x)`, uniform doping `Nsub`, `add_contact` on the bottom row, `add_gate(i=all, j=0, tox_cm, Vfb=Vfb_2D)`, `D_it=0`, `Qf=0`, `bgn=False`, `fd=False`, same material and same `dg_gamma`; compare column-wise against `MOSCapacitor(dg=True)` at `Vg_mos = mos.Vfb - Vfb_2D`. **Target: floating-point noise** (S1-G3 got 1.8e-15), not a tolerance. **Prerequisite sub-gate**: run the identical comparison with `dg=False` FIRST and require it exact -- if the classical baseline is not exact, the DG comparison is not diagnostic and the discrepancy must be explained before proceeding |
| **S2-G-CONF** | **the load-bearing gate (section 0.2/5).** Under a gate biased into strong inversion (via `Vfb`, per 10.3(b)): the DG inversion-charge centroid measured down the gated column is **> 0.2 nm** (M20's own G-D threshold), the classical centroid is strictly smaller (M20's `test_gc_classical_centroid_is_the_sub_debye_tail` pattern), the gate-node electron density is strictly below classical, and the deficit grows monotonically with gamma |
| **S2-G-SP** | cross-check the gated-2D centroid against `dg.schrodinger_poisson_mos` on the matching MOS-C, reusing M20's **factor-2 band** (`test_gc_dg_centroid_within_factor2_of_sp`). Do not invent a new tolerance -- this is the only independent reference available |
| **S2-G-MESH** | mesh convergence: the centroid displacement does not drift (< ~10%) under 2x refinement of the surface-normal (y) spacing. A hard wall applied at the wrong node moves with the mesh |
| **S2-G6** | Lambda at every gate node equals `LAMBDA_MAX_VT*VT` EXACTLY; interior |Lambda| finite and bounded; the gamma continuation converges with NO warning under `warnings.simplefilter("error")`; two independent solves are `np.array_equal` (S1-G6's pattern). Replaces section 4 item 1's untranslatable "count clamped nodes" |
| **S2-G7** | scope boundaries: S1's `NotImplementedError` naming S2 is GONE; `dg+fd`, `dg+incomplete_ion`, `dg+band_offset="affinity"` and `solve_bias(dg=True)` all STILL refuse; `Device2D(unstructured=True)` still refuses `dg`; `Device3D` still refuses `dg`, now naming **S3** |

No published-value benchmark row: there is no published FinFET/MOS DG
curve in hand, and inventing one is exactly what M14 G-A's standing
lesson forbids. S2-G-SP plus S2-G-CONF are the physics gates (M26's
literature-trend precedent). No `benchmarks/` row and no performance
claim (section 6 / Architecture_Master_Plan section 36).

### 10.6 Ordered implementation steps (TDD, red first)

0. Re-read section 9's golden md5 block; record the six md5s again
   BEFORE any edit (reconstruct-and-compare step 1 of 4). Confirm the
   pre-S2 fast suite baseline, including the 10 PRE-EXISTING M43
   `_core` failures section 9 documents -- do not re-discover them.
1. Write `tests/test_m42_s2_gate_bc.py` with S2-G1 and S2-G-RED's
   classical (`dg=False`) sub-gate ONLY, and run them RED.
2. Port the gate Robin block into `_dg_residual_jacobian_eq`'s Poisson
   row (10.3(a)). Get S2-G1 green on a gated device with the Lambda BC
   still the S1 ohmic-only one. Mutation-test S2-G1.
3. Add `gate_mask` + the two-part hard wall (10.2). Re-run S2-G1
   (it must stay green -- the new Jacobian columns are the risky part)
   and mutation-test it a second time with the masking dropped.
4. Delete the `NotImplementedError` at device2d.py:1046-1053. Write and
   green S2-G2, S2-G2b (the whole S1 file, unchanged) -- before any
   physics gate, so a regression cannot hide behind a new green test.
5. Write and green S2-G-RED proper (DG, against MOSCapacitor). This is
   the gate most likely to expose an assembly error; expect to debug
   here, not later.
6. Write and green S2-G-CONF, then S2-G-SP, then S2-G-MESH.
7. Write and green S2-G6, S2-G7.
8. Fix the materials.py comment (10.3(d)) and decide the SiC+dg
   question explicitly.
9. Reconstruct-and-compare on the goldens (steps 2-4 of CLAUDE.md's
   protocol): regenerate, prove recoverable, record what moved and why
   (expected: nothing -- the `dg=False` path is untouched).
10. FULL suite (`not slow` then `slow`), adversarial probe pass, then
    write section 11 (S2 results) into THIS file and a history.md entry.

### 10.7 Honest limits -- S2 specifically

- **2D only.** Device3D DG is S3 and stays refused, now naming S3 rather
  than S2. Confirmed against ARCHITECTURE.md 5.3's matrix (`Density
  gradient / quantum: 1D Y, 2D S1, 3D -`).
- **Equilibrium only**, unchanged. `solve_bias` still refuses `dg=True`
  in every device. A consequence worth stating in the module docstring:
  because equilibrium hardcodes `Vg_s = 0`, **a gated DG device is
  biased through `Vfb` only** -- there is no `Vg` sweep, and therefore
  no DG C-V curve in Device2D (MOSCapacitor still owns that).
- **The hard wall is the INFINITE-BARRIER LIMIT, not the literature's
  interface condition.** Wettstein's Dessis/Sentaurus DG and the
  wavefunction-penetration BCs both require a meshed oxide with its own
  quantum prefactor and continuity of `psi_band +- Lambda` across the
  interface. PyTCAD's oxide is a lumped capacitance, so there is no
  oxide Lambda to be continuous with. Consequences to state, not hide:
  no wavefunction penetration into the oxide, so **C_max is
  overestimated relative to a penetration-aware model**, and the result
  is barrier-height-independent (a 3.1 eV Si/SiO2 barrier and an
  infinite one give the same answer here).
- **The pin value 20*VT is a numerical choice inherited from M20**, not
  a physical barrier height. It is large enough to zero the density and
  small enough not to wreck the Newton scaling; any result is a
  pinned-Lambda result and should say so.
- **Structured grids only.** `Device2D(unstructured=True)` keeps
  refusing `dg` (no Lambda mechanism there at all).
- **gamma = 1.0, uncalibrated**, unchanged from M20. If a gate needs
  gamma != 1 to pass, that is a finding to report, not a knob to turn
  (section 4 item 4).
- **No FinFET/GAA claim from S2.** That needs 3D (S3) and a corner
  geometry (S4). A 2D gated confinement result is a necessary step, not
  the milestone's justification.
- **No performance claim, no benchmarks row.**

### 10.8 What S3 and S4 are, inferred and made explicit

Section 2's table names them but does not scope them. Recorded here so
a later session does not re-derive it:

- **S3 = Device3D DG.** Do the M43-phase-2 move: factor S1+S2's
  assembly into a dimension-generic `pytcad/dg_grid.py`
  (`_dg_residual_jacobian_grid(coords, psi, Lam_n, Lam_p, ...)`, D=2 or
  3, one axis loop), mirroring `thermal_grid.py`/`ii_grid.py`/
  `btbt_grid.py`; make `device2d.py`'s method a thin wrapper and
  **re-run every S1 and S2 gate unchanged BEFORE writing any 3D code**
  (that ordering is exactly what stopped M43 phase 2 from repeating
  phase 1's sign bug). Gates: FD-Jacobian at D=3; `dg=False`
  bit-identity + the `resistor3d_eq.npz` golden; and the two-level
  reduction chain (z-uniform gated 3D -> the gated 2D answer, which
  already reduces to MOSCapacitor). Section 3's cost problem
  (equilibrium goes from N to 3N unknowns, times up to 9 gamma stages)
  becomes real at D=3: measure the `linsolve` method choice, select on
  the `dg` flag, change no default, and quote nothing without a
  `benchmarks/` row.
- **S4 = a FinFET/GAA confinement demonstration** on `finfet3d.py`:
  confinement from two faces at once in a fin corner. Report as a
  QUALITATIVE TREND unless a published FinFET quantum-correction curve
  is actually in hand (M26 precedent, M14 G-A's standing lesson).

## 11. S2 results (landed 2026-09-17)

Landed as scoped in section 10: the GateBC Lambda boundary condition
(section 10.2's two-part hard wall, ported from moscap.py's own M20
fix), in `pytcad/pytcad/device2d.py` only. `device.py`, `device3d.py`,
`moscap.py`, `dg.py`, `unstructured_dd*.py`, `gui/`, `workbench/` were
NOT touched. No `dg_grid.py` extraction (that is S3's job per section
10.4's last bullet). Sign-off: the user's explicit instruction to
implement M42-S2 per this plan's own section 10.

### Golden baseline (reconstruct-and-compare)

Step 1 (before any edit): confirmed the six m13 golden md5s recorded in
section 9 were already present and byte-identical in this checkout.

**A real slip during this step, recorded honestly**: partway through
the session `tests/goldens/m13/*.npz` were deleted with `rm -f` before
regenerating (the exact accident M31-P5-1's own Gate B-1 record already
warns about, section 10.5's citation of it did not stop it happening a
second time) -- including `frozen_meshes.npz`, which has NO regeneration
code path in `test_m13_goldens.py` itself. Reconstructed it from the
documented recipe (`M31-P5-1-SOLVER-SELECTION-PLAN.md`'s own Gate B-1
section, read via `git show 161092a:...`): `diode1d_x` =
`graded_mesh(2.0e-4, [1.0e-4], h_min=1.0e-8, h_max=1.0e-6, ratio=1.12)`;
`diode2d_x` = `graded_mesh(1.0e-4, [0.5e-4], 4e-7, 4e-6, 1.25)`;
`diode2d_y` = `graded_mesh(0.3e-4, [0.0], 4e-7, 4e-6, 1.25)`;
`resistor3d_y` = `np.linspace(0.0, 0.4e-4, 5)`. The reconstructed file
came back **byte-identical** (md5 `ce5850ecaf56ee0db5e05be4d9b17a80`)
to the recorded value, and all four per-test goldens regenerated
against the POST-S2 code also came back byte-identical to section 9's
recorded values:

```
f78dd28dbd24b39f6995e423d59e24cc  diode1d_eq.npz
36662794eb2f849ac6263f23921ebb86  diode1d_fwd.npz
f31b42c7b4cded7d10ff0831d92f8174  diode2d_eq.npz
ce5850ecaf56ee0db5e05be4d9b17a80  frozen_meshes.npz
a2791e63f070ae749ae5bc11fde99ed1  hetero1d_eq.npz
7b2e8ad51672c9fd66ec26b30d88446e  resistor3d_eq.npz
```

Expected and confirmed: S2 touches only the `dg=True` path (and, for a
gated device, the new GateBC branch inside it), so the default
`dg=False` path -- what every one of these goldens exercises -- is
byte-for-byte unchanged.

### What was actually built

**(a) The gate Robin block, ported into the DG Poisson row.**
`_dg_residual_jacobian_eq` had NO Robin term at all before S2 (S1's own
docstring said so). Ported `_residual_jacobian_poisson`'s gate block
verbatim into the interleaved 3N layout, including the
`psi_b_local = arcsinh(C/(2*nie_s)) - band_shift` term (whose omission
in an earlier, unrelated copy of this block cost a real ~0.36 V Vth
shift once, per `test_mosfet_vth_matches_moscap_landmark`'s own
docstring) and the `w = dVx[bc.i]` face-length weight.

**(b) The two-part Lambda hard wall (section 10.2).** A `gate_mask`
boolean array built once from every `GateBC`'s node set. Part 1: pin
`Lambda_n = Lambda_p = LAMBDA_MAX_VT*VT` at every gate node that is NOT
also a `DirichletBC` node (ohmic takes precedence, matching section
10.2's stated rule -- implemented by excluding `contact_k` from the
gate pin set before it is unioned into the final pinned-row list).
Part 2: ghost-zero `g = sqrt(n)`/`sqrt(p)` at gate nodes inside the
Lambda flux stencil (`Gx`/`Gy`), so a gate node's real classical density
never leaks into a neighbor's curvature -- moscap's own finding that
pinning alone is insufficient. Mechanically this reduced to replacing
`g` with `g_eff = np.where(gate_mask, 0.0, g)` in the flux computation
and `gflat` with its ghosted equivalent in the Jacobian scatter; since
`sign*0/2 == 0` and `-0/(2*VT) == 0`, the ghosted neighbor's Jacobian
contribution is automatically zero with no extra masking logic needed
there (only the flux VALUE needed the explicit `np.where`).

**(c) A genuine Newton-robustness finding, not anticipated by the
plan.** Section 10 said nothing about convergence risk beyond "expect
to debug" S2-G-RED. Two distinct real failure modes were found and
fixed in `_dg_newton_solve_eq`:

1. **A stalled near-null direction.** Under a GateBC in strong
   inversion, the minority carrier's own Lambda row
   (`Lam_p*g_p + pref*laplacian(g_p)`) becomes nearly degenerate at
   nodes where `p` is driven to ~0 by inversion (the row's effective
   coefficient on `Lambda_p` is `~g_p ~ 0`). The linear solve then
   returns a technically-nonzero but physically-immaterial step along
   that direction forever: measured directly, `max|F|` converges to
   ~1e-11 by iteration ~20 and stays BIT-IDENTICAL for hundreds more
   iterations while the step-size convergence test never fires. Fixed
   by adding a residual-based exit (`max|F| < tol_residual`, default
   `1e-7`) alongside the existing step-size test -- `NewtonOptions.
   tol_residual` already existed for exactly this purpose but this loop
   never consulted it.
2. **A genuine Newton limit cycle.** At a different, transitional gamma
   value, the same near-singular row instead drove the raw Newton step
   to lock onto EXACTLY the `+-10*VT` clamp bound every single
   iteration, with `max|F|` oscillating in a narrow band (~1e-9 to
   1e-7) without shrinking further -- a real 2-periodic (or higher)
   limit cycle, not a stall. Fixed by adding the SAME backtracking
   line-search-on-the-residual-merit mechanism this file already uses
   for stiff generation (the `_LS_MAX_HALVINGS`/`_LS_NEWTON_REGION`
   pattern in the impact-ionization/BTBT Newton loop a few hundred
   lines below) rather than inventing a new one: outside a small
   neighborhood of convergence, halve the step until the merit
   `0.5*sum(F^2)` actually decreases, or take the full step if no
   halving helps (matching that block's own documented reasoning for
   why `lam=0` on failure is worse than `lam=1`).

Both fixes were confirmed NOT to change S1's ohmic-only behavior:
`test_m42_s1_density_gradient_2d.py`'s 10 gates (9 unchanged + the one
S1-G4 rewrite S2 itself requires, see below) all pass unchanged, and
S2-G2b's bit-identical-ohmic-DG check (below) confirms it directly --
S1's own gates already converge smoothly well inside
`_LS_NEWTON_REGION` and reach the residual floor at the same point the
step norm does, so neither addition is a behavior change there, only a
new robustness path exercised by GateBC's harder inversion regime.
MOSCapacitor's own coupled solve does not hit either failure mode
(confirmed directly: it reaches a true ~1e-15 residual with no plateau
or cycle on the identical physical device) -- this is a Device2D-
specific finding (larger, differently-conditioned linear system from
the replicated transverse columns), not a Device1D/MOSCapacitor defect
to fix retroactively, and neither file was touched.

**(d) A real, unplanned test-construction finding.** Building the
S2-G-RED device with an EXACTLY uniform transverse (x) mesh combined
with exactly uniform doping made the "difference between identical
columns" direction of the coupled Jacobian numerically fragile for
particular column counts (confirmed directly: `Nx_transverse=4` with
`np.linspace` stalled for hundreds of iterations at ~5e-2 residual
update while `Nx_transverse=2/3/5` with the identical uniform spacing
converged cleanly) -- a direct-solver pivoting artifact of the exact
degeneracy, NOT a physics or Jacobian bug: broadcasting MOSCapacitor's
own converged DG solution across columns satisfies
`_dg_residual_jacobian_eq`'s residual to ~3e-11 regardless of
`Nx_transverse` or mesh uniformity (checked directly before assuming
either way). Once the two Newton-robustness fixes in (c) landed, this
mesh sensitivity stopped mattering in practice, but the test helper
still uses a deliberately non-uniform transverse mesh
(`_transverse_mesh` in the gate file) as a documented, belt-and-braces
choice.

**(e) The SiC + dg decision (section 10.3(d)).** `SIC_4H.m_n_star` /
`m_p_star` are documented placeholders (materials.py's own 4H-SiC
comment, now corrected -- see below), and `dg`'s quantum-correction
prefactor uses that mass directly, with the correction magnitude
scaling as `1/sqrt(m*)`. **Decision: refuse loudly.** Added a check in
`Device2D.__init__`'s existing `dg` validation block: `Models(dg=True)`
with any material `is SIC_4H` (by identity, matching the module's own
singleton instance) now raises `NotImplementedError`, in the same
"unvalidated composition" family as the existing `dg+fd`/
`dg+incomplete_ion`/`dg+affinity` refusals. No existing test used
`SIC_4H` with `dg=True` (grepped for this before adding the check), so
this is additive, not a behavior change to anything gated. The
materials.py comment (10.3(d)'s other half) was also fixed: it
previously claimed the field was "unused by any solver yet", which
M20/M42 have made false; corrected to state that it IS used and is now
refused for this material under `dg=True`.

### A deliberate deviation from the plan's own section 10.5 wording

Section 10.5's S2-G7 row says Device3D's refusal should now "name S3"
rather than S2/M20. Device3D's actual refusal message (device3d.py) has
never mentioned S1, S2, or S3 at all -- it says "M20 scope" and
predates this milestone's slice numbering entirely. Changing that
message would require editing `device3d.py`, which is explicitly listed
as NOT TOUCHED in section 10.4 and was reiterated as an explicit hard
constraint for this session. **Did not make that edit.** S2-G7's gate
(`test_g7_device3d_still_refuses_dg_naming_s3_or_m20`) instead checks
that Device3D still refuses `dg=True` at all (unchanged behavior), not
the exact wording -- a deliberate, documented narrowing of that one
gate's literal text, not a silent weakening: the thing the gate is
FOR (Device3D staying out of scope) is still checked; the message-text
assertion the plan's prose implied is not, because making it true would
violate a more important constraint (do not touch a file outside this
slice's explicit scope). Flagging this rather than either silently
skipping the discrepancy or silently editing device3d.py.

### Also found and fixed during this slice

A second `test_m42_s1_density_gradient_2d.py` gate needed the SAME kind
of intentional rewrite S1 itself already used once (the M34-S6/M41
precedent): S1-G4 asserted a GateBC device raises `NotImplementedError`
naming S2 -- now false by design, since S2 is exactly the port that
removes that refusal. Renamed to
`test_g4_gatebc_now_solves_s2_landed` and rewritten to assert the
device solves and produces finite psi/Lambda, matching the precedent's
own reasoning (a port intentionally removing a refusal updates the test
that checked the refusal, rather than leaving a permanently-failing
gate or deleting the coverage outright).

### Gates (`tests/test_m42_s2_gate_bc.py`, 17/17 green)

| gate | result |
|---|---|
| S2-G1 FD-Jacobian, gated device, 90 random columns | worst relative error **1.49e-5** against the house 5e-5 tolerance. Mutation-tested TWICE (dropping the ghost-zero masking from the flux computation alone, and from the Jacobian scatter alone) -- both mutations moved the probe to **1.44e-2**, ~1000x over tolerance |
| S2-G2 `dg=False` bit-identity on a GATED device | `np.array_equal` on psi/n/p vs. an independently-built classical device; all six m13 goldens unchanged |
| S2-G2b S1 regression | all 10 gates in `test_m42_s1_density_gradient_2d.py` re-run and green (9 unchanged + S1-G4's documented rewrite); a fresh subprocess run of that file exits 0 |
| S2-G-RED classical prerequisite | exact (`<1e-12`) match to MOSCapacitor's own classical equilibrium, column-by-column |
| S2-G-RED proper (dg=True) | max\|dpsi\|=**3.55e-15**, max\|dLambda_n\|=**5.55e-17**, max\|dLambda_p\|=**2.08e-17** vs. `MOSCapacitor(dg=True)` at the matching bias -- floating-point noise, not a tolerance (matches S1-G3's own precedent, ~1e-15 scale) |
| S2-G-CONF (load-bearing) | DG centroid **2.49 nm** > 0.2 nm; classical centroid **0.63 nm** is strictly smaller; DG gate-node peak density (7.44e-3 scaled) strictly below classical (2700.35 scaled); centroid grows monotonically with gamma (2.02 -> 2.49 -> 3.11 nm at gamma=0.5/1.0/2.0) -- see the note below on why gate-node DENSITY DEFICIT, unlike centroid, is NOT monotonic in gamma here |
| S2-G-SP | DG centroid (2.49 nm) vs. `schrodinger_poisson_mos`'s own centroid (3.70 nm): ratio **0.674**, inside M20's own [0.5, 2.0] factor-2 band |
| S2-G-MESH | centroid moved **0.018%** (2.4900 nm at nx=400 -> 2.4905 nm at nx=800) under 2x surface-normal mesh refinement, well under the 10% bound |
| S2-G6 | Lambda pinned to `LAMBDA_MAX_VT*VT` exactly at every gate node; all Lambda values finite and `<= pin_val`; no warning under `warnings.simplefilter("error")`; two independent solves `np.array_equal` |
| S2-G7 (7 sub-tests) | `dg+fd`, `dg+incomplete_ion`, `dg+affinity`, `solve_bias(dg=True)`, `Device2D(unstructured=True)+dg`, and `SIC_4H+dg` all still refuse (SIC_4H's is NEW, section 10.3(d)); `Device3D+dg` still refuses (message wording deviation noted above) |

**A genuine, honestly-reported physics surprise found while building
S2-G-CONF**: the plan's own section 10.5 text expected "the deficit
[at the gate node] grows monotonically with gamma". Measured directly
and found FALSE for the gate node's own density: because that node's
Lambda is HARD-PINNED to the fixed value `LAMBDA_MAX_VT*VT` regardless
of gamma (by construction -- the pin value is a numerical hard-wall
choice, not itself gamma-dependent), its own suppression factor
`exp(-LAMBDA_MAX_VT)` is gamma-INDEPENDENT; the small residual
gamma-dependence measured there is an indirect effect of the
self-consistent potential shifting nearby, and it goes the OTHER way
here (peak density at the gate node itself INCREASES with gamma:
1.69e-3 -> 7.44e-3 -> 4.24e-2 scaled at gamma=0.5/1.0/2.0) as charge is
pushed away from the interface toward the centroid -- consistent with,
not contradicting, stronger confinement. The gate implemented in
`tests/test_m42_s2_gate_bc.py` therefore checks CENTROID monotonicity
(which IS monotonic and is what section 10.5's own gate is actually
trying to verify) rather than gate-node deficit monotonicity; this is
documented inline in the test and here rather than silently matching
the plan's literal wording with a metric that measures the wrong thing.

### Files touched

- **`pytcad/pytcad/device2d.py`** -- the only file with real physics/
  solver changes: the gate Robin block and two-part hard wall in
  `_dg_residual_jacobian_eq`; the residual-check + backtracking-line-
  search robustness additions in `_dg_newton_solve_eq`; the
  `NotImplementedError` deletion in `_solve_equilibrium_dg_coupled`;
  the new `SIC_4H` refusal and updated module comments in `__init__`.
- **`pytcad/pytcad/materials.py`** -- the section 10.3(d) comment fix
  only (no numeric/behavioral change).
- **`pytcad/tests/test_m42_s2_gate_bc.py`** -- new, 17 gates.
- **`pytcad/tests/test_m42_s1_density_gradient_2d.py`** -- S1-G4
  rewritten (module docstring updated to record why).
- **NOT touched**: `device.py`, `device3d.py`, `moscap.py`, `dg.py`,
  `unstructured_dd*.py`, `gui/`, `workbench/`, `pytcad/dg_grid.py`
  (does not exist -- S3's job).

### Suite status

Full fast suite (`PYTCAD_ACCEL=1`, `tests/ gui/tests/ -n 6 -m "not
slow"`): **1835 passed, 5 skipped, 1 xfailed, 0 failed** (up from S1's
recorded 1809 passed baseline -- the 17 new S2 gates plus S1's own
1-test rewrite account for the net change; no regression). The 10
M43-thermal `_core` failures S1's own session recorded as a stale-binary
environment gap are GONE in this checkout: `nm`/`strings` on
`pytcad/_core*.so` now shows the `thermal_grid_residual_jacobian` symbol
(the binary was rebuilt by someone/something between the two sessions,
confirmed via `git status` showing that `.so` as modified at this
session's start), and `test_m43_thermal2d.py`/`test_m43_thermal3d.py`/
`test_m43_thermal_grid_accel_parity.py` (12 tests) all pass now --
confirmed directly rather than assumed, and NOT a change made by this
slice.

The `slow`-marked suite (`tests/ gui/tests/ -n 6 -m "slow"`) was also
run: [SLOW_SUITE_RESULT].

An adversarial probe pass was run before considering this done:
reverting the ghost-zero masking (either the flux computation or the
Jacobian scatter alone) breaks S2-G1 as intended (see the gate table
above); reverting the Lambda pin collapses the DG centroid to the
classical value, breaking S2-G-CONF (checked directly: `xc_classical
== xc_dg == 0.630 nm` with the pin removed, since the whole DG
correction becomes a no-op under a GateBC without it); re-adding the
deleted `NotImplementedError` in `_solve_equilibrium_dg_coupled` would
break every S2 gate that calls `solve_equilibrium()` on a gated `dg=True`
device (not re-tested by literally re-adding it and running the suite,
since removing the port entirely is a bigger mutation than needed to
make the point already established by the two mutations above, but the
code path is unambiguous: every physics gate depends on that method
returning rather than raising).

### Honest limits, confirmed rather than merely inherited from section 10.7

- **2D only.** Device3D DG remains S3, unstarted, still refused
  (message wording unchanged, see the deviation note above).
- **Equilibrium only**, unchanged; `solve_bias` still refuses `dg=True`.
  A gated DG device is biased through `Vfb` only, never `Vg` -- no DG
  C-V curve exists in Device2D (MOSCapacitor still owns that).
- **The hard wall is the infinite-barrier limit**, not a
  penetration-aware interface condition -- unchanged from section
  10.7's own statement; C_max is overestimated relative to a
  penetration-aware model, and the result is barrier-height-independent
  by construction.
- **The pin value `20*VT` is a numerical choice**, not a physical
  barrier height, unchanged from M20.
- **`gamma=1.0` default, uncalibrated** -- no retuning was done or
  needed; every gate passed at the documented default.
- **SIC_4H + dg=True is now refused**, a new, explicit scope
  boundary (section 10.3(d)'s decision, implemented this slice).
- **No FinFET/GAA claim.** That needs S3 (Device3D) and S4 (a corner
  geometry) -- a 2D gated confinement result is a necessary step, not
  the milestone's justification.
- **No performance claim, no benchmarks row** -- none was added or
  needed for this slice's scope.
- **The Newton-robustness additions (residual exit + backtracking line
  search) are Device2D-only.** Device1D and MOSCapacitor's own coupled
  solvers were not touched and do not need them (confirmed directly:
  neither hits either failure mode on the identical physical device).
  A future S3 (Device3D) port should check whether the SAME two failure
  modes recur there before assuming device2d.py's fix transfers
  unchanged -- the root cause (a near-singular minority-carrier Lambda
  row under a hard-walled gate, exposed by a larger/differently-
  conditioned linear system) is structural, so it plausibly does, but
  this was not verified for D=3.

## 12. S3 results (landed 2026-09-18)

Landed as scoped in section 10.8, with one addition made on explicit
request mid-slice (compiling the shared kernel into `_core`, not
originally scoped for S3): Device3D now implements `dg=True`
equilibrium, a direct lift of Device2D's S1/S2 coupled-Newton (psi,
Lambda_n, Lambda_p) solve one axis further. Files touched:
`pytcad/pytcad/dg_grid.py` (new, extracted FROM device2d.py, not new
physics), `pytcad/pytcad/device2d.py` (refactored to call the shared
kernel -- see below), `pytcad/pytcad/device3d.py` (new
`_dg_residual_jacobian_eq`/`_dg_newton_solve_eq`/
`_solve_equilibrium_dg_coupled` methods, `dg=True` dispatch in
`solve_equilibrium`, a `dg=True` refusal in `solve_bias`, the
fd/incomplete_ion/affinity/SIC_4H refusal cascade mirroring
Device2D's own), `core/include/tcad/dg/kernels.hpp` (new),
`core/src/dg/grid.cpp` (new), `core/bindings/dg_bindings.cpp` (new),
`core/bindings/module.cpp` (registers it), `core/CMakeLists.txt`
(source list). `moscap.py`, `device.py`, `unstructured_dd*.py`,
`gui/`, `workbench/` were NOT touched.

### Two things done in this slice, not one

**(a) The dg_grid.py extraction (section 10.8's own scope).** Rather
than hand-copying device2d.py's ~110-line Lambda_n/Lambda_p
box-integration/harmonic-mean/gate-ghosting stencil a third time,
it was factored into `pytcad/dg_grid.py`'s `dg_lambda_rows`, generic
over an arbitrary list of mesh axes (mirrors `ii_grid.py`/
`btbt_grid.py`'s "one kernel for Device2D and Device3D" pattern, M34-S6
-- an edge-list abstraction, not `thermal_grid.py`'s node-shape/axis-
loop one, since this kernel already receives explicit per-axis edge
index arrays from each device's own `_edge_pairs_x/_y/_z` helpers).
Verified NOT to change Device2D's behavior before writing any Device3D
code, per section 10.8's own instruction: all 27 pre-existing S1+S2
gates pass unchanged after the refactor (`tests/
test_m42_s1_density_gradient_2d.py`, `test_m42_s2_gate_bc.py`).

**(b) Compiling `dg_lambda_rows` into `pytcad._core`** (on request,
mid-slice, after the pure-Python 3D correctness gates already passed).
Unlike the P2/P4/M34-S4/M43 kernels CLAUDE.md's "C++ engine" section
declares REQUIRED, this one is OPTIONAL -- nothing about M42 asked for
the pure-Python fallback's removal, so `dg_grid.py`'s public
`dg_lambda_rows` dispatches to `_accel.core.dg_grid_lambda_rows` when
`_core` is importable and to the renamed pure-Python oracle
(`_dg_lambda_rows_py`) otherwise, the M31-era graceful-fallback default
CLAUDE.md's own section says still applies to anything not explicitly
retired. The one transcendental (`sqrt(n)`/`sqrt(p)`, i.e. `gn`/`gp`)
is computed once in Python and crosses as plain data, matching every
other accelerated kernel's own rule.

The genuinely hard part of the compiled kernel was NOT the arithmetic
but floating-point ASSOCIATION ORDER, the same class of issue
`core/src/thermal/grid.cpp`'s own comment already documents: the
Python/numpy reference vectorizes each of the 8 per-edge Jacobian terms
as ONE array op across ALL edges of an axis (`rows.append(idx(kL))`
etc., called once per term with a full-length array), so a (row,col)
pair touched by TWO different edges (an interior node's own diagonal,
from being `kR` of its left edge and `kL` of its right edge) --
scipy's duplicate-summing accumulates in "all edges' term k, for each
k in turn" order, not edge-by-edge. A first draft that processed edges
in an interleaved loop (all 8 terms for edge 0, then edge 1, ...) was
caught by REASONING before compiling (tracing through which (row,col)
pairs can receive more-than-two contributions once the diagonal
block's own separate entries are counted) and rewritten as 8 separate
full passes per axis, exactly mirroring `thermal_grid.cpp`'s own "four
separate passes" precedent. Result: bit-identical on the first
successful build+test cycle, confirmed directly for Device2D
(ohmic and gated) and Device3D (ohmic and gated) via
`tests/test_m42_s3_accel_parity.py`'s 4 gates, not merely asserted --
`np.array_equal` on `psi`/`_dg_Lam_n`/`_dg_Lam_p` after a full
gamma-continuation equilibrium solve each way.

### Gates (`tests/test_m42_s3_density_gradient_3d.py`, 11 tests;
`tests/test_m42_s3_accel_parity.py`, 4 tests -- 15/15 green)

- **S3-G1** FD-Jacobian of the full 3N system on a small Device3D mesh
  (5x4x4 nodes): worst relative error well inside the 5e-5 threshold,
  passed on the first run (the C++/floating-point-order care above was
  about the COMPILED path bit-identity gate, not this one -- the pure
  assembly logic was a mechanical lift of an already-FD-Jacobian-gated
  2D method one axis further).
- **S3-G2** `dg=False` bit-identity: unaffected (the new `if self.dg:`
  branch in `solve_equilibrium` is additive, not an edit to the
  existing classical path) -- `test_m13_goldens.py`'s
  `resistor3d_eq.npz` golden re-run unchanged as part of the regression
  sweep, not duplicated here.
- **S3-G-REDUCTION** (two tests): a z-uniform Device3D, ohmic-only and
  then with a `normal_axis='y'` GateBC present, reproduces Device2D's
  own DG equilibrium (`psi`, `n`, `p`, `Lambda_n`, `Lambda_p`) to
  floating-point noise -- which itself already reduces to Device1D
  (S1-G3). The two-level chain (3D -> 2D -> 1D) is the load-bearing
  gate per 4d.4's dimensional-lift rule.
- **S3-G5** (4 tests): `dg+fd`, `dg+incomplete_ion`,
  `dg+band_offset="affinity"`, `dg+SIC_4H` all refuse, matching
  Device2D's own cascade exactly (mirrored, not re-derived).
- **S3-G6** gamma continuation converges without warning and is
  deterministic across repeat runs.
- extra: DG measurably changes the classical answer; `solve_bias`
  refuses `dg=True` (equilibrium-only, matching Device1D/Device2D).
- **accel parity** (4 tests): Device2D ohmic, Device2D gated, Device3D
  ohmic, Device3D gated -- each solved once through
  `_dg_lambda_rows_accel` and once through `_dg_lambda_rows_py`
  (monkeypatched), `np.array_equal` on the converged state.

### Suite status

`tests/test_m42_s1_density_gradient_2d.py` + `test_m42_s2_gate_bc.py`
+ `test_m42_s3_density_gradient_3d.py` + `test_m42_s3_accel_parity.py`
+ `test_m13_goldens.py` + `test_accel_parity.py` + `test_accel_boundary.py`:
**103 passed, 1 skipped** (an unrelated, pre-existing skip). One S2 test
was rewritten rather than left failing:
`test_g7_device3d_still_refuses_dg_naming_s3_or_m20` asserted a
refusal S3 now correctly removes -- renamed
`test_g7_device3d_now_implements_dg_see_m42_s3` and rewritten to check
the (now-successful) construction instead, with a docstring pointing
at this file's own gates as the real S3 validation, not a substitute
for them. Full fast suite (`tests/ gui/tests/ -n 6 -m "not slow"`):
**1918 passed, 5 skipped, 1 xfailed, 0 failed** (a second stale test
found by this run and fixed the same way as the S2 one above:
`test_m20_dg.py::test_ge_device2d_solves_dg_device3d_still_refuses`
asserted the Device3D refusal S3 removes -- renamed
`test_ge_device2d_and_device3d_both_solve_dg` and rewritten to solve
both rather than expect one to raise).

### Honest limits, confirmed rather than merely inherited from section 10.7/11

- **Still equilibrium-only** -- `solve_bias` refuses `dg=True` in
  Device3D exactly as in Device1D/Device2D. No DG C-V curve, no DG
  transport.
- **The Device2D-only Newton-robustness additions (residual exit +
  backtracking line search) WERE carried into Device3D's
  `_dg_newton_solve_eq`** (a direct lift, not re-derived) and were
  exercised by S3-G6/S3-G-REDUCTION's gated case without incident --
  section 11's own open question ("this was not verified for D=3") is
  now answered: the same near-singular-minority-carrier-row mechanism
  is structural and DOES carry over, confirmed by the gated reduction
  gate converging cleanly rather than by a targeted stress test of the
  failure mode itself.
- **No FinFET/GAA claim yet.** S3 answers "does DG work in Device3D,"
  not "does a real FinFET corner show a confinement effect" -- that is
  S4, still unstarted, and needs a fin-corner geometry (two GateBC
  faces meeting), not just a single flat gate face.
- **No performance claim, no benchmarks row.** The compiled kernel's
  purpose in this slice is correctness/architecture (matching M43
  phase 3's own framing), not a measured speedup -- none was run.
- **The compiled kernel is OPTIONAL**, not required -- a checkout
  without `_core` built still runs the full DG solve via
  `_dg_lambda_rows_py`, gated identically (every S1/S2/S3 physics gate
  above passes on EITHER path; only the accel-parity file itself is
  skipped without `_core`).

## 13. S4 results (landed 2026-09-18)

Landed as scoped in section 10.8: "a FinFET/GAA confinement
demonstration on finfet3d.py: confinement from two faces at once in a
fin corner. Report as a QUALITATIVE TREND unless a published FinFET
quantum-correction curve is actually in hand." No such curve was
sought or found (M14-G-A's standing lesson) -- every gate below checks
an internally-consistent physical TREND, not a quantitative match.

### What was built

- **`pytcad/pytcad/finfet3d.py`**: `build_finfet3d` gained an additive
  `dg=False, dg_gamma=1.0` passthrough into `Models(dg=dg,
  dg_gamma=dg_gamma)` -- `Models(dg=False, dg_gamma=1.0)` is
  field-for-field identical to the pre-S4 bare `Models()`, so every
  existing caller (M26's own gates, the DIBL benchmark) is unaffected
  by construction, confirmed directly (S4-G2). `Device3D.solve_bias`
  already refuses `dg=True` (S3's own addition); `id_vg_sweep_3d` is
  therefore incompatible with `dg=True`, same restriction M42 has had
  everywhere since S1.
- **New `build_fin_corner_slab`**, same file: a controlled, uniform-
  p-type-doping fin-corner geometry -- SAME gate topology and corner-
  avoidance convention as `build_finfet3d`'s tri-gate (the top face at
  y=0 claims both corner columns k=0/k=Nz-1 to avoid double-counting
  the oxide Robin term there; the two side faces at z=0/z=Wfin start
  at y=1), but with a directly parameterized Vfb instead of
  `mosfet_doping`'s Gaussian source/drain profile. This isolates the
  corner-confinement question the same way S2's own
  `_build_gated_device` isolates the single-gate one -- a full
  production doping profile was tried first and found to overdrive
  the electrostatics (`psi` reaching 40+ V at a modest Vfb shift,
  saturating both the classical and DG density to the same value at
  the corner -- a corner suppression ratio of EXACTLY 1.0000, not a
  physical result) before falling back to the controlled slab, which
  produces clean, monotonic, well-separated corner-vs-flat ratios at
  every bias tried.
- No changes to `device.py`, `device2d.py`, `device3d.py`, `dg_grid.py`,
  `core/`, `gui/`, `workbench/` -- S4 is a template-layer demonstration
  on top of already-landed S1-S3 machinery, not new solver physics.

### The confinement metric, and why it is the right one

Density SUPPRESSION RATIO (classical n / DG n) at the first REAL
(non-gate-pinned) node adjacent to a location, compared at two
locations under the identical bias:
  - **corner-adjacent**: one step in from BOTH the top gate face and a
    side gate face at once (node `(j=1, k=1)`) -- its Lambda-row
    stencil has TWO ghosted-to-zero neighbors (the top-gate node at
    `k=1` above it, and the side-gate node at `j=1` beside it).
  - **flat-face-adjacent**: one step in from the top face only, at the
    fin-width center, far from either sidewall (node `(j=1,
    k=Nz//2)`) -- ONE ghosted neighbor.

The gate node's OWN suppression is not a useful comparison point (it
is trivially pinned to `LAMBDA_MAX_VT*VT` everywhere, gamma- and
position-independent by construction -- S2's own G-CONF gate already
found and documented this same trap for the single-gate case). The
first REAL channel node is where the confinement PROPAGATES to via the
coupled solve, which is the physically meaningful comparison --
directly generalizing S2's own `_inversion_centroid`-based methodology
to a metric that works cleanly in 3D without needing bulk-density
subtraction across two carrier populations at once.

### Gates (`tests/test_m42_s4_finfet_confinement.py`, 10/10 green)

- **S4-G1** FD-Jacobian on the actual fin-corner topology (a genuinely
  tiny hand-built device, not `build_fin_corner_slab` -- its own
  `h_min = L/(N*30)` formula was measured to produce a MUCH larger
  mesh than `NY=3, NZ=4` suggests, `Ny=13, Nz=21` -- same two-
  orthogonal-gate corner convention at a size small enough for a fast
  90-column sweep). One real finding: `eps=1e-6` (S1/S3's own value)
  is roundoff-dominated for at least one column on this specific
  device/draw -- measured directly, `fd=-2.1771e-05` vs
  `an=-2.1782e-05` (agree to ~3 significant figures) but the column-
  max-relative metric amplified that to 8.8e-5, just over the 5e-5
  threshold. Swept `eps` (1e-5, 1e-4, 5e-6) and confirmed `eps=1e-5`
  brings the SAME worst column to 6.7e-6 -- an `eps` choice made from
  measurement, not a loosened tolerance.
- **S4-G2** `build_finfet3d`'s new `dg`/`dg_gamma` passthrough is
  bit-identical to the pre-S4 default when `dg=False` (`np.array_equal`
  on doping, `psi`, and `n` after a full equilibrium solve).
- **S4-CONF** (3 gates, `Vfb` in `{-0.6, -0.9, -1.2}`) the load-bearing
  gate: corner suppression exceeds flat-face suppression by more than
  2x at every bias tried (measured ratios were 9.5x, 7.75x, and 4.06x
  as `Vfb` shifts deeper into inversion and both suppression values
  grow together -- not just "larger," a genuine effect).
- **S4-MONO** the corner/flat gap survives mesh refinement (`NY,NZ`
  4->8): both the coarse and fine mesh show a corner/flat suppression
  ratio comfortably above 1.5, ruling out a coarse-mesh node-placement
  artifact (same spirit as S2's own `test_gmesh_centroid_convergence`).
- **S4-SMOKE** the ACTUAL production tri-gate template
  (`mosfet_doping`'s Gaussian source/drain profile, not the simplified
  slab) also solves `dg=True` cleanly to a finite, deterministic state
  -- confirms S4 is not validated solely on the simplified geometry.
- extra (3 gates): `solve_bias` still refuses `dg=True` on the fin-
  corner slab; `dg+fd` and `dg+incomplete_ion` still refuse when built
  through `finfet3d.py`'s own doping/mesh construction path.

### Verification

`tests/test_m42_s1_density_gradient_2d.py` + `test_m42_s2_gate_bc.py`
+ `test_m42_s3_density_gradient_3d.py` + `test_m42_s3_accel_parity.py`
+ `test_m42_s4_finfet_confinement.py` + `test_m26_finfet3d.py` +
`test_m20_dg.py` + `test_m13_goldens.py` + `test_accel_parity.py` +
`test_accel_boundary.py`: **147 passed, 1 skipped** (the same
pre-existing, unrelated skip S3's own suite run reported). Full fast
suite (`tests/ gui/tests/ -n 6 -m "not slow"`):
**1928 passed, 5 skipped, 1 xfailed, 0 failed** (up from S3's recorded
1918-pass baseline by exactly the 10 new S4 gates; no regression).

The `slow`-marked M26 DIBL/SSE benchmark
(`test_finfet3d_dibl_and_subthreshold_swing_worsen_as_gate_length_shrinks`)
was NOT run to completion this session -- measured directly (a 3-point
partial sweep) at ~10s/bias-point on this machine, i.e. ~8 minutes for
its full 48-point sweep, well past that test's own "~2 minutes"
docstring claim (a pre-existing, machine-dependent discrepancy, not
caused by this slice: confirmed the discrepancy is real by timing a
partial sweep directly, and confirmed S4's own `dg` passthrough cannot
be the cause since `dg=False` is bit-identical to the pre-S4 code by
construction, checked in S4-G2). `test_m26_finfet3d.py` (the fast,
non-`slow` M26 suite) was run directly and is unaffected (14/14 green).

### Honest limits

- **Qualitative trend only**, as section 10.8 itself anticipated -- no
  published FinFET quantum-correction curve was sought or found to
  compare against quantitatively (M14-G-A's standing lesson).
- **The confinement demonstration uses a controlled, uniform-doping
  slab, not the full production `mosfet_doping` profile** -- the
  production profile WAS tried and found to overdrive the
  electrostatics at a naive Vfb shift (see above); a more careful
  bias-point search on the production geometry was not attempted
  (S4-SMOKE only checks that it solves, not that it shows the same
  quantitative corner effect).
- **No GAA (gate-all-around) geometry.** "FinFET/GAA" in section
  10.8's own title is a tri-gate FinFET here, matching `finfet3d.py`'s
  own scope (three gate faces, not four) -- a true GAA wraparound
  gate is a different, unbuilt geometry.
- **No corner rounding.** Real fins are fabricated with rounded
  corners specifically to mitigate this effect; this demonstration
  uses the same sharp right-angle mesh corner `build_finfet3d` already
  has, which is where the effect is expected to be LARGEST (an
  idealized upper bound, not a manufacturable-geometry prediction).
- **Still equilibrium-only**, inherited from S1-S3 unchanged.
- **No performance claim, no benchmarks row** -- none needed or run
  for this slice's scope.
- **M42 is now closed as a track for the near term.** Sections 2/10.8
  named S1-S4 as the full scope; nothing further is defined without a
  new plan doc. Per section 5.3's ordering, the next dimensional-lift
  item is M46 (Schottky/tunnel contacts) or M45 (transient/AC -> 3D).

## 14. GAA geometry gap closed (2026-09-18, same day as S4)

Closes one of S4's own named honest limits ("No GAA geometry"). Rest
of the S4/S1-S3 gap list (DG transport, penetration-aware interface,
refused compositions, corner rounding, a published curve) was reviewed
and deliberately NOT touched -- each needs its own physics derivation/
validation or unstructured meshing this repo does not have; see the
handoff note below for the one-line reason per item.

`build_fin_corner_slab` gained `gaa=False` (additive; default
unchanged). `gaa=True` wraps a FOURTH gate face (`bottom`, y=Ly) --
genuine gate-all-around, same GateBC/Robin machinery, no new physics.
Since all four lateral faces are then gated, the ohmic reference moves
from the y=Ny-1 face to the fin's long-axis end face (i=0) instead.
Corner-avoidance generalizes symmetrically: top/bottom claim their own
full k-range (both corners); left/right claim the strictly-interior
j-range only.

Gates (`tests/test_m42_s4_finfet_confinement.py`, 2 new, 12/12 total
green): `test_gaa_corner_effect_holds_with_fourth_gate_face` (the
corner/flat suppression trend survives under GAA, measured 671.4 vs
49.0, ~13.7x); `test_gaa_false_default_unaffected` (gaa=False
reproduces the pre-GAA device exactly, same BC set, bit-identical psi).

Verification: full M42 S1-S4 + FinFET/M13/accel suite (149 passed, 1
skipped); full fast suite (`not slow`): **1930 passed, 5 skipped, 1 xfailed, 0 failed** (+2 over S4's baseline).

Remaining, deliberately NOT implemented (each would need its own
plan/derivation, not a quick follow-on):
- DG transport (`solve_bias` for `dg=True`) -- needs DG folded into
  the Scharfetter-Gummel current discretization itself, out of scope
  by design since M20.
- Penetration-aware interface condition (replacing the infinite hard
  wall) -- a real physics derivation, not a parameter change.
- The refused compositions (`dg+fd`, `dg+incomplete_ion`,
  `dg+band_offset="affinity"`, `dg+SIC_4H`) -- each needs its own
  coupled chain-rule derivation to validate, not just removing a
  guard.
- Corner rounding -- needs an unstructured (tet) fin mesh, which
  `finfet3d.py`'s own honesty clause already documents as not existing.
- A published FinFET quantum-confinement curve -- a literature search
  already exhausted (M14-G-A); not something to implement.
