# M35 — 3D Process Simulation

Written 2026-09-12. **Plan only — not implemented, not signed off.**
`ARCHITECTURE.md` 4c.2 sizes M35 [XL] and calls it "the single biggest
remaining Sentaurus-parity gap"; 4d.2 observation 3 says the same from
the dimensional side ("a 3D device built from a 2D process flow is only
as 3D as its weakest input").

This plan does **not** ask for sign-off as a unit. It asks for sign-off
on **S1 only**, because S1 is the decision the rest depends on and the
one that is cheapest to get wrong.

## 0. The finding that reorders this milestone

4c.2 states M35's remaining scope as a feature list:

> 2D moving-boundary oxidation (LOCOS/STI bird's beak), the
> deposition/etch topology engine, masks, silicidation, epitaxy, CMP —
> and none of it in 3D.

Read against the code, **that list is misleading, and taking it at face
value would produce six independently-broken features.** Every item on
it is blocked by one thing:

`process2d.ProcessGeometry2D` is a **single-valued height field** —
three per-column scalars (`surface_um`, `ox_thick_um`,
`si_consumed_um`) on a fixed lateral grid `x`. A height field cannot
represent re-entrant geometry, by construction. So it cannot represent:

| feature 4c.2 asks for | what it needs that a height field cannot hold |
|---|---|
| deposition/etch topology | conformal sidewall coverage on a vertical wall; undercut; a pinched-off void |
| moving-boundary oxidation | the oxide/silicon interface AND the oxide/ambient surface as two independent fronts that move at different rates |
| silicidation | a buried reacting interface consuming two materials |
| epitaxy | facet-dependent growth rates (a single height has no facet normal) |
| CMP | trivially expressible — the one genuine exception |
| any of it in 3D | nothing in the representation is dimension-generic |

The current module is honest about this (its honesty clause says
deposit/etch are "purely vertical", the isotropic-etch option is "a
smoothing approximation, not a transport-limited etch model", and
bird's beak comes from "a lateral oxidant-diffusion suppression kernel
under the mask edge, not from a mechanical model"). Nothing here is a
criticism of M23 — it shipped a disclosed slice and said so. The point
is that **the slice's boundary is the representation**, and M35 is the
milestone that has to move it.

So the spine of this plan is: **replace the representation first, port
the existing physics onto it with the existing gates as the identity,
then add features, then go to 3D.** Features added before the
representation moves would each have to be written twice.

## 1. Slices

Each is independently shippable and independently gated. Sizes are
relative to each other, not absolute.

| slice | what | size | depends |
|---|---|---|---|
| **S1** | level-set front representation, 2D, replacing the height field behind the existing API | L | — |
| **S2** | deposit/etch as real topology ops on S1 (conformal, isotropic, re-entrant) | M | S1 |
| **S3** | 2D oxidation as a genuine moving-boundary problem (oxidant transport + volume expansion + stress-LITE) | L | S1 |
| **S3b** | **dopant transport across the moving boundary**: advection with moving material + segregation as a flux condition | M | S3 |
| **S4** | masks as first-class 2D objects; silicidation, epitaxy, CMP as topology ops | M | S2 |
| **S5** | the same level set in 3D + tet meshing of the result | L | S1–S4 |
| **S6** | the process→device handoff in 3D: a real 3D doping field, not per-region constants | M | S5 |

**S1 is the sign-off gate for the whole milestone.** If S1 lands and
the M23 gates still pass, the rest is incremental. If S1 cannot be made
to reproduce them, stop and re-plan rather than proceeding.

## 2. S1 — the representation

### 2.1 What to build

A signed-distance level set φ on a fixed background grid, one field per
**material region** (silicon, SiO2, nitride, poly, resist, metal,
silicide, ambient), with the convention φ < 0 inside. Geometry queries
("which material is at this point", "where is the Si/SiO2 interface")
become sign tests and zero-crossing interpolations rather than column
bookkeeping.

Motion is the standard level-set advection

    dφ/dt + V |∇φ| = 0

with V the normal speed supplied by whichever process step is running
(etch rate, deposition rate, oxidation rate). Reinitialize φ to a
signed distance between steps.

### 2.2 The three decisions that need to be right

1. **Multi-material bookkeeping.** Independent per-material level sets
   drift apart: after a few steps two can claim the same point, or
   neither can, leaving vacuum slivers at a triple junction. The fix in
   the literature is a Voronoi-style rule (assign each point to the
   material with the most negative φ) plus a projection step that
   removes overlaps and gaps. **This must be in from the start.** It is
   the single most common way a multi-material level set quietly
   produces garbage, and it cannot be retrofitted because every later
   slice consumes the material map.
2. **Grid vs narrow band.** Start with a **full background grid**, not
   a narrow band. A narrow band is the standard performance answer, but
   M31 P2's own measurement discipline applies: build the simple thing,
   measure it against a real LOCOS/STI flow, and only then decide.
   Premature banding would also make S5's 3D version much harder to get
   right.
3. **Where the background grid comes from.** Its own **uniform** grid
   (see 2.4), not the device mesh and not `Mesh2D`. The process grid
   resolves the *front*, the device mesh resolves the *solution*. Say
   so in the module docstring; conflating them is how a process engine
   ends up dictating device mesh refinement.

### 2.3 The API question, and the answer

`process2d` has **eleven** referencing files, not the handful this
section originally listed (measured, not recalled):

| consumer | why it constrains S1 |
|---|---|
| `tests/test_m23_process2d.py` | 8 behavioural gates, two of which assert EXACT arithmetic (see below) |
| `tests/test_public_api_surface.py` | freezes `"process2d"` in the public API list — the module must keep its name and exports |
| `tests/test_model_benchmarks.py` | published-value gates |
| `tests/test_accel_parity.py` | imports it as `_p2d` — the compiled/Python oracle diff |
| `tests/test_m26_finfet3d.py` | constructs `ProcessGeometry2D` directly |
| `pytcad/gmsh_finfet3d.py` | reads `surface_um` to extrude |
| `pytcad/ted.py` | names `oxidize_2d`'s moving boundary in its honesty clause |
| `pytcad/finfet3d.py` | references the convention in its docstring |
| `pytcad/__init__.py` | re-exports it |
| `examples/08_locos_flow.py`, `examples/13_finfet3d_from_process2d.py` | demos that must keep running |

**Do not change those signatures in S1**, and do not make the height
field a derived view either — that was this plan's first design and it
is wrong. Two of the M23 gates assert arithmetic a level set cannot
reproduce:

```python
# test_deposit_then_etch_round_trip_conserves_thickness_exactly
assert np.allclose(g2.surface_um, geom.surface_um, rtol=0, atol=1e-13)
# test_deposit_etch_respect_the_open_mask
assert np.all(g.surface_um[mask] == 1.0)      # literal float equality
```

A height recovered from a level set comes from zero-crossing
interpolation and is **grid-limited**, nowhere near `1e-13` and never
exactly `1.0`. So "the height field is a derived view" and "the M23
gates pass unchanged" cannot both be true.

**The resolution: S1 carries BOTH states, and the height field stays
authoritative for the purely vertical ops.** `deposit`/`etch` with no
lateral argument keep their exact arithmetic untouched; the level set
is advanced in parallel and is authoritative only for the operations
that need it — which are exactly the ones S2 introduces and which have
no legacy gates to contradict. The two representations are reconciled
at S2, when the vertical-only ops are superseded and their exactness
claim retires with them.

This costs a redundant state through S1 and is worth it: it makes
S1-G1 ("every M23 test passes unchanged") an achievable gate rather
than a contradiction, which is the whole point of having it.

A new API that exposes re-entrant geometry arrives in **S2**, as an
addition. The height-field view stays until a consumer no longer needs
it — `gmsh_finfet3d` will stop needing it at S5.

### 2.4 The background grid must be uniform

S1 originally said "reuse `mesh2d.Mesh2D`". That is wrong as stated:
`Mesh2D` is a graded tensor-product mesh, and the standard level-set
machinery (upwind Hamilton–Jacobi advection, fast-marching
reinitialization) assumes **uniform** spacing. On a graded grid those
schemes lose their order and the reinitialization stops producing a
signed distance.

So: the process level set lives on its **own uniform grid**, sized
independently of any device mesh, and results are resampled onto the
device mesh at handoff. This is also the cleaner statement of the
"process grid resolves the front, device mesh resolves the solution"
separation below.

### 2.5 S1 gates

| gate | what it proves |
|---|---|
| S1-G1 | all 8 `tests/test_m23_process2d.py` tests pass **unchanged** against the level-set-backed implementation |
| S1-G2 | a flat front advected at constant speed for N steps lands at the analytic position to the grid's own truncation order — and the ORDER is measured by refinement, not asserted |
| S1-G3 | reinitialization preserves the zero level set: the front moves by < one-tenth of a cell over 100 reinit cycles with V = 0 |
| S1-G4 | multi-material: no point is claimed by two materials and no point is claimed by none, after a 3-material flow with a triple junction |
| S1-G5 | mass conservation of a pure deposit: integrated area change equals rate × exposed-length × time to a stated tolerance (level sets do NOT conserve mass exactly — state the measured error, do not claim machine precision) |
| S1-G6 | `examples/08_locos_flow.py` still runs and produces a qualitatively unchanged bird's beak |

**S1-G5 is a deliberate honesty gate.** M23's `deposit` conserves mass
*exactly, by construction* (it adds `thickness × width`). A level set
does not — it conserves it to discretization error. **This is a
regression in one measurable respect**, and the plan says so up front
rather than discovering it in review. The trade is exact mass on a
representation that cannot do the geometry, versus approximate mass on
one that can. Record the measured error at the working resolution; if
it exceeds ~1% on the LOCOS flow, that is a finding worth escalating
before S2, not absorbing silently.

## 3. S2 — deposition and etch as topology

Replaces the vertical string ops:

- **Conformal deposition**: V = constant normal speed. Sidewalls get
  coverage; a narrow trench pinches off and leaves a void. The void is
  the point — it is the thing the height field could not represent and
  the thing that matters for STI fill.
- **Directional (anisotropic) etch**: V = rate × (n̂ · beam direction)
  clamped at 0, with optional shadowing by the mask.
- **Isotropic etch**: V = constant, which produces genuine undercut at
  a mask edge rather than the current Gaussian smoothing of a depth
  profile.

`etch`'s `lateral_kernel_cm` argument becomes legacy. **Keep it
working** (S1-G1 requires it) but document it as superseded, and route
it to the isotropic path only if that is shown numerically equivalent —
which it probably is not, since the current one explicitly does not
conserve removed material at mask edges. If it is not equivalent, keep
the old code path for the old argument and let it die with its
consumers; do not silently change what an existing call computes.

S2 gates: trench pinch-off produces a closed void of the expected
approximate area; isotropic undercut length equals etch depth at a
mask edge to the grid's resolution; directional etch on a vertical wall
removes nothing; and a conformal deposit into a re-entrant profile
produces a front the height-field view **cannot** represent — asserted
by showing the view is lossy there, which is the positive statement
that S1's representation change bought something.

## 4. S3 — oxidation as a moving-boundary problem

The real model, replacing the column-independent Deal-Grove plus
lateral-suppression kernel:

1. Solve oxidant diffusion in the oxide: ∇·(D∇C) = 0, with a gas-side
   mass-transfer BC and a reactive BC at the Si/SiO₂ interface
   (flux = k_s·C).
2. Interface speed V = flux / N₁ (N₁ = oxidant molecules per unit
   volume of oxide).
3. Volume expansion: the oxide surface moves outward by the 2.17
   expansion ratio while the interface consumes silicon at the 0.44
   factor `process.silicon_consumed` already encodes.

**Reduction identity (the gate that makes this safe):** in 1D with no
mask, this must reproduce `process.oxide_thickness`'s Deal-Grove result
— including the linear and parabolic regimes separately — to a stated
tolerance. That is the acceptance criterion M23's own spec named
("1D Deal-Grove recovered exactly for unmasked oxide") and never got to
test against a real moving boundary.

**Stress: LITE ONLY, and this is a hard boundary.** `ARCHITECTURE.md`
section 6 lists "full viscoelastic oxidation mechanics" as
**permanently out of scope per the parity plan**. S3 may include the
oxidation-rate pressure factor that M23's original spec called
"stress-lite" and nothing more. Mechanical stress as a *physics model*
is M36, a different milestone with a different justification. If S3
starts growing a stress solver, it has escaped its scope.

With a real moving boundary the bird's beak stops being a knob and
becomes an outcome. It should then be gated against published
qualitative shape metrics — **and still labeled qualitative**, per
M23's precedent, unless a quantitative source is actually in hand.

**S3 depends on S1, not on S2.** An earlier draft of this plan wrote
`S3 → S1, S2`; that was asserted rather than argued. Oxidation needs
the multi-material projection (S1 decision 1) and nothing S2 adds.
Doing S3 before S2 is a legitimate reordering if oxidation is the more
valuable half.

## 4b. S3b — dopant across the moving boundary

**This slice was missing from the first draft of this plan, and it is
the largest physics gap in it.** The repo had already identified it;
`ted.py`'s own honesty clause says:

> Segregation is an equilibrium partition at a *fixed* interface slab
> (`segregation_partition`), not a moving-boundary flux condition
> tracked through an evolving Deal-Grove interface — composing it with
> `process2d.oxidize_2d`'s moving Si/SiO2 boundary is future work.

Without S3b, S3 moves the geometry while the dopant field stays where
it was. Everything downstream of that is wrong in a way that still
*looks* plausible: segregation, interface pile-up or depletion, and
total dose after a sacrificial-oxide step. A LOCOS flow would produce a
believable bird's beak wrapped around a dopant profile that never
noticed the silicon under it was consumed.

Scope: advect the dopant field with the moving material; replace
`segregation_partition`'s fixed slab with a flux condition at the
moving interface; conserve total dopant across the step.

Gate: **dose conservation is the strong one** — total dopant (silicon
side + oxide side) is unchanged by an oxidation step to a stated
tolerance, with the segregation coefficient controlling only the
*split*, never the total. That is checkable without any published
number and would catch every plausible implementation error here.

Whether S3b is in M35 or is handed back to M24 as its own follow-up is
a real question — it is dopant physics, not geometry. This plan claims
it for M35 because it is unusable without a moving boundary, but
flagging it as arguable rather than settled.

## 5. S4 — masks, silicidation, epitaxy, CMP

- **Masks** become 2D regions (their own level set), so a mask has a
  thickness, erodes during etch, and casts a shadow for directional
  steps. `mask_from_intervals` stays as the 1D convenience constructor.
- **Silicidation**: a reacting buried interface consuming Si and metal
  in fixed stoichiometry — structurally the same solver as S3's
  oxidation with different constants, which is the argument for doing
  it after S3 rather than alongside.
- **Epitaxy**: deposition with a facet-dependent rate V(n̂). The level
  set already carries n̂ = ∇φ/|∇φ|, so this is small once S2 exists.
- **CMP**: planarize to a height — trivial in either representation,
  and the one item on 4c.2's list that did not need S1 at all.

### 5b. `implant_2d` — an open decision, not an oversight

`implant_2d` is a `process2d` public function with gated consumers, and
the first draft of this plan never said what becomes of it. It models
lateral spread as a Gaussian convolution of the vertical SUPREM profile
by a fixed straggle ratio, keyed off **one** surface height per column.

Once geometry is multi-material and re-entrant, that is no longer
well-defined: an ion entering under a mask edge crosses resist, then
oxide, then silicon, and stopping differs in each. Three options, in
increasing cost:

1. **Leave it.** Keep the current model, document that it assumes a
   single-material single-valued surface, and refuse (loudly) when the
   geometry is re-entrant. Cheapest; keeps every existing gate.
2. **Path-integrate stopping power** along the ion direction through
   the material map. Moderate; the material map is already there from
   S1.
3. **Defer to `mc_implant.py`** (M25's BCA) for multi-material cases.
   Most physical, most expensive, and M25's own honesty clause already
   limits its accuracy to ±35% over a calibration window.

**Recommend option 1 for S1–S4 and option 2 as its own slice if a real
consumer appears.** Option 3 is not an M35 decision. What matters is
that this is chosen deliberately rather than discovered when a masked
implant onto an undercut profile silently returns nonsense.

## 6. S5 / S6 — 3D

S5 is the same level set on a 3D background grid. Structurally it
should be a dimension-generic rewrite of S1–S4's kernels rather than a
parallel implementation; if it is not, S1 was written too
dimension-specifically and that is worth fixing in S1 rather than
duplicating in S5.

**The rule from 4d.4 applies and is the main gate:** a 3D process flow
with no variation along z must reproduce the 2D answer to
floating-point noise. That makes S5 self-gating against S1–S4.

The output must be meshed. `gmsh_mesh3d.py` exists, and M31 P2's
compiled geometry kernels (1.99M tets/s, so a 1M-tet mesh is ~0.7 s)
mean tet throughput is no longer a blocker — that measurement is
already in `ARCHITECTURE.md` 4c.1 and should not be re-derived.

S6 closes the handoff. Today `gmsh_finfet3d.build_finfet_mesh3d_from_
process2d` takes the **median** surface height per x-region (its own
docstring: it "will silently flatten a more complex profile (e.g. a
LOCOS bird's-beak taper) to its regional median") and assigns **uniform
doping per region**, explicitly not extruding the 2D implant field. S6
replaces both: real geometry from the 3D level set, and a real 3D
doping field sampled onto the device mesh.

Until S6, **a 3D device built from this process flow still is not a 3D
process result**, and no claim to the contrary should be made.

## 7. Honest limits, stated before any code

- **No full viscoelastic oxidation mechanics.** Permanently out of
  scope (section 6). Stress-lite in S3 means the rate pressure factor,
  nothing more.
- **No kinetic-Monte-Carlo diffusion, no radiation/SEE.** Same list.
- **Level sets do not conserve mass exactly.** S1-G5 measures the
  error instead of claiming it away. This is a real regression against
  M23's exactly-conservative `deposit`.
- **Bird's beak stays qualitative** unless a quantitative published
  cross-section is actually obtained. M14's G-A is this repo's standing
  precedent that a paywalled source blocks a gate for months, and the
  right response is a loud `xfail`, not a fitted constant.
- **Material set is finite and declared.** Si, SiO₂, Si₃N₄, poly,
  resist, one metal, one silicide. Anything else refuses loudly.
- **No performance claim** without a `benchmarks/` row (section 36).
  A process flow is a plausible benchmark case; adding one is optional
  but quoting a number without it is not.
- **This milestone does not touch the device numerical core.** It ends
  at "here is geometry and a doping field"; `device*.py` is untouched,
  so the frozen-core amendment protocol does not apply to S1–S6 — which
  is a large part of why an XL milestone is tractable at all.

## 8. What could make this not worth doing

Recorded so the decision is reversible rather than sunk:

- If the only consumer of 3D process output is FinFET-class demos,
  `gmsh_finfet3d`'s extrusion may already be enough, and M35 is
  expensive ceremony. **The test of this is S6's necessity**: if nobody
  needs a real 3D doping field, stop after S4 and keep 2D process +
  extrusion, which is exactly what M26's original spec chose ("3D
  process geometry stays OUT — 2D process + extrusion covers
  FinFET-class demos"). M35 contradicts that earlier decision; this
  plan should not pretend otherwise, and whoever signs off should say
  which of the two they mean.
- If S1-G5's mass error is large at usable resolution, the level set
  may be the wrong representation for a tool whose users care about
  dose bookkeeping, and a front-tracking or cut-cell method deserves a
  look before S2.

## 9. Suggested order

S1 → measure S1-G5 → decide → S2 → S3 → S3b → S4 → **stop and
re-evaluate whether S5/S6 are wanted** → S5 → S6.

(S3 depends only on S1, so S3 → S3b may run before S2 if oxidation is
judged the more valuable half. S2 before S3 is the default only because
S2 is smaller and exercises the S1 representation harder.)

The stop is deliberate. S1–S4 deliver a genuinely better 2D process
engine that the existing extrusion path can already consume. S5/S6 are
the expensive half and should be bought separately.

## 10. Review record (2026-09-12, same session)

This plan was reviewed against the code immediately after being
written. Five findings, all now folded in above; recorded here because
the first draft's errors are informative about how the milestone can go
wrong.

1. **The primary gate was self-contradictory.** S1-G1 ("all 8 M23
   tests pass unchanged") is impossible if the height field is a
   derived view of the level set: two of those tests assert `atol=1e-13`
   and literal `== 1.0` float equality, which zero-crossing
   interpolation cannot deliver. Fixed by carrying both states through
   S1 (§2.3). **A plan whose main gate cannot pass is worse than no
   plan**, and this one shipped that way for about ten minutes.
2. **Blast radius understated 4 consumers as the full set; there are
   11**, including `test_public_api_surface.py`, which freezes the
   module name and exports (§2.3 table).
3. **A whole physics slice was missing** — dopant transport across the
   moving boundary, which `ted.py`'s honesty clause had already flagged
   as future work. Now S3b (§4b).
4. **`implant_2d` was listed as a consumer and then never addressed.**
   Now an explicit three-option decision (§5b).
5. **"Reuse `Mesh2D`" was wrong**: it is graded, and level-set
   advection/reinitialization assume uniform spacing. Now its own
   uniform grid (§2.4).

Two things the review did **not** find a problem with, recorded so they
are not re-litigated: the S1-first ordering (the representation really
is the blocker — §0), and the S5/S6 stop point (§8's reversibility
argument stands).

Still open after review, and deliberately left open:

- **No effort estimate** beyond relative slice sizes. An XL milestone
  with six slices deserves one before sign-off, and this plan cannot
  honestly produce it without S1 being attempted first.
- **Whether S3b belongs to M35 or M24** (§4b).
- **Whether M35 is wanted at all** given M26 explicitly chose "3D
  process geometry stays OUT" (§8). That contradiction is the real
  sign-off question, and it is a product decision, not a technical one.
