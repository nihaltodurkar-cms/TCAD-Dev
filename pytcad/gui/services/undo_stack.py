"""A small command-based undo/redo stack, scoped to structure/mesh
metadata edits.  Commands carry closures over scalar/small-list diffs --
never a doping array, never a ResultStore/solve result -- per the design
spec's explicit "no fragile snapshot of huge arrays" constraint.
"""


class Command:
    def __init__(self, do, undo, description=""):
        self._do = do
        self._undo = undo
        self.description = description

    def do(self):
        self._do()

    def undo(self):
        self._undo()


class UndoStack:
    def __init__(self):
        self._undo = []
        self._redo = []
        self._clean_index = 0

    def push(self, command):
        command.do()
        self._undo.append(command)
        self._redo.clear()

    def undo(self):
        if not self._undo:
            return
        command = self._undo.pop()
        command.undo()
        self._redo.append(command)

    def redo(self):
        if not self._redo:
            return
        command = self._redo.pop()
        command.do()
        self._undo.append(command)

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    def mark_clean(self):
        self._clean_index = len(self._undo)

    @property
    def is_dirty(self):
        return len(self._undo) != self._clean_index
