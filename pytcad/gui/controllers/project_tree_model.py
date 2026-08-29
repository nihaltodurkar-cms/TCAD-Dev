"""The Project -> Process/Structure/Mesh/Device/Results tree.

v0.1 populates Structure and Results; the other nodes are present but
inert, because they are the v0.2-v0.5 workflow stages and the tree is
the map of where the application is going.
"""
from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt


class _Node:
    def __init__(self, label, node_id, parent=None):
        self.label = label
        self.node_id = node_id
        self.parent = parent
        self.children = []


class ProjectTreeModel(QAbstractItemModel):
    NodeIdRole = Qt.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root = _Node("<root>", "root")
        project = _Node("Project", "project", self._root)
        self._root.children.append(project)
        for label in ("Process", "Structure", "Mesh", "Device", "Results"):
            project.children.append(_Node(label, label.lower(), project))

    # -- QAbstractItemModel -------------------------------------------
    def index(self, row, column, parent=QModelIndex()):
        node = parent.internalPointer() if parent.isValid() else self._root
        if row < 0 or row >= len(node.children) or column != 0:
            return QModelIndex()
        return self.createIndex(row, column, node.children[row])

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        node = index.internalPointer()
        if node.parent is None or node.parent is self._root:
            return QModelIndex()
        grand = node.parent.parent
        row = grand.children.index(node.parent) if grand else 0
        return self.createIndex(row, 0, node.parent)

    def rowCount(self, parent=QModelIndex()):
        node = parent.internalPointer() if parent.isValid() else self._root
        return len(node.children)

    def columnCount(self, parent=QModelIndex()):
        return 1

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        node = index.internalPointer()
        if role in (Qt.DisplayRole,):
            return node.label
        if role == self.NodeIdRole:
            return node.node_id
        return None

    def roleNames(self):
        return {Qt.DisplayRole: b"display", self.NodeIdRole: b"nodeId"}

    def nodeIdAt(self, index):
        return self.data(index, self.NodeIdRole)
