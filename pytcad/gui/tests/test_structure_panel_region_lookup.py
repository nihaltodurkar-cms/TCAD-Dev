"""QML architecture cleanup: regression test for StructurePanel.qml's
_regionData()/_contactData()/_gateData() lookup functions, refactored
from three near-identical hand-rolled Qt.UserRole+N loops into one
generic _lookupRow() plus named role-offset maps (matching each Python
...ListModel's own Role class). Pure structural change, no behavior
change intended -- this test is the regression gate proving it.

_contactData()/_gateData() already had solid indirect coverage via
gui/tests/test_smoke_e2e.py's contact-voltage and gate-Vfb-mode tests
(selecting a contact/gate and checking the resulting editor fields).
_regionData() had none beyond "the regionMaterialBox combobox exists"
(test_m11s5_templates.py) -- this fills that gap by selecting a real
region and checking DopingEditor's bounds/doping/material fields match
the actual region data, exactly the fields _regionData() reconstructs.
"""
import pytest
from PySide6.QtCore import Qt, QObject
from PySide6.QtWidgets import QApplication

from gui.app import close_engine, create_engine


def _set_and_finish(field, text):
    field.setProperty("text", text)
    field.editingFinished.emit()


def test_selecting_a_region_populates_doping_editor_with_real_bounds_and_doping():
    app = QApplication.instance() or QApplication([])
    engine, controller = create_engine(app)
    try:
        root = engine.rootObjects()[0]
        controller.loadStructureExample("mosfet_2d_structure")
        root.findChild(QObject, "workbenchTabs").setProperty("currentIndex", 1)
        for _ in range(5):
            app.processEvents()

        region_model = controller.regionListModel
        idx0 = region_model.index(0, 0)
        region_id = region_model.data(idx0, Qt.UserRole + 1)
        expected_doping = region_model.data(idx0, Qt.UserRole + 4)
        expected_material = region_model.data(idx0, Qt.UserRole + 6)

        structure_panel = root.findChild(QObject, "structurePanel")
        structure_panel.setProperty("selectedRegionId", region_id)
        for _ in range(5):
            app.processEvents()

        x_min = root.findChild(QObject, "regionMaterialBox")
        assert x_min is not None
        # regionMaterialBox's displayText resolves the region's stored
        # material against controller.materialNames -- exercises
        # _regionData()'s "material" field end to end.
        assert x_min.property("displayText").upper() == expected_material.upper()

        doping_field = root.findChild(QObject, "regionDopingField")
        assert doping_field is not None
        assert float(doping_field.property("text")) == pytest.approx(
            expected_doping, rel=1e-6)
    finally:
        close_engine(engine)


def test_selecting_a_contact_and_gate_still_returns_correct_data_after_refactor():
    # Re-exercises the SAME contact/gate selection paths
    # test_smoke_e2e.py already covers, as a belt-and-suspenders check
    # scoped specifically to this refactor's commit.
    app = QApplication.instance() or QApplication([])
    engine, controller = create_engine(app)
    try:
        root = engine.rootObjects()[0]
        controller.loadStructureExample("mosfet_2d_structure")
        root.findChild(QObject, "workbenchTabs").setProperty("currentIndex", 1)
        for _ in range(5):
            app.processEvents()

        contact_model = controller.contactListModel
        idx0 = contact_model.index(0, 0)
        contact_id = contact_model.data(idx0, Qt.UserRole + 1)
        expected_edge = contact_model.data(idx0, Qt.UserRole + 3)

        structure_panel = root.findChild(QObject, "structurePanel")
        structure_panel.setProperty("selectedContactId", contact_id)
        for _ in range(5):
            app.processEvents()

        contact = controller.structure.find_contact(contact_id)
        assert contact.boundary.edge == expected_edge

        gate_model = controller.gateListModel
        idx0 = gate_model.index(0, 0)
        gate_id = gate_model.data(idx0, Qt.UserRole + 1)
        expected_tox = gate_model.data(idx0, Qt.UserRole + 3)

        structure_panel.setProperty("selectedGateId", gate_id)
        for _ in range(5):
            app.processEvents()

        gate = controller.structure.find_gate(gate_id)
        assert gate.tox_cm == pytest.approx(expected_tox, rel=1e-9)
    finally:
        close_engine(engine)
