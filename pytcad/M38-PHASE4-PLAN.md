# M38 Phase 4 -- compact-model extraction, GUI panel + deck statement

STATUS: LANDED 2026-09-10. Suite green both ways after the change:
`PYTCAD_ACCEL=0` 1629 passed/13 skipped/1 xfailed,
`PYTCAD_ACCEL=1` 1637 passed/5 skipped/1 xfailed, 39 warnings and zero
failures in both -- the pre-Phase-4 baselines (1616/1624) plus exactly
this phase's 13 new gates. See section 4 for what was actually built
and one correction to this plan's own section 3.

Parent: `M38-COMPACT-MODEL-PLAN.md` section 2 named this phase
("a GUI panel and a `workbench/workflow.py` deck statement") but left
it unscoped -- Phases 1-3 built the library (`workbench/compact.py`)
and its gates only. This document is that missing scope, written
before implementation per the project workflow.

## 1. Why now

`ARCHITECTURE.md` 4c.2/4c.3 lists M38 as landed for Phases 1-3;
Phase 4 is the only remaining named item and has no C++/frozen-core
dependency, so it can land as a pure GUI + workbench slice.

## 2. Scope

IN:
  * `gui/services/compact_runner.py` -- a new JobRunner subprocess
    module (same contract as `moscap_runner.py`/`process_runner.py`):
    builds a REAL `Device1D` p-n diode or `Device2D` n-MOSFET directly
    from scalar geometry/doping parameters (the same helper functions
    `tests/test_m38_compact_model.py`'s G1-TCAD/G2-TCAD gates already
    exercise -- `graded_mesh`+`Device1D` for the diode,
    `pytcad.mosfet.build_mosfet`/`id_vg_sweep` for the MOSFET), sweeps
    it, calls `workbench.compact.extract_diode` or `extract_mosfet1`,
    and writes a JSON manifest (`RESULT_PATH=`, `.tmp.json` atomic
    write -- `process_runner.py`'s contract, not the npz/ResultStore
    one, since a fitted parameter set is not sweep/mesh data).
  * `gui/controllers/compact_model_controller.py` -- owns a JobRunner
    pointed at that module, exposes `runDiode(...)`/`runMosfet(...)`
    slots and the manifest's contents as QML properties. Controllers
    never import pytcad (layering rule); this controller only reads
    the JSON manifest the subprocess wrote.
  * `gui/qml/panels/CompactModelPanel.qml` -- kind selector, geometry
    fields (sensible defaults matching the test fixtures), Run button,
    and a read-only results area (fitted parameters, RMS error, the
    generated `.MODEL` card). Wired into `AppController` as a child
    controller and into `Main.qml`'s panel set, same pattern as
    `ACPanel.qml`.
  * `workbench/workflow.py` -- an `EXTRACT model=diode|mosfet1
    scale=<value>` deck statement. Parsed and validated (unknown
    model name, non-positive/non-numeric scale) and stored on
    `DeckRun.extract` as `{"model": ..., "scale": ...}`. Parse-only:
    it is NOT wired into `workbench/batch.py`/`study_manifest.py`
    execution in this slice -- that would need its own reference-curve
    convention (which sweep result to fit against) and is a separate,
    larger decision. Stated here so nobody assumes a deck with an
    EXTRACT line drives batch extraction yet.

OUT (named so nobody assumes otherwise):
  * Batch/Study execution of EXTRACT (see above).
  * PMOS support in the GUI panel/runner (`build_mosfet` only builds
    the n-channel structure `test_m38_compact_model.py` gates; the
    library's `extract_mosfet1(kind="p")` path is untouched and still
    gated, just not reachable from this GUI panel).
  * Anything from M38 Phases 1-3's own OUT list (BSIM, AC/C-V
    extraction, external SPICE, performance claims).

## 3. Gates

  * `gui/tests/test_compact_runner.py` -- runs the subprocess module
    directly (CLI subprocess, same pattern as `test_process_runner.py`)
    for both kinds against a REAL `Device1D`/`Device2D` sweep, and
    checks the manifest against the same tolerances
    `test_m38_compact_model.py`'s G1-TCAD/G2-TCAD gates use for the
    identical fixtures (ideality factor in [0.9, 1.1] for the diode,
    `rel_rms_error < 0.06` for the MOSFET) -- not the G1-SELF/G2-SELF
    synthetic-recovery gates this plan originally described; those
    already exist in the library's own test file and are not
    duplicated here.
  * `gui/tests/test_compact_model_panel.py` -- headless QML: the panel
    exists, `controller` binds, kind toggle shows/hides the right
    field groups, Run invokes the right controller slot with the
    fields' current values.
  * `tests/test_m38_phase4_deck.py` -- EXTRACT statement parses into
    `DeckRun.extract`, unknown model name and non-positive scale both
    raise with a line number, a deck with no EXTRACT line leaves
    `run.extract` at its default (`None`).

No frozen-core edit anywhere in this phase.

## 4. What actually landed, and two findings

Landed exactly the section-2 scope: `gui/services/compact_runner.py`,
`gui/controllers/compact_model_controller.py`,
`gui/qml/panels/CompactModelPanel.qml` (a new "Compact Model" tab,
14th in `Main.qml`'s `workbenchTabs`, wired through
`AppController.compactModel`), and the `EXTRACT` statement in
`workbench/workflow.py` (parse-only, per section 2's OUT list).
13 new gates: 3 in `test_compact_runner.py`, 3 in
`test_compact_model_panel.py`, 7 in `test_m38_phase4_deck.py`.

Two things found while landing it, both fixed before the gates were
called green:

1. **`build_mosfet`'s own default junction sharpness
   (`sigma_y=sigma_lat=Lg/4`) does not reproduce a clean, monotonic
   Id-Vg/Id-Vd family** -- confirmed directly: the runner's first cut
   used those defaults and `extract_mosfet1` refused the result
   (`G2-REFUSE`, an apparent overdrive of ~9.7 V, i.e. a garbage
   Vt0 fit). `test_m38_compact_model.py`'s own `_tcad_mosfet` fixture
   uses `sigma_y=sigma_lat=0.05e-4` (5 um in `build_mosfet`'s cm units,
   i.e. 0.05 um) and `nx=48, ny=28` instead -- the runner's defaults
   now match that validated fixture exactly, overridable by a caller
   but no longer a guess.
2. **`Property(object, notify=...)` returning a Python dict/None was
   measured to hand QML a stale, effectively-empty value on every
   read** in this controller (confirmed by instrumenting the QML
   binding directly: `typeof r === "object"`, `!r === false`,
   `r.kind === undefined`, on every evaluation including the one after
   a real, successful extraction). Root cause not fully isolated
   (a PySide6 QVariant-marshalling quirk on this environment, not
   reproduced against a minimal case); worked around by exposing the
   manifest as `Property(str, ...)` (`resultJson`, JSON-encoded) and
   parsing it QML-side with `JSON.parse`, which is unaffected. Noted
   here so a future `Property(object)` returning a Python dict on this
   stack is treated as suspect until proven otherwise, not repeated
   blindly.

Also fixed along the way, not a physics/library finding: the deck tab
count in `gui/tests/test_shell_icons.py`'s `EXPECTED_TAB_COUNT` is a
hardcoded literal that any new sidebar tab must bump (13 -> 14) --
caught by the full-suite run, not by this phase's own new tests.
