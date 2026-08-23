"""Application state and the only object QML needs to talk to.

Everything dimension-specific has already been normalized away by
solver_runner.extract_result(), so nothing here branches on 1D/2D/3D --
it just renders whatever fields and units the ResultStore reports.
"""
import numpy as np
from PySide6.QtCore import QObject, Property, Signal, Slot

from ..services import examples
from ..services.job_runner import JobRunner
from ..services.project_store import load_project, save_project
from ..services.result_store import NpzResultStore, SpecResultStore
from ..services.structure_model import GateModel, RegionSpec
from ..services.undo_stack import Command, UndoStack
from .console_model import ConsoleModel
from .contact_list_model import ContactListModel
from .gate_list_model import GateListModel
from .project_tree_model import ProjectTreeModel
from .properties_model import PropertiesModel
from .region_list_model import RegionListModel


class AppController(QObject):
    statusChanged = Signal()
    busyChanged = Signal()
    resultChanged = Signal()
    fieldChanged = Signal()
    errorRaised = Signal(str, str)          # concise summary, expandable details
    structureChanged = Signal()
    undoStateChanged = Signal()

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

        self._runner = JobRunner(parent=self)
        self._runner.progressLine.connect(self.consoleModel.append)
        self._runner.stageChanged.connect(self._on_stage)
        self._runner.finished.connect(self._on_finished)
        self._runner.failed.connect(self._on_failed)
        self._runner.canceled.connect(self._on_canceled)

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
        return isinstance(self._store, NpzResultStore)

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
        self._region_list_model.refresh(self.structure.regions)
        self._contact_list_model.refresh(self.structure.contacts)
        self._gate_list_model.refresh(self.structure.gates)
        self._run_validation_quiet()
        self.structureChanged.emit()

    def _run_validation_quiet(self):
        self._structure_errors = self.structure.validate(self.mesh_model)

    def _push(self, do, undo, description=""):
        self._undo_stack.push(Command(do, undo, description))
        self._refresh_structure_models()
        self.undoStateChanged.emit()

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
        self._refresh_structure_models()
        self.undoStateChanged.emit()

    @Slot()
    def redo(self):
        self._undo_stack.redo()
        self._refresh_structure_models()
        self.undoStateChanged.emit()

    @Slot(result=bool)
    def runStructureValidation(self):
        self._run_validation_quiet()
        self.structureChanged.emit()
        return not self._structure_errors

    @Slot(str, str)
    def saveProject(self, path, name):
        if not self.runStructureValidation():
            self.errorRaised.emit("Cannot save an invalid structure",
                                  "\n".join(self.structureValidationErrors))
            return
        save_project(path, name, self.structure, self.mesh_model)
        self._undo_stack.mark_clean()
        self.undoStateChanged.emit()
        self.consoleModel.append(f"Saved project to {path}.")

    @Slot(str)
    def loadProject(self, path):
        try:
            name, structure, mesh_model = load_project(path)
        except Exception as exc:
            self.errorRaised.emit("Could not load project", str(exc))
            return
        self.structure, self.mesh_model = structure, mesh_model
        self._undo_stack = UndoStack()
        self._undo_stack.mark_clean()
        self._refresh_structure_models()
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
    def _properties_for(self, node_id):
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
            return rows
        if node_id == "process":
            return [("Status", "Process editing arrives in a later version")]
        return [("Selected", node_id)]

    def _on_stage(self, stage):
        self._set_status({"equilibrium": "Solving equilibrium...",
                          "bias": "Solving at bias...",
                          "extract": "Extracting results..."}.get(stage, "Solving..."))

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
