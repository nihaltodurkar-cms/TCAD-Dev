"""Phase 3d: provenance trace view.

Verifies that LabController.provenanceRows() includes mesh node count
and model config from the RunRecord.
"""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from PySide6.QtGui import QGuiApplication
from gui import app as gui_app


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def test_provenance_rows_include_mesh_nodes(gapp):
    """provenanceRows() includes mesh node count from the store."""
    from gui.controllers.app_controller import AppController
    from gui.services.result_store import NpzResultStore
    import tempfile
    import json
    import numpy as np

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "test.npz")
        meta = {
            "backend": "pytcad",
            "created_utc": "2026-01-01T00:00:00Z",
            "dimensionality": 1,
            "material": "Si",
            "T": 300.0,
            "models": {"impact_ionization": True, "surface_mobility": False},
            "numerics": {},
            "schema_version": 2,
        }
        np.savez(path,
                 record__meta=np.array([json.dumps(meta)]),
                 dimensionality=np.array(1),
                 axis_x=np.array([0.0, 1e-4, 2e-4]),
                 field__potential=np.array([0.0, 0.1, 0.2]),
                 unit__potential=np.array("V"),
                 solved_bias=np.array([0.0, 0.1, 0.2]),
                 result__schema=np.array(2))

        store = NpzResultStore(path)
        ctl = AppController()
        ctl._store = store
        rows = dict(ctl.lab.provenanceRows())
        assert rows["Backend"] == "pytcad"
        assert rows["Material"] == "Si"
        assert rows["Mesh nodes"] == "3"
        assert rows["model: impact_ionization"] == "on"
        assert rows["model: surface_mobility"] == "off"


def test_provenance_rows_none_when_no_record(gapp):
    """When there's no run record, provenanceRows returns None."""
    from gui.controllers.app_controller import AppController
    ctl = AppController()
    ctl._store = None
    rows = ctl.lab.provenanceRows()
    assert rows is None
