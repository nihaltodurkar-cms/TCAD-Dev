import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from gui.services.process_model import ProcessStep, ProcessFlow, reconstruct_doping


def test_process_step_round_trips_through_dict():
    step = ProcessStep(id="s1", name="Implant B", operation="implant",
                       enabled=True, parameters={"species": "B", "energy_keV": 30.0,
                                                 "dose_cm2": 1e14, "tilt_deg": 7.0})
    d = step.to_dict()
    back = ProcessStep.from_dict(d)
    assert back == step


def test_flow_add_remove_find_step():
    flow = ProcessFlow()
    s1 = ProcessStep(id="a", name="Substrate", operation="substrate", parameters={})
    flow.add_step(s1)
    assert flow.find_step("a") is s1
    flow.remove_step("a")
    assert flow.find_step("a") is None


def test_flow_move_step_clamps_and_preserves_ids():
    flow = ProcessFlow(steps=[
        ProcessStep(id="a", name="A", operation="substrate", parameters={}),
        ProcessStep(id="b", name="B", operation="implant", parameters={}),
        ProcessStep(id="c", name="C", operation="anneal", parameters={}),
    ])
    flow.move_step("c", -5)   # clamp to index 0
    assert [s.id for s in flow.steps] == ["c", "a", "b"]


def test_flow_duplicate_step_gets_new_id_and_independent_parameters():
    flow = ProcessFlow(steps=[
        ProcessStep(id="a", name="Implant", operation="implant",
                   parameters={"species": "B", "dose_cm2": 1e14}),
    ])
    dup = flow.duplicate_step("a")
    assert dup.id != "a"
    assert dup.parameters == flow.find_step("a").parameters
    dup.parameters["dose_cm2"] = 9e14
    assert flow.find_step("a").parameters["dose_cm2"] == 1e14   # not shared


def test_flow_round_trip_through_dict():
    flow = ProcessFlow(steps=[
        ProcessStep(id="a", name="Substrate", operation="substrate",
                   parameters={"length_cm": 3e-4, "background_doping_cm3": -1e16,
                               "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}}),
    ])
    back = ProcessFlow.from_dict(flow.to_dict())
    assert back.steps[0] == flow.steps[0]


def test_reconstruct_doping_single_species_matches_hand_formula():
    x = np.linspace(0.0, 1e-4, 11)
    background = -1e16
    C_p = np.full_like(x, 5e17)
    net, ntotal = reconstruct_doping(x, background, {"P": C_p})
    assert np.allclose(net, background + 1 * C_p)          # DOPANT_TYPE["P"] == +1
    assert np.allclose(ntotal, abs(background) + C_p)


def test_reconstruct_doping_no_species_returns_background_only():
    x = np.linspace(0.0, 1e-4, 5)
    net, ntotal = reconstruct_doping(x, -1e16, {})
    assert np.allclose(net, -1e16)
    assert np.allclose(ntotal, 1e16)


def test_reconstruct_doping_multi_species_uses_dopant_type_signs():
    x = np.linspace(0.0, 1e-4, 5)
    C_p = np.full_like(x, 3e17)   # donor, +1
    C_b = np.full_like(x, 2e17)   # acceptor, -1
    net, ntotal = reconstruct_doping(x, 1e15, {"P": C_p, "B": C_b})
    assert np.allclose(net, 1e15 + C_p - C_b)
    assert np.allclose(ntotal, 1e15 + C_p + C_b)


def test_validate_flow_requires_a_leading_substrate_step():
    from gui.services.process_model import validate_flow
    flow = ProcessFlow(steps=[
        ProcessStep(id="a", name="Implant", operation="implant",
                   parameters={"species": "B", "energy_keV": 30.0, "dose_cm2": 1e14}),
    ])
    errors = validate_flow(flow)
    assert any("substrate" in e.message.lower() for e in errors)


def test_validate_flow_flags_out_of_table_energy():
    from gui.services.process_model import validate_flow
    flow = ProcessFlow(steps=[
        ProcessStep(id="a", name="Substrate", operation="substrate",
                   parameters={"length_cm": 3e-4, "background_doping_cm3": -1e16,
                               "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}}),
        ProcessStep(id="b", name="Implant", operation="implant",
                   parameters={"species": "As", "energy_keV": 500.0, "dose_cm2": 1e14}),
    ])
    errors = validate_flow(flow)
    assert any(e.object_id == "b" and "energy" in e.message.lower() for e in errors)


def test_validate_flow_flags_anneal_with_no_preceding_implant():
    from gui.services.process_model import validate_flow
    flow = ProcessFlow(steps=[
        ProcessStep(id="a", name="Substrate", operation="substrate",
                   parameters={"length_cm": 3e-4, "background_doping_cm3": -1e16,
                               "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}}),
        ProcessStep(id="b", name="Anneal", operation="anneal",
                   parameters={"temperature_C": 950.0, "time_s": 1800.0}),
    ])
    errors = validate_flow(flow)
    assert any(e.object_id == "b" and "implant" in e.message.lower() for e in errors)


def test_validate_flow_passes_a_valid_flow():
    from gui.services.process_model import validate_flow
    flow = ProcessFlow(steps=[
        ProcessStep(id="a", name="Substrate", operation="substrate",
                   parameters={"length_cm": 3e-4, "background_doping_cm3": -1e16,
                               "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}}),
        ProcessStep(id="b", name="Implant", operation="implant",
                   parameters={"species": "P", "energy_keV": 50.0, "dose_cm2": 3e14}),
        ProcessStep(id="c", name="Anneal", operation="anneal",
                   parameters={"temperature_C": 950.0, "time_s": 1800.0}),
    ])
    assert validate_flow(flow) == []


def test_validate_flow_flags_more_than_one_enabled_substrate_step():
    """A second enabled substrate step resets species_profiles to {} in
    process_runner._run_substrate, silently wiping out anything implanted
    before it -- validate_flow must reject this up front rather than let
    it reach the runner and KeyError inside _anneal_species."""
    from gui.services.process_model import validate_flow
    flow = ProcessFlow(steps=[
        ProcessStep(id="a", name="Substrate", operation="substrate",
                   parameters={"length_cm": 3e-4, "background_doping_cm3": -1e16,
                               "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}}),
        ProcessStep(id="b", name="Implant", operation="implant",
                   parameters={"species": "P", "energy_keV": 50.0, "dose_cm2": 3e14}),
        ProcessStep(id="c", name="Substrate again", operation="substrate",
                   parameters={"length_cm": 3e-4, "background_doping_cm3": -1e16,
                               "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}}),
        ProcessStep(id="d", name="Anneal", operation="anneal",
                   parameters={"temperature_C": 950.0, "time_s": 1800.0}),
    ])
    errors = validate_flow(flow)
    assert any("one enabled" in e.message.lower() and "substrate" in e.message.lower()
               for e in errors)


def test_validate_flow_allows_a_disabled_second_substrate_step():
    from gui.services.process_model import validate_flow
    flow = ProcessFlow(steps=[
        ProcessStep(id="a", name="Substrate", operation="substrate",
                   parameters={"length_cm": 3e-4, "background_doping_cm3": -1e16,
                               "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}}),
        ProcessStep(id="b", name="Substrate again", operation="substrate", enabled=False,
                   parameters={"length_cm": 3e-4, "background_doping_cm3": -1e16,
                               "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}}),
    ])
    assert validate_flow(flow) == []


def test_validate_flow_flags_tilt_at_or_above_90_degrees():
    from gui.services.process_model import validate_flow
    flow = ProcessFlow(steps=[
        ProcessStep(id="a", name="Substrate", operation="substrate",
                   parameters={"length_cm": 3e-4, "background_doping_cm3": -1e16,
                               "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}}),
        ProcessStep(id="b", name="Implant", operation="implant",
                   parameters={"species": "P", "energy_keV": 50.0, "dose_cm2": 3e14,
                               "tilt_deg": 90.0}),
    ])
    errors = validate_flow(flow)
    assert any(e.object_id == "b" and "tilt" in e.message.lower() for e in errors)


def test_validate_flow_flags_negative_tilt():
    from gui.services.process_model import validate_flow
    flow = ProcessFlow(steps=[
        ProcessStep(id="a", name="Substrate", operation="substrate",
                   parameters={"length_cm": 3e-4, "background_doping_cm3": -1e16,
                               "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}}),
        ProcessStep(id="b", name="Implant", operation="implant",
                   parameters={"species": "P", "energy_keV": 50.0, "dose_cm2": 3e14,
                               "tilt_deg": -1.0}),
    ])
    errors = validate_flow(flow)
    assert any(e.object_id == "b" and "tilt" in e.message.lower() for e in errors)


def test_validate_flow_flags_disabled_implant_as_not_satisfying_anneal():
    from gui.services.process_model import validate_flow
    flow = ProcessFlow(steps=[
        ProcessStep(id="a", name="Substrate", operation="substrate",
                   parameters={"length_cm": 3e-4, "background_doping_cm3": -1e16,
                               "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}}),
        ProcessStep(id="b", name="Implant", operation="implant", enabled=False,
                   parameters={"species": "P", "energy_keV": 50.0, "dose_cm2": 3e14}),
        ProcessStep(id="c", name="Anneal", operation="anneal",
                   parameters={"temperature_C": 950.0, "time_s": 1800.0}),
    ])
    errors = validate_flow(flow)
    assert any(e.object_id == "c" for e in errors)
