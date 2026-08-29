"""ProcessResultStore is a read-only view onto process_runner.py's
per-step .npz checkpoints. It implements the same minimal
mesh_axes()/scalar_field() interface as NpzResultStore/SpecResultStore
(gui/services/result_store.py) so the viewport's existing rendering
pipeline can be reused for process-flow previews, not duplicated --
design section 7.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np

from gui.services.process_model import ProcessFlow, ProcessStep
from gui.services.process_runner import run_flow
from gui.services.process_result_store import ProcessResultStore
from gui.services.result_store import ScalarField, MeshAxes


def _make_manifest(tmp_path):
    flow = ProcessFlow(steps=[
        ProcessStep(id="sub", name="Substrate", operation="substrate",
                   parameters={"length_cm": 2e-4, "background_doping_cm3": -1e16,
                               "mesh": {"h_min_cm": 2e-8, "h_max_cm": 2e-6, "ratio": 1.15}}),
        ProcessStep(id="i1", name="Implant", operation="implant",
                   parameters={"species": "P", "energy_keV": 50.0, "dose_cm2": 3e14}),
    ])
    flow_path = str(tmp_path / "flow.json")
    manifest_path = str(tmp_path / "manifest.json")
    with open(flow_path, "w") as fh:
        json.dump(flow.to_dict(), fh)
    run_flow(flow_path, manifest_path)
    with open(manifest_path) as fh:
        return json.load(fh)


def test_step_ids_in_flow_order(tmp_path):
    store = ProcessResultStore(_make_manifest(tmp_path))
    assert store.step_ids() == ["sub", "i1"]


def test_state_for_returns_arrays(tmp_path):
    store = ProcessResultStore(_make_manifest(tmp_path))
    state = store.state_for("i1")
    assert state["x"].ndim == 1
    assert state["net_doping"].shape == state["x"].shape
    assert state["ntotal"].shape == state["x"].shape
    assert "P" in state["species_profiles"]
    assert state["species_profiles"]["P"].shape == state["x"].shape


def test_state_for_substrate_has_no_species(tmp_path):
    store = ProcessResultStore(_make_manifest(tmp_path))
    state = store.state_for("sub")
    assert state["species_profiles"] == {}
    assert state["bookkeeping"] == {}


def test_scalar_field_and_mesh_axes_for_a_selected_step(tmp_path):
    store = ProcessResultStore(_make_manifest(tmp_path))
    store.select_step("i1")
    axes = store.mesh_axes()
    assert isinstance(axes, MeshAxes)
    assert axes.dimensionality == 1
    assert set(axes.axes) == {"x"}
    field = store.scalar_field("net_doping")
    assert isinstance(field, ScalarField)
    assert field.values.shape == np.asarray(axes.axes["x"]).shape
    assert field.unit == "cm^-3"


def test_scalar_field_for_species(tmp_path):
    store = ProcessResultStore(_make_manifest(tmp_path))
    store.select_step("i1")
    field = store.scalar_field("P")
    assert field.name == "P"
    assert field.values.max() > 0


def test_default_selected_step_is_the_last_one(tmp_path):
    store = ProcessResultStore(_make_manifest(tmp_path))
    field_default = store.scalar_field("net_doping")
    store.select_step("i1")
    field_explicit = store.scalar_field("net_doping")
    assert np.array_equal(field_default.values, field_explicit.values)


def test_select_unknown_step_raises_keyerror(tmp_path):
    store = ProcessResultStore(_make_manifest(tmp_path))
    try:
        store.select_step("does-not-exist")
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_scalar_field_unknown_name_raises_keyerror(tmp_path):
    store = ProcessResultStore(_make_manifest(tmp_path))
    try:
        store.scalar_field("not_a_field")
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_available_scalars_includes_species(tmp_path):
    store = ProcessResultStore(_make_manifest(tmp_path))
    store.select_step("i1")
    scalars = store.available_scalars()
    assert set(scalars) == {"net_doping", "ntotal", "P"}


def test_bookkeeping_present_only_for_oxidize_steps(tmp_path):
    flow = ProcessFlow(steps=[
        ProcessStep(id="sub", name="Substrate", operation="substrate",
                   parameters={"length_cm": 2e-4, "background_doping_cm3": -1e16,
                               "mesh": {"h_min_cm": 2e-8, "h_max_cm": 2e-6, "ratio": 1.15}}),
        ProcessStep(id="ox", name="Oxidize", operation="oxidize",
                   parameters={"temperature_C": 900.0, "time_hours": 1.0, "ambient": "dry"}),
    ])
    flow_path = str(tmp_path / "flow.json")
    manifest_path = str(tmp_path / "manifest.json")
    with open(flow_path, "w") as fh:
        json.dump(flow.to_dict(), fh)
    run_flow(flow_path, manifest_path)
    with open(manifest_path) as fh:
        manifest = json.load(fh)

    store = ProcessResultStore(manifest)
    ox_state = store.state_for("ox")
    assert "oxide_thickness_um" in ox_state["bookkeeping"]
    assert "silicon_consumed_um" in ox_state["bookkeeping"]
    assert ox_state["bookkeeping"]["oxide_thickness_um"] > 0.0
    sub_state = store.state_for("sub")
    assert sub_state["bookkeeping"] == {}
