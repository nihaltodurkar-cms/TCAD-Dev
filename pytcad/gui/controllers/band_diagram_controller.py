"""Band Diagram Viewer: conduction/valence band edges and quasi-Fermi
levels for the currently-loaded result.

Architecture note: the GUI process never holds a live Device1D -- every
solve runs in a separate subprocess (see job_runner.py's docstring), so
the only object this controller can read from is a NpzResultStore
(gui/services/result_store.py), the same object AppController._store
already becomes after JobRunner.finished (see _on_finished there).
Rather than reconstruct band_diagram() from psi/n/p plus per-node
material arrays in this process, solver_runner.extract_result() calls
the REAL Device1D.band_diagram() once, in the subprocess where the
solved device object actually exists, and stamps the four arrays into
the .npz -- this controller only reads them back.

1D-only: Device2D/Device3D have no band_diagram() method (confirmed by
grep -- a real, separate gap, out of scope for this pass), so
ResultStore.has_band_diagram() is False for every 2D/3D result and the
panel must show an honest "not available" state rather than fabricate
one.

Same ownership pattern as ProbeStationController/CVController: a plain
sub-controller holding the AppController reference, exposed to QML via
a `@Property(QObject, constant=True)` getter (see `bandDiagram` on
AppController).
"""
from PySide6.QtCore import QObject, Property, Signal, Slot


class BandDiagramController(QObject):
    diagramChanged = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app
        self._x = []
        self._ec = []
        self._ev = []
        self._efn = []
        self._efp = []
        self._available = False
        self._reason = "No result loaded yet."
        app.resultChanged.connect(self.refresh)

    @Slot()
    def refresh(self):
        """Re-read band-diagram data from the app's current ResultStore.
        Called on every AppController.resultChanged (a new solve
        finished, or the result was cleared) -- never call
        loadFromResult() directly from QML, this is the entry point."""
        store = self._app.currentStore()
        self.loadFromResult(store)

    def loadFromResult(self, store):
        """Populate from a ResultStore (or None). Honest no-op states:
        no store, a store with no band-diagram data (e.g. 2D/3D, or a
        result predating this feature), or a read error -- all leave
        `available` False with a human-readable `reason` rather than
        raising into QML or silently showing stale data."""
        self._x, self._ec, self._ev, self._efn, self._efp = [], [], [], [], []
        if store is None:
            self._available = False
            self._reason = "No result loaded yet."
        elif not getattr(store, "is_solved_result", lambda: False)():
            self._available = False
            self._reason = "No solved result yet -- run a solve first."
        elif not store.has_band_diagram():
            dim = None
            try:
                dim = store.mesh_axes().dimensionality
            except Exception:
                pass
            if dim in (2, 3):
                self._available = False
                self._reason = (f"Band diagram is not available for {dim}D "
                                f"results yet -- Device{dim}D has no "
                                "band_diagram() method.")
            else:
                self._available = False
                self._reason = "This result carries no band-diagram data."
        else:
            try:
                x, Ec, Ev, EFn, EFp = store.band_diagram()
                self._x = [float(v) for v in x]
                self._ec = [float(v) for v in Ec]
                self._ev = [float(v) for v in Ev]
                self._efn = [float(v) for v in EFn]
                self._efp = [float(v) for v in EFp]
                self._available = True
                self._reason = ""
            except Exception as exc:
                self._available = False
                self._reason = f"Could not read band-diagram data: {exc}"
        self.diagramChanged.emit()

    # -- QML-facing data --------------------------------------------------
    @Property(bool, notify=diagramChanged)
    def available(self):
        return self._available

    @Property(str, notify=diagramChanged)
    def unavailableReason(self):
        return self._reason

    @Property(list, notify=diagramChanged)
    def x(self):
        return list(self._x)

    @Property(list, notify=diagramChanged)
    def ec(self):
        return list(self._ec)

    @Property(list, notify=diagramChanged)
    def ev(self):
        return list(self._ev)

    @Property(list, notify=diagramChanged)
    def efn(self):
        return list(self._efn)

    @Property(list, notify=diagramChanged)
    def efp(self):
        return list(self._efp)
