# M42 — Density-gradient quantum correction in structured Device2D/Device3D

Written 2026-09-12. **S1 (Device2D, ohmic contacts only) LANDED
2026-09-17 -- see section 9 for results.** S2 (the GateBC Lambda
boundary condition), S3 (Device3D) and S4 (FinFET demonstration) remain
NOT STARTED -- see section 9's own honest-limits note before assuming
otherwise.

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
