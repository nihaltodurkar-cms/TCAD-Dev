"""Physics Lab controller (M4): the educational surface over the REAL
pipeline.  This module owns the physics-model configuration students
toggle, the catalog view over ModelCatalog (equations, references,
honest limitations), and read access to the M2 RunRecord's convergence
history.

Deliberately a separate controller from AppController -- the "god
controller" must not grow another domain.  Integration is minimal:
AppController instantiates this and applies `model_config` to the spec
at Run(); defaults equal the wire-format defaults, so untouched runs
are byte-identical to pre-M4 behavior.
"""
from PySide6.QtCore import (
    QAbstractListModel, QModelIndex, QObject, Property, Qt, Signal, Slot,
)

from workbench.core.catalog import ModelCatalog


class CatalogModel(QAbstractListModel):
    """The ModelCatalog as a bindable list: one row per registered
    physics model, carrying its documentation with it."""

    KeyRole = Qt.UserRole + 1
    TitleRole = Qt.UserRole + 2
    EnabledRole = Qt.UserRole + 3
    EquationsRole = Qt.UserRole + 4
    ReferencesRole = Qt.UserRole + 5
    ApplicabilityRole = Qt.UserRole + 6
    LimitationsRole = Qt.UserRole + 7

    def __init__(self, config_getter, parent=None):
        super().__init__(parent)
        self._keys = ModelCatalog.list()
        self._config_getter = config_getter

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._keys)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._keys)):
            return None
        key = self._keys[index.row()]
        info = ModelCatalog.describe(key)
        if role == self.KeyRole:
            return key
        if role == self.TitleRole:
            return info.title
        if role == self.EnabledRole:
            return bool(self._config_getter().get(key, False))
        if role == self.EquationsRole:
            return "\n".join(info.equations)
        if role == self.ReferencesRole:
            return "\n".join(info.references)
        if role == self.ApplicabilityRole:
            return info.applicability
        if role == self.LimitationsRole:
            return info.limitations
        return None

    def roleNames(self):
        return {
            self.KeyRole: b"key", self.TitleRole: b"title",
            self.EnabledRole: b"enabled", self.EquationsRole: b"equations",
            self.ReferencesRole: b"references",
            self.ApplicabilityRole: b"applicability",
            self.LimitationsRole: b"limitations",
        }

    def refresh(self):
        self.beginResetModel()
        self.endResetModel()


class PhysicsLabController(QObject):
    configChanged = Signal()
    selectionChanged = Signal()
    labError = Signal(str)          # concise validation failure text

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app
        # Start from the catalog defaults -- byte-identical to the wire
        # format's own defaults, so M4 changes nothing until toggled.
        self._config = ModelCatalog.default_config()
        self._catalog = CatalogModel(lambda: self._config, self)
        keys = ModelCatalog.list()
        self._selected = keys[0] if keys else None
        # GUI-IMPROVEMENT-PLAN.md Phase 1c: dg is equilibrium-only in the
        # solver (Device1D.solve_bias refuses it unconditionally), but
        # every Run path always attaches a bias dict, so a job with dg=True
        # always crashed on Run -- there was no way to exercise the
        # already-landed M20 physics from the GUI at all. This flag, read
        # by AppController.run(), sets spec.bias = None instead of the
        # usual contact-voltage dict; _solve_all() (solver_runner.py)
        # already skips solve_bias entirely whenever spec.bias is None,
        # so nothing on the solver side needed to change.
        self._equilibrium_only = False

    # -- python-side convenience (tests / future services) ---------------
    @property
    def model_config(self):
        return self._config

    @property
    def equilibrium_only(self):
        return self._equilibrium_only

    # -- QML surface ------------------------------------------------------
    @Property(QObject, constant=True)
    def catalogModel(self):
        return self._catalog

    @Property(dict, notify=configChanged)
    def modelConfig(self):
        return dict(self._config)

    @Property(bool, notify=configChanged)
    def equilibriumOnly(self):
        return self._equilibrium_only

    @Slot(bool)
    def setEquilibriumOnly(self, value):
        self._equilibrium_only = bool(value)
        self.configChanged.emit()

    @Slot(str, bool)
    def setModelEnabled(self, key, value):
        trial = dict(self._config)
        trial[key] = value
        try:
            ModelCatalog.validate(trial)
        except ValueError as exc:
            self.labError.emit(str(exc))
            return
        self._config = trial
        self._catalog.refresh()
        self.configChanged.emit()

    @Slot("QVariant")
    def setModelConfig(self, config):
        """Bulk-restore a model config -- used by project load (M-persist:
        the config a project was saved with). Merges onto the catalog
        defaults rather than replacing wholesale, so a config missing a
        key (an old save, or a future model this build doesn't know
        about being silently dropped) degrades to that key's documented
        default instead of raising or leaving it unset."""
        if not isinstance(config, dict):
            self.labError.emit(
                f"model config must be a dict of {{model_key: bool}}, got "
                f"{type(config).__name__}")
            return
        merged = ModelCatalog.default_config()
        merged.update({k: v for k, v in config.items() if k in merged})
        try:
            ModelCatalog.validate(merged)
        except ValueError as exc:
            self.labError.emit(str(exc))
            return
        self._config = merged
        self._catalog.refresh()
        self.configChanged.emit()

    @Slot(str)
    def selectModel(self, key):
        self._selected = key
        self.selectionChanged.emit()

    @Slot(result="QVariant")
    def selectedDetail(self):
        try:
            info = ModelCatalog.describe(self._selected or "")
        except KeyError:
            return None
        return {
            "key": info.key,
            "title": info.title,
            "equations": list(info.equations),
            "references": list(info.references),
            "applicability": info.applicability,
            "limitations": info.limitations,
            "enabled": bool(self._config.get(info.key, False)),
        }

    # -- run record access (M2 substrate) ----------------------------------
    def _record(self):
        store = self._app.currentStore()
        getter = getattr(store, "run_record", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:
            return None

    @Slot(result=bool)
    def hasRunRecord(self):
        return self._record() is not None

    @Slot(result="QVariant")
    def provenanceRows(self):
        """"What produced this quantity": the last run's record as
        label/value rows for the Properties-style display. Extended in
        Phase 3d to include mesh node count from the store."""
        record = self._record()
        if record is None:
            return None
        rows = [("Backend", record.backend),
                ("Solved at", record.created_utc or "unknown"),
                ("Dimensionality", f"{record.dimensionality}D"),
                ("Material", record.material),
                ("Temperature", f"{record.T:g} K"),
                ("Schema version", str(record.schema_version))]
        # Phase 3d: include mesh node count -- reuse AppController's own
        # meshStats() (Phase 3c) rather than re-deriving node_count from
        # the store's axes a second time.
        stats = self._app.meshStats
        if stats is not None:
            rows.append(("Mesh nodes", str(stats["node_count"])))
        rows += [(f"model: {k}", "on" if v else "off")
                 for k, v in sorted(record.models.items())]
        return [list(map(str, r)) for r in rows]

    @Slot(result="QVariant")
    def convergenceData(self):
        """Per-stage Newton history for plotting: [{stage, iterations,
        residuals}].  residuals is the first recorded metric series with
        non-finite entries as NaN (matplotlib gaps)."""
        record = self._record()
        if record is None or not record.trace:
            return None
        out = []
        for step in record.trace:
            series = next(iter(step.metrics.values()), []) \
                if step.metrics else []
            residuals = [float(v) if v is not None else float("nan")
                         for v in series]
            out.append({"stage": step.stage,
                        "iterations": list(step.iterations),
                        "residuals": residuals})
        return out

    @Slot(result="QVariant")
    def continuationData(self):
        """Per-stage continuation history for the stage table: [{index,
        parameter, nodes, accepted}].  Read-only, no new computation.
        Sourced from RunRecord.continuation_records when available;
        falls back to an empty list."""
        record = self._record()
        if record is None or not record.continuation_records:
            return []
        out = []
        for i, rec in enumerate(record.continuation_records):
            out.append({
                "index": i,
                "parameter": rec.get("parameter", rec.get("V", "")),
                "nodes": rec.get("nodes", ""),
                "accepted": bool(rec.get("accepted", True)),
            })
        return out
