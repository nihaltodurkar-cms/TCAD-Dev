"""Phase 3c: mesh statistics panel.

Verifies that AppController.meshStats returns correct node counts and
axis information from the ResultStore.
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


def test_mesh_stats_from_result(gapp):
    """AppController.meshStats returns node count and axis info from store."""
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
            "models": {},
            "numerics": {},
            "schema_version": 2,
        }
        np.savez(path,
                 record__meta=np.array([json.dumps(meta)]),
                 dimensionality=np.array(1),
                 axis_x=np.array([0.0, 1e-4, 2e-4, 3e-4, 4e-4]),
                 field__potential=np.array([0.0, 0.1, 0.2, 0.3, 0.4]),
                 unit__potential=np.array("V"),
                 solved_bias=np.array([0.0, 0.1, 0.2, 0.3, 0.4]),
                 result__schema=np.array(2))

        store = NpzResultStore(path)
        ctl = AppController()
        ctl._store = store
        stats = ctl.meshStats
        assert stats is not None
        assert stats["node_count"] == 5
        assert stats["dimensionality"] == 1
        assert stats["axes"]["x"]["size"] == 5
        assert abs(stats["axes"]["x"]["min"] - 0.0) < 1e-15
        assert abs(stats["axes"]["x"]["max"] - 4e-4) < 1e-15


def test_mesh_stats_none_when_no_store(gapp):
    """When there's no store, meshStats returns None."""
    from gui.controllers.app_controller import AppController
    ctl = AppController()
    ctl._store = None
    stats = ctl.meshStats
    assert stats is None
