"""process_runner is the process boundary for the Process Workbench: it
must maintain per-species doping state across an arbitrary sequence of
implant/anneal steps without ever losing or cross-contaminating a
species' profile, and it must treat oxidation as pure bookkeeping that
never touches x/background/species_profiles.

The multi-species regression test (test_multi_species_flow_survives_
both_species) is the single most important test in this file -- see
task-3-brief.md and the design spec section 17 correction 6.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np

from gui.services.process_model import ProcessFlow, ProcessStep

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _substrate_step():
    return ProcessStep(id="sub", name="Substrate", operation="substrate",
                       parameters={"length_cm": 3e-4, "background_doping_cm3": -1e16,
                                   "mesh": {"h_min_cm": 2e-8, "h_max_cm": 2e-6, "ratio": 1.15}})


def _run_cli(flow, tmp_path, name):
    flow_path = str(tmp_path / f"{name}-flow.json")
    manifest_path = str(tmp_path / f"{name}-manifest.json")
    with open(flow_path, "w") as fh:
        json.dump(flow.to_dict(), fh)
    proc = subprocess.run(
        [sys.executable, "-m", "gui.services.process_runner", flow_path, manifest_path],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=120)
    return proc, manifest_path


def test_multi_species_flow_survives_both_species(tmp_path):
    """The design spec's own required regression (correction 6):
    substrate -> implant P -> anneal P -> implant As -> anneal As."""
    flow = ProcessFlow(steps=[
        _substrate_step(),
        ProcessStep(id="i1", name="Implant P", operation="implant",
                   parameters={"species": "P", "energy_keV": 50.0, "dose_cm2": 3e14}),
        ProcessStep(id="a1", name="Anneal P", operation="anneal",
                   parameters={"temperature_C": 950.0, "time_s": 600.0}),
        ProcessStep(id="i2", name="Implant As", operation="implant",
                   parameters={"species": "As", "energy_keV": 30.0, "dose_cm2": 2e14}),
        ProcessStep(id="a2", name="Anneal As", operation="anneal",
                   parameters={"temperature_C": 900.0, "time_s": 300.0}),
    ])
    proc, manifest_path = _run_cli(flow, tmp_path, "multispecies")
    assert proc.returncode == 0, proc.stderr
    with open(manifest_path) as fh:
        manifest = json.load(fh)
    assert manifest["step_ids"] == ["sub", "i1", "a1", "i2", "a2"]

    final = np.load(manifest["state_paths"]["a2"])
    x = final["x"]
    C_p = final["species_P"]
    C_as = final["species_As"]
    background = float(final["background"])

    # (a) both species present and nonzero
    assert C_p.max() > 0
    assert C_as.max() > 0

    # (b)/(c) net_doping and ntotal independently recomputed by hand,
    # NOT via reconstruct_doping() itself -- must be able to catch a bug
    # INSIDE reconstruct_doping(), not just prove the runner agrees with
    # whatever that function happens to compute.
    expected_net = background + 1.0 * C_p + 1.0 * C_as   # both P, As are donors (+1)
    expected_ntotal = abs(background) + C_p + C_as
    assert np.allclose(final["net_doping"], expected_net, rtol=1e-9)
    assert np.allclose(final["ntotal"], expected_ntotal, rtol=1e-9)

    # (d) the P profile survived the As-only anneal step BYTE-IDENTICAL --
    # a1 (right after P's own anneal) and a2 (after implanting AND
    # annealing As) must carry the exact same species_P array. Any
    # cross-species mutation (e.g. re-diffusing all species instead of
    # just the resolved one, or aliasing dict entries) would perturb this.
    after_p_anneal = np.load(manifest["state_paths"]["a1"])["species_P"]
    after_as_anneal = np.load(manifest["state_paths"]["a2"])["species_P"]
    assert np.array_equal(after_p_anneal, after_as_anneal)

    # Sanity: As's own profile actually changed shape between implant and
    # anneal (diffusion did something), proving a1->a2 P-unchanged isn't
    # trivially true because nothing at all happened during a2.
    as_after_implant = np.load(manifest["state_paths"]["i2"])["species_As"]
    assert not np.array_equal(as_after_implant, C_as)

    # species_profiles for i1/a1 must not contain "As" at all yet, and the
    # P array present at i1 must differ from the P array at a1 (implant
    # profile is NOT the same as the post-anneal diffused profile) --
    # otherwise "anneal" could be a no-op and this test would still pass.
    i1_data = np.load(manifest["state_paths"]["i1"])
    assert "species_As" not in i1_data.files
    a1_data = np.load(manifest["state_paths"]["a1"])
    assert not np.array_equal(i1_data["species_P"], a1_data["species_P"])


def test_disabled_step_is_skipped(tmp_path):
    flow = ProcessFlow(steps=[
        _substrate_step(),
        ProcessStep(id="i1", name="Implant B", operation="implant", enabled=False,
                   parameters={"species": "B", "energy_keV": 30.0, "dose_cm2": 1e14}),
    ])
    proc, manifest_path = _run_cli(flow, tmp_path, "disabled")
    assert proc.returncode == 0, proc.stderr
    with open(manifest_path) as fh:
        manifest = json.load(fh)
    assert manifest["step_ids"] == ["sub"]           # i1 skipped entirely
    assert "i1" not in manifest["state_paths"]
    # Derive the checkpoint directory from an actual written path rather
    # than assuming checkpoints live next to manifest_path -- run_flow()
    # now writes them into a per-run "<manifest-stem>-state/" subdirectory
    # (see process_runner.py's run_flow() for why).
    state_dir = os.path.dirname(manifest["state_paths"]["sub"])
    assert not os.path.exists(os.path.join(state_dir, "state-i1.npz"))


def test_oxidize_does_not_alter_x_or_profiles(tmp_path):
    flow = ProcessFlow(steps=[
        _substrate_step(),
        ProcessStep(id="i1", name="Implant B", operation="implant",
                   parameters={"species": "B", "energy_keV": 30.0, "dose_cm2": 1e14}),
        ProcessStep(id="ox", name="Oxidize", operation="oxidize",
                   parameters={"temperature_C": 900.0, "time_hours": 1.0, "ambient": "dry"}),
    ])
    proc, manifest_path = _run_cli(flow, tmp_path, "oxidize")
    assert proc.returncode == 0, proc.stderr
    with open(manifest_path) as fh:
        manifest = json.load(fh)
    before = np.load(manifest["state_paths"]["i1"])
    after = np.load(manifest["state_paths"]["ox"])
    assert np.array_equal(before["x"], after["x"])
    assert np.array_equal(before["species_B"], after["species_B"])
    assert np.array_equal(before["background"], after["background"])
    assert np.array_equal(before["net_doping"], after["net_doping"])
    assert np.array_equal(before["ntotal"], after["ntotal"])
    assert float(after["bookkeeping_oxide_thickness_um"]) > 0.0
    assert float(after["bookkeeping_silicon_consumed_um"]) > 0.0
    # bookkeeping keys must be absent on non-oxidize steps -- oxidation's
    # bookkeeping must not leak backward into earlier checkpoints.
    assert not any(k.startswith("bookkeeping_") for k in before.files)


def test_invalid_flow_exits_nonzero_with_no_manifest(tmp_path):
    flow = ProcessFlow(steps=[
        ProcessStep(id="i1", name="Implant", operation="implant",
                   parameters={"species": "B", "energy_keV": 30.0, "dose_cm2": 1e14}),
    ])   # no substrate step -- invalid
    proc, manifest_path = _run_cli(flow, tmp_path, "invalid")
    assert proc.returncode != 0
    assert not os.path.exists(manifest_path)
    assert "PYTCAD_ERROR=" in proc.stderr


def test_double_substrate_flow_is_rejected_before_it_can_keyerror(tmp_path):
    """Final-review finding: substrate -> implant P -> substrate -> anneal
    used to pass validation (only the FIRST enabled step was checked to be
    'substrate') and then crash with a raw KeyError inside
    _anneal_species/_run_anneal, because the second substrate step resets
    species_profiles to {} and the anneal step still tries to resolve
    'P'. validate_flow() now rejects more than one enabled substrate step
    up front, so run_flow() must exit nonzero with a clean, parseable
    error instead of an unhandled KeyError."""
    flow = ProcessFlow(steps=[
        _substrate_step(),
        ProcessStep(id="i1", name="Implant P", operation="implant",
                   parameters={"species": "P", "energy_keV": 50.0, "dose_cm2": 3e14}),
        ProcessStep(id="s2", name="Substrate again", operation="substrate",
                   parameters={"length_cm": 3e-4, "background_doping_cm3": -1e16,
                               "mesh": {"h_min_cm": 2e-8, "h_max_cm": 2e-6, "ratio": 1.15}}),
        ProcessStep(id="a1", name="Anneal P", operation="anneal",
                   parameters={"temperature_C": 950.0, "time_s": 600.0}),
    ])
    proc, manifest_path = _run_cli(flow, tmp_path, "double-substrate")
    assert proc.returncode != 0
    assert not os.path.exists(manifest_path)
    assert "PYTCAD_ERROR=" in proc.stderr
    assert "KeyError" not in proc.stderr, (
        "flow reached the runner and raw-KeyError'd instead of being "
        "rejected by validate_flow() up front:\n" + proc.stderr)


def test_two_runs_of_the_same_flow_do_not_share_or_overwrite_checkpoints(tmp_path):
    """Final-review finding: two runs of a flow with the same step IDs
    (e.g. re-running after editing a parameter) used to write into the
    SAME checkpoint directory, so the second run's files silently
    overwrote the first run's in place. run_flow() now derives a
    per-run checkpoint subdirectory from manifest_path's own stem, which
    JobRunner already guarantees is unique per run -- confirm two runs of
    an identical flow land in two different directories and that the
    first run's checkpoint file is completely untouched by the second."""
    flow = ProcessFlow(steps=[
        _substrate_step(),
        ProcessStep(id="i1", name="Implant B", operation="implant",
                   parameters={"species": "B", "energy_keV": 30.0, "dose_cm2": 1e14}),
    ])
    proc1, manifest_path1 = _run_cli(flow, tmp_path, "run1")
    assert proc1.returncode == 0, proc1.stderr
    with open(manifest_path1) as fh:
        manifest1 = json.load(fh)
    first_checkpoint_path = manifest1["state_paths"]["i1"]
    first_checkpoint_bytes = open(first_checkpoint_path, "rb").read()

    # A second run of the very same flow (same step IDs) but through a
    # DIFFERENT manifest path, mirroring a real re-run in the same
    # session (JobRunner.start() always gives every run a fresh
    # manifest/result path).
    proc2, manifest_path2 = _run_cli(flow, tmp_path, "run2")
    assert proc2.returncode == 0, proc2.stderr
    with open(manifest_path2) as fh:
        manifest2 = json.load(fh)
    second_checkpoint_path = manifest2["state_paths"]["i1"]

    assert os.path.dirname(first_checkpoint_path) != os.path.dirname(second_checkpoint_path), (
        "both runs wrote checkpoints into the same directory -- a second "
        "run can still overwrite the first run's files in place")
    assert os.path.exists(first_checkpoint_path), (
        "the first run's checkpoint no longer exists after a second run")
    assert open(first_checkpoint_path, "rb").read() == first_checkpoint_bytes, (
        "the first run's checkpoint file was mutated by the second run")


def test_stdout_has_stage_and_result_markers(tmp_path):
    """job_runner.py's regexes (^PYTCAD_STAGE=(\\w+), ^RESULT_PATH=(.+)$)
    must match this runner's stdout exactly, since Task 5's JobRunner
    reuses them unmodified for process runs."""
    flow = ProcessFlow(steps=[_substrate_step()])
    proc, manifest_path = _run_cli(flow, tmp_path, "stages")
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert any(line == "PYTCAD_STAGE=step_sub" for line in lines)
    assert any(line == f"RESULT_PATH={manifest_path}" for line in lines)
