"""Read-only QAbstractListModel view onto ProcessFlow.steps.
AppController owns mutation (through the undo stack); this model just
mirrors whatever ProcessFlow currently holds, refreshed via refresh().
Mirrors region_list_model.py's exact pattern."""
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


class ProcessStepListModel(QAbstractListModel):
    IdRole = Qt.UserRole + 1
    NameRole = Qt.UserRole + 2
    OperationRole = Qt.UserRole + 3
    EnabledRole = Qt.UserRole + 4
    SummaryRole = Qt.UserRole + 5    # short parameter summary for the list row

    def __init__(self, parent=None):
        super().__init__(parent)
        self._steps = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._steps)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        s = self._steps[index.row()]
        if role in (Qt.DisplayRole, self.NameRole):
            return s.name
        if role == self.IdRole:
            return s.id
        if role == self.OperationRole:
            return s.operation
        if role == self.EnabledRole:
            return s.enabled
        if role == self.SummaryRole:
            return ", ".join(f"{k}={v}" for k, v in list(s.parameters.items())[:2])
        return None

    def roleNames(self):
        return {self.IdRole: b"stepId", self.NameRole: b"name",
                self.OperationRole: b"operation", self.EnabledRole: b"enabled",
                self.SummaryRole: b"summary"}

    def refresh(self, steps):
        self.beginResetModel()
        self._steps = list(steps)
        self.endResetModel()
