"""Append-only log lines for the simulation console."""
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

MAX_LINES = 5000      # bound memory on a chatty solve


class ConsoleModel(QAbstractListModel):
    LineRole = Qt.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lines = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._lines)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role in (self.LineRole, Qt.DisplayRole):
            return self._lines[index.row()]
        return None

    def roleNames(self):
        return {self.LineRole: b"line"}

    def append(self, line):
        if len(self._lines) >= MAX_LINES:
            self.beginRemoveRows(QModelIndex(), 0, 0)
            self._lines.pop(0)
            self.endRemoveRows()
        row = len(self._lines)
        self.beginInsertRows(QModelIndex(), row, row)
        self._lines.append(line)
        self.endInsertRows()

    def clear(self):
        self.beginResetModel()
        self._lines = []
        self.endResetModel()
