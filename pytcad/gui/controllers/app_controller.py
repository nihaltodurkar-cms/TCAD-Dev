"""Application state and the only object QML needs to talk to.

Everything dimension-specific has already been normalized away by
solver_runner.extract_result(), so nothing here branches on 1D/2D/3D --
it just renders whatever fields and units the ResultStore reports.
"""
import numpy as np
from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot

from ..services import examples
from ..services.device_spec import (
    ContactSpec, DeviceSpec, DopingSpec, MeshSpec, SweepSpec,
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


class _ProcessFlowJob:
    """Adapts a ProcessFlow to the `to_json(path)` contract JobRunner.start()
    expects on whatever it is handed (it calls `spec.to_json(job_path)`
    generically -- see job_runner.py). ProcessFlow (Task 3/7) only exposes
    to_dict()/from_dict(), matching process_runner.py's own CLI contract
    (gui/tests/test_process_runner.py writes `flow.to_dict()` by hand), so
    this tiny wrapper is added here rather than growing process_model.py,
    which this task must not touch.
    """
    def __init__(self, flow):
        self._flow = flow

    def to_json(self, path):
        import json
        with open(path, "w") as fh:
            json.dump(self._flow.to_dict(), fh)


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
        self._left_contact_v = 0.0
        self._right_contact_v = 0.0
        # v0.4 voltage sweep applied to the next Run (not undoable: it is
        # run configuration, like field selection -- not device geometry)
        self._sweep_config = None
        # v0.5.0 M4: the Physics Lab owns the model-flag configuration.
        # Its defaults equal the wire-format defaults, so this is
        # invisible until a student toggles something.
        from .lab_controller import PhysicsLabController
        self.lab = PhysicsLabController(self)
        from .builder_controller import BuilderController
        self.builder = BuilderController(self)

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

    @Property(float, notify=processResultChanged)
    def leftContactV(self):
        return self._left_contact_v

    @leftContactV.setter
    def leftContactV(self, value):
        self._left_contact_v = float(value)

    @Property(float, notify=processResultChanged)
    def rightContactV(self):
        return self._right_contact_v

    @rightContactV.setter
    def rightContactV(self, value):
        self._right_contact_v = float(value)

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
        rows = [("Nx", str(nx)), ("Ny", str(ny)),
                ("Total nodes", str(total_nodes)), ("Total cells", str(total_cells)),
                ("Domain width", f"{self.structure.width_cm * 1e4:g} um"),
                ("Domain height", f"{self.structure.height_cm * 1e4:g} um"),
                ("Min spacing (x)", f"{hx.min() * 1e4:.4g} um" if hx.size else "n/a"),
                ("Max spacing (x)", f"{hx.max() * 1e4:.4g} um" if hx.size else "n/a"),
                ("Min spacing (y)", f"{hy.min() * 1e4:.4g} um" if hy.size else "n/a"),
                ("Max spacing (y)", f"{hy.max() * 1e4:.4g} um" if hy.size else "n/a"),
                ("Estimated memory (rough)", f"{est_mb:.1f} MB")]
        if total_nodes > 50_000:
            rows.append(("Warning", "This mesh is large; 2D drift-diffusion may "
                                    "require substantial memory and solve time."))
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
        old = region.net_doping_cm3
        self._push(lambda: setattr(region, "net_doping_cm3", net_doping_cm3),
                  lambda: setattr(region, "net_doping_cm3", old),
                  "set region doping")

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
        old = contact.V
        self._push(lambda: setattr(contact, "V", V),
                  lambda: setattr(contact, "V", old), "set contact voltage")

    @Slot(str, float)
    def setGateVoltage(self, gate_id, V):
        gate = self.structure.find_gate(gate_id)
        if gate is None:
            return
        old = gate.V
        self._push(lambda: setattr(gate, "V", V),
                  lambda: setattr(gate, "V", old), "set gate voltage")

    @Slot(str, float)
    def setGateToxCm(self, gate_id, tox_cm):
        gate = self.structure.find_gate(gate_id)
        if gate is None:
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
            self._process_runner.start(_ProcessFlowJob(self.process_flow))
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
                     self.process_flow, self._sweep_config)
        self._undo_stack.mark_clean()
        self.undoStateChanged.emit()
        self.consoleModel.append(f"Saved project to {path}.")

    @Slot(str)
    def loadProject(self, path):
        path = self._to_local_path(path)
        try:
            name, structure, mesh_model, process_flow, sweep = load_project(path)
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
        self.spec.sweep = self._sweep_config
        # The Lab's validated catalog config is what executes; the M2
        # RunRecord stamps it, so every run proves which physics ran.
        self.spec.models = dict(self.lab.model_config)
        # Final review I-3: a fresh run invalidates whatever is on show.
        # Mirrors runProcess()'s clear-on-start: during a long sweep, the
        # previous run's curves must not sit there looking current.
        self._store = None
        self.resultChanged.emit()
        self.consoleModel.append("Starting solve...")
        self._set_status("Solving...")
        self._set_busy(True)
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

    def _on_failed(self, summary, details):
        self._set_busy(False)
        self._set_status("Simulation failed")
        self.consoleModel.append(f"ERROR: {summary}")
        self.errorRaised.emit(summary, details)

    def _on_canceled(self):
        self._set_busy(False)
        self._set_status("Canceled")
        self.consoleModel.append("Solve canceled -- no results were kept.")
