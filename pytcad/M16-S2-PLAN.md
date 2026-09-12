# M16-S2 — Local Kane BTBT in structured Device2D/Device3D

Written 2026-09-12. **Plan only — not implemented, not signed off.**
The user asked for the plan to be written now and implemented later, so
nothing in `device2d.py`/`device3d.py` has been touched for this slice.

This amends the frozen numerical cores `device2d.py` and `device3d.py`,
so the house gates in `CLAUDE.md` ("Hard rules") apply in full when it
is implemented: explicit sign-off, **FD-Jacobian first**, default-off
bit-identity, and the reconstruct-and-compare md5 protocol on
`tests/goldens/m13/*.npz`.

M16's original plan doc is no longer in the working tree (removed with
the other M14–M22 docs in commit `e948fbe`); read it with

    git show e948fbe^:pytcad/M16-BTBT-PLAN.md

## 0. Why this slice, and why it is small

`ARCHITECTURE.md` 4d.1 currently reads:

    BTBT, local Kane                  Y     R     R    M16 follow-up
    BTBT, nonlocal                    Y     Y     Y    -- (structured)

That is an inversion, not just a gap: the *harder* model (M34-S3's
field-line path integration, `nonlocal_path.py`) runs in structured
2D/3D while the *simpler* one still raises `NotImplementedError` at
`device2d.py:186` / `device3d.py:264`. A user can run nonlocal Zener
leakage but not local. It reads as a bug.

It is small because M34-S6a/S6b already built the thing that was
actually hard — a per-node generation term on a structured grid,
stamped into both continuity rows with an exact coupled Jacobian,
driven through the `_II_STAGES` strength ladder with S7's stiff-path
Newton test underneath (`pytcad/ii_grid.py`, `M34-S6-PLAN.md`). Local
BTBT is strictly *less* than that:

| | impact ionization (S6a) | local BTBT (this slice) |
|---|---|---|
| depends on | psi, n, p | psi only |
| needs carrier current direction | yes (`E_par` along **J**) | no |
| needs the smoothed-\|J\| eps | yes | no |
| coefficient law | piecewise `alpha_n/alpha_p` | single C-infinity `G(F)` |
| Jacobian columns | psi, n, p on both end nodes | psi only |

`pytcad/btbt.py` already provides `btbt_generation(F)` and the analytic
`dbtbt_dF(F)`, both vectorized, both pinned to the Hurkx 1992 Table I
silicon constants by `tests/test_model_benchmarks.py`. **No new physics
and no new constant is introduced by this slice** — it is a
dimensional lift, so 4d.3's rule applies: the gate is the 1D code that
already passed, not a published number.

## 1. The model on a grid

Device1D (`device.py`, the `if btbt_enabled:` block, and
`_ii_compute_E_from_state`):

    E_i = 0.5 * (|E|_{i-1/2} + |E|_{i+1/2})        interior
    E_0 = |E|_{1/2},  E_{N-1} = |E|_{N-3/2}        ends
    G_i = A * E_i^2 * exp(-B / E_i)                [cm^-3 s^-1]

with `|E|_e = |psi_R - psi_L| * VT / (LD * h_e)` [V/cm].

Grid form, per node, over every axis `a`:

    E_a  = mean over the node's incident a-edges of |E_e|
    F    = sqrt( sum_a E_a^2 )
    G    = A * F^2 * exp(-B / F)

This is deliberately the *same* per-axis edge average `ii_grid.py`
already computes (its `Ea`, built with the same `inv = 1/count`
weighting), combined by Euclidean norm instead of projected onto a
current direction — because BTBT is driven by the field magnitude, not
by transport along anything.

**Two reduction identities, both EXACT rather than round-off-close.**

1. *1D reduction.* With one axis, `F = E_x` = the mean of the node's
   incident x-edge magnitudes. The `inv = 1/count` weighting gives
   `0.5*(...)` at interior nodes and the single adjacent edge at the
   two ends — bit-for-bit Device1D's `_ii_compute_E_from_state`.
2. *Transverse-uniform reduction.* In a device with no y (or z)
   variation, `psi_R - psi_L = 0` exactly on every transverse edge, so
   `E_y = 0` exactly and `F = E_x`.

Both are exact because, unlike S6a, there is no `eps`-smoothed `|J|`
anywhere in this model. **The 2D/3D-reduces-to-1D gates for this slice
should therefore be tighter than S6a's** (which had to absorb
`eps^2/(2 S_x)` ~ 5e-13); write them at Newton-solve round-off and let
the number be what it is, rather than copying S6a's tolerances.

**The one kink.** `|E_e|` is non-smooth where `psi_R = psi_L`, and
`F = sqrt(sum E_a^2)` is non-smooth where `F = 0`. Both are the same
kinks `ii_grid.py` already lives with, both sit exactly where `G` and
`dG/dF` vanish to all orders, and neither is anywhere near a junction
under reverse bias. `G(F)` itself is C-infinity in `F` for `F > 0`
(`btbt.py`'s `dbtbt_dF` docstring makes the point for 1D), so the FD
probe needs no kink-avoidance window beyond not straddling zero field —
same as S6a's gate already does.

## 2. The Jacobian

`G` reaches the state through `psi` alone. Writing `i` for the node and
`e` for an incident edge on axis `a`:

    dG_i/dpsi_j = G'(F_i) * sum_a (E_a,i / F_i) * dE_a,i/dpsi_j

    dE_a,i/dpsi_j = inv_i * sum_{e incident on i, axis a} d|E_e|/dpsi_j

    d|E_e|/dpsi_{kR(e)} = + sign(psi_{kR} - psi_{kL}) * VT/(LD h_e)
    d|E_e|/dpsi_{kL(e)} = - the same

`G'(F)` is `btbt.dbtbt_dF`. `E_a/F` is `ii_grid._ratio(E_a, F)` — the
existing divide-by-zero-safe helper, which returns 0 where `F = 0`,
which is correct here (both `G` and `G'` vanish there).

Every factor on the right already exists in `ii_grid.py`'s loop as
`inv`, `cEs` (`np.sign(dpsi) * cE`) and `Ea`. There are exactly **two**
nonzero Jacobian columns per (node, incident edge) pair — `3*kL` and
`3*kR` — against S6a's six.

## 3. Touch points, file by file

### 3.1 New: `pytcad/btbt_grid.py`

Mirrors `ii_grid.py`'s shape and contract so one kernel serves both
devices:

```python
def grid_btbt(N, axes, psi, VT, LD, R0):
    """Local Kane BTBT generation on a structured grid.

    axes : one dict per grid axis with kL, kR, h (the SAME dicts
           device2d/device3d already build for ii_grid.grid_impact;
           the current entries are ignored here).
    Returns (G, rows, cols, vals, F_node): G (N,) SCALED generation
    (physical/R0), the Jacobian dG_i/du as COO triples (cols are
    3*node, psi only), and the node field [V/cm] G was evaluated at.
    """
```

Returning the same 5-tuple shape as `grid_impact` keeps the two call
sites symmetric. `F_node` is returned for the same reason `ii_grid`
returns `(E_n, E_p)`: the gates read it.

### 3.2 `pytcad/device2d.py` and `pytcad/device3d.py`

Identical changes in both (2D first, then 3D — the S6a/S6b order).

1. **Constructor.** Delete the `btbt` `NotImplementedError`
   (`device2d.py:186`, `device3d.py:264`). Replace with a comment
   naming this slice, the way S6c replaced the `impact_nonlocal`
   refusal. Nothing else gates `btbt`: it has no lambda-style
   precondition and no heterojunction restriction of its own.
   **Decided, from reading the 1D code (2026-09-12):** do NOT add a
   homojunction refusal. Device1D refuses `btbt_nonlocal` on a
   heterostructure (`device.py`'s `if getattr(self.models,
   "btbt_nonlocal", False)` guard) but has no equivalent guard for
   local `btbt` — so a hetero Device1D already applies the single
   silicon `A`/`B` pair across a material boundary. That is arguably a
   gap in 1D, but a dimensional lift must not quietly tighten the
   model relative to the code it is being gated against; raise it as
   its own question if it matters.
2. **`_residual_jacobian`: hoist the `axes` list.** It is built inside
   `if getattr(self.models, "impact", False):` today. Move it to
   `if impact or btbt:`, contents unchanged. Pure code motion,
   bit-identical with `btbt=False`.
3. **`_residual_jacobian`: the generation block.** After the impact
   block, before the Dirichlet stamping — the same ordering invariant
   M15/M16/M34 all state, and the same `live` mask S6a built
   (contact rows get overwritten, so generation there is unrepresentable
   and must not be stamped):

   ```python
   if getattr(self.models, "btbt", False):
       Gb, b_r, b_c, b_v, self._btbt_fields = _btbt_grid(
           N, axes, psi.ravel(), self.VT, self.LD, self.R0)
       Gs = np.where(live, self._ii_strength * Gb, 0.0)
       self._btbt_gs_cache = Gs.copy()
       F[1::3] += Gs * dVf
       F[2::3] -= Gs * dVf
       # ... same keep/rows/cols/vals stamping as the impact block
   ```

   `live` and `dVf` are currently built inside the impact block; they
   need hoisting alongside `axes`.
4. **`solve_bias`: the stiff path.** Today `ii_on` alone drives
   `stages`, `backtrack` and `dens_floor` (`device2d.py:1239-1244`).
   Extend to `stiff_on = impact or btbt`, matching Device1D's own
   `stiff_gen = ii_enabled or btbt_enabled or btbt_nl_enabled`. A Zener
   source is stiffer than avalanche onset (`G ~ exp(-1e8/F)`), so the
   leading generation-free stage matters at least as much here — M16's
   own plan section 2 says exactly this for 1D.
5. **Caches.** Add `self._btbt_gs_cache = None` next to
   `_ii_gs_cache` in the constructor and reset it wherever
   `_ii_gs_cache` is reset (`solve_equilibrium`, the start of
   `solve_bias`). Equilibrium is Poisson-only with slaved carriers, so
   there is no BTBT source at the V=0 gauge — same as Device1D
   (`device.py:1138`).

### 3.3 Noticed while planning, NOT part of this slice

Device1D puts `btbt_nonlocal` in its stiff-generation set; Device2D and
Device3D do not (`device2d.py:1230` computes `btbt_nl` but only `ii_on`
reaches `stages`/`backtrack`/`dens_floor`). That asymmetry is either a
deliberate S3 scope call or an oversight, and this plan does not
resolve it. **Do not "fix" it as a drive-by while implementing this
slice** — it would change the arithmetic of every existing
`btbt_nonlocal` 2D/3D run and belongs in its own gated change. Check
`M34-PLAN.md` S3 for whether it was decided; if it was not, raise it
with the user separately.

### 3.4 Metadata and existing tests

- `workbench/core/catalog.py`: `btbt`'s `applicability` /
  `limitations` strings — currently "1D only" — become 1D + structured
  2D/3D, naming `pytcad/btbt_grid.py`, and keep "unstructured
  Device2D refuses it".
- `tests/test_m16_btbt.py::test_g_f_2d_and_3d_refuse` must be rewritten
  (it asserts the refusal this slice removes), the way
  `test_m34_s2_nonlocal_ii.py`'s refusal test was rewritten for S6c.
  Grep for any other test asserting the `btbt` refusal before
  implementing — `test_m34_s5_catalog.py` is the likely second one.
- The wire format already carries `btbt`; only applicability text moves.

## 4. Gates (`tests/test_m16_s2_btbt_grid.py`)

Following S6c's file layout, and cross-importing
`test_m34_s6_impact_2d3d`'s `graded_mesh` / `_ramp` / `_currents` /
`_check_reduction` helpers the way `test_m34_s6c_impact_nonlocal_grid.py`
already does.

| gate | what it proves | slow? |
|---|---|---|
| G1 | `grid_btbt` on a `(1, Nx)` grid reproduces Device1D's `_ii_compute_E_from_state` + `btbt_generation` node-for-node | no |
| G2 | FD-Jacobian, 2D, at a reverse-biased corner device | yes |
| G3 | FD-Jacobian, 3D | yes |
| G4 | transverse-uniform 2D reduces to Device1D's `btbt=True` fixed point | yes |
| G5 | transverse-uniform 3D, same | yes |
| G6 | `btbt=False` bit-identity: a 2D and a 3D solve unchanged vs. the pre-edit code (`np.array_equal`) | no |
| G7 | reverse ramp converges and reverse current rises steeply (M16's own G-C/G-E shape, in 2D) | yes |

G1 is the cheap one and should be written and green **before** any
device wiring — it isolates the kernel from the Newton loop entirely.
G2/G3 are the FD-Jacobian-first requirement; write them before the
convergence gates, not after.

**On `_fd_gate` reuse:** S6c had to write its own `_fd_gate_nl` because
S6a's `used_top >= 2` assertion does not apply to a model whose
generation term drops the `dalpha*(Ea - E*u)` piece. This slice's `G`
has *no* `eps`/`used_top` concept at all (no smoothed `|J|`), so that
assertion is meaningless here too — expect to need a third variant, or
better, factor the shared body once both callers exist. Decide when
G2 is written, not before.

**Bit-identity and goldens.** `btbt=False` must be untouched: the only
arithmetic change on that path is code motion (3.2 step 2), which must
be verified `np.array_equal`, not "looks the same". Record the six
`tests/goldens/m13/*.npz` md5s in this file before the edit, per
CLAUDE.md's reconstruct-and-compare protocol — they should not move,
and if one does that is a defect to explain, not a re-baseline.

## 5. Honest limits, stated up front

- **Structured grids only.** `Device2D(unstructured=True)` keeps
  refusing `btbt` via its existing `unsupported` dict; no change there.
- **Silicon Hurkx constants only**, as in 1D. No per-material BTBT
  table exists anywhere in the tree, and inventing one is not this
  slice's job.
- **The known model failure mode is inherited, not fixed.**
  `btbt.py`'s docstring is explicit that local Kane underestimates
  leakage at large reverse bias relative to the nonlocal line integral.
  Porting it to 2D/3D does not improve that; users who want the better
  physics have `btbt_nonlocal` in the same devices already. Say so in
  the catalog `limitations` string.
- **No performance claim.** Section 36 forbids one without a benchmark
  row, and this slice adds none. If a claim is wanted, add a
  `benchmarks/` case; do not quote a number from a test run.
- **No expectation this is expensive.** Unlike S6c there is no sparse
  solve and no per-line search — it is `bincount` + elementwise numpy,
  cheaper per Newton iteration than S6a. If the gates turn out slow,
  that is a signal something was implemented wrong, not a reason to
  coarsen meshes.

## 6. Order of work

1. `btbt_grid.py` + G1 (kernel only, no device edit). Green before
   anything else.
2. Record golden md5s here.
3. Device2D: code motion (3.2 step 2), verify G6 2D bit-identity.
4. Device2D: generation block + ladder + constructor. G2, then G4, G7.
5. Device3D: the same, in the same order. G3, G5.
6. Catalog + rewrite the two refusal tests.
7. Fast suite both `PYTCAD_ACCEL=0/1`, slow battery separately, golden
   md5 re-check, then docs (`ARCHITECTURE.md` 4d.1 row → `Y Y Y --
   (structured)`, `CLAUDE.md` M16 entry, `history.md`).
