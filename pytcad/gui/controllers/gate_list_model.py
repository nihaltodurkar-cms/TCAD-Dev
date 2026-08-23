"""Read-only QAbstractListModel view onto StructureModel.gates."""
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


class GateListModel(QAbstractListModel):
    IdRole = Qt.UserRole + 1
    NameRole = Qt.UserRole + 2
    ToxRole = Qt.UserRole + 3
    VfbModeRole = Qt.UserRole + 4
    VfbValueRole = Qt.UserRole + 5
    VoltageRole = Qt.UserRole + 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self._gates = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._gates)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        g = self._gates[index.row()]
        if role in (Qt.DisplayRole, self.NameRole):
            return g.name
        if role == self.IdRole:
            return g.id
        if role == self.ToxRole:
            return g.tox_cm
        if role == self.VfbModeRole:
            return g.vfb_mode
        if role == self.VfbValueRole:
            return g.vfb_manual if g.vfb_mode == "manual" else None
        if role == self.VoltageRole:
            return g.V
        return None

    def roleNames(self):
        return {self.IdRole: b"gateId", self.NameRole: b"name", self.ToxRole: b"tox",
                self.VfbModeRole: b"vfbMode", self.VfbValueRole: b"vfbValue",
                self.VoltageRole: b"voltage"}

    def refresh(self, gates):
        self.beginResetModel()
        self._gates = list(gates)
        self.endResetModel()
