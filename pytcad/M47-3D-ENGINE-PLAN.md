# M47: 3D numerical engine completion

Status: Step 0 (benchmark-first decision) complete. Slice 1 design
reviewed and corrected across 3 rounds (transcendental placement, exact
COO/F emission order, Jn/Jp parity requirements, equilibrium-vs-coupled
Poisson API split). Slice 1 groundwork (Python-only COO block refactor
+ FD-Jacobian gates) landed and verified bit-identical -- see "Slice 1
groundwork" below. No C++ kernels, no nanobind bindings, no numerical
behavior change anywhere yet.

## Slice 1 groundwork (landed, Python-only, no C++)

Per the corrected design's item 1 ("add raw COO parity tests" needs the
Python oracle's blocks exposed individually) and the traced COO-ordering
requirement (see design record in conversation history -- not
duplicated here in full), `pytcad/unstructured_dd3d.py`'s two assembly
functions were refactored from one monolithic `add()`-closure body each
into named block functions, called in the EXACT traced source order:

- `_poisson_flux_geometry_coo` -- shared verbatim by both equilibrium
  and coupled paths (the one term genuinely identical in both regimes).
- `_poisson_equilibrium_diag_coo` -- equilibrium-ONLY (slaved n+p
  diagonal chain-rule term), emitted AFTER flux geometry.
- `_poisson_charge_coupling_coo` -- coupled-ONLY (independent n/p
  off-diagonal terms), emitted BEFORE flux geometry -- confirms
  equilibrium and coupled Poisson are genuinely different Jacobian
  shapes with different emission orders, not the same term restated;
  no shared public API between them beyond the flux-geometry helper.
- `_srh_auger_coo` -- emitted FIRST in the coupled assembly (before
  Poisson's own charge-coupling block), a real, previously-undocumented
  ordering fact found by tracing the code, not assumed.
- `_sg_carrier_coo` -- one shared 8-entry-block helper for BOTH
  electron (comp=1) and hole (comp=2) SG current Jacobians, called
  twice with different derivative arrays; electron emitted before hole.

Verified byte-identical (`/tmp/m47_s1_capture_baseline.py`, sha256 of
`F`, `J.data/.indices/.indptr`, `Jn`, `Jp` on a `build_diode_mesh3d`
fixture with randomized psi/n/p, both equilibrium and coupled paths) --
all 10 digests identical before and after the refactor. Full existing
regression re-run green: `test_unstructured_dd3d.py` +
`test_m26_finfet3d.py` (24 passed), `test_validation_3d.py` +
`test_m21_phase3.py` + `test_m22_linsolve.py` blast-radius check
(62 passed, 1 skipped, unrelated).

New FD-Jacobian gate added (`tests/test_m47_s1_unstructured3d_fd_jacobian.py`,
3 tests, all green) -- closes the coverage gap found during design
review: `unstructured_dd3d.py`'s assembly had NO direct FD-Jacobian
check before this (only physics/reduction/regression tests), unlike
structured `device3d.py`'s own `test_dd_jacobian_matches_finite_differences`.
Same relative-step, per-column-normalized convention as that test and
`test_m13_solver.py`'s own `_jacobian_probe`. Covers Poisson equilibrium,
coupled DD with srh=True/auger=True, and coupled DD with srh=False (a
different code path -- the SRH/Auger COO block is absent, not zeroed,
when both flags are off).

## Nanobind binding-shape micro-benchmark (design review item 2)

Throwaway prototype (`/tmp/m47_micro/`, not part of the repo -- built,
measured, and discarded, per "throwaway if it loses"): a scratch
nanobind extension with 5 trivial reduction functions over realistic
B9-full-comparable array sizes (N=7,464, E=60,000), measured two ways --
(A) 4 separate bound calls per simulated Newton iterate, (B) 1 bound
call whose C++ body internally does the same 4 reductions. Compiled
with `/usr/bin/g++` (system compiler, this machine's `cpp` conda env has
the same toolchain available but the Python env's own system compiler
was sufficient -- no separate-env indirection needed here, unlike the
Windows/MinGW case CLAUDE.md's own note describes).

3 runs, best-of-5 within each, 5,000 iterations each:

| run | A (4 calls) us/iter | B (1 call) us/iter | A/B ratio |
|---|---|---|---|
| 1 | 58.408 | 57.774 | 1.011x |
| 2 | -     | -     | 1.007x |
| 3 | -     | -     | 0.996x |

A/B ratio stays within +-1.1% across all 3 runs -- noise-level, no
consistent direction. Expressed against B9-full's own REAL measured
per-call assembly cost (Step 0: 8.05-8.23 ms/call), the 4-call pattern's
worst-case extra overhead (~0.63 us) is **0.0078% of one real assembly
call** -- not a measurable cost at the scale this module actually runs
at.

**Decision, confirmed by measurement (not intuition, per instruction)**:
ONE bound nanobind entry point per solve mode
(`unstructured3d_residual_jacobian_equilibrium`,
`unstructured3d_residual_jacobian_coupled`), each internally calling the
modular C++ functions (`srh_auger`, `poisson_*`, `sg_electron`,
`sg_hole`) directly in C++ -- the design's own provisional default is
now the FINAL choice, not merely the lower-risk one. A future 4-separate-
bound-calls split (if ever wanted for finer-grained profiling) remains a
free simplification per the design's own reasoning, not attempted here
since it buys nothing measured.

## C++ implementation (landed, verified)

New files: `core/include/tcad/unstructured3d/kernels.hpp`,
`core/src/unstructured3d/kernels.cpp` (5 modular block functions --
`poisson_flux_geometry`, `poisson_equilibrium_diag`,
`poisson_charge_coupling`, `srh_auger`, `sg_carrier_jacobian` +
carrier-specific `sg_electron`/`sg_hole` -- plus the 2 orchestrated
entry points `residual_jacobian_equilibrium`/`_coupled`, all in the
exact traced COO/F order from the Python oracle), `core/bindings/
unstructured3d_bindings.cpp`. Wired into `core/CMakeLists.txt` (+1
source in `tcad_core`, +1 in the `-ffp-contract=off` list, +1 binding
TU) and `core/bindings/module.cpp` (`register_unstructured3d`). Builds
clean with the system `g++` (this machine's Python env already has a
usable compiler -- the `cpp` conda env, NOT `tcad-cpp` as CLAUDE.md's
own doc names it, exists as a fallback but wasn't needed).

**Two real bugs found and fixed by the parity tests below (not by
inspection) before declaring this correct:**
1. Python's own COO block functions (`_poisson_flux_geometry_coo` etc.)
   concatenate PER-TERM across all edges/nodes (`np.concatenate([term1,
   term2,...])` -- e.g. all `(i,i)` entries for every edge, THEN all
   `(i,j)` entries for every edge), not one N-term group PER edge/node.
   First C++ draft built per-edge interleaved groups instead -- caught
   immediately by the tier-1 raw-COO test (exact index mismatch), fixed
   by rewriting all 4 multi-term block builders to emit contiguous
   per-term blocks of length E (or N).
2. The oracle's coupled path computes `trans = eps_trans * LD` (the
   M26-fix "bare geometric" recovery) and uses THAT for the SG-current
   flux/Jacobian terms, while Poisson's own flux/geometry uses
   `eps_trans` directly -- two genuinely different scaled quantities.
   First draft collapsed both into one `trans` parameter passed to
   `sg_electron`/`sg_hole` -- caught by the tier-2 F/Jn/Jp mismatch
   (37.9/8.7/2.2 max diff, far outside floating-point noise), fixed by
   adding a separate `trans_bare` parameter threaded through the
   coupled orchestrator and both SG kernels, named to make the two
   quantities impossible to silently swap again.

**Validation, all green** (`tests/test_m47_s1_unstructured3d_accel_parity.py`,
5 tests, skipif no `_core`):
- Tier 1 raw-COO: Python's `_poisson_flux_geometry_coo` output vs the
  first `4*E` entries of the compiled equilibrium kernel's raw
  `(rows,cols,vals)`, `np.array_equal`.
- Tier 2 full-CSR: F, Jn_edge, Jp_edge, and the assembled `csr_matrix`
  (indptr/indices/data via `.tocsc()`) for equilibrium, coupled
  (srh=True/auger=True), and coupled (srh=False/auger=False) -- all
  `np.array_equal` against the Python oracle, non-uniform randomized
  psi/n/p on the same `build_diode_mesh3d` fixture Step 0/the FD gates
  use.
- Reproducibility: same input twice through the compiled coupled
  kernel, bit-identical output (the one property the sole compiled
  path can verify against itself).

Full regression re-run green: `test_unstructured_dd3d.py` +
`test_m26_finfet3d.py` + the new FD-Jacobian + parity files +
`test_validation_3d.py` + `test_m21_phase3.py` (67 passed);
`test_accel_parity.py` + `test_accel_boundary.py` +
`test_m43_thermal_grid_accel_parity.py` blast-radius check on the
OTHER compiled kernels (61 passed, 1 skipped unrelated) -- confirms
the new binding/CMakeLists wiring did not disturb anything already
compiled.

## Production dispatch (landed)

`_residual_jacobian_poisson3d`/`_residual_jacobian_dd3d` (the names
`solve_poisson_equilibrium3d`/`solve_bias3d` already call -- ZERO call-
site changes needed) are now thin dispatchers: recompute the
transcendentals Python must own (exp for n/p, bernoulli/dbernoulli,
`flux`, `trans_bare = eps_trans*LD`, `nie_phys = nie_s*Ns`), call
`_accel.require_accel()` then `_accel.core.unstructured3d_residual_
jacobian_equilibrium`/`_coupled`, and wrap the returned raw COO into a
`csr_matrix`. The old Python bodies were RENAMED (not deleted) to
`_residual_jacobian_poisson3d_py`/`_residual_jacobian_dd3d_py` -- pure
validation oracles now, no production call-time role, matching M43's
own `_py`-suffix convention and this document's architectural
constraint (no `PYTCAD_ACCEL=0`, no runtime fallback branch, no
duplicate production path). `tests/test_m47_s1_unstructured3d_fd_
jacobian.py` and `..._accel_parity.py` updated to import the `_py`
oracle names explicitly (their whole point is testing the reference,
not production) plus 2 NEW end-to-end tests
(`test_production_dispatch_{equilibrium,coupled}_matches_oracle`)
verifying the DISPATCHER itself (not just the raw kernel binding)
reproduces the oracle exactly.

Full regression, all green: `test_unstructured_dd3d.py` +
`test_m26_finfet3d.py` (24 passed, now exercising the COMPILED
production path through `solve_poisson_equilibrium3d`/`solve_bias3d`
directly, not the oracle); `test_validation_3d.py` + `test_m21_phase3.py`
+ `test_m22_linsolve.py` + `test_accel_parity.py` + `test_accel_
boundary.py` (119 passed, 2 skipped unrelated).

**Benchmark re-run, honest result (M32 rule -- report what was
measured, not what was hoped for):** re-ran `benchmarks/m47_s0_
assembly_measure.py` (same script, same fixtures, 3 runs) with the
compiled path now live. B9's assembly_s is **statistically
indistinguishable from the pre-compile Python-only numbers** --
0.0557-0.0585s pre-compile vs 0.0557-0.0563s post-compile at "quick"
size (15 calls), 0.1369-0.1456s vs 0.1394s at "full" size (17 calls).
**No measurable speedup was found.** Per-DOF ratio against structured
B4 is unchanged too (10.4-10.6x post-compile vs 11.5-11.7x pre-compile
at quick, both within the pre-compile run-to-run spread). The most
likely reason, stated as a hypothesis rather than a proven cause (not
profiled further this session): the transcendental precompute
(exp/bernoulli/dbernoulli, kept in Python per the design's own rule)
and the binding's `to_vec()` array-copy marshalling were NOT the
Step-0 benchmark's target -- Step 0 measured the WHOLE `_residual_
jacobian_*` call including that Python-side work, and porting only the
COO-assembly arithmetic leaves that other cost exactly where it was,
now with an added marshalling cost on top. This is the honest
counterpart to M44's own Slice 2/3 findings (measuring, not assuming,
that a port pays off) -- here the measurement says it did NOT
pay off in wall-clock terms for THIS kernel, at THIS problem size,
with THIS binding shape. Correctness (all parity/FD-Jacobian/
regression gates) is unaffected; only the original C++-for-performance
premise for this specific slice is now disclosed as unconfirmed.

## Investigating the null speedup result

Split the production dispatcher's own cost on the real B9-full fixture
(N=2488, E=15462; 20-run best-of, `time.perf_counter()`):

| stage | time |
|---|---|
| (a) Python precompute (exp/bernoulli/flux/trans_bare) | 0.75 ms (6.8% of dispatcher) |
| (b) marshalling + C++ kernel compute | 8.80 ms (80.5% of dispatcher) |
| (c) pure-Python oracle (whole thing) | 13.19 ms |
| (d) production dispatcher (a+b as actually called) | 10.93 ms |

So (b) -- the compiled kernel call itself, NOT the Python-side
precompute the design deliberately kept -- is the dominant cost, and it
alone (8.80ms) is not much less than the ENTIRE pure-Python function
(13.19ms, a 1.5x ratio) despite doing strictly less work (assembly
only, no exp/bernoulli). Precompute (a) is a small, expected cost
(6.8%) -- NOT the explanation for the null result found earlier.

A synthetic scaling probe (`_accel.core.unstructured3d_residual_
jacobian_coupled` called directly on random arrays, no mesh/Python
overhead, sizes independent of any real fixture) rules out FIXED
per-call marshalling overhead as the cause: cost scales linearly with
edge count (0.071 us/edge at E=300 up to 0.51-0.57 us/edge at
E=15,462-61,848, roughly flat per-edge once past a small-E startup
transient) -- this is real O(E) COMPUTE cost inside the kernel, not a
constant per-call tax that would shrink as a fraction of a larger
problem.

**Conclusion, stated as a hypothesis for a future session to confirm
or refute, not asserted as proven**: the C++ implementation's own
internal structure is likely LESS efficient than numpy's vectorized
equivalent for this specific workload -- `Coo::rows/cols/vals` are
built as several independently-`resize()`d `std::vector`s per block
(poisson_flux_geometry, srh_auger's diag, sg_electron's/sg_hole's
8-entry block), then concatenated via `extend()`'s `vector::insert`
(a full copy per call, 4-5 times in the coupled orchestrator) -- where
`np.concatenate` does one allocation and one memcpy. Numpy's own
elementwise arithmetic (the Bernoulli/exp precompute this port
correctly kept in Python) is itself SIMD-vectorized C code; the C++
kernel's per-edge scalar loops were written for CORRECTNESS
(bit-identical association order, per the design's own hard
requirement) and were never profiled or tuned for speed, so losing to
numpy's decades-optimized vectorized ops on the same arithmetic is
plausible, not surprising in hindsight.

## Fix (b) applied and re-measured: real, but partial, improvement

Applied option (b) from the recommendation above: added `reserve_total()`
(`core/src/unstructured3d/kernels.cpp`), called before every `extend()`
chain in both orchestrators, so the final `Coo`'s `rows`/`cols`/`vals`
are sized ONCE up front instead of growing geometrically across 4-5
sequential `insert()` calls. No correctness change (COO content and
order untouched) -- all 10 parity/FD-Jacobian tests re-run green
immediately after, byte-for-byte, confirming this was purely an
allocation-strategy change.

**Re-measured, same profiling scripts, same B9-full fixture:**
- Kernel-call-only cost: 8.80ms -> 6.23-6.28ms (a real ~29% drop).
- Synthetic scaling probe: 0.51-0.57 us/edge -> 0.41-0.48 us/edge
  (~15-20% drop, confirmed across two array sizes, not a fluke of one
  measurement).
- Step 0's own benchmark script, re-run 2x for reproducibility: B9
  full assembly_s dropped from 0.1369-0.1456s (pre-fix) to
  0.1188-0.1236s (post-fix) -- roughly **12-18% faster**, a real,
  reproducible, if modest, win. Per-DOF ratio against structured B4
  correspondingly improved from ~7.4-8.1x to ~6.6-6.8x.

**Honest limit of this fix**: the reallocation storm was CONFIRMED as
one real cause (the hypothesis is no longer just a hypothesis for that
specific mechanism), but it does not close the gap -- 0.41-0.48 us/edge
of pure arithmetic is still far slower than what compiled code doing
this little work per edge should cost, and the kernel is still not
dramatically faster than the pure-Python oracle it replaces (6.2ms vs
13.0ms oracle, 2.1x -- better than the pre-fix 1.5x, but the WHOLE
production dispatcher including precompute is still only marginally
faster than the oracle alone was). Remaining, unexplored candidates:
the `to_vec()` copy in `unstructured3d_bindings.cpp` (every input array
is copied from the nanobind view into a fresh `std::vector` before the
kernel ever runs -- a second real copy this session did not measure in
isolation), and whether the per-edge scalar loops in `sg_electron`/
`sg_hole`/`poisson_flux_geometry` auto-vectorize as well as numpy's own
SIMD kernels do. Not pursued further this session -- diminishing
returns against the time already spent on this specific investigation;
a genuine `perf record`/`gprof` profile (recommendation (a), still not
done) would be the next concrete step if more speed is wanted here.

**Bottom line for Slice 2 (structured device3d.py)**: proceed only with
this lesson applied FROM THE START -- reserve exact output sizes up
front in any new orchestrator, and budget for the `to_vec()` copy cost
explicitly rather than assuming compiled-equals-fast. The original
"C++ obviously wins" premise remains unconfirmed as a general rule for
this class of kernel; each slice needs its own measurement, exactly as
CLAUDE.md's M32 section already insists.

## Architectural constraint (binding on every later slice)

M43 phase 4 (see CLAUDE.md "The C++ engine (M31)") already removed the
project-wide pure-Python production fallback: `_accel.require_accel()`
hard-fails without `_core` for every kernel it gates, and
`PYTCAD_ACCEL=0` no longer selects a Python runtime path anywhere. M47
does not reopen that decision and does not restore a fallback for its
own new kernels:

- Production execution of any M47-compiled kernel goes through
  `_accel.require_accel()` and the compiled path ONLY. There is no
  `PYTCAD_ACCEL=0` branch, no runtime dispatch between a Python and a
  C++ implementation, and no duplicate production code path.
- The Python implementation that exists BEFORE a kernel is ported
  (`Device3D._residual_jacobian`, `unstructured_dd3d._residual_jacobian_*`)
  is retained ONLY as a validation/reference oracle for the slice that
  ports it, exactly the way `thermal_grid.py`'s `_py` body and
  `dg_grid.py`'s kept fallback each already work as precedent for "keep
  the Python body for FD-Jacobian + parity, decide fallback-or-not
  explicitly before deleting it." The oracle is not a second production
  path; once a kernel's compiled version is proven bit-identical, the
  Python body's ONLY remaining job is that oracle role.
- Validation shape for every ported kernel:

  ```
  Python reference/oracle
          |
          v  FD-Jacobian, parity (np.array_equal), reduction-identity,
          ^  golden/regression gates
          |
  C++ production implementation
  ```

  All four gate classes (FD-Jacobian correctness, Python-vs-C++
  numerical parity, reduction-identity, existing regression/golden
  gates) must pass before a kernel's Python body stops being called at
  all -- consistent with CLAUDE.md's frozen-core amendment protocol
  and M43's own precedent, not a new rule invented for M47.

## Step 0 -- benchmark-first: structured vs. unstructured 3D assembly

### Method

New script `benchmarks/m47_s0_assembly_measure.py` (not a permanent
B1-B9 dashboard case -- a one-off decision script, same shape as
`benchmarks/m44_s2_hydro_measure.py`). It reuses the EXISTING B4 (3D
MOSFET, structured `Device3D`) and B9 (3D unstructured DD,
`unstructured_dd3d.py`) case builders from `benchmarks/cases.py`
UNCHANGED -- no new mesh/device construction, so the comparison rides
on the project's own already-size-controlled fixtures rather than a
new invented one. Assembly time is read via `benchmarks/instrument.py`'s
existing `instrumented()` context manager, the SAME wrapper that
produces BASELINE.md's `assembly_s` column for every case in the
dashboard (patches `Device3D._residual_jacobian` as a bound method for
B4, and the module-level `unstructured_dd3d._residual_jacobian_poisson3d`/
`_residual_jacobian_dd3d` functions for B9 -- both paths were already
instrumented, nothing new added to `instrument.py`). `assembly_s` is
the sum over every Newton-iterate assembly call within one full solve,
matching how BASELINE.md's own numbers are defined.

Both "quick" and "full" case sizes run, per the project's own two-size
discipline (a single size is exactly the "quoted forever, never
re-measured" number CLAUDE.md's M32 section warns against). Each
size/case combination ran 3 times (separate process-level repeats of
the whole script) to check reproducibility before trusting the
direction of the result -- not a formal best-of-N inside one process
(the mesh/device build itself is not separated from the instrumented
solve in this decision script, unlike the permanent dashboard's
`harness.py`, since this script's job is a yes/no architectural call,
not a tracked capability needing that separation).

Command:
```
OPENBLAS_NUM_THREADS=1 conda run -n TCAD python benchmarks/m47_s0_assembly_measure.py
```

### Results (3 runs, `tcad-dev`/TCAD conda env, this machine)

| case | size | DOF | NNZ | assembly calls | assembly_s (sum) | us/DOF | linsolve_s | assembly share |
|---|---|---|---|---|---|---|---|---|
| B4 structured   | quick | 4,913  | 32,657  | 7  | 0.0127-0.0129 | 2.58-2.62 | ~1.01-1.03 | 1.2-1.3% |
| B9 unstructured | quick | 2,889  | 62,907  | 15 | 0.0563-0.0585 | 19.50-20.26 | ~0.138-0.149 | 28.2-29.3% |
| B4 structured   | full  | 68,921 | 472,361 | 9  | 0.1576-0.1735 | 2.29-2.52 | 0.40-0.44 | 26.9-28.8% |
| B9 unstructured | full  | 7,464  | 177,012 | 17 | 0.1369-0.1398 | 18.34-18.73 | 0.40-0.62 | 18.1-19.2% |

Per-DOF ratio (unstructured / structured assembly cost), 3 runs each:

- quick: **11.49x, 11.57x, 11.73x**
- full: **7.83x, 8.06x, 7.44x**

Reproducibility: the ratio's direction and rough magnitude (7-12x, unstructured
costs materially more per DOF at every size tried) held across all 3
runs at both sizes -- no run flipped the sign of the comparison. NNZ/DOF
also shows the same structural story independent of timing noise: B9's
tet mesh carries roughly double the NNZ/DOF of B4's structured grid at
matched size class (quick: 21.8 vs 6.65; full: 23.7 vs 6.86), consistent
with a wider unstructured stencil, which is the structural reason
assembly costs more per DOF there (each edge/node touches more
neighbors, so more Jacobian entries and more per-edge work per node).

### Decision

No disagreement between sizes to escalate (item 6 of the instruction:
"if the metrics materially disagree, STOP and ask" -- they agree, both
in direction and rough magnitude). **Unstructured 3D assembly
(`unstructured_dd3d.py`) is the higher-value C++ port and goes first.**
Its per-DOF assembly cost is 7-12x the structured path's at comparable
sizes, and it already carries a materially larger share of total
solve time (18-29% vs. 1-29%, with structured only reaching a
comparable share at "full" size where the direct linear solve itself
gets relatively cheaper -- not because structured assembly got
absolutely more expensive per DOF, its own per-DOF number stayed flat
2.3-2.6 us/DOF across both sizes).

This also lines up with BASELINE.md's own already-recorded B9 number
(670.7m assembly at 2,889 nodes, the single most assembly-heavy row in
the whole dashboard) -- Step 0 confirms, with a controlled per-DOF
comparison against a same-class structured case, that this was a real
structural cost difference and not an artifact of B9's own case
parameters.

## Slices (unchanged from the approved plan except reordered by Step 0's result)

1. **Unstructured C++ slice** (`unstructured_dd3d.py` assembly) --
   FIRST, per Step 0.
2. **Structured C++ slice** (`device3d.py::_residual_jacobian`
   assembly) -- second; still planned, since its own per-DOF cost is
   real (2.3-2.6 us/DOF) even though smaller than unstructured's, and
   at "full" size assembly is already 27-29% of assembly+solve time --
   not negligible on its own.
3. **Heterojunction slice** (`materials_per_node`/`dlnnie` for
   `unstructured_dd3d.py`) -- separate feature work, not part of
   either mechanical port, staged after both C++ slices per the
   approved plan's own item 7.

Full per-slice detail (C++ module boundaries, Python/C++ API boundary,
validation gates, out-of-scope items) is as approved in the prior
planning turn and is not restated here to avoid drift between two
copies of the same list; this document's job is Step 0's own record.

## Next step

Awaiting approval to proceed to the unstructured C++ slice's own design
(module boundaries: `poisson.cpp`, `sg.cpp`, `bc.cpp` under
`core/src/unstructured3d/`, per the approved plan) -- no source code
changes beyond this benchmark script and this doc happen without that
approval.

## Slice 2a: structured device3d.py base assembly -- LANDED

Scope: the 4 base-assembly COO blocks device3d.py's own
`_residual_jacobian` traced into (Poisson flux row, electron
continuity, hole continuity, local diagonal terms) -- flag-independent
by construction (fd/incomplete_ion affect the VALUES Python computes
upstream, not which code stamps the COO pattern), so these run
unconditionally, covering every `Models()` combination. Optional-
physics composition (impact/btbt/nonlocal-btbt/hydrodynamic Tn/GateBC)
stays entirely in Python, appended after these 4 blocks, unchanged.

**Groundwork** (Python-only, mechanical): the 4 blocks factored into
named module-level functions (`_poisson_flux_row_coo`,
`_electron_continuity_coo`, `_hole_continuity_coo`,
`_base_diagonal_coo`), safe by construction since `np.concatenate` is
associative (grouping sub-arrays into named functions cannot change
the final flat element order, unlike Slice 1's unstructured module,
which needed the ordering re-derived from scratch). Verified via
`test_validation_3d.py`'s existing FD-Jacobian gate (8 passed) --
applying Slice 1's own lesson from the start this time, no separate
bit-identity capture script was even needed.

**C++ kernels**: `core/include/tcad/device3d/kernels.hpp`,
`core/src/device3d/kernels.cpp`, `core/bindings/device3d_bindings.cpp`
-- 4 bound functions (`device3d_poisson_flux_row`,
`device3d_electron_continuity`, `device3d_hole_continuity`,
`device3d_base_diagonal`), each writing DIRECTLY into one pre-sized
output buffer at computed offsets -- NO intermediate per-term vectors,
NO `insert()`/concatenation chain (Slice 1's reallocation-storm lesson
applied as the design from line one, not retrofitted). Wired into
`core/CMakeLists.txt` (+1 source, +1 in the `-ffp-contract=off` list,
+1 binding TU) and `core/bindings/module.cpp`.

**Validation, all green on the FIRST attempt** (no bugs found this
time, unlike Slice 1's 2 real bugs) -- `tests/test_m47_s2_device3d_
accel_parity.py` (4 tests: all 4 kernels' raw COO vs the Python
oracle, `np.array_equal`, plus reproducibility); `test_validation_3d.py`
(8 passed, including the FD-Jacobian gate, now running against the
COMPILED production path since dispatch was wired directly into
`_residual_jacobian` -- `_poisson_flux_row_coo` etc. are kept as
validation-oracle-only, no production role, matching the architectural
constraint).

**Production dispatch**: wired directly into `Device3D._residual_
jacobian` (no separate dispatcher function needed, unlike Slice 1 --
this is one method's own inline code, not a swappable module-level
function). `_accel.require_accel()` guard, no `PYTCAD_ACCEL=0` branch.
4 SEPARATE bound calls (not 1 orchestrator) -- the natural call sites
here are 4 distinct points inside one large method with unrelated
Python code (derivative-array computation) between each, unlike
Slice 1's coupled kernel which had one natural single-call point; no
micro-benchmark was run to confirm this shape is optimal (see below,
this turned out to matter).

**Benchmark re-run, HONEST result -- a regression, not a win (M32
rule, same discipline as Slice 1)**: re-ran `benchmarks/m47_s0_
assembly_measure.py`'s B4 row (2 runs). B4 full-size assembly is
**measurably SLOWER after the compile**: 2.29-2.62 us/DOF (Step 0,
pre-compile) -> 3.20-3.59 us/DOF (post-compile) -- a ~25-35% REGRESSION,
not an improvement. Quick-size shows the same direction (2.29-2.62 ->
2.10-3.87, noisier but not better). Not yet root-caused with a real
profiler (same limitation as Slice 1's own unresolved item), but the
most likely candidate, by direct analogy to Slice 1's confirmed
mechanism: 4 SEPARATE bound calls means 4 separate marshalling passes
(`to_vec()` copies) per Newton iterate, and `electron_continuity`/
`hole_continuity` alone each carry 9 float64 arrays per call (3 axes x
3 derivative arrays) -- likely more total marshalling VOLUME than
Slice 1's unstructured kernel had, while the underlying arithmetic
(4-or-8-entries-per-edge stamping) is exactly as cheap as before. The
"4 bound calls vs 1 orchestrator" question Slice 1 measured and found
negligible was measured on TRIVIAL reduction bodies at unstructured's
own array sizes -- it was never re-measured for structured's larger
per-call array COUNT, and this result suggests that assumption did not
transfer.

## Regression root-caused and fixed

The "4 bound calls vs 1" hypothesis above was WRONG -- disproved by
direct measurement rather than assumed correct. A per-kernel Python-
vs-C++ timing split (isolating each of the 4 kernels' own raw call
cost, same B4-full array sizes, no `Device3D` instrumentation
overhead) showed the compiled kernels were ALREADY AS FAST OR FASTER
than the Python oracle at the kernel level (`electron_continuity`:
13.2ms C++ vs 19.9ms Python; `poisson_flux_row`: 2.3ms C++ vs 4.1ms
Python) -- directly contradicting the benchmark harness's own 25-35%
REGRESSION finding. That contradiction is what located the real bug:
it had to be something in `_residual_jacobian`'s OWN call sites, not
the kernels.

Found it: all 9 call-site occurrences of `kLx.astype(np.int64)` (and
the 5 sibling edge-index arrays) were passed to `_accel.core.device3d_*`
with a BARE `.astype(np.int64)` -- and `np.ndarray.astype()` copies
UNCONDITIONALLY unless `copy=False` is passed, even when the array's
dtype already matches. `_edge_pairs_x`/`_y`/`_z` already return int64
on this platform (`np.mgrid`'s default dtype), confirmed directly, so
every one of those 9 calls was a wasted full-array copy, EVERY Newton
iterate, of nothing. Fixed with `.astype(np.int64, copy=False)`
(9 occurrences) -- a one-line-pattern fix, not a kernel change, and
zero effect on FD-Jacobian/parity gates (12 re-run green,
`test_validation_3d.py` + `test_m47_s2_device3d_accel_parity.py`).

**Re-measured, 2 runs**: B4 full-size assembly is now 2.48-2.61 us/DOF
-- squarely back inside the ORIGINAL pre-compile baseline range
(2.29-2.62 us/DOF, Step 0). The regression is GONE. This is parity,
not a clear win (same ballpark as the pure-Python path this replaced),
consistent with Slice 1's own honest finding that this class of kernel
does not obviously pay off from a straight port -- but the earlier
25-35% REGRESSION was a real, fixable bug in the Python-side call
sites, not an inherent property of the compiled kernels, and is now
closed out.

**Lesson for any future slice**: `ndarray.astype(dtype)` is NOT a
no-op cast when the dtype already matches -- it copies regardless,
silently, unless `copy=False` is passed explicitly. Check dtype
assumptions at every `_accel` call-site boundary before assuming a
"defensive cast" is free.
