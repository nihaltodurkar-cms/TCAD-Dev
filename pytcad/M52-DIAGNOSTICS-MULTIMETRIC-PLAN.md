# M52 — multi-metric convergence + mesh stats in diagnostics surfaces

## Scope

ARCHITECTURE.md sec 7 flagged "No full numerical-diagnostics panel ...
as a first-class GUI surface; a 'convergence' viewport mode and RunRecord
plumbing exist, not the dedicated panel." Investigating before building a
new panel found that claim stale: the GUI already has THREE diagnostics
surfaces reading the same M2 `RunRecord`/`ConvergenceStep` substrate --
`SolverTelemetryPanel` (live, scrape-fed during a run), the `convergence`
viewport mode (post-hoc, `_draw_convergence` in `mpl_canvas_item.py`), and
`PhysicsLabPanel`'s provenance/continuation tables
(`PhysicsLabController`). Building a fourth panel would duplicate them.

Both `_draw_convergence` and `PhysicsLabController.convergenceData()`
independently do `next(iter(step.metrics.values()))` -- only the FIRST
tracked Newton metric. Checked what a bias-solve verbose line actually
prints (`pytcad/device.py:2451-2453`): `|F|`, `|dpsi|`, and `|dn/n|`, three
metrics per iteration -- so today's convergence plot and Lab panel data
silently discard 2 of 3 tracked quantities. Separately, `AppController.
meshStats` computes per-axis node/extent stats but only `node_count`
reaches any diagnostics UI (`PhysicsLabController.provenanceRows()`);
axis extents are computed and thrown away.

Scoped with the user to: fix the first-metric-only defect in place (both
the viewport plot and `PhysicsLabController.convergenceData()`), and add
the missing mesh-axis-extent rows to `provenanceRows()`. Explicitly
out of scope (declined): a new panel/tab, and unifying the live
`SolverTelemetryPanel` scrape path with the post-hoc `RunRecord` path --
two independently-sourced pipelines for conceptually the same chart, left
as a separate future call.

## What shipped

- `gui/visualization/mpl_canvas_item.py` `_draw_convergence`: now iterates
  every key in `step.metrics`, not just the first. Each stage keeps its
  existing color; each metric within a stage gets its own linestyle
  (solid/dashed/dotted/dash-dot, cycled), legend labeled `"{stage}:
  {metric}"` (each unique label shown once). The "rejected" marker still
  anchors to the FIRST metric's last point (arbitrary but stable -- any
  metric works equally as a rejection anchor since all end at the same
  iteration).
- `gui/controllers/lab_controller.py` `PhysicsLabController.
  convergenceData()`: each row gains a `"metrics"` dict (`{name: [values
  with None for non-finite]}`) alongside the existing `"residuals"` key
  (kept, unchanged, for backward compatibility with
  `test_physics_lab.py`'s existing assertion on it -- `residuals` is just
  `metrics[first_key]`, same value as before).
- `PhysicsLabController.provenanceRows()`: added one row per mesh axis
  (`"Mesh x"` / `"Mesh y"` / `"Mesh z"` -> `"N=<size> [<min>, <max>] um"`)
  sourced from the SAME `AppController.meshStats` dict already joined in
  for the node-count row -- no new computation, just reading fields that
  were already being computed and discarded.
- Tests: extended `gui/tests/test_phase3a_rejected_overlay.py` and
  `gui/tests/test_physics_lab.py` with real-multi-metric assertions (a
  bias-solve RunRecord's `ConvergenceStep.metrics` genuinely has >=2 keys;
  assert the plotted line count / `convergenceData()`'s `metrics` dict
  reflect that), plus a `provenanceRows()` mesh-axis-row test.
- Verified against the real running app (`mosfet_2d`, a real 2D bias
  solve): `convergenceData()`'s bias stage carries `dpsi`/`dn/n` (2 of
  the 3 metrics `device.py:2451-2453` prints -- `F` wasn't captured for
  this particular device/path; not a regression, this milestone doesn't
  touch the parser), the viewport's convergence render shows 3 lines
  total (`equilibrium:dpsi`, `bias:dpsi`, `bias:dn/n`) where it used to
  show 2 (one per stage, first-metric-only), and the Lab panel's
  provenance trace lists `Mesh x`/`Mesh y` (`N=136 [0, 1.2] um` / `N=55
  [0, 0.2] um`, a plausible MOSFET channel size) alongside the existing
  node count.
  - A real bug was caught by this verification pass and fixed before
    landing: `provenanceRows()`'s new mesh-axis rows initially labeled
    `AppController.meshStats`' raw values "um" without converting --
    `meshStats`' min/max are cm (same units `store.mesh_axes()` returns
    everywhere else), so the first version printed nonsense ranges like
    `[0, 0.00012] um` for a 1.2 um channel. Fixed by multiplying by 1e4,
    matching the *1e4 conversion every other mesh-coordinate readout in
    the GUI already uses (e.g. `MplCanvasItem`'s hover reports, M51).

## Honest limits (deliberately not addressed here)

- `SolverTelemetryPanel`'s LIVE plot (during a run, stdout-scraped) is
  still single-metric (`|dpsi|` only) -- untouched, per the explicitly
  declined "unify live + post-hoc" option. It has its own independent
  scrape pipeline in `job_runner.py`.
- No rejected-bias-POINT-level data (the actual trial voltage/state of a
  backtracked continuation attempt) -- `continuation.py`'s
  `adaptive_bias_sweep`/`arc_length_sweep` drivers still never persist
  backoff attempts; only the coarse `ConvergenceStep.converged=False` flag
  on the whole stage exists, as before this milestone.
- No element/refinement mesh statistics (only node count + per-axis
  extents, structured-grid-only) -- `pytcad/adapt.py` still has no output
  hook into the npz.
