"""Regression test for a real, pre-existing bug found during the QML
architecture cleanup pass (2026-09-04): MeshEditor.qml's stats grid
showed "undefined" for every label/value cell once a 2D structure was
loaded (any path where AppController.mesh_model is populated -- 1D
Process-Flow devices leave mesh_model as None, so meshInfo returns []
and never exercises the buggy code).

Root cause: AppController.meshInfo built its `rows` list out of Python
tuple literals, e.g. ("Nx", str(nx)). PySide6's QVariant marshaling
does NOT expose a list-of-tuples as indexable JS arrays -- only a
list-of-lists. MeshEditor.qml's delegate reads modelData[0]/modelData[1]
for each row, which came back `undefined` for every tuple-based row.

Confirmed empirically with a standalone QQmlComponent probe before this
fix: a @Property(list) returning [('Nx', '80'), ...] produced
modelData[0]/[1] === undefined in QML, while the identical data as
[['Nx', '80'], ...] read back correctly.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.controllers.app_controller import AppController


def test_mesh_info_rows_are_plain_lists_not_tuples():
    # PySide6 only marshals list-of-lists to indexable JS arrays; a
    # list-of-tuples silently degrades to non-indexable objects in QML,
    # which is exactly what MeshEditor.qml's modelData[0]/[1] delegate
    # relies on.
    app = QApplication.instance() or QApplication([])
    ctl = AppController()
    ctl.loadStructureExample("mosfet_2d_structure")
    assert ctl.mesh_model is not None, "need a populated mesh_model to exercise meshInfo's real code path"
    rows = ctl.meshInfo
    assert rows, "expected non-empty meshInfo rows for a loaded 2D structure"
    for row in rows:
        assert isinstance(row, list), (
            f"row {row!r} is a {type(row).__name__}, not a list -- "
            "QML modelData[0]/[1] will be undefined"
        )
        assert row[0] and row[1], f"row {row!r} has an empty label or value"
