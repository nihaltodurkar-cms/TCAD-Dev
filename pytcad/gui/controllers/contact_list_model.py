"""Read-only QAbstractListModel view onto StructureModel.contacts."""
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


class ContactListModel(QAbstractListModel):
    IdRole = Qt.UserRole + 1
    NameRole = Qt.UserRole + 2
    EdgeRole = Qt.UserRole + 3
    VoltageRole = Qt.UserRole + 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._contacts = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._contacts)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        c = self._contacts[index.row()]
        if role in (Qt.DisplayRole, self.NameRole):
            return c.name
        if role == self.IdRole:
            return c.id
        if role == self.EdgeRole:
            return c.boundary.edge
        if role == self.VoltageRole:
            return c.V
        return None

    def roleNames(self):
        return {self.IdRole: b"contactId", self.NameRole: b"name",
                self.EdgeRole: b"edge", self.VoltageRole: b"voltage"}

    def refresh(self, contacts):
        self.beginResetModel()
        self._contacts = list(contacts)
        self.endResetModel()
