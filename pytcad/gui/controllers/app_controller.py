"""Application state and the only object QML needs to talk to.

Everything dimension-specific has already been normalized away by
solver_runner.extract_result(), so nothing here branches on 1D/2D/3D --
it just renders whatever fields and units the ResultStore reports.
"""
import numpy as np
from PySide6.QtCore import QObject, Property, Signal, Slot

from ..services import examples
from ..services.job_runner import JobRunner
from ..services.result_store import NpzResultStore, SpecResultStore
from .console_model import ConsoleModel
from .project_tree_model import ProjectTreeModel
from .properties_model import PropertiesModel


class AppController(QObject):
    statusChanged = Signal()
    busyChanged = Signal()
    resultChanged = Signal()
    fieldChanged = Signal()
    errorRaised = Signal(str, str)          # concise summary, expandable details

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

    # -- actions ------------------------------------------------------
    @Slot(str)
    def loadExample(self, name):
        try:
            self.spec = examples.EXAMPLES[name]()
        except Exception as exc:
            self.errorRaised.emit(f"Could not load example '{name}'", str(exc))
            return
        self._store = SpecResultStore(self.spec)
        self._current_field = "doping"
        self.consoleModel.append(f"Loaded example '{name}'.")
        self._set_status(f"Loaded '{name}' -- not yet solved")
        self.resultChanged.emit()
        self.fieldChanged.emit()
        self.selectNode("structure")

    @Slot()
    def run(self):
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
