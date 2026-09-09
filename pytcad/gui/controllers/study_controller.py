"""M30 Phase 5: GUI Split/Study Manager.

A "study" is Phase 1's split matrix (workbench.splits.run_split_matrix)
run through Phase 4's parallel-job idea, GUI-side: a small pool of
JobRunner instances (each its own QProcess, driven by the SAME Qt event
loop -- library-level batch parallelism uses a real
ProcessPoolExecutor instead, see workbench/batch.py, since there is no
Qt event loop to share there).

Deliberately its own controller (the god controller must not grow),
shaped exactly like FamilySweepController: takes the AppController
reference, owns its own execution resources, exposed through a Qt
property. `family_sweep_controller.py` itself is NOT touched by this
phase -- per the M30 plan (pytcad/M30-WORKBENCH-PLAN.md section 9), its
sequential batch loop is retrofitted, if ever, in a later phase.

A row that fails to BUILD (workbench.splits.run_split_matrix's own
per-row isolation) never reaches a JobRunner at all; a row that solves
successfully or fails during Run is tracked the same way, so Phase 6's
matrix viewer has one consistent status vocabulary to render:
"build_error" | "pending" | "running" | "done" | "failed".

M30 Phase 12 (GUI wiring): when `setRemoteHosts()` has configured one
or more remote hosts, runStudy() pools `RemoteJobRunner`s (SSH-backed,
gui/services/remote_job_runner.py) instead of local `JobRunner`s --
each worker slot is bound to one host, round-robin, at pool-creation
time. Both runner classes share the same `start(spec)` /
`finished`/`failed`/`canceled` surface, so `_dispatch_next` and the
`_on_row_*` handlers below are unchanged either way; only the pool
factory in `runStudy()` chooses which class to instantiate. No remote
host configured -> unchanged local-only behavior (empty list is the
default, same as before this phase).
"""
import tempfile

import numpy as np
from PySide6.QtCore import QObject, Property, Signal, Slot

from ..services.job_runner import JobRunner
from ..services.remote_job_runner import RemoteJobRunner


class StudyController(QObject):
    studyChanged = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app
        self._template_id = ""
        self._bias = None
        self._split_axes = {}    # name -> value list, insertion order
        self._rows = []          # list of dict rows, see module docstring
        self._runners = []       # JobRunner pool, sized at runStudy()
        self._active = {}        # JobRunner -> row index currently running
        self._pending = []       # row indices still queued
        self._canceled = False
        self._work_dir = None
        self._remote_hosts = []  # workbench.remote_executor.RemoteHost list

    # -- configuration ----------------------------------------------------
    @Slot(str, "QVariant", "QVariant", result=bool)
    def configureStudy(self, template_id, base_values, split_spec):
        """Build every row of the split matrix (no solving yet).  A row
        the template rejects is recorded as 'build_error' rather than
        aborting the whole study -- Phase 1's own G-ISOLATION gate,
        restated through this controller's status vocabulary."""
        from workbench.splits import run_split_matrix
        from workbench.workflow import DeckRun

        run = DeckRun(template_id=str(template_id))
        run._values = dict(base_values or {})
        run.splits = {k: [float(v) for v in vals]
                     for k, vals in dict(split_spec or {}).items()}
        try:
            split_rows = run_split_matrix(run)
        except Exception as exc:
            self._app.errorRaised.emit("Could not configure study", str(exc))
            return False

        self._template_id = run.template_id
        self._split_axes = dict(run.splits)
        self._rows = []
        for row in split_rows:
            self._rows.append({
                "params": dict(row.params),
                "status": "build_error" if row.error else "pending",
                "resultPath": "",
                "error": row.error or "",
                "_device": row.device,
            })
        self.studyChanged.emit()
        return True

    @Slot("QVariant")
    def setBias(self, bias):
        """None/empty -> equilibrium-only solve for every row (Phase
        2's calibration convention); a dict -> that fixed bias point."""
        self._bias = dict(bias) if bias else None

    # -- M30 Phase 12: remote hosts ---------------------------------------
    @Slot("QVariant")
    def setRemoteHosts(self, hosts):
        """`hosts`: a list of hostname strings (plain -- same
        "type what you mean" style as the base-parameter/splits text
        areas), or empty/None to go back to local-only. Each host gets
        `workbench.remote_executor.RemoteHost` defaults (current SSH
        user, port 22, `python` on PATH, /tmp/pytcad-remote scratch
        dir) -- per-host overrides are not exposed in the GUI; use the
        library-level `RemoteExecutor` directly for that."""
        from workbench.remote_executor import RemoteHost
        names = [str(h).strip() for h in (hosts or []) if str(h).strip()]
        self._remote_hosts = [RemoteHost(host=name) for name in names]
        self.studyChanged.emit()

    @Property(list, notify=studyChanged)
    def remoteHosts(self):
        return [h.host for h in self._remote_hosts]

    # -- run / cancel -------------------------------------------------
    @Slot()
    def runStudy(self):
        if self.running:
            return
        self._pending = [i for i, r in enumerate(self._rows)
                         if r["status"] in ("pending", "failed")]
        if not self._pending:
            return
        self._canceled = False
        self._work_dir = tempfile.mkdtemp(prefix="pytcad-study-")

        if self._remote_hosts:
            # I/O-bound dispatch (ssh/scp waiting on the network), so
            # more workers than hosts is fine and useful; still capped,
            # same conservative spirit as default_worker_count's own
            # "-n 6" reasoning, since an unbounded ssh fan-out is its
            # own hazard.
            n_workers = min(len(self._pending), max(1, len(self._remote_hosts)) * 4, 12)
        else:
            from workbench.batch import default_worker_count
            n_workers = default_worker_count(len(self._pending))

        self._runners = []
        for i in range(n_workers):
            if self._remote_hosts:
                host = self._remote_hosts[i % len(self._remote_hosts)]
                runner = RemoteJobRunner(host, parent=self, work_dir=self._work_dir)
            else:
                runner = JobRunner(parent=self, work_dir=self._work_dir)
            runner.finished.connect(
                lambda path, r=runner: self._on_row_finished(r, path))
            runner.failed.connect(
                lambda summary, details, r=runner:
                    self._on_row_failed(r, summary, details))
            runner.canceled.connect(
                lambda r=runner: self._on_row_canceled(r))
            self._runners.append(runner)

        for runner in self._runners:
            self._dispatch_next(runner)
        self.studyChanged.emit()

    @Slot()
    def cancelStudy(self):
        self._canceled = True
        self._pending = []
        for runner in self._runners:
            if runner.running:
                runner.cancel()
        self.studyChanged.emit()

    def _dispatch_next(self, runner):
        if self._canceled or not self._pending:
            return
        idx = self._pending.pop(0)
        row = self._rows[idx]
        try:
            spec = self._spec_for_row(row)
            self._active[runner] = idx
            row["status"] = "running"
            runner.start(spec)
        except Exception as exc:
            row["status"] = "failed"
            row["error"] = str(exc)
            self._active.pop(runner, None)
            self._dispatch_next(runner)

    def _spec_for_row(self, row):
        from workbench.adapters.spec import spec_from_domain
        spec = spec_from_domain(row["_device"])
        spec.bias = dict(self._bias) if self._bias else None
        spec.sweep = None
        return spec

    def _on_row_finished(self, runner, result_path):
        idx = self._active.pop(runner, None)
        if idx is not None:
            row = self._rows[idx]
            row["status"] = "done"
            row["resultPath"] = result_path
        self.studyChanged.emit()
        if not self._canceled:
            self._dispatch_next(runner)

    def _on_row_failed(self, runner, summary, details):
        idx = self._active.pop(runner, None)
        if idx is not None:
            row = self._rows[idx]
            row["status"] = "failed"
            row["error"] = details or summary
        self.studyChanged.emit()
        if not self._canceled:
            self._dispatch_next(runner)

    def _on_row_canceled(self, runner):
        """A row terminated by cancelStudy() -- interrupted, not
        failed, so it goes back to 'pending' and can be re-run rather
        than being reported as a solver error."""
        idx = self._active.pop(runner, None)
        if idx is not None:
            self._rows[idx]["status"] = "pending"
        self.studyChanged.emit()
        if not self._canceled:
            self._dispatch_next(runner)

    # -- QML surface ----------------------------------------------------
    @Property(list, notify=studyChanged)
    def rows(self):
        return [{"params": r["params"], "status": r["status"],
                 "resultPath": r["resultPath"], "error": r["error"]}
                for r in self._rows]

    @Property(bool, notify=studyChanged)
    def running(self):
        return bool(self._active) or bool(self._pending)

    @Property(str, notify=studyChanged)
    def templateId(self):
        return self._template_id

    # -- M30 Phase 6: Sweep Matrix Viewer support -----------------------
    @Property("QVariant", notify=studyChanged)
    def splitAxes(self):
        """{name: [values...]} in the same order expand_splits() used
        to build the row matrix -- the LAST axis varies fastest, so a
        2-axis study's rows are already in row-major (axis0, axis1)
        order for a Grid view."""
        return dict(self._split_axes)

    @Slot(str, result=list)
    def matrixCells(self, field_name):
        """One entry per row, in row order: {params, status, value,
        resultPath}. `value` is max(scalar_field(field_name)) for a
        'done' row (a real reduction of the real solved field, never a
        synthesized number), and None for anything else -- callers
        must render None distinctly, never as 0 (see gate G-PARTIAL,
        pytcad/M30-WORKBENCH-PLAN.md section 10). Reads each result
        fresh from disk, same "small file, no caching needed"
        convention as gui/services/process_result_store.py."""
        from ..services.result_store import NpzResultStore

        out = []
        for row in self._rows:
            value = None
            if row["status"] == "done" and row["resultPath"]:
                try:
                    store = NpzResultStore(row["resultPath"])
                    arr = store.scalar_field(field_name).values
                    value = float(np.max(arr))
                except Exception:
                    value = None
            out.append({"params": dict(row["params"]),
                        "status": row["status"], "value": value,
                        "resultPath": row["resultPath"]})
        return out

    # -- M30 Phase 7: Run Comparison -------------------------------------
    @Slot(list, str, str, float, result="QVariant")
    def compareRows(self, indices, field_name, orientation="horizontal",
                    position_cm=0.0):
        """N-way comparison across chosen 'done' rows: a line-cut of
        `field_name` per row (workbench... no -- reuses
        gui.services.result_store.extract_line_cut VERBATIM, the same
        function the main viewport's own line-cut mode already calls;
        no new extraction code) plus a provenance diff table
        (gui.services.provenance_diff.provenance_diff) built from each
        row's own RunRecord. An index that is out of range, not 'done',
        or whose field isn't 2D (extract_line_cut's own dimensionality
        requirement) is reported in `skipped` with a reason -- never
        silently dropped or allowed to abort the other rows' curves."""
        from ..services.provenance_diff import provenance_diff
        from ..services.result_store import NpzResultStore, extract_line_cut

        curves, records, labels, skipped = [], [], [], []
        for raw_idx in indices:
            idx = int(raw_idx)
            if not (0 <= idx < len(self._rows)) or \
                    self._rows[idx]["status"] != "done":
                skipped.append({"index": idx, "reason": "not a completed row"})
                continue
            row = self._rows[idx]
            label = ", ".join(f"{k}={v:g}" for k, v in row["params"].items())
            try:
                store = NpzResultStore(row["resultPath"])
                x, y, actual_pos = extract_line_cut(
                    store.mesh_axes(), store.scalar_field(field_name),
                    orientation, position_cm)
            except Exception as exc:
                skipped.append({"index": idx, "reason": str(exc)})
                continue
            curves.append({"label": label, "x": list(map(float, x)),
                           "y": list(map(float, y)),
                           "actualPositionCm": actual_pos})
            records.append(store.run_record())
            labels.append(label)

        return {"curves": curves, "skipped": skipped,
                "provenance": provenance_diff(records, labels)}

    @Slot(result=list)
    def availableDisplayFields(self):
        """Scalar field names readable off the first completed row's
        result -- populates the matrix viewer's field selector."""
        from ..services.result_store import NpzResultStore

        for row in self._rows:
            if row["status"] == "done" and row["resultPath"]:
                try:
                    return NpzResultStore(row["resultPath"]).available_scalars()
                except Exception:
                    return []
        return []
