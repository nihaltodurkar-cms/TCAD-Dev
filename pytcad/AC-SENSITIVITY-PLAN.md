# AC ohmic-port sensitivity: exact rows instead of ~5,000 re-assemblies — plan

Status: **APPROVED 2026-09-26** (the user's "approved", with the §5b defaults). Steps 1-5 done (§7, §8, §9). One open item, not caused by this change: §9.
It amends frozen numerical-core files (`pytcad/ac2d.py`, `pytcad/ac3d.py`,
`pytcad/device2d.py`, `pytcad/device3d.py`), so it needs the explicit
sign-off CLAUDE.md's hard rules require, plus FD-first and
bit-identical-off-path gates (§4).

## 1. The problem, measured

`ac2d.y_parameters` / `ac3d.y_parameters` compute, for every **ohmic** port,
a real row `S` = d(contact current)/d(state), by central finite differences
(`_ohmic_current_sensitivity`). For each node of the contact's support
(the contact nodes plus their neighbours), and for each of psi, n and p, it
perturbs +h and -h and **re-assembles the whole device**
(`_residual_jacobian`) to read the contact current.

That is 2 × 3 × |support| full assemblies per ohmic port. On the 3D MOSFET
of `tests/test_m45_ac3d.py` (96×35×3 = 10,080 nodes, 3 ohmic ports) it was
5,220 assemblies at ~0.047 s each.

**Motivating measurement** (ad hoc, 2026-09-26, this PC; to be replaced by
the benchmark row of step 5, per the M32 rule that performance numbers come
from `benchmarks/`):

| 3D MOSFET (10,080 nodes) | time |
|---|---|
| build + equilibrium + bias | 3.2 s |
| `y_parameters`, 1 frequency | 251 s |
| `y_parameters`, 20 frequencies | 268 s |
| of which `_ohmic_current_sensitivity` (cProfile) | 258 s of 259 s |

So ~97 % of an AC analysis is this frequency-independent setup. In the
fast suite it made the six MOSFET AC gates the longest tests (1,165 s CPU
before the test-side sharing that landed 2026-09-26); in the apps it makes
a 3D AC run take minutes.

## 2. The exact replacement

The quantity differentiated is the terminal current's own residual sum
(`terminal_current()` reads the same thing):

    I = sum_{k in kk} ( F_n[k] + F_p[k] )

so, exactly,

    S_j = dI/du_j = sum_{k in kk} ( dF_n[k]/du_j + dF_p[k]/du_j )

i.e. **the sum of the raw continuity Jacobian rows 3k+1 and 3k+2 over the
contact's nodes**. Those rows are already assembled on every call: they
are in the COO triplets `(rows, cols, vals)` right up to the contact-BC
block, which then strips them and writes Dirichlet unit rows (3D:
`device3d.py` ~L1869; 2D: `device2d.py` ~L1738). The FD loop differentiates
numerically what the assembler already has analytically.

Three facts make "the raw rows at that point" the right object. Each is
checked by a gate in §4, not assumed.

1. **`F_n`/`F_p` are returned raw.** Both cores build them before the BC
   block, and the BC edits go into `F3`, a separate view. The Robin
   (S_n/S_p, Robin Schottky) additions and Dirichlet replacements are
   therefore NOT in what the FD differentiates. So the rows are captured
   **before** the BC block, and the Robin extras appended after it are
   excluded.
2. **Generation cancels.** Impact ionization and local BTBT add +G·dV to
   `F[1::3]` (and its Jacobian to the n rows) and -G·dV to `F[2::3]`, but
   not to the returned `F_n`/`F_p`. In the sum n-row + p-row the two
   stamps are equal and opposite at the same node, so they cancel.
   Recombination (-R in F_n, +R in F_p) cancels the same way. Including
   those rows is exact.
3. **Only psi/n/p columns.** `S` has length 3N, as now. A density-gradient
   or hydrodynamic block, if present in J, is outside the columns the FD
   perturbs.

The analytic row is also **more accurate**: FD carries O(h²) truncation
plus eps/h roundoff; the existing code comments document the care its
shared step size needed. The Jacobian it reads is the one Newton already
converges with, whose correctness is FD-gated per model elsewhere (M13,
M14, M15, M16, M34, M41, M47 gates).

## 3. Design

- **Core (additive, default path unchanged).**
  - `Device2D._residual_jacobian` and `Device3D._residual_jacobian` gain one
    keyword, `current_rows_for=None`.
  - When it is an index array of nodes, the triplets whose row is 3k+1 or
    3k+2 for those k are stashed on the device as
    `self._raw_current_rows = (rows, cols, vals)`, immediately before the
    contact-BC block. `self._dirichlet_rows` is the existing precedent for
    this pattern.
  - With `None` (every existing caller), not one operation changes: gate G1.
- **AC modules.**
  - `_ohmic_current_sensitivity` becomes one assembly for ALL ohmic ports:
    `S_port = sum over kk of (row 3k+1 + row 3k+2)`, a sparse row sum
    restricted to columns < 3N.
  - The FD routine is kept, renamed `_ohmic_current_sensitivity_fd`, as the
    gate oracle.
- **Scope.**
  - Structured Device2D and Device3D. `ac.py` (1D) is untouched: it is
    cheap, and its `ac_sweep` reduction gate pins its exact arithmetic.
  - Any configuration where G2 fails keeps the FD path through an explicit,
    named dispatch (decision 1), never silently.
  - `Device2D(unstructured=True)`: whatever `ac2d` does today is kept; it is
    checked during step 1 and recorded.

## 4. Gates (FD first, per CLAUDE.md)

- **G1 — off path bit-identical.** `_residual_jacobian(...)` with
  `current_rows_for=None` returns byte-identical `F`, `J`, `F_n`, `F_p` (and
  the 3D current arrays) before and after the edit:
  - on the 2D and 3D MOSFETs;
  - on each model configuration listed under G2.

  Protocol (CLAUDE.md "golden baseline"): record the md5 of every
  `tests/goldens/**` file the change could touch **before** the edit, in
  this plan. Then regenerate, and show that the goldens do not move. If
  this checkout has no goldens (they are gitignored; `frozen_meshes.npz`
  is absent here today), say so rather than claim the gate.
- **G2 — analytic equals FD within FD's own error.** For each ohmic port,
  `|S_analytic - S_fd|_max <= 10 · |S_fd(h) - S_fd(h/2)|_max + 1e-14·|S|_max`.
  The FD error bar is measured on the same case, not a round number.
  Configurations:
  - 2D: default; the MOSFET (`build_mosfet`); surface mobility;
    S_n/S_p ≠ 0 (Robin); Robin Schottky; Fermi-Dirac; incomplete
    ionization; impact; btbt; hetero; density-gradient if `ac2d` accepts it.
  - 3D: default; the 3D MOSFET; GAA; and each of the stiff-coupling test's
    models (srh+impact, btbt, incomplete_ion, dg).
- **G3 — mutations must fail G2:** dropping the p rows; capturing after
  the BC block (Robin extras included); an off-by-one on the node set; and
  omitting generation from one of the two rows.
- **G4 — every existing AC gate passes with its tolerance unchanged:**
  `test_m18_ac2d.py`, `test_m45_ac3d.py`, `test_m45_gaa_multigate.py`,
  `test_m45_stiff_physics_coupling.py`, `gui/tests/test_ac_gui.py`, and
  `test_m18_yparam.py` (1D, should be untouched). Y moves only at the
  FD-error level. A test that pins a Y value exactly and moves is
  recorded with its cause, not re-baselined blindly.
- **G5 — benchmark.** Add an AC case to `benchmarks/cases.py`
  (`y_parameters` on the 3D MOSFET), run before and after, and quote only
  that table.
- **Invariants.** The full fast suite green with zero warnings, and the
  slow battery, since this changes core files.

## 5. Steps

| Step | Content |
|---|---|
| 1 | Baselines: goldens md5 (or their absence) recorded here; the benchmark case added and run on the unchanged tree; the `unstructured=True` behaviour recorded. |
| 2 | Red: G2 written against a stub analytic routine (fails), and the G1 byte-compare harness. |
| 3 | Core keyword in `device2d.py` / `device3d.py`; G1 green. |
| 4 | Analytic `S` in `ac2d.py` / `ac3d.py`; G2, G3, G4 green; mutations run. |
| 5 | Benchmark after; the fast suite and the slow battery; results written back here. |

## 5b. Decisions (defaults proposed; say if you want otherwise)

1. **A configuration failing G2 keeps FD**, by explicit dispatch with the
   reason recorded, rather than blocking the whole change. The alternative
   is to stop and fix that model's Jacobian first.
2. **FD stays in the module** as the gate oracle, not deleted.
3. **The test-side sharing that landed 2026-09-26 stays.** It still saves
   the repeated per-frequency LU work, and it is harmless.

## 6. Risks

- **A model whose Jacobian is deliberately approximate** (lagged or frozen
  terms) would make the analytic row disagree with FD. G2 catches this per
  configuration, and decision 1 handles it.
- **Contact nodes that are also gate or pinned nodes** (corner priority):
  G2 includes the MOSFET, whose gate never overlaps the ohmic nodes, and the
  GAA case. An overlap case is added if one exists in the tree.
- **Bit-identity in the ON path is not claimed.** Y changes at the FD-error
  level, by design. G4 bounds it against every existing tolerance.

## 7. Step 1 results: baselines on the unchanged tree (2026-09-26)

- **Goldens: none in this checkout.** `tests/goldens/` does not exist here (it is gitignored, per CLAUDE.md), so the md5 protocol has nothing to record. G1's off-path proof is therefore carried by the two byte comparisons below.
- **One-off G1 digests.** sha256 of `_residual_jacobian`'s full output (F, J, F_n, F_p, and in 3D the current arrays), and of the current FD rows, recorded before any edit. The script is `g1_digests.py` in the session scratchpad; its output is `g1_before.json`. Coverage:
  - 2D default, impact (−3 V), MOSFET and S_n/S_p Robin; 3D default, impact and MOSFET;
  - the FD rows of the 2D and 3D default diodes.

  After the core edit, the off path and the renamed FD oracle must reproduce every one byte-for-byte. The digests pin this machine's summation order, so they are evidence here, not a suite test. The permanent, portable G1 is the within-run comparison in `tests/test_ac_sensitivity.py`.
- **Benchmark B11** (`benchmarks/cases.py`, new: the 3D MOSFET, DC bias + `y_parameters` at 5 frequencies). `tests/test_m32_benchmarks.py`'s case list gains B11, and B11 meets the harness contract at quick size. **Before, full size** (`python -m benchmarks --case B11 --size full --repeats 2`, OPENBLAS_NUM_THREADS=1, this PC, 2026-09-26 17:55):

  | DOF | NNZ | assembly | asm calls | linsolve | ls calls | total |
  |---|---|---|---|---|---|---|
  | 30,240 | 343,698 | 255.28 s | 5,228 | 2.80 s | 6 | **265.50 s** |

  Of the 5,228 assembly calls, 5,220 are the FD sensitivity (2 × 3 × |support| over the 3 ohmic ports) and the rest the bias solve.
- **`Device2D(unstructured=True)` today.** It returns from `__init__` before setting `Nx`, and `ac2d.y_parameters` never checks for it. So an AC run on it fails with a bare `AttributeError: ... 'Nx'`, not a named refusal. That is kept as is (out of scope) and recorded here; an explicit refusal would be a small separate change.

## 8. Steps 2-5 results (2026-09-26)

**Built.**
- **Core.** `Device2D._residual_jacobian` and `Device3D._residual_jacobian` gain `current_rows_for=None`. When nodes are given, the raw rows 3k+1 / 3k+2 are copied to `self._raw_current_rows` just before the contact-BC block. 15 lines each; the default path is untouched.
- **`ac2d.py` / `ac3d.py`.** `_ohmic_current_sensitivities(device, psi, n, p, voltages, node_sets)` computes every ohmic port's row from ONE extra assembly. `y_parameters` fills its ohmic rows from it after the port loop, and its own `J0` assembly is unchanged. The FD routine is kept as `_ohmic_current_sensitivity_fd(..., rel_step=1e-6)`, the gate oracle; `rel_step=1e-6` reproduces the old step exactly.
- **Gate file** `tests/test_ac_sensitivity.py` (25 tests):
  - G1: 7 cases;
  - G2: 17 configurations, 10 in 2D and 7 in 3D (the 3D DG case at equilibrium, since DG bias is refused by design);
  - the one-assembly check.

**Correction to §2's fact 2.** Generation never reaches a contact row at all: both cores stamp impact and BTBT generation only at "live" nodes, and every Dirichlet/Pinned contact node is masked out. The cancellation argument is true but not needed. Recombination IS stamped at contact nodes, as −R in the n row and +R in the p row, and cancels in the sum. That is the case the gate can and does test (G3 below).

**Gates.**
- **Step 2 (red).** Against the unchanged solver, all 25 failed for the intended reason: the missing keyword or functions, and ~thousands of assemblies in the one-assembly test. One fixture first failed for a wrong reason (the DG bias refusal); it was fixed to run at equilibrium before the implementation.
- **G1 (green).** Requesting the rows changes no output byte (7/7). The one-off pre/post sha256 digests of §7 are **all identical** after steps 3 and 4:
  - the off path of `_residual_jacobian` on 7 configurations;
  - the FD oracle rows at the default step.
- **G2 (green, 17/17).** The analytic row agrees with FD to **~1e-11 relative on every port**, at or below the FD's own error:

  | config | worst \|S_a − S_fd\| / \|S\| | FD's own error / \|S\| | ratio |
  |---|---|---|---|
  | 2D default, impact, btbt, incomplete-ion, Robin S_n/S_p, Robin Schottky, hetero, MOSFET, MOSFET + surface mobility | ≤ 9.4e-11 | ≤ 2.3e-10 | 0.17-1.24 |
  | 2D Fermi-Dirac | 3.1e-8 | 1.6e-8 | **2.00** |
  | 3D default, impact, btbt, incomplete-ion, DG, Schottky, MOSFET | ≤ 8.6e-11 | ≤ 2.2e-10 | 0.22-0.53 |

  Fermi-Dirac's exact 2.00 is the signature of an FD error linear in h, not h². The FD converges onto the analytic row as h→0 rather than disagreeing with it.
- **G3 (mutations, each run and restored byte-for-byte):**

  | mutation | result |
  |---|---|
  | drop the p rows from the sum | 5/5 targeted G2 tests fail |
  | capture after the BC block (2D) | 5/5 fail |
  | node set off by one | 5/5 fail |
  | drop SRH's d/dn from the n row (2D) | 3/3 fail |
  | drop impact generation from the n row (3D) | **not detectable, by construction**: generation is never stamped at contact nodes (above), so no contact row changes |

- **G4 (green).** All 110 tests in the AC files pass with tolerances unchanged:
  - `test_m18_ac2d`, `test_m45_ac3d`, `test_m45_gaa_multigate`, `test_m45_stiff_physics_coupling`, `test_m18_yparam`, `gui/tests/test_ac_gui`;
  - the new gate file and `test_m32_benchmarks`.

  The two shared MOSFET AC calls in the suite fell from 288 s to 58 s (3D) and from 184 s to 63 s (2D). The remainder is the per-frequency LU.
- **G5: benchmark B11, full size, same command and machine:**

  | | before | after |
  |---|---|---|
  | total | **265.50 s** | **12.30 s** |
  | assembly (calls) | 255.28 s (5,228) | 0.57 s (9) |
  | linsolve (6 calls, the DC bias; code unchanged) | 2.80 s | 4.20 s |

  ~21.6× on the whole AC analysis. The linsolve difference is run-to-run variation of unchanged code. What remains of the total is mostly `y_parameters`' per-frequency LU (5 frequencies).

## 9. Step 5: the suites (2026-09-26)

- **Fast suite** (`-n 6 -m "not slow and not timing"`): **2610 passed, 37 skipped, 2 xfailed, 0 failed, zero warnings** (11 min 54 s).
- **Slow battery** (`-n 6 -m slow`): **29 passed, 2 skipped, 0 failed** (14 min 18 s).
  - **6 warnings, pre-existing and not from this change.** All are `UserWarning`s from `pytcad/adapt_unstructured.py` / `adapt_unstructured3d.py` in `test_adapt_unstructured*.py`: the refinement loop stopped on its pass limit before the QoI converged, and one Debye-adequacy warning. Neither those modules nor those tests were touched (checked with `git status`). The zero-warnings invariant says tests that intend a warning should assert it with `pytest.warns`; that is proposed, not done.
- **Timing pass** (`-m timing`, serial): 9 passed, 2 skipped, **1 failed**, `test_throughput_floor[stencil3d]`: 0.89-0.995 M tets/s against its 1.0 M floor, in 3 of 3 runs. Best of 7 direct calls: 0.993 M/s, samples 0.96-0.99.
  - **Not this change:** no compiled-kernel or assembly code was edited (`git status core/ pytcad/unstructured_assembly3d.py` is clean). The machine was running a game, Apex Legends (`r5apex_dx12`), plus Discord, during the measurement.
  - The floor was not lowered. It needs re-measuring on an idle machine before deciding anything.
- **Two timing-suite fixes found on the way (tests only).**
  - `test_accel_parity.py`'s throughput floors moved from the `slow` marker to `timing`. They run in ~1 s, but failed under the parallel slow battery's load; they now run in the serial pass.
  - `test_viewport_pan_zoom_fast_path.py`'s setup waited at most ~3 s for a subprocess solve. After a full suite that was too short once. It now waits up to a 60 s deadline, returning as soon as the solve ends; the speed assertion is unchanged.

