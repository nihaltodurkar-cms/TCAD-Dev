"""Key/value rows describing whatever is selected in the project tree."""
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


class PropertiesModel(QAbstractListModel):
    KeyRole = Qt.UserRole + 1
    ValueRole = Qt.UserRole + 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        key, value = self._rows[index.row()]
        if role == self.KeyRole:
            return key
        if role in (self.ValueRole, Qt.DisplayRole):
            return value
        return None

    def roleNames(self):
        return {self.KeyRole: b"key", self.ValueRole: b"value"}

    def rows(self):
        return list(self._rows)

    def setRows(self, rows):
        self.beginResetModel()
        self._rows = [(str(k), str(v)) for k, v in rows]
        self.endResetModel()
