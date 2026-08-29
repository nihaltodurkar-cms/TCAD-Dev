"""UndoStack is metadata-only: commands carry small closures over
scalar/list diffs, never arrays or results."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from gui.services.undo_stack import Command, UndoStack


def _rename_command(state, old_name, new_name):
    return Command(
        do=lambda: state.__setitem__("name", new_name),
        undo=lambda: state.__setitem__("name", old_name),
        description=f"rename to {new_name}",
    )


def test_push_applies_the_command_immediately():
    state = {"name": "A"}
    stack = UndoStack()
    stack.push(_rename_command(state, "A", "B"))
    assert state["name"] == "B"


def test_undo_reverts_and_redo_reapplies():
    state = {"name": "A"}
    stack = UndoStack()
    stack.push(_rename_command(state, "A", "B"))
    stack.undo()
    assert state["name"] == "A"
    stack.redo()
    assert state["name"] == "B"


def test_can_undo_and_can_redo_flags():
    stack = UndoStack()
    assert stack.can_undo is False and stack.can_redo is False
    state = {"name": "A"}
    stack.push(_rename_command(state, "A", "B"))
    assert stack.can_undo is True and stack.can_redo is False
    stack.undo()
    assert stack.can_undo is False and stack.can_redo is True


def test_pushing_after_undo_clears_the_redo_history():
    state = {"name": "A"}
    stack = UndoStack()
    stack.push(_rename_command(state, "A", "B"))
    stack.undo()
    stack.push(_rename_command(state, "A", "C"))
    assert state["name"] == "C"
    assert stack.can_redo is False


def test_dirty_tracks_distance_from_the_last_clean_mark():
    state = {"name": "A"}
    stack = UndoStack()
    assert stack.is_dirty is False
    stack.push(_rename_command(state, "A", "B"))
    assert stack.is_dirty is True
    stack.mark_clean()
    assert stack.is_dirty is False
    stack.push(_rename_command(state, "B", "C"))
    assert stack.is_dirty is True
    stack.undo()
    assert stack.is_dirty is False   # back exactly at the saved state
