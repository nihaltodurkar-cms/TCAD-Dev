"""M3 acceptance tests, part 1: the ResultStore / analysis boundary
(ARCHITECTURE.md revised roadmap, milestone M3a).

Contract under test:
  - The ResultStore ABC itself carries the sweep protocol
    (has_sweep()/sweep_result()) and a solved-result marker, with honest
    defaults -- so the CONTROLLER can ask the store instead of
    type-checking it against NpzResultStore.
  - A third-party/future-backend store that satisfies the protocol works
    everywhere NpzResultStore did, WITHOUT importing it.
  - ProcessResultStore exposes its selected step through a public
    accessor (no more _selected reach-ins from the visualization layer).
  - The controller no longer imports pytcad directly: derived-quantity
    math lives in the service layer.
"""
import inspect, json, os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from gui.controllers.app_controller import AppController
from gui.services.process_result_store import ProcessResultStore
from gui.services.result_store import ResultStore


# ----------------------------------------------------------------------
#  ABC defaults
# ----------------------------------------------------------------------
def test_abc_defaults_are_honest():
    class Bare(ResultStore):
        def mesh_axes(self): ...
        def scalar_field(self, name): ...
        def vector_field(self, name): ...
        def terminal_current(self, name): ...
        def available_scalars(self): return []
        def available_terminals(self): return []

    bare = Bare()
    assert bare.has_sweep() is False
    assert bare.is_solved_result() is False
    with pytest.raises(KeyError):
        bare.sweep_result()


# ----------------------------------------------------------------------
#  a foreign backend store satisfies the controller with NO import of
#  NpzResultStore
# ----------------------------------------------------------------------
class _ForeignSwept(ResultStore):
    """Stands in for a future backend's store."""

    def __init__(self, sweep=None):
        self._sweep = sweep

    def mesh_axes(self): ...
    def scalar_field(self, name): ...
    def vector_field(self, name): ...
    def terminal_current(self, name): ...
    def available_scalars(self): return ["potential"]
    def available_terminals(self): return []
    def is_solved_result(self): return True
    def has_sweep(self): return self._sweep is not None
    def sweep_result(self): return self._sweep


_SENTINEL_SWEEP = object()


def _controller_with(store):
    app = AppController()
    app._store = store
    return app


def test_controller_accepts_foreign_solved_store():
    app = _controller_with(_ForeignSwept(sweep=_SENTINEL_SWEEP))
    assert app.hasResult is True
    assert app.hasSweep is True
    assert app.sweepResultForQml is _SENTINEL_SWEEP


def test_controller_handles_foreign_store_without_sweep():
    app = _controller_with(_ForeignSwept())
    assert app.hasResult is True
    assert app.hasSweep is False
    assert app.sweepResultForQml is None


def test_preview_store_is_not_a_result():
    """SpecResultStore (pre-solve doping preview) must NOT flip the
    'results loaded' state -- the original reason for the type check."""
    from gui.services.examples import EXAMPLES
    from gui.services.result_store import SpecResultStore
    app = _controller_with(SpecResultStore(EXAMPLES["mosfet_2d"]()))
    assert app.hasResult is False
    assert app.hasSweep is False


# ----------------------------------------------------------------------
#  ProcessResultStore public accessor
# ----------------------------------------------------------------------
def test_process_store_exposes_selected_step_publicly(tmp_path):
    from gui.services.process_model import ProcessFlow, ProcessStep
    from gui.services.process_runner import run_flow
    flow = ProcessFlow(steps=[
        ProcessStep(id="sub", name="Substrate", operation="substrate",
                    parameters={"length_cm": 2e-4,
                                "background_doping_cm3": -1e16,
                                "mesh": {"h_min_cm": 2e-8, "h_max_cm": 2e-6,
                                         "ratio": 1.15}}),
        ProcessStep(id="i1", name="Implant", operation="implant",
                    parameters={"species": "P", "energy_keV": 50.0,
                                "dose_cm2": 3e14}),
    ])
    flow_path = str(tmp_path / "flow.json")
    manifest_path = str(tmp_path / "manifest.json")
    with open(flow_path, "w") as fh:
        json.dump(flow.to_dict(), fh)
    run_flow(flow_path, manifest_path)

    with open(manifest_path) as fh:
        store = ProcessResultStore(json.load(fh))
    assert store.selected_step_id == "i1"          # default = last step
    store.select_step("sub")
    assert store.selected_step_id == "sub"         # accessor reads LIVE state


# ----------------------------------------------------------------------
#  no core imports left in the controller / visualization layers
# ----------------------------------------------------------------------
def test_app_controller_never_imports_pytcad_core():
    import gui.controllers.app_controller as mod
    src = inspect.getsource(mod)
    assert "from pytcad" not in src and "import pytcad" not in src, \
        "controller must reach core math only through services"


def test_mpl_canvas_never_imports_pytcad_core():
    import gui.visualization.mpl_canvas_item as mod
    src = inspect.getsource(mod)
    assert "from pytcad" not in src and "import pytcad" not in src


def test_process_derived_offers_junction_depth_in_service_layer():
    from gui.services.process_derived import junction_depth_um
    x = np.linspace(0.0, 2e-4, 50)
    net = np.where(x < 1e-4, -1e17, 1e17)
    um = junction_depth_um(x, net)
    from pytcad.process import junction_depth
    expected = [float(v) * 1e4 for v in junction_depth(x, net)]
    assert um == pytest.approx(expected)


def test_process_store_is_a_first_class_resultstore():
    from gui.services.result_store import NpzResultStore
    assert issubclass(ProcessResultStore, ResultStore)
    # protocol defaults hold even before any manifest is loaded
    assert ProcessResultStore.__mro__[1] is ResultStore
    store = object.__new__(ProcessResultStore)
    assert store.has_sweep() is False
    assert store.is_solved_result() is False
    with pytest.raises(KeyError):
        store.sweep_result()
    assert store.available_terminals() == []
    with pytest.raises(KeyError):
        store.terminal_current("drain")
    with pytest.raises(KeyError):
        store.vector_field("current_density")
