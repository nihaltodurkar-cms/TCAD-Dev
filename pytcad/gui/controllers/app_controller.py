"""Application state and the only object QML needs to talk to.

Everything dimension-specific has already been normalized away by
solver_runner.extract_result(), so nothing here branches on 1D/2D/3D --
it just renders whatever fields and units the ResultStore reports.
"""
import math
import re
import tempfile

import numpy as np
from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot

from ..services import examples
from ..services.device_spec import (
    ContactSpec, DeviceSpec, DopingSpec, MeshSpec, SweepSpec,
    TransientSpec, WaveformSpec, ACSpec,
)
from ..services.job_runner import JobRunner
from ..services.process_model import ProcessFlow, ProcessStep, validate_flow
from ..services.process_result_store import ProcessResultStore
from ..services.project_store import load_project, save_project
from ..services.result_store import NpzResultStore, SpecResultStore
from ..services import sweep_derived
from ..services.structure_model import GateModel, RegionSpec
from ..services.undo_stack import Command, UndoStack
from .console_model import ConsoleModel
from .contact_list_model import ContactListModel
from .gate_list_model import GateListModel
from .process_step_list_model import ProcessStepListModel
from .project_tree_model import ProjectTreeModel
from .properties_model import PropertiesModel
from .region_list_model import RegionListModel


def _has_non_finite_leaf(value):
    """True if `value` (or anything nested inside a dict it contains) is a
    non-finite number -- e.g. QML's parseFloat("") / parseFloat("abc")
    landing as NaN. GUI smoke-test finding: unlike SweepSpec.validate_values()
    and ImplantEditor's window fields (both of which already guard against
    exactly this), every plain numeric field wired through
    setProcessStepParameters()/setContactVoltage()/setGateVoltage()/
    setGateToxCm()/leftContactV/rightContactV accepted NaN silently and let
    it reach the solver. This is the single choke point shared by all of
    them."""
    if isinstance(value, dict):
        return any(_has_non_finite_leaf(v) for v in value.values())
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return not math.isfinite(value)
    return False


class AppController(QObject):
    statusChanged = Signal()
    busyChanged = Signal()
    resultChanged = Signal()
    fieldChanged = Signal()
    errorRaised = Signal(str, str)          # concise summary, expandable details
    structureChanged = Signal()
    undoStateChanged = Signal()
    processResultChanged = Signal()
    sweepChanged = Signal()                 # v0.4 sweep configuration edits
    transientChanged = Signal()             # M17 phase 3 transient config edits
    acChanged = Signal()                    # M18 Phase 4 AC config edits
    comparisonChanged = Signal()            # M9 model on/off overlay

    def __init__(self, parent=None):
        super().__init__(parent)
        self.spec = None
        self._store = None
        self._status = "Ready"
        self._busy = False
        self._current_field = ""
        self._selected = "project"

        self._tree_model = ProjectTreeModel()
        self._properties_model = PropertiesModel()
        self._console_model = ConsoleModel()

        self.structure = None
        self.mesh_model = None
        self._undo_stack = UndoStack()
        self._region_list_model = RegionListModel()
        self._contact_list_model = ContactListModel()
        self._gate_list_model = GateListModel()
        self._structure_errors = []

        self.process_flow = ProcessFlow()
        self._process_flow_model = ProcessStepListModel()
        self._process_errors = []

        self._runner = JobRunner(parent=self)
        self._runner.progressLine.connect(self.consoleModel.append)
        self._runner.progressLine.connect(self._on_progress_line)
        self._runner.stageChanged.connect(self._on_stage)
        self._runner.finished.connect(self._on_finished)
        self._runner.failed.connect(self._on_failed)
        self._runner.canceled.connect(self._on_canceled)

        # Process -> Device(1D) handoff (v0.3, Task 8): a second JobRunner
        # instance driving process_runner.py instead of solver_runner.py.
        # Kept entirely separate from self._runner/self._store above --
        # a process-flow run and a device solve are different subprocess
        # jobs with different result shapes (a manifest.json vs. a
        # result.npz) and must not be conflated.
        self._process_runner = JobRunner(parent=self, module="gui.services.process_runner")
        self._process_runner.progressLine.connect(self.consoleModel.append)
        self._process_runner.finished.connect(self._on_process_finished)
        self._process_runner.failed.connect(self._on_process_failed)
        self._process_runner.canceled.connect(self._on_process_canceled)
        self._process_result = None      # ProcessResultStore, once a flow has run
        # M9: model on/off comparison -- a SECOND, fully independent
        # solve of the last-run device with every catalog model disabled,
        # so the series viewport can overlay "models on" vs "all off".
        # Own JobRunner, own output, never touches _store/_busy: a slow
        # comparison can be canceled by quitting without disturbing any
        # primary run.
        self._comparison_runner = JobRunner(parent=self,
                                            work_dir=tempfile.mkdtemp(
                                                prefix="pytcad-compare-"))
        self._comparison_runner.progressLine.connect(self.consoleModel.append)
        self._comparison_runner.finished.connect(self._on_comparison_finished)
        self._comparison_runner.failed.connect(self._on_comparison_failed)
        self._comparison_store = None
        self._comparison_label = "all models off"
        self._last_run_spec = None
        self._left_contact_v = 0.0
        self._right_contact_v = 0.0
        # v0.4 voltage sweep applied to the next Run (not undoable: it is
        # run configuration, like field selection -- not device geometry)
        self._sweep_config = None
        # M17 phase 3: transient (time-domain) waveform run applied to
        # the next Run -- same non-undoable run-configuration status as
        # _sweep_config, and mutually exclusive with it (enforced in
        # run()).
        self._transient_config = None
        self._ac_config = None
        # v0.6 Phase 2c: which SolverBackend id the next Run uses. Run
        # configuration, like the sweep config above -- not undoable,
        # not device geometry.
        self._backend = "pytcad"
        # v0.6 Phase 2d: which linear-solve ENGINE the next Run uses
        # (Direct / GPU direct / AMG / MPI Schwarz) -- distinct from
        # _backend above (pytcad vs. devsim, a different SOLVER
        # entirely). "auto" reproduces solver_runner.run_job's existing
        # node-count/dimensionality heuristic unchanged; see
        # engineOptionsForQml's docstring for the rest.
        self._engine = "auto"
        # v0.5.0 M4: the Physics Lab owns the model-flag configuration.
        # Its defaults equal the wire-format defaults, so this is
        # invisible until a student toggles something.
        from .lab_controller import PhysicsLabController
        # Both sub-controllers are exposed to QML as context properties
        # (gui/app.py), so their lifetime must ride the QObject parent
        # chain -- Qt children of THIS controller -- not bare Python
        # attributes. Unparented, they were destroyed whenever Python GC
        # got around to them, racing QML binding evaluation at shutdown
        # and printing 'TypeError: Cannot read property ... of null'
        # for physicsLab/deviceBuilder (the class b381124 fixed for
        # AppController itself). The first positional still names the
        # app so they can reach currentStore(); parent=self makes the
        # engine -> controller -> lab/builder destruction order total.
        self.lab = PhysicsLabController(self, parent=self)
        from .builder_controller import BuilderController
        self.builder = BuilderController(self, parent=self)
        # Batch sweeps: same ownership pattern -- Qt child of THIS
        # controller, exposed to QML through a property (not a bare
        # attribute).
        from .family_sweep_controller import FamilySweepController
        self.family = FamilySweepController(self, parent=self)
        from .cv_controller import CVController
        self.cv = CVController(self, parent=self)
        # Virtual Probe Station: DC/RF device characterization sweeps and
        # extraction (Vth, SS, gds/ro, breakdown voltage, fT). Same
        # ownership pattern as cv/family above.
        from .probe_station_controller import ProbeStationController
        self.probe_station = ProbeStationController(self, parent=self)
        # Solver Telemetry: listens to self._runner's (already
        # constructed above) iterationChanged/residualChanged signals --
        # same ownership pattern as probe_station, but this one reads a
        # JobRunner that already exists rather than driving its own.
        from .solver_telemetry_controller import SolverTelemetryController
        self.solver_telemetry = SolverTelemetryController(self, parent=self)
        # Band Diagram Viewer: reads band__* arrays off the current
        # ResultStore on every resultChanged.
        from .band_diagram_controller import BandDiagramController
        self.band_diagram = BandDiagramController(self, parent=self)
        # 3D-VISUALIZATION-PLAN.md Phase 1: the currently-open 3D viewer
        # window, if any (a plain Python attribute, not Qt-parented --
        # it's a separate top-level window, not a QML-owned object).
        self._viewer3d_window = None
        # GUI-IMPROVEMENT-PLAN Phase 4: runtime validation layer to catch
        # hard-to-detect bugs (state inconsistencies, invalid inputs, etc.)
        from ..services.gui_state_validator import GuiStateValidator
        self.stateValidator = GuiStateValidator(parent=self)
        # A result goes stale the moment an edit dirties the project, not
        # just at the next Run start/stop -- undoStateChanged already
        # fires at every structure/doping/contact edit site, so hook it
        # directly rather than waiting for _set_busy to catch up.
        self.undoStateChanged.connect(self._notify_state_validator)

    # -- properties ---------------------------------------------------
    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

    def _set_status(self, text):
        self._status = text
        self.statusChanged.emit()

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    def _set_busy(self, value):
        self._busy = value
        self.busyChanged.emit()
        self._notify_state_validator()

    def _notify_state_validator(self):
        """GUI-IMPROVEMENT-PLAN Phase 4: push current state to the
        validator. Called on every busy-flag flip (Run start/stop) AND
        on every undoStateChanged (structure/doping/contact edits) --
        the latter is what actually makes a result stale, so the
        validator must not wait for the next Run to notice."""
        self.stateValidator.onStateChange(
            self.hasResult, self._store is not None, self.isDirty)

    @Property(bool, notify=resultChanged)
    def hasResult(self):
        # Ask the store, never type-check it: any backend's solved-result
        # store satisfies this without importing NpzResultStore here.
        return self._store is not None and self._store.is_solved_result()

    @Property(list, notify=resultChanged)
    def fieldNames(self):
        return self._store.available_scalars() if self._store else []

    @Property(str, notify=fieldChanged)
    def currentField(self):
        return self._current_field

    def currentStore(self):
        return self._store

    @Property("QVariant", notify=resultChanged)
    def meshStats(self):
        """Mesh statistics for the 3c panel: {dimensionality, node_count,
        axes}. Read-only, sourced from the current ResultStore."""
        store = self._store
        if store is None:
            return None
        try:
            axes = store.mesh_axes()
            dim = axes.dimensionality
            node_count = 1
            axis_info = {}
            for name in ("x", "y", "z")[:dim]:
                arr = np.asarray(axes.axes[name])
                node_count *= arr.size
                axis_info[name] = {"size": int(arr.size),
                                   "min": float(arr.min()),
                                   "max": float(arr.max())}
            return {"dimensionality": dim,
                    "node_count": node_count,
                    "axes": axis_info}
        except Exception:
            return None

    @Property(str, notify=resultChanged)
    def solverEngineLabel(self):
        """Human-readable summary of which numerical engine actually
        produced the CURRENT result -- plain direct solve, AMG/GPU-
        accelerated, or MPI Schwarz domain decomposition -- so a
        multi-second speedup from an opt-in backend (pyamg/cupy/
        mpi4py, see M22-LINSOLVE-PLAN.md sections 9-11) is visible to
        the user instead of being a silent internal choice. Read
        directly from record__meta.numerics (stamped by
        gui/services/solver_runner.py's run_job()), never re-derived
        or guessed -- empty string when there is no result or no
        provenance record (pre-v2 result files)."""
        store = self._store
        if store is None or not store.has_record():
            return ""
        record = store.run_record()
        if record is None:
            return ""
        numerics = record.numerics or {}
        if numerics.get("engine") == "mpi_schwarz":
            axis = numerics.get("mpi_split_axis", "?")
            return f"MPI Schwarz ({axis}-split, 4 ranks)"
        labels = {"direct": "Direct", "gpu_direct": "GPU direct",
                 "bicgstab": "AMG (bicgstab)", "gmres": "AMG (gmres)"}
        return labels.get(numerics.get("linsolve", "direct"), "")

    @Slot()
    def openViewer3d(self):
        """3D-VISUALIZATION-PLAN.md Phase 1/2: open the PyVista/VTK 3D
        window for the current result. Refuses (loudly, via
        errorRaised) rather than silently no-op'ing for anything that
        isn't a solved 3D result -- same house rule as every other
        dimensionality guard in this codebase. Phase 4: also wires up
        sweep snapshots for animation playback when available."""
        stats = self.meshStats
        if stats is None or not self.hasResult:
            self.errorRaised.emit("Nothing to view in 3D",
                                  "Run a solve first.")
            return
        if stats["dimensionality"] != 3:
            self.errorRaised.emit(
                "Not a 3D result",
                f"The current result is {stats['dimensionality']}D. "
                "The 3D viewer only applies to a solved 3D device.")
            return
        from ..services.viewer3d import Viewer3DWindow
        # Held on self so the window (and its VTK render context) isn't
        # garbage-collected the instant this method returns; closing an
        # old one before opening a new one avoids piling up live VTK
        # windows across repeated clicks. Viewer3DWindow takes the
        # store directly (Phase 2): it attaches EVERY available scalar
        # field to one grid up front, so its sidebar can switch fields
        # without this method rebuilding anything.
        try:
            window = Viewer3DWindow(self._store)
        except Exception as exc:
            self.errorRaised.emit("Could not open the 3D viewer", str(exc))
            return
        if self._viewer3d_window is not None:
            self._viewer3d_window.close()
        self._viewer3d_window = window
        # Phase 4: wire up sweep snapshots for animation playback.
        if self._store.has_sweep_snapshots():
            try:
                window.set_sweep_snapshots(self._store.sweep_snapshots())
            except Exception:
                # Snapshots exist but are corrupt/incomplete -- leave
                # playback disabled rather than crashing the viewer.
                pass
        self._viewer3d_window.show()

    def lastRunSpec(self):
        """The spec of the last executed Run -- the base device for
        batch sweeps.  Public: FamilySweepController reads it."""
        return self._last_run_spec

    # Plain Python instance attributes are NOT visible to QML's
    # meta-object-based property lookup -- an `appController.propertiesModel`
    # binding against a bare attribute silently resolves to undefined,
    # leaving the panel's ListView with no model and no error anywhere.
    # These three must be real Qt properties, not attributes, for QML to
    # see them at all. (The viewport didn't need this: MplCanvasItem's
    # bindController is an explicit @Slot that calls Python methods
    # directly, never an `appController.X` attribute lookup from QML.)
    @Property(QObject, constant=True)
    def treeModel(self):
        return self._tree_model

    @Property(QObject, constant=True)
    def propertiesModel(self):
        return self._properties_model

    @Property(QObject, constant=True)
    def consoleModel(self):
        return self._console_model

    @Property(QObject, constant=True)
    def familySweep(self):
        return self.family

    @Property(QObject, constant=True)
    def cvSweep(self):
        return self.cv

    @Property(QObject, constant=True)
    def probeStation(self):
        return self.probe_station

    @Property(QObject, constant=True)
    def solverTelemetry(self):
        return self.solver_telemetry

    @Property(QObject, constant=True)
    def bandDiagram(self):
        return self.band_diagram

    @Property(QObject, constant=True)
    def regionListModel(self):
        return self._region_list_model

    @Property(QObject, constant=True)
    def contactListModel(self):
        return self._contact_list_model

    @Property(QObject, constant=True)
    def gateListModel(self):
        return self._gate_list_model

    @Property(QObject, constant=True)
    def processFlowModel(self):
        return self._process_flow_model

    # Material is a scalar read from StructureModel, not the whole
    # object: a plain (non-QObject) Python object exposed via
    # @Property(object, ...) is NOT attribute-readable from QML/JS at
    # all -- `structureForQml.material` resolves to `undefined` even
    # though `structureForQml` itself is truthy (found via a real
    # rendered screenshot showing "Material: undefined"; confirmed with
    # an isolated repro). structureForQml/meshModelForQml below exist
    # only to be handed opaquely into a @Slot(object, object) on the
    # Python side (MplCanvasItem.setStructureSource) -- QML never reads
    # attributes off them directly.
    @Property("QVariantList", constant=True)
    def materialNames(self):
        """M11-S5: registered library keys for the region-material
        editor (sorted, canonical uppercase keys)."""
        from workbench.core.materials import LIBRARY
        return LIBRARY.names()

    @Property(str, notify=structureChanged)
    def structureMaterial(self):
        return self.structure.material if self.structure else "Silicon"

    # Plain self.structure/self.mesh_model attributes are, per the same
    # v0.1 treeModel/propertiesModel bug, invisible to QML property
    # lookup -- exposed here so ViewportPanel.setViewMode() can hand them
    # to MplCanvasItem.setStructureSource() without a raw attribute read.
    @Property(object, notify=structureChanged)
    def structureForQml(self):
        return self.structure

    @Property(object, notify=structureChanged)
    def meshModelForQml(self):
        return self.mesh_model

    @Property(list, notify=structureChanged)
    def structureValidationErrors(self):
        return [e.message for e in self._structure_errors]

    # design section 10's documented format: "Step 03 -- Implant: <message>",
    # a 1-based flow index and the operation's display name, resolved from
    # the ValidationError's object_id (a step uuid) back to its current
    # position/operation in self.process_flow -- not the raw uuid hex the
    # code used to emit directly.
    _OPERATION_LABELS = {"substrate": "Substrate", "implant": "Implant",
                         "anneal": "Anneal", "oxidize": "Oxidize"}

    def _format_process_error(self, error):
        if error.object_id:
            idx = next((i for i, s in enumerate(self.process_flow.steps)
                       if s.id == error.object_id), None)
            if idx is not None:
                step = self.process_flow.steps[idx]
                label = self._OPERATION_LABELS.get(step.operation, step.operation.title())
                return f"Step {idx + 1:02d} — {label}: {error.message}"
        # Flow-level errors (e.g. "must start with an enabled substrate
        # step") aren't scoped to any one step, so there is no step number
        # to resolve -- just the message.
        return error.message

    @Property(list, notify=structureChanged)
    def processValidationErrors(self):
        # Reuses the existing generic structureChanged signal rather than
        # adding a parallel signal every QML binding would need to
        # duplicate-listen to -- processFlowModel and this property both
        # key off it, refreshed together in _refresh_process_flow.
        return [self._format_process_error(e) for e in self._process_errors]

    @Property(bool, notify=processResultChanged)
    def hasProcessResult(self):
        return self._process_result is not None

    # Same rationale as structureForQml/meshModelForQml above: a plain
    # Python object property is not attribute-readable from QML, so this
    # exists only to be handed opaquely into MplCanvasItem.setProcessSource()
    # (ViewportPanel.setViewMode()'s "process" branch) -- QML never reads
    # attributes off it directly.
    @Property(object, notify=processResultChanged)
    def processResultForQml(self):
        return self._process_result

    # -- v0.4 sweep configuration and results -------------------------
    @Property(bool, notify=sweepChanged)
    def hasSweepConfig(self):
        return self._sweep_config is not None

    @Property(bool, notify=resultChanged)
    def hasSweep(self):
        return self._store is not None and self._store.has_sweep()

    # Same opaque-handoff rationale as processResultForQml above: handed
    # to MplCanvasItem.setSweepSource() by ViewportPanel, never
    # attribute-read from QML.
    @Property(object, notify=resultChanged)
    def sweepResultForQml(self):
        if self._store is None or not self._store.has_sweep():
            return None
        try:
            return self._store.sweep_result()
        except Exception:
            return None

    # Candidate sweep targets for the QML panel, in structure order:
    # what the Structure workbench currently defines, else what the
    # current spec (example / process handoff) carries.
    @Property(list, notify=structureChanged)
    def sweepContactNames(self):
        if self.structure is not None:
            names = [c.name for c in self.structure.contacts]
            names += [g.name for g in self.structure.gates]
            return names
        if self.spec is not None:
            return [c.name for c in self.spec.contacts]
        return []

    @Slot(str, float, float, float)
    def setSweepConfig(self, contact, start, stop, step):
        """Configure the voltage sweep Run() will attach to the spec.
        Numeric sanity is checked immediately (final review M-6) so a
        typo'd field cannot sit there labeled 'armed'; contact-name
        validity still waits for Run, where the real spec is known."""
        cfg = SweepSpec(contact=str(contact), start=float(start),
                        stop=float(stop), step=float(step))
        try:
            cfg.validate_values()
        except ValueError as exc:
            self.errorRaised.emit("Invalid sweep configuration", str(exc))
            return
        self._sweep_config = cfg
        self.sweepChanged.emit()

    @Slot()
    def clearSweepConfig(self):
        self._sweep_config = None
        self.sweepChanged.emit()

    @Slot(result="QVariant")
    def sweepConfig(self):
        """Read back the LIVE armed sweep as {contact,start,stop,step}
        (or null).  The panel's TextFields are write-only -- after a
        rejected arm attempt it uses this to revert its fields to what
        is actually armed, so the displayed values can never disagree
        with the configuration a Run would execute."""
        s = self._sweep_config
        if s is None:
            return None
        return {"contact": s.contact, "start": s.start,
                "stop": s.stop, "step": s.step}

    # -- M17 phase 3: transient configuration and results -----------------
    @Property(bool, notify=transientChanged)
    def hasTransientConfig(self):
        return self._transient_config is not None

    @Property(bool, notify=resultChanged)
    def hasTransient(self):
        return self._store is not None and self._store.has_transient()

    # Same opaque-handoff rationale as sweepResultForQml above: handed to
    # MplCanvasItem by ViewportPanel, never attribute-read from QML.
    @Property(object, notify=resultChanged)
    def transientResultForQml(self):
        if self._store is None or not self._store.has_transient():
            return None
        try:
            return self._store.transient_result()
        except Exception:
            return None

    @Slot(str, str, float, float, float, float, float, float)
    def setTransientConfig(self, contact, kind, v0, v1, t0, t1, t_end, dt0):
        """Configure the transient waveform Run() will attach to the
        spec. Numeric sanity is checked immediately (same M-6 precedent
        setSweepConfig follows) so a typo'd field cannot sit there
        labeled 'armed'; contact-name validity still waits for Run,
        where the real spec is known."""
        cfg = TransientSpec(
            contact=str(contact),
            waveform=WaveformSpec(kind=str(kind), v0=float(v0), v1=float(v1),
                                  t0=float(t0), t1=float(t1)),
            t_end=float(t_end), dt0=float(dt0))
        try:
            cfg.validate_values()
        except ValueError as exc:
            self.errorRaised.emit("Invalid transient configuration", str(exc))
            return
        self._transient_config = cfg
        self.transientChanged.emit()

    @Slot()
    def clearTransientConfig(self):
        self._transient_config = None
        self.transientChanged.emit()

    @Slot(result="QVariant")
    def transientConfig(self):
        """Read back the LIVE armed transient config (or null), same
        write-only-fields-revert-from-here role as sweepConfig()."""
        c = self._transient_config
        if c is None:
            return None
        return {"contact": c.contact, "kind": c.waveform.kind,
                "v0": c.waveform.v0, "v1": c.waveform.v1,
                "t0": c.waveform.t0, "t1": c.waveform.t1,
                "t_end": c.t_end, "dt0": c.dt0}

    # -- M18 Phase 4: AC/Y-parameter configuration and results ------------
    @Property(bool, notify=acChanged)
    def hasACConfig(self):
        return self._ac_config is not None

    @Property(bool, notify=resultChanged)
    def hasAc(self):
        return self._store is not None and self._store.has_ac()

    # Same opaque-handoff rationale as transientResultForQml above:
    # handed to MplCanvasItem by ViewportPanel, never attribute-read
    # from QML.
    @Property(object, notify=resultChanged)
    def acResultForQml(self):
        if self._store is None or not self._store.has_ac():
            return None
        try:
            return self._store.ac_result()
        except Exception:
            return None

    @Property(bool, notify=structureChanged)
    def canRunAc(self):
        """AC analysis has no ac3d module -- hidden for a 3D spec, same
        "must not even appear" convention canSelectBackend's own
        DEVSIM-is-1D-only gate already uses (not merely disabled)."""
        return self.spec is not None and self.spec.mesh.dimensionality != 3

    @Slot(str, float, float, int)
    def setACConfig(self, contact, f_start, f_stop, n_points):
        """Configure the AC sweep Run() will attach to the spec.
        Numeric sanity is checked immediately (same precedent setSweep
        Config/setTransientConfig follow) so a typo'd field cannot sit
        there labeled 'armed'; contact-name validity still waits for
        Run, where the real spec is known."""
        cfg = ACSpec(contact=str(contact), f_start=float(f_start),
                     f_stop=float(f_stop), n_points=int(n_points))
        try:
            cfg.validate_values()
        except ValueError as exc:
            self.errorRaised.emit("Invalid AC configuration", str(exc))
            return
        self._ac_config = cfg
        self.acChanged.emit()

    @Slot()
    def clearACConfig(self):
        self._ac_config = None
        self.acChanged.emit()

    @Slot(result="QVariant")
    def acConfig(self):
        c = self._ac_config
        if c is None:
            return None
        return {"contact": c.contact, "f_start": c.f_start,
                "f_stop": c.f_stop, "n_points": c.n_points}

    # -- workflow-friction pass: Run enablement ---------------------------
    @Property(bool, notify=structureChanged)
    def hasDeviceToRun(self):
        """Mirrors run()'s own early-return check ("Nothing to run" /
        "Load an example first.") so Main.qml can disable the Run button
        instead of letting the user click it into a dead-end error
        dialog -- same condition, surfaced before the click rather than
        after it."""
        return self.structure is not None or self.spec is not None

    # -- v0.6 Phase 2c: solver backend selection --------------------------
    @Property(bool, notify=structureChanged)
    def canSelectBackend(self):
        """DEVSIM is 1D-two-terminal-only (check_devsim_compatible), and
        the Structure/Device-Builder path always builds 2D -- so the
        selector must not even APPEAR there, not just be disabled. Gate
        on the built spec's own dimensionality rather than "is
        self.structure set", which would go stale the moment a 2D
        structure is cleared by a process handoff without a fresh spec
        yet built (buildDeviceFromProcess's own one-way precedence
        switch, documented above)."""
        return self.spec is not None and self.spec.mesh.dimensionality == 1

    @Slot(result="QVariant")
    def backendOptionsForQml(self):
        """[{"id","label","enabled","reason"}, ...] for the backend
        selector. "pytcad" is always enabled; "devsim" is enabled only
        if installed AND check_devsim_compatible(...) passes -- the SAME
        function DevsimBackend.run() itself enforces, so this can never
        promise a run that would then be refused.

        Checked against the Lab's CURRENT model_config, not
        self.spec.models directly: run() only copies model_config onto
        the spec at Run time (see run()'s own comment on this), so
        self.spec.models can be stale/default here even though toggling
        a model in the Physics Lab should immediately be reflected in
        whether devsim looks selectable."""
        from workbench.solvers.base import backend_ids
        opts = [{"id": "pytcad", "label": "pytcad", "enabled": True, "reason": ""}]
        if "devsim" not in backend_ids():
            opts.append({"id": "devsim", "label": "devsim", "enabled": False,
                        "reason": "optional devsim dependency not installed"})
            return opts
        reason = ""
        try:
            from workbench.solvers.devsim_backend import check_devsim_compatible
            if self.spec is not None:
                import copy
                trial = copy.copy(self.spec)
                trial.models = dict(self.lab.model_config)
                check_devsim_compatible(trial)
        except ValueError as exc:
            reason = str(exc)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
        opts.append({"id": "devsim", "label": "devsim",
                    "enabled": self.spec is not None and not reason,
                    "reason": reason})
        return opts

    @Property(str, notify=structureChanged)
    def selectedBackend(self):
        return self._backend

    @Slot(str)
    def setBackend(self, backend_id):
        self._backend = str(backend_id)
        self.structureChanged.emit()

    # -- v0.6 Phase 2d: solver ENGINE selection ---------------------------
    # Distinct from the backend selector above: backend picks WHICH
    # SOLVER runs the job (pytcad vs. devsim); this picks WHICH LINEAR-
    # SOLVE PATH the pytcad backend itself uses (Direct / GPU direct /
    # AMG / MPI Schwarz domain decomposition) -- solver_runner.run_job()
    # already implements every one of these and auto-selects among them
    # by node count/dimensionality; this exposes a manual override
    # (DeviceSpec.engine, "auto" by default) so a user can force one.
    @Slot(result="QVariant")
    def engineOptionsForQml(self):
        """[{"id","label","enabled","reason"}, ...] for the engine
        selector. Cheap, best-effort checks only (dimensionality,
        transient, optional-dependency presence) -- same "defense in
        depth" contract backendOptionsForQml documents: run() re-sends
        whatever was picked and solver_runner.run_job() is the actual,
        authoritative gate (e.g. mpi_schwarz's precise per-axis
        doping/gate-layout refusal via _pick_mpi_split_axis is NOT
        re-derived here, since that needs the full doping array this
        list must stay cheap enough to recompute on every
        structureChanged)."""
        # Reached through gui.services.solver_runner, never imported
        # directly out of core (test_m3_store_seam.py's own
        # test_app_controller_never_imports_pytcad_core enforces that
        # this controller only ever reaches core math through services);
        # solver_runner.py already re-exports these three exactly for
        # this "is the optional dependency present" purpose.
        from gui.services.solver_runner import _HAVE_MPI, _HAVE_PYAMG, _HAVE_CUPY
        dim = self.spec.mesh.dimensionality if self.spec is not None else None
        opts = [{"id": "auto", "label": "Auto", "enabled": True,
                "reason": ""}]
        opts.append({"id": "direct", "label": "Direct", "enabled": True,
                    "reason": ""})
        opts.append({"id": "gpu_direct", "label": "GPU direct",
                    "enabled": _HAVE_CUPY,
                    "reason": "" if _HAVE_CUPY
                              else "optional cupy dependency not installed"})
        opts.append({"id": "amg", "label": "AMG (bicgstab)",
                    "enabled": _HAVE_PYAMG,
                    "reason": "" if _HAVE_PYAMG
                              else "optional pyamg dependency not installed"})
        mpi_reason = ""
        if not _HAVE_MPI:
            mpi_reason = "optional mpi4py dependency / mpirun not available"
        elif dim != 3:
            mpi_reason = "only available for 3D devices"
        elif self._transient_config is not None:
            mpi_reason = "not compatible with an armed transient run"
        opts.append({"id": "mpi_schwarz", "label": "MPI Schwarz",
                    "enabled": not mpi_reason, "reason": mpi_reason})
        return opts

    @Property(str, notify=structureChanged)
    def selectedEngine(self):
        return self._engine

    @Slot(str)
    def setEngine(self, engine_id):
        self._engine = str(engine_id)
        self.structureChanged.emit()

    @Property(float, notify=processResultChanged)
    def leftContactV(self):
        return self._left_contact_v

    @leftContactV.setter
    def leftContactV(self, value):
        value = float(value)
        if not math.isfinite(value):
            self.errorRaised.emit("Invalid contact voltage",
                                  "Voltage must be a finite number.")
            return
        self._left_contact_v = value

    @Property(float, notify=processResultChanged)
    def rightContactV(self):
        return self._right_contact_v

    @rightContactV.setter
    def rightContactV(self, value):
        value = float(value)
        if not math.isfinite(value):
            self.errorRaised.emit("Invalid contact voltage",
                                  "Voltage must be a finite number.")
            return
        self._right_contact_v = value

    @Property(bool, notify=undoStateChanged)
    def canUndo(self):
        return self._undo_stack.can_undo

    @Property(bool, notify=undoStateChanged)
    def canRedo(self):
        return self._undo_stack.can_redo

    @Property(bool, notify=undoStateChanged)
    def isDirty(self):
        return self._undo_stack.is_dirty

    @Property(list, notify=structureChanged)
    def meshInfo(self):
        if self.structure is None or self.mesh_model is None:
            return []
        mesh_spec = self.mesh_model.to_mesh_spec(self.structure.width_cm, self.structure.height_cm)
        nx, ny = len(mesh_spec.axes["x"]), len(mesh_spec.axes["y"])
        x = np.asarray(mesh_spec.axes["x"]); y = np.asarray(mesh_spec.axes["y"])
        hx, hy = np.diff(x), np.diff(y)
        total_nodes = nx * ny
        total_cells = (nx - 1) * (ny - 1)
        dof = 3 * total_nodes
        est_mb = dof * 8 * 3 / (1024 * 1024)   # rough: psi/n/p doubles + Jacobian working set order-of-magnitude
        # Rows must be plain lists, not tuples: PySide6 marshals a
        # list-of-lists to an indexable JS array but NOT a list-of-tuples,
        # and MeshEditor.qml's delegate reads modelData[0]/modelData[1].
        rows = [["Nx", str(nx)], ["Ny", str(ny)],
                ["Total nodes", str(total_nodes)], ["Total cells", str(total_cells)],
                ["Domain width", f"{self.structure.width_cm * 1e4:g} um"],
                ["Domain height", f"{self.structure.height_cm * 1e4:g} um"],
                ["Min spacing (x)", f"{hx.min() * 1e4:.4g} um" if hx.size else "n/a"],
                ["Max spacing (x)", f"{hx.max() * 1e4:.4g} um" if hx.size else "n/a"],
                ["Min spacing (y)", f"{hy.min() * 1e4:.4g} um" if hy.size else "n/a"],
                ["Max spacing (y)", f"{hy.max() * 1e4:.4g} um" if hy.size else "n/a"],
                ["Estimated memory (rough)", f"{est_mb:.1f} MB"]]
        if total_nodes > 50_000:
            rows.append(["Warning", "This mesh is large; 2D drift-diffusion may "
                                    "require substantial memory and solve time."])
        return rows

    def _refresh_structure_models(self):
        # Guarded: process-flow-only sessions (no loadStructureExample/
        # loadProject yet) share the same UndoStack, and undo()/redo()
        # call this unconditionally -- self.structure is None until a
        # structure is actually loaded, so this must be a no-op rather
        # than an AttributeError in that case. Every existing v0.2 call
        # site (addRegion, moveRegion, etc.) already requires a loaded
        # structure to run at all, so this guard changes nothing for them.
        if self.structure is None:
            return
        self._region_list_model.refresh(self.structure.regions)
        self._contact_list_model.refresh(self.structure.contacts)
        self._gate_list_model.refresh(self.structure.gates)
        self._run_validation_quiet()
        self.structureChanged.emit()

    def _run_validation_quiet(self):
        # Guarded (Task 9): saveProject/runStructureValidation may now be
        # called on a project with no structure loaded (process-only
        # projects) -- self.structure/self.mesh_model can legitimately be
        # None, in which case there is nothing to validate.
        self._structure_errors = (
            self.structure.validate(self.mesh_model)
            if self.structure is not None and self.mesh_model is not None
            else []
        )

    def _push(self, do, undo, description=""):
        self._undo_stack.push(Command(do, undo, description))
        self._refresh_structure_models()
        self.undoStateChanged.emit()

    def _refresh_process_flow(self):
        self._process_flow_model.refresh(self.process_flow.steps)
        self._process_errors = validate_flow(self.process_flow)
        self.structureChanged.emit()

    def _push_process(self, do, undo, description=""):
        # Twin of _push, used only by process-flow mutations: refreshes
        # ProcessStepListModel/processValidationErrors instead of the
        # structure models. Keeps _push's existing structure-only
        # contract untouched for every v0.2 call site.
        self._undo_stack.push(Command(do, undo, description))
        self._refresh_process_flow()
        self.undoStateChanged.emit()

    @Slot(object, object, str)
    def adoptStructure(self, structure, mesh_model, label):
        """Adopt an externally built (StructureModel, MeshModel) pair --
        e.g. from a Device Builder template -- into the existing
        Structure workbench: same undo reset, model refresh and console
        trail as loadStructureExample."""
        self.structure, self.mesh_model = structure, mesh_model
        self._undo_stack = UndoStack()
        self._refresh_structure_models()
        self.undoStateChanged.emit()
        self.consoleModel.append(
            f"Built device from template '{label}' -- edit it in the "
            "Structure workbench.")

    @Slot(str)
    def loadStructureExample(self, name):
        builder = examples.STRUCTURE_EXAMPLES.get(name)
        if builder is None:
            self.errorRaised.emit(f"Unknown structure example '{name}'", "")
            return
        self.structure, self.mesh_model = builder()
        self._undo_stack = UndoStack()
        self._refresh_structure_models()
        self.undoStateChanged.emit()
        self.consoleModel.append(f"Loaded structure example '{name}'.")

    @Slot(str, float, float, float, float, float)
    def addRegion(self, name, x_min, x_max, y_min, y_max, net_doping_cm3):
        import uuid
        region = RegionSpec(uuid.uuid4().hex[:8], name, x_min, x_max, y_min, y_max, net_doping_cm3)
        self._push(lambda: self.structure.add_region(region),
                  lambda: self.structure.remove_region(region.id),
                  f"add region {name}")

    @Slot(str)
    def removeRegion(self, region_id):
        region = self.structure.find_region(region_id)
        if region is None:
            return
        self._push(lambda: self.structure.remove_region(region_id),
                  lambda: self.structure.add_region(region),
                  f"remove region {region.name}")

    @Slot(str, str)
    def renameRegion(self, region_id, new_name):
        region = self.structure.find_region(region_id)
        if region is None:
            return
        old_name = region.name
        self._push(lambda: setattr(region, "name", new_name),
                  lambda: setattr(region, "name", old_name),
                  f"rename region to {new_name}")

    @Slot(str, float, float, float, float)
    def setRegionBounds(self, region_id, x_min, x_max, y_min, y_max):
        region = self.structure.find_region(region_id)
        if region is None:
            return
        old = (region.x_min, region.x_max, region.y_min, region.y_max)
        new = (x_min, x_max, y_min, y_max)
        def apply(vals):
            region.x_min, region.x_max, region.y_min, region.y_max = vals
        self._push(lambda: apply(new), lambda: apply(old), "resize region")

    @Slot(str, float)
    def setRegionDoping(self, region_id, net_doping_cm3):
        region = self.structure.find_region(region_id)
        if region is None:
            return
        if not math.isfinite(net_doping_cm3):
            self.errorRaised.emit("Invalid doping value",
                                  "Doping must be a finite number.")
            return
        old = region.net_doping_cm3
        self._push(lambda: setattr(region, "net_doping_cm3", net_doping_cm3),
                  lambda: setattr(region, "net_doping_cm3", old),
                  "set region doping")

    @Slot(str, str, float, float, float, float, str)
    def setRegionDopingProfile(self, region_id, kind, peak_cm3, sigma_y,
                              sigma_lat, edge_x, high_side):
        """GUI README "per-region doping profiles" item: "uniform" (the
        existing net_doping_cm3 fill, untouched) or "gaussian_erfc"
        (mosfet_doping()'s own Gaussian-in-depth x erfc-lateral-rolloff
        shape, see structure_model.rasterize_doping). QML always passes
        all five profile fields (0.0/"left" when kind == "uniform" and
        they don't apply) -- same positional-args convention as
        setRegionBounds, validated here rather than only inside
        rasterize_doping so a bad edit is rejected at entry, not at the
        next solve."""
        region = self.structure.find_region(region_id)
        if region is None:
            return
        if kind not in ("uniform", "gaussian_erfc"):
            self.errorRaised.emit("Invalid doping profile",
                                  f"Unknown profile kind '{kind}'.")
            return
        if kind == "gaussian_erfc":
            if not all(math.isfinite(v) for v in
                      (peak_cm3, sigma_y, sigma_lat, edge_x)):
                self.errorRaised.emit(
                    "Invalid doping profile",
                    "Peak, sigma_y, sigma_lat and edge_x must be finite.")
                return
            if sigma_y <= 0.0 or sigma_lat <= 0.0:
                self.errorRaised.emit(
                    "Invalid doping profile",
                    "sigma_y and sigma_lat must be positive.")
                return
            if high_side not in ("left", "right"):
                self.errorRaised.emit(
                    "Invalid doping profile",
                    "high_side must be 'left' or 'right'.")
                return
        old = (region.doping_profile, region.profile_peak_cm3,
              region.profile_sigma_y, region.profile_sigma_lat,
              region.profile_edge_x, region.profile_high_side)
        new = (kind, peak_cm3, sigma_y, sigma_lat, edge_x, high_side)

        def apply(vals):
            (region.doping_profile, region.profile_peak_cm3,
             region.profile_sigma_y, region.profile_sigma_lat,
             region.profile_edge_x, region.profile_high_side) = vals
        self._push(lambda: apply(new), lambda: apply(old),
                  "set region doping profile")

    @Slot(str, str)
    def setRegionMaterial(self, region_id, material):
        """M11-S5: per-region material editing (MaterialLibrary key,
        case-insensitive on resolve; stored verbatim)."""
        region = self.structure.find_region(region_id)
        if region is None:
            return
        from workbench.core.materials import LIBRARY
        key = next((n for n in LIBRARY.names()
                    if n.upper() == str(material).upper()), None)
        if key is None:
            raise KeyError(
                f"unknown material '{material}' (available: "
                f"{', '.join(LIBRARY.names())})")
        material = key                          # canonical key stored
        old = region.material
        def apply(m):
            region.material = m
        self._push(lambda: apply(material),
                   lambda: apply(old),
                   f"set region material to {material}")

    @Slot(str, int)
    def moveRegion(self, region_id, offset):
        region = self.structure.find_region(region_id)
        if region is None:
            return
        # Resolve the exact, already-clamped index delta up front rather
        # than pushing the raw requested offset: StructureModel.move_region
        # clamps at the list ends, so undoing a large offset that got
        # clamped (e.g. offset=-5 in a 3-region list) by negating the
        # RAW offset would overshoot past the original position. Moving
        # by the actual delta on both do and undo is exactly reversible
        # regardless of how large the requested offset was.
        old_idx = self.structure.regions.index(region)
        new_idx = max(0, min(len(self.structure.regions) - 1, old_idx + offset))
        if new_idx == old_idx:
            return
        delta = new_idx - old_idx
        self._push(lambda: self.structure.move_region(region_id, delta),
                  lambda: self.structure.move_region(region_id, -delta),
                  f"reorder region {region.name}")

    @Slot(str, float)
    def setContactVoltage(self, contact_id, V):
        contact = self.structure.find_contact(contact_id)
        if contact is None:
            return
        if not math.isfinite(V):
            self.errorRaised.emit("Invalid contact voltage",
                                  "Voltage must be a finite number.")
            return
        old = contact.V
        self._push(lambda: setattr(contact, "V", V),
                  lambda: setattr(contact, "V", old), "set contact voltage")

    @Slot(str, float)
    def setGateVoltage(self, gate_id, V):
        gate = self.structure.find_gate(gate_id)
        if gate is None:
            return
        if not math.isfinite(V):
            self.errorRaised.emit("Invalid gate voltage",
                                  "Voltage must be a finite number.")
            return
        old = gate.V
        self._push(lambda: setattr(gate, "V", V),
                  lambda: setattr(gate, "V", old), "set gate voltage")

    @Slot(str, float)
    def setGateToxCm(self, gate_id, tox_cm):
        gate = self.structure.find_gate(gate_id)
        if gate is None:
            return
        if not math.isfinite(tox_cm):
            self.errorRaised.emit("Invalid gate oxide thickness",
                                  "Thickness must be a finite number.")
            return
        old = gate.tox_cm
        self._push(lambda: setattr(gate, "tox_cm", tox_cm),
                  lambda: setattr(gate, "tox_cm", old), "set gate tox")

    @Slot(str, str)
    def setGateType(self, gate_id, gate_type):
        gate = self.structure.find_gate(gate_id)
        if gate is None:
            return
        old = gate.gate_type
        self._push(lambda: setattr(gate, "gate_type", gate_type),
                  lambda: setattr(gate, "gate_type", old), "set gate type")

    @Slot(str, str, float)
    def setGateVfbMode(self, gate_id, mode, manual_value):
        gate = self.structure.find_gate(gate_id)
        if gate is None:
            return
        if mode == "manual" and not math.isfinite(manual_value):
            self.errorRaised.emit("Invalid Vfb value",
                                  "Manual flatband voltage must be a finite number.")
            return
        old = (gate.vfb_mode, gate.vfb_manual)
        new = (mode, manual_value if mode == "manual" else None)
        def apply(vals):
            gate.vfb_mode, gate.vfb_manual = vals
        self._push(lambda: apply(new), lambda: apply(old), "set gate Vfb mode")

    @Slot(int, int)
    def setMeshNxNy(self, nx, ny):
        old = (self.mesh_model.nx, self.mesh_model.ny)
        def apply(vals):
            self.mesh_model.nx, self.mesh_model.ny = vals
        self._push(lambda: apply((nx, ny)), lambda: apply(old), "set mesh Nx/Ny")

    @Slot(str)
    def setMeshGrading(self, grading):
        old = self.mesh_model.grading
        self._push(lambda: setattr(self.mesh_model, "grading", grading),
                  lambda: setattr(self.mesh_model, "grading", old), "set mesh grading")

    @Slot()
    def undo(self):
        self._undo_stack.undo()
        # One shared UndoStack now carries both structure and
        # process-flow commands (Task 7), so a generic undo() must
        # refresh both projections -- _refresh_structure_models() is a
        # no-op when no structure is loaded, and _refresh_process_flow()
        # is a no-op-ish refresh of an empty ProcessFlow when no process
        # steps exist, so this is behavior-preserving for pure v0.2
        # structure sessions.
        self._refresh_structure_models()
        self._refresh_process_flow()
        self.undoStateChanged.emit()

    @Slot()
    def redo(self):
        self._undo_stack.redo()
        self._refresh_structure_models()
        self._refresh_process_flow()
        self.undoStateChanged.emit()

    @Slot(result=bool)
    def runStructureValidation(self):
        self._run_validation_quiet()
        self.structureChanged.emit()
        return not self._structure_errors

    # -- process flow (v0.3) ------------------------------------------
    @Slot(str, str, dict)
    def addProcessStep(self, operation, name, parameters):
        import uuid
        step = ProcessStep(id=uuid.uuid4().hex[:8], name=name, operation=operation,
                           parameters=dict(parameters))
        self._push_process(lambda: self.process_flow.add_step(step),
                           lambda: self.process_flow.remove_step(step.id),
                           f"add process step {name}")

    @Slot(str)
    def removeProcessStep(self, step_id):
        step = self.process_flow.find_step(step_id)
        if step is None:
            return
        self._push_process(lambda: self.process_flow.remove_step(step_id),
                           lambda: self.process_flow.add_step(step),
                           f"remove process step {step.name}")

    @Slot(str, int)
    def moveProcessStep(self, step_id, offset):
        step = self.process_flow.find_step(step_id)
        if step is None:
            return
        # Same clamped-delta resolution as moveRegion: resolve the
        # actual, already-clamped index delta up front rather than
        # pushing the raw requested offset, so undo (negating the
        # resolved delta) is exactly reversible even when the requested
        # offset would have overshot the list ends.
        old_idx = self.process_flow.steps.index(step)
        new_idx = max(0, min(len(self.process_flow.steps) - 1, old_idx + offset))
        if new_idx == old_idx:
            return
        delta = new_idx - old_idx
        self._push_process(lambda: self.process_flow.move_step(step_id, delta),
                           lambda: self.process_flow.move_step(step_id, -delta),
                           f"reorder process step {step.name}")

    @Slot(str)
    def duplicateProcessStep(self, step_id):
        original = self.process_flow.find_step(step_id)
        if original is None:
            return
        new_id_holder = {}
        def do():
            dup = self.process_flow.duplicate_step(step_id)
            new_id_holder["id"] = dup.id
        def undo():
            self.process_flow.remove_step(new_id_holder["id"])
        self._push_process(do, undo, f"duplicate process step {original.name}")

    @Slot(str, bool)
    def setProcessStepEnabled(self, step_id, enabled):
        step = self.process_flow.find_step(step_id)
        if step is None:
            return
        old = step.enabled
        self._push_process(lambda: setattr(step, "enabled", enabled),
                           lambda: setattr(step, "enabled", old), "toggle process step")

    @Slot(str, str)
    def renameProcessStep(self, step_id, new_name):
        step = self.process_flow.find_step(step_id)
        if step is None:
            return
        old_name = step.name
        self._push_process(lambda: setattr(step, "name", new_name),
                           lambda: setattr(step, "name", old_name),
                           f"rename process step to {new_name}")

    @Slot(str, dict)
    def setProcessStepParameters(self, step_id, parameters):
        step = self.process_flow.find_step(step_id)
        if step is None:
            return
        if _has_non_finite_leaf(parameters):
            self.errorRaised.emit(
                "Invalid step parameter",
                "A parameter value is not a finite number (empty or "
                "non-numeric text field?). The edit was discarded.")
            return
        old = dict(step.parameters)
        new = dict(parameters)
        def apply(vals):
            step.parameters.clear()
            step.parameters.update(vals)
        self._push_process(lambda: apply(new), lambda: apply(old),
                           "edit process step parameters")

    @Slot(str, result=str)
    def processStepOperation(self, step_id):
        step = self.process_flow.find_step(step_id)
        return step.operation if step is not None else ""

    @Slot(str, result="QVariant")
    def processStepParameters(self, step_id):
        step = self.process_flow.find_step(step_id)
        return dict(step.parameters) if step is not None else {}

    @Slot(str, result="QVariant")
    def processDerivedQuantities(self, step_id):
        """Design section 19: the Derived Quantities panel's data source.
        Reads a single process checkpoint (ProcessResultStore.state_for)
        and computes a small set of GUI-facing derived values -- junction
        depth, per-species peak concentration/depth/dose, sheet
        resistance, and (for oxidize steps) oxide thickness / silicon
        consumed. Keys are named with explicit unit suffixes
        (junction_depth_um, peak_concentration_cm3_<species>, ...) so
        DerivedQuantitiesPanel.qml can format each one without guessing
        units from a bare key name.
        """
        if self._process_result is None:
            return {}
        state = self._process_result.state_for(step_id)
        from ..services.process_derived import junction_depth_um, sheet_resistance
        x, net, ntotal = state["x"], state["net_doping"], state["ntotal"]
        result = {
            "junction_depth_um": junction_depth_um(x, net),
            # Task 15 (real-display verification) finding: sheet_resistance()
            # returns a bare numpy.float64 (from 1.0 / np.trapezoid(...)).
            # Left unconverted, PySide6's QVariant marshaling of a
            # numpy.float64 across this Slot(result="QVariant") boundary
            # does NOT produce a JS number -- confirmed with an isolated
            # repro: QML saw typeof "object" whose string/numeric coercion
            # is literally -1, so DerivedQuantitiesPanel.qml's
            # Math.round(value) rendered "-1 Ω/□" for every step,
            # regardless of the real (positive, correct) computed
            # resistance. Every other value in this dict is already
            # explicitly cast with float(...) for exactly this reason;
            # sheet_resistance_ohm_sq was the one omission.
            "sheet_resistance_ohm_sq": float(sheet_resistance(x, net, ntotal)),
        }
        for species, C in state["species_profiles"].items():
            peak_idx = int(C.argmax())
            result[f"peak_concentration_cm3_{species}"] = float(C[peak_idx])
            result[f"peak_depth_um_{species}"] = float(x[peak_idx]) * 1e4
            result[f"implanted_dose_cm2_{species}"] = float(np.trapezoid(C, x))
        if "oxide_thickness_um" in state["bookkeeping"]:
            result["oxide_thickness_um"] = state["bookkeeping"]["oxide_thickness_um"]
            result["silicon_consumed_um"] = state["bookkeeping"]["silicon_consumed_um"]
        return result

    @Slot(result=bool)
    def runProcessValidation(self):
        self._process_errors = validate_flow(self.process_flow)
        self.structureChanged.emit()
        return not self._process_errors

    @Slot()
    def runProcess(self):
        if not self.runProcessValidation():
            self.errorRaised.emit("Cannot run an invalid process flow",
                                  "\n".join(self.processValidationErrors))
            return
        if self._busy:
            return
        # Final-review finding: a previous run's result must not be
        # presented as "current" once a new run starts. Each run now
        # writes its checkpoints into its own isolated per-run directory
        # (process_runner.py's run_flow()), so the OLD result is not
        # literally corrupted by a new run -- but showing it while a
        # fresh run is in flight (or after that fresh run fails/is
        # canceled) would silently look like results for the flow as it
        # exists right now, which it is not.
        self._process_result = None
        self.processResultChanged.emit()
        self.consoleModel.append("Starting process flow...")
        self._set_status("Running process flow...")
        self._set_busy(True)
        try:
            self._process_runner.start(self.process_flow)
        except Exception as exc:
            self._set_busy(False)
            self._set_status("Failed to start")
            self.errorRaised.emit("Could not start the process flow", str(exc))

    @Slot()
    def cancelProcess(self):
        if self._process_runner.running:
            self.consoleModel.append("Cancelling process flow...")
            self._process_runner.cancel()

    @Slot(result=bool)
    def buildDeviceFromProcess(self):
        """Design section 14: the final process checkpoint becomes a 1D
        DeviceSpec, with ntotal always populated -- unlike other DeviceSpec
        producers (e.g. loadExample), which may leave it None, a
        process-generated spec's ntotal is the actual total ionized
        impurity concentration tracked through the whole flow, and it
        would be physically wrong to drop it here.
        """
        if self._process_result is None:
            self.errorRaised.emit("No process result to hand off",
                                  "Run the process flow first.")
            return False
        final_id = self._process_result.step_ids()[-1]
        state = self._process_result.state_for(final_id)
        x = state["x"]
        n = len(x)
        mesh = MeshSpec(dimensionality=1, axes={"x": x.tolist()})
        doping = DopingSpec(kind="array", values=state["net_doping"].tolist(),
                            ntotal=state["ntotal"].tolist())
        contacts = [
            ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=self._left_contact_v),
            ContactSpec(name="right", kind="ohmic", nodes={"i": [n - 1]},
                       V=self._right_contact_v),
        ]
        self.spec = DeviceSpec(mesh=mesh, doping=doping, contacts=contacts,
                               bias={"left": self._left_contact_v,
                                    "right": self._right_contact_v})
        # Process handoff takes priority over any stale v0.2 structure:
        # run() checks self.structure first, so it must be cleared here
        # (along with mesh_model, its QML-visible counterpart) for the
        # newly-built spec to actually be used on the next Run.
        #
        # This is an intentional, one-way precedence switch (design
        # section 14's Process-handoff-takes-priority rule), not a bug --
        # but it IS destructive and has no undo: unlike every other
        # structure/mesh mutation in this file, it does not go through
        # _push()/the UndoStack, so a cleared 2D structure cannot be
        # recovered by Ctrl+Z, and a subsequent saveProject() will write
        # "structure": null over whatever 2D work existed before this
        # call. Final-review finding: this used to clear both attributes
        # without emitting structureChanged at all, so QML bound to
        # structureForQml/meshModelForQml (and anything reading
        # structureMaterial/meshInfo) kept showing stale pre-clear data
        # until some unrelated signal happened to fire. Emitting it here
        # closes that gap; full undo-tracking of a "handoff mode switch"
        # would be a larger redesign (treating structure/process as two
        # mutually exclusive modes with their own undo scoping) not
        # warranted for this fix pass.
        self.structure = None
        self.mesh_model = None
        self.structureChanged.emit()
        self.consoleModel.append("Built a 1D device spec from the process flow.")
        return True

    def _on_process_finished(self, manifest_path):
        import json
        self._set_busy(False)
        with open(manifest_path) as fh:
            manifest = json.load(fh)
        self._process_result = ProcessResultStore(manifest)
        self.consoleModel.append("Process flow finished.")
        self._set_status("Process flow complete")
        self.processResultChanged.emit()

    def _on_process_failed(self, summary, details):
        self._set_busy(False)
        # Belt-and-braces alongside runProcess()'s own clear-on-start:
        # a failed run must not leave a (now out-of-sync-with-the-current-
        # flow) previous result reachable via hasProcessResult/
        # _process_result. Already None by the time this fires in
        # practice (runProcess() clears it before starting), but this
        # keeps the handler correct on its own even if that ordering ever
        # changes.
        self._process_result = None
        self.processResultChanged.emit()
        self._set_status("Process flow failed")
        self.consoleModel.append(f"ERROR: {summary}")
        self.errorRaised.emit(summary, details)

    def _on_process_canceled(self):
        # Task 15 (real-display verification) finding: this handler did not
        # exist and self._process_runner.canceled was never connected to
        # anything, unlike self._runner.canceled -> self._on_canceled for
        # the device-solve path. Canceling a running process flow therefore
        # left self._busy stuck True forever -- Run stayed disabled and the
        # BusyIndicator/Stop button never cleared, with no console message
        # explaining why. Mirrors _on_canceled() above.
        self._set_busy(False)
        # Same belt-and-braces clear as _on_process_failed above.
        self._process_result = None
        self.processResultChanged.emit()
        self._set_status("Process flow canceled")
        self.consoleModel.append("Process flow canceled -- no results were kept.")

    @Slot(str, str)
    def saveProject(self, path, name):
        path = self._to_local_path(path)
        # Task 9: structure and process flow are independently optional.
        # Only validate whichever piece is actually present -- a
        # process-only project (self.structure is None) or a
        # structure-only project (no process steps) must be saveable
        # without tripping validation for the piece that was never
        # loaded/authored.
        if self.structure is not None and not self.runStructureValidation():
            self.errorRaised.emit("Cannot save an invalid structure",
                                  "\n".join(self.structureValidationErrors))
            return
        if self.process_flow.steps and not self.runProcessValidation():
            self.errorRaised.emit("Cannot save an invalid process flow",
                                  "\n".join(self.processValidationErrors))
            return
        # A session whose only device is a built-in example (the raw v0.1
        # spec) cannot be represented in a project file: the schema stores
        # Structure/Process workbench state plus the armed sweep, never a
        # DeviceSpec.  Save anyway -- the sweep configuration alone is
        # still worth keeping -- but say so loudly instead of letting the
        # user discover an empty project after reopening the file.
        if self.structure is None and self.spec is not None:
            self.errorRaised.emit(
                "This project cannot store the device itself",
                "The current device came from a built-in example (or a raw "
                "v0.1 device spec), which project files do not embed: they "
                "store the Structure/Process workbench and the voltage-sweep "
                "settings only.\n\nThe saved file will contain just the "
                "sweep configuration; reopening it will NOT restore this "
                "device.")
        save_project(path, name, self.structure, self.mesh_model,
                     self.process_flow, self._sweep_config,
                     self.lab.model_config)
        self._undo_stack.mark_clean()
        self.undoStateChanged.emit()
        self.consoleModel.append(f"Saved project to {path}.")

    @Slot(str)
    def loadProject(self, path):
        path = self._to_local_path(path)
        try:
            name, structure, mesh_model, process_flow, sweep, model_config = \
                load_project(path)
        except Exception as exc:
            self.errorRaised.emit("Could not load project", str(exc))
            return
        # structure/mesh_model may legitimately be None (process-only
        # project) -- _refresh_structure_models() already no-ops on a
        # None structure (see its guard above), so it is safe to call
        # unconditionally here, consistent with undo()/redo().
        self.structure, self.mesh_model = structure, mesh_model
        self.process_flow = process_flow
        # v0.4: restore the project's armed sweep (None for v2/v3 files).
        # Never into a project with no device at all (no structure AND an
        # empty process flow): the contact it names cannot exist anywhere
        # yet, so the setting would dangle -- silently re-arming itself
        # against whatever unrelated device happens to be loaded next.
        if structure is None and not process_flow.steps and sweep is not None:
            self._sweep_config = None
            self.consoleModel.append(
                "Dropped the project's voltage-sweep setting: the file "
                "contains no device (no structure, no process flow) to "
                "sweep.")
        else:
            self._sweep_config = sweep
        self.sweepChanged.emit()
        # v5: restore the Physics Lab config the project was saved with.
        # None means either a pre-v5 file (no "models" key at all) or a
        # v5 file explicitly saved with no config -- either way, leave
        # whatever the Physics Lab already has untouched, exactly the
        # (only possible) pre-v5 behavior, so old projects keep loading
        # byte-identically.
        if model_config is not None:
            self.lab.setModelConfig(model_config)
        # A project file never contains results: whatever was solved in
        # this session belongs to the PREVIOUS project and must not stay
        # on show as if it belonged to the one just loaded.
        self._store = None
        # Final review I-2: same for a stale device spec -- otherwise
        # Run would silently re-solve the PREVIOUS project's device
        # (with the newly-restored sweep config validated against ITS
        # contacts) whenever the loaded project defines no structure.
        self.spec = None
        self.resultChanged.emit()
        self._undo_stack = UndoStack()
        self._undo_stack.mark_clean()
        self._refresh_structure_models()
        self._refresh_process_flow()
        self.undoStateChanged.emit()
        self.consoleModel.append(f"Loaded project '{name}' from {path}.")

    # -- actions ------------------------------------------------------
    @Slot(str)
    def loadExample(self, name):
        try:
            self.spec = examples.EXAMPLES[name]()
        except Exception as exc:
            self.errorRaised.emit(f"Could not load example '{name}'", str(exc))
            return
        # A previously-loaded v0.2 structure must not silently win over
        # this v0.1 spec in run() (see run()'s structure-takes-priority
        # rule below).
        self.structure = None
        self.mesh_model = None
        self._store = SpecResultStore(self.spec)
        self._current_field = "doping"
        self.consoleModel.append(f"Loaded example '{name}'.")
        self._set_status(f"Loaded '{name}' -- not yet solved")
        # Final review I-1: the spec change alters sweepContactNames (and
        # structureForQml consumers); without this signal the Sweep
        # panel's contact combo stayed empty after loadExample.
        self.structureChanged.emit()
        self.resultChanged.emit()
        self.fieldChanged.emit()
        self.selectNode("structure")

    @Slot()
    def run(self):
        # A loaded StructureModel takes priority over a v0.1 spec: it
        # reflects whatever the user most recently built/edited in the
        # Structure/Mesh workbench. Convert it fresh on every Run (the
        # structure may have changed since the last solve) rather than
        # caching a DeviceSpec anywhere.
        if self.structure is not None:
            if not self.runStructureValidation():
                self.errorRaised.emit("Cannot run an invalid structure",
                                      "\n".join(self.structureValidationErrors))
                return
            try:
                self.spec = self.structure.to_device_spec(self.mesh_model)
            except Exception as exc:
                self.errorRaised.emit(
                    "Could not build a solver job from the structure", str(exc))
                return
        if self.spec is None:
            self.errorRaised.emit("Nothing to run", "Load an example first.")
            return
        if self._busy:
            return
        # v0.4: attach the CURRENT sweep config (None included) so a
        # previously-run sweep can never linger on the spec after
        # clearSweepConfig().  Validate BEFORE starting the subprocess --
        # an unexecutable sweep should be an immediate, actionable error,
        # not a failed job.
        if self._sweep_config is not None:
            try:
                self._sweep_config.validate([c.name for c in self.spec.contacts])
            except ValueError as exc:
                # Deliberately NOT the arm-time summary ("Invalid sweep
                # configuration"): this failure means the DEVICE changed
                # under an armed sweep (e.g. the contact no longer
                # exists), not that the user just typed bad values.
                # SweepPanel keys its "arm rejected" note off the arm-time
                # summary alone and must stay silent here.
                self.errorRaised.emit(
                    "Sweep cannot run on this device", str(exc))
                return
        # M17 phase 3: same pre-flight validation for an armed
        # transient config, plus the mutual-exclusion check a sweep and
        # a transient run can never both attach to the same spec --
        # _solve_all resolves that deterministically (transient wins)
        # but arming both is a user-facing mistake, not a state worth
        # silently picking a winner for.
        if self._transient_config is not None:
            try:
                self._transient_config.validate(
                    [c.name for c in self.spec.contacts])
            except ValueError as exc:
                self.errorRaised.emit(
                    "Transient run cannot run on this device", str(exc))
                return
        # M18 Phase 4: same pre-flight validation for an armed AC
        # config, plus extending the sweep/transient mutual-exclusion
        # check to a 3-way one -- at most ONE of the three may be
        # armed on a single Run.
        if self._ac_config is not None:
            try:
                self._ac_config.validate([c.name for c in self.spec.contacts])
            except ValueError as exc:
                self.errorRaised.emit(
                    "AC analysis cannot run on this device", str(exc))
                return
        armed = sum(cfg is not None for cfg in
                    (self._sweep_config, self._transient_config, self._ac_config))
        if armed > 1:
            self.errorRaised.emit(
                "Cannot run more than one of Sweep/Transient/AC together",
                "Clear all but one of the armed configurations first.")
            return
        # GUI-IMPROVEMENT-PLAN.md Phase 1c: "Equilibrium only" sets
        # spec.bias = None instead of the usual contact-voltage dict --
        # solver_runner.py's _solve_all() already skips solve_bias
        # entirely whenever spec.bias is None (test_solver_runner.py's
        # test_equilibrium_only_when_bias_is_none exercises exactly this
        # path). A sweep always overrides the bias branch regardless of
        # spec.bias (_solve_all checks spec.sweep FIRST), so the two are
        # mutually exclusive -- catch that here with an actionable error
        # rather than letting it reach solve_bias inside the sweep ramp.
        if self.lab.equilibrium_only and self._sweep_config is not None:
            self.errorRaised.emit(
                "Cannot run equilibrium-only with a sweep armed",
                "Clear the voltage sweep configuration first, or turn "
                "off 'Equilibrium only' in the Physics Lab.")
            return
        self.spec.sweep = self._sweep_config
        self.spec.transient = self._transient_config
        if self.lab.equilibrium_only:
            self.spec.bias = None
        # The Lab's validated catalog config is what executes; the M2
        # RunRecord stamps it, so every run proves which physics ran.
        self.spec.models = dict(self.lab.model_config)
        # v0.6 Phase 2c: apply the selected backend. Defense in depth --
        # the QML selector should already prevent choosing an
        # incompatible backend (backendOptionsForQml uses this SAME
        # check), but re-check here too in case the spec changed after
        # the backend was picked (e.g. picked "devsim" on a 1D device,
        # then a process re-run or structure edit changed dimensionality
        # without the selector being touched again).
        if self._backend != "pytcad":
            try:
                from workbench.solvers.devsim_backend import check_devsim_compatible
                check_devsim_compatible(self.spec)
            except Exception as exc:
                self.errorRaised.emit(
                    f"Cannot run with backend '{self._backend}'", str(exc))
                return
        self.spec.backend = self._backend
        # v0.6 Phase 2d: engine selection only applies to the pytcad
        # backend's own linear-solve path (solver_runner.run_job) --
        # devsim has no such concept, so a stray non-"auto" engine left
        # selected from a prior pytcad run must not leak into a devsim
        # job (harmless either way, since devsim_backend.run() never
        # reads spec.engine, but explicit is safer than relying on that).
        self.spec.engine = self._engine if self._backend == "pytcad" else "auto"
        # Final review I-3: a fresh run invalidates whatever is on show.
        # Mirrors runProcess()'s clear-on-start: during a long sweep, the
        # previous run's curves must not sit there looking current.
        self._store = None
        self.resultChanged.emit()
        self.consoleModel.append("Starting solve...")
        self._set_status("Solving...")
        self._set_busy(True)
        # M9: remember exactly what this Run solved so runModelComparison()
        # can re-solve the SAME device with every model off.
        self._last_run_spec = self.spec
        try:
            self._runner.start(self.spec)
        except Exception as exc:
            self._set_busy(False)
            self._set_status("Failed to start")
            self.errorRaised.emit("Could not start the solver", str(exc))

    @Slot()
    def cancel(self):
        if self._busy:
            self.consoleModel.append("Cancelling...")
            self._runner.cancel()

    # -- M9: model on/off comparison runs ------------------------------
    @Property(bool, notify=comparisonChanged)
    def hasComparison(self):
        return self._comparison_store is not None

    @Property(object, notify=comparisonChanged)
    def comparisonSweepForQml(self):
        """The all-models-OFF run's sweep (or None), handed opaquely to
        MplCanvasItem.setComparisonSource() -- same contract as
        sweepResultForQml."""
        if self._comparison_store is None:
            return None
        try:
            return (self._comparison_store.sweep_result()
                    if self._comparison_store.has_sweep() else None)
        except Exception:
            return None

    @Property(str, notify=comparisonChanged)
    def comparisonLabelForQml(self):
        """v0.6 Phase 2d: which comparison produced the current overlay
        -- "all models off" (M9) or a backend id -- for the dashed
        curve's legend label."""
        return self._comparison_label

    @Slot()
    def runModelComparison(self):
        """Re-solve the last-run device with EVERY catalog model
        disabled, into a separate result store.  Requires a completed
        Run (the spec is reused verbatim, only `models` changes) and a
        free runner -- never races the primary or process runners."""
        if self._last_run_spec is None:
            self.errorRaised.emit(
                "Nothing to compare",
                "Run the device once; the comparison re-solves that "
                "exact device with every model off.")
            return
        if self._busy or self._comparison_runner.running:
            return
        from workbench.core.catalog import ModelCatalog
        off = {key: False for key in ModelCatalog.list()}
        import copy
        spec_off = copy.deepcopy(self._last_run_spec)
        spec_off.sweep = copy.deepcopy(self._last_run_spec.sweep)
        spec_off.models = off
        spec_off.bias = dict(self._last_run_spec.bias or {}) \
            if self._last_run_spec.bias else None
        self.consoleModel.append(
            "Starting comparison solve (all models OFF)...")
        self._comparison_label = "all models off"
        try:
            self._comparison_runner.start(spec_off)
        except Exception as exc:
            self.errorRaised.emit("Could not start the comparison", str(exc))

    @Slot()
    def runBackendComparison(self):
        """v0.6 Phase 2d: re-solve the last-run device with the OTHER
        backend, into the SAME comparison overlay runModelComparison()
        above uses (one dashed overlay at a time; whichever comparison
        ran most recently). Unlike the models-off comparison, `models`
        is left UNCHANGED -- this compares engines on the SAME physics
        request, not a different one.

        Reuses check_devsim_compatible (the same function
        backendOptionsForQml/run() already check) rather than a
        separate guess at what devsim can solve."""
        if self._last_run_spec is None:
            self.errorRaised.emit(
                "Nothing to compare",
                "Run the device once; the comparison re-solves that "
                "exact device on the other backend.")
            return
        if self._busy or self._comparison_runner.running:
            return
        other = "devsim" if self._last_run_spec.backend == "pytcad" else "pytcad"
        if other == "devsim":
            try:
                from workbench.solvers.devsim_backend import check_devsim_compatible
                check_devsim_compatible(self._last_run_spec)
            except Exception as exc:
                self.errorRaised.emit(
                    "Cannot compare against devsim", str(exc))
                return
        import copy
        spec_other = copy.deepcopy(self._last_run_spec)
        spec_other.backend = other
        self.consoleModel.append(
            f"Starting comparison solve (backend={other})...")
        self._comparison_label = other
        try:
            self._comparison_runner.start(spec_other)
        except Exception as exc:
            self.errorRaised.emit("Could not start the comparison", str(exc))

    @Slot(str)
    def runDeck(self, text):
        """M10: the deck front door.  Translates deck text through
        workbench.workflow into the SAME objects the GUI already edits:
        an adopted Structure-workbench session, contact voltages, and an
        armed sweep.  Never a second simulation path."""
        from workbench.workflow import run_deck_full
        try:
            run = run_deck_full(text)
        except ValueError as exc:
            self.errorRaised.emit("Deck error", str(exc))
            return False
        except Exception as exc:
            self.errorRaised.emit("Could not read the deck", str(exc))
            return False
        from workbench.adapters.spec import structure_from_domain
        try:
            structure, mesh_model = structure_from_domain(run.device)
        except Exception as exc:
            self.errorRaised.emit(
                "Deck device cannot be edited here", str(exc))
            return False
        self.adoptStructure(structure, mesh_model,
                            f"deck: {run.template_id}")
        for c in structure.contacts:
            if c.name in run.bias and c.V != run.bias[c.name]:
                self.setContactVoltage(c.id, run.bias[c.name])
        if run.sweep is not None:
            self.setSweepConfig(run.sweep["contact"], run.sweep["start"],
                                run.sweep["stop"], run.sweep["step"])
        self.consoleModel.append(
            f"Deck loaded: template '{run.template_id}' with "
            f"{len(run.bias)} bias statement(s) and "
            f"{'a' if run.sweep else 'no'} sweep.")
        return True

    def _on_comparison_finished(self, result_path):
        from ..services.result_store import NpzResultStore
        self._comparison_store = NpzResultStore(result_path)
        self.consoleModel.append(
            "Comparison solve finished -- switch to Curves mode to see "
            "the models-off overlay.")
        self.comparisonChanged.emit()

    def _on_comparison_failed(self, summary, details):
        self._comparison_store = None
        self.comparisonChanged.emit()
        self.errorRaised.emit(f"Comparison failed: {summary}", details)

    @Slot(str)
    def setField(self, name):
        if name and name != self._current_field:
            self._current_field = name
            self.fieldChanged.emit()

    @Slot(str)
    def selectNode(self, node_id):
        self._selected = node_id
        self.propertiesModel.setRows(self._properties_for(node_id))

    # -- internals ----------------------------------------------------
    @staticmethod
    def _to_local_path(path):
        # QtQuick.Dialogs' FileDialog hands back a file:// URL string;
        # existing callers (tests, scripts) pass a plain filesystem path.
        # QUrl.toLocalFile() only does something for the former, so both
        # keep working through the same slot.
        if path.startswith("file:"):
            return QUrl(path).toLocalFile()
        return path

    def _sweep_vds(self, sweep):
        """The held-terminal bias magnitude to use as Vds for the Vth
        estimate (final review I-6): the largest |V| among contacts other
        than the swept one.  0.0 when nothing is known."""
        if self.spec is None or self.spec.bias is None:
            return 0.0
        others = [abs(float(v)) for name, v in self.spec.bias.items()
                  if name != sweep.contact]
        return max(others) if others else 0.0

    def _properties_for(self, node_id):
        # The "process" node has its own data source (self.process_flow)
        # and must not be masked by the self.spec is None guard below --
        # self.spec is normally None for a process-only session (no
        # structure loaded, no device solved yet) precisely because
        # nothing has happened on the STRUCTURE/DEVICE side, which says
        # nothing about whether a process flow has been authored. Final-
        # review finding: this branch used to be unreachable in that
        # common case (the self.spec is None early return above fired
        # first) and, even when reached, returned a stale v0.1 placeholder
        # ("Process editing arrives in a later version") predating this
        # entire plan.
        if node_id == "process":
            if not self.process_flow.steps:
                return [("Status", "No process steps yet")]
            rows = [("Steps", str(len(self.process_flow.steps))),
                    ("Enabled steps",
                     str(sum(1 for s in self.process_flow.steps if s.enabled)))]
            errors = validate_flow(self.process_flow)
            rows.append(("Validation", "OK" if not errors else f"{len(errors)} error(s)"))
            rows.append(("Result", "Available" if self.hasProcessResult else "Not run yet"))
            return rows
        if self.spec is None:
            return [("Status", "No project loaded")]
        mesh = self.spec.mesh
        shape = mesh.shape()
        if node_id in ("structure", "device", "project"):
            rows = [("Dimensionality", f"{mesh.dimensionality}D"),
                    ("Nodes", str(int(np.prod(shape)))),
                    ("Material", self.spec.material),
                    ("Temperature", f"{self.spec.T:g} K")]
            rows += [(f"Contact: {c.name}", f"{c.kind}, V = {c.V:g} V")
                     for c in self.spec.contacts]
            return rows
        if node_id == "mesh":
            rows = [("Dimensionality", f"{mesh.dimensionality}D")]
            for name in ("x", "y", "z")[:mesh.dimensionality]:
                axis = np.asarray(mesh.axes[name], dtype=float)
                rows.append((f"N{name}", str(axis.size)))
                rows.append((f"{name} extent",
                             f"{axis.min()*1e4:g} to {axis.max()*1e4:g} um"))
            rows.append(("Total nodes", str(int(np.prod(shape)))))
            # full drift-diffusion carries psi, n and p per node
            rows.append(("DOF (psi,n,p)", str(3 * int(np.prod(shape)))))
            return rows
        if node_id == "results":
            if not self.hasResult:
                return [("Status", "Not solved yet")]
            rows = [("Fields", ", ".join(self._store.available_scalars()))]
            for name in self._store.available_terminals():
                t = self._store.terminal_current(name)
                # never render a current without its unit: it is A/cm in
                # 2D but real A in 3D
                rows.append((f"I({t.name})", f"{t.value:.6g} {t.unit}"))
            # v0.4: sweep-derived readouts (curve statistics only -- see
            # services/sweep_derived.py).  summarize() omits any quantity
            # it cannot derive honestly from converged points.
            if self.hasSweep:
                try:
                    sweep = self._store.sweep_result()
                    stats = sweep_derived.summarize(
                        sweep, vds=self._sweep_vds(sweep))
                except Exception:
                    stats = None
                if stats:
                    rows.append(("Sweep points",
                                 f"{stats['points_converged']} of "
                                 f"{stats['points_total']} converged"))
                    unit = sweep.unit
                    if "current_max" in stats:
                        rows.append((f"Sweep Imax ({sweep.contact})",
                                     f"{stats['current_max']:.4g} {unit}"))
                        rows.append((f"Sweep Imin ({sweep.contact})",
                                     f"{stats['current_min']:.4g} {unit}"))
                    # Final review M-2: Ion/Ioff and a threshold are
                    # transfer-curve (gate-sweep) quantities; presenting
                    # them for an output-characteristic sweep would be
                    # misleading.
                    swept = next((c for c in (self.spec.contacts
                                              if self.spec else [])
                                  if c.name == sweep.contact), None)
                    is_gate = bool(swept and swept.kind == "gate")
                    if is_gate and "on_off_ratio" in stats:
                        rows.append(("Sweep Ion/Ioff",
                                     f"{stats['on_off_ratio']:.3g}"))
                    if is_gate and "threshold_voltage_v" in stats:
                        rows.append(("Sweep Vth (max-gm est.)",
                                     f"{stats['threshold_voltage_v']:.3g} V"))
            return rows
        return [("Selected", node_id)]

    def _on_progress_line(self, line):
        """Sweep-point granularity for the status bar, parsed from the
        runner's own progress markers ("PYTCAD_STAGE=sweep point 3/10").
        Diagnostic only -- results are read from the npz, never this."""
        if not self._busy:
            return
        m = re.search(r"point (\d+)/(\d+)", line)
        if m:
            self._set_status(f"Running voltage sweep... point "
                             f"{m.group(1)}/{m.group(2)}")

    @Slot(result="QVariant")
    def convergenceRecordForQml(self):
        """The last run's RunRecord (or null) for the convergence
        viewport.  Lives here -- not as a generic store accessor --
        because only Qt-annotated slots cross into QML safely."""
        store = self._store
        getter = getattr(store, "run_record", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:
            return None

    def _on_stage(self, stage):
        self._set_status({"equilibrium": "Solving equilibrium...",
                          "bias": "Solving at bias...",
                          "extract": "Extracting results...",
                          # v0.4: solver_runner emits PYTCAD_STAGE=sweep per
                          # point; JobRunner's \w+ regex delivers just
                          # "sweep" (the point counter reaches the console
                          # via progressLine).
                          "sweep": "Running voltage sweep..."}.get(stage, "Solving..."))

    def _on_finished(self, path):
        self._set_busy(False)
        try:
            self._store = NpzResultStore(path)
        except Exception as exc:
            self._set_status("Failed to read results")
            self.errorRaised.emit("Could not read the result file", str(exc))
            return
        names = self._store.available_scalars()
        if self._current_field not in names and names:
            self._current_field = "potential" if "potential" in names else names[0]
            self.fieldChanged.emit()
        self.consoleModel.append("Solve finished.")
        self._set_status("Solve complete")
        self.resultChanged.emit()
        self.selectNode(self._selected)
        # Phase 4: if sweep snapshots are available, update any open
        # 3D viewer so playback controls become active.
        if self._viewer3d_window is not None and self._store.has_sweep_snapshots():
            try:
                self._viewer3d_window.set_sweep_snapshots(
                    self._store.sweep_snapshots())
            except Exception:
                pass

    def _on_failed(self, summary, details):
        self._set_busy(False)
        self._set_status("Simulation failed")
        self.consoleModel.append(f"ERROR: {summary}")
        self.errorRaised.emit(summary, details)

    def _on_canceled(self):
        self._set_busy(False)
        self._set_status("Canceled")
        self.consoleModel.append("Solve canceled -- no results were kept.")
