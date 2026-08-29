"""Process-flow subprocess entry point.

    python -m gui.services.process_runner <flow.json> <manifest.json>

Run in a SEPARATE PROCESS by JobRunner (gui/services/job_runner.py),
generalized in a later task to accept any runner module -- this file needs
no special-case support there beyond matching solver_runner.py's own
stdout/atomic-write contract (PYTCAD_STAGE=..., RESULT_PATH=..., a
".tmp.<ext>" + os.replace atomic write).  Imports pytcad.process directly
and no Qt, exactly matching solver_runner.py, so a process flow is
runnable from a script or notebook too.

State model: see docs/superpowers/specs/2026-08-23-gui-v0.3-process-
workbench-design.md sections 7, 9, 17, 21.  Each enabled step advances a
running (background, species_profiles) pair, where species_profiles is
{species: ndarray} and every species' array is independent -- an implant
step only ever ADDS to its own species' entry, and an anneal step only
ever replaces its one resolved species' entry, leaving every other
species' ndarray the exact same object it already was.  net_doping/ntotal
are always produced by process_model.reconstruct_doping(), never
recomputed here by hand (design section 21's single-formula audit).

Oxidation is bookkeeping only: `_run_oxidize` returns the SAME state dict
it was given (x/background/species_profiles untouched, same array
objects) plus a separate bookkeeping dict of oxide_thickness_um and
silicon_consumed_um -- it must never construct a new x, background, or
species_profiles value.
"""
import json
import os
import sys
import traceback

import numpy as np

from pytcad import process
from pytcad.mesh import graded_mesh

from .process_model import reconstruct_doping, ProcessFlow, validate_flow


def _run_substrate(step, state):
    p = step.parameters
    mesh = p["mesh"]
    x = graded_mesh(p["length_cm"], [0.0, p["length_cm"]],
                    mesh["h_min_cm"], mesh["h_max_cm"], mesh["ratio"])
    return {"x": x, "background": p["background_doping_cm3"], "species_profiles": {}}


def _run_implant(step, state):
    """ADDS to the existing profile for this step's species (starting a
    new one at zero if this is the species' first implant) -- every OTHER
    species' array in the dict is carried over as the same object,
    never touched."""
    p = step.parameters
    x = state["x"]
    species = p["species"]
    contribution = process.implant(x, species, p["energy_keV"], p["dose_cm2"],
                                   p.get("tilt_deg", 0.0))
    # v0.5.0 M6: OPTIONAL ion-implanter window ("x_range_cm": [lo, hi]).
    # Composition of the existing core function with a hard mask -- no
    # numerical code changes.  Absent key -> whole domain, exactly as
    # before.
    window = p.get("x_range_cm")
    if window is not None:
        lo, hi = float(window[0]), float(window[1])
        contribution = np.where((x >= lo) & (x <= hi), contribution, 0.0)
    profiles = dict(state["species_profiles"])
    existing = profiles.get(species, np.zeros_like(x))
    profiles[species] = existing + contribution
    return {"x": x, "background": state["background"], "species_profiles": profiles}


def _anneal_species(flow, step):
    """The most recent enabled implant step before `step` in flow order --
    design section 9. Returns the species string, or None if there is
    none (validate_flow() rejects that case before run_flow ever gets
    here, so this should not be reachable in a successful run)."""
    last = None
    for s in flow.steps:
        if s.id == step.id:
            break
        if s.enabled and s.operation == "implant":
            last = s.parameters["species"]
    return last


def _run_anneal(step, state, species):
    """Diffuses ONLY `species`'s profile. `profiles` is a shallow copy of
    the dict -- every entry other than `species` is the exact same ndarray
    object as before this step, so it is provably untouched (not just
    numerically close)."""
    p = step.parameters
    x = state["x"]
    profiles = dict(state["species_profiles"])
    profiles[species] = process.diffuse_numeric(
        x, profiles[species], species, p["temperature_C"], p["time_s"])
    return {"x": x, "background": state["background"], "species_profiles": profiles}


def _run_oxidize(step, state):
    """Bookkeeping only -- x/background/species_profiles pass through as
    the SAME state dict object, unmodified (design section 7's oxidize
    semantics). Returns (state, bookkeeping)."""
    p = step.parameters
    thickness_um = process.oxide_thickness(p["temperature_C"], p["time_hours"],
                                           ambient=p["ambient"])
    consumed_um = process.silicon_consumed(thickness_um)
    return state, {"oxide_thickness_um": float(np.asarray(thickness_um)),
                   "silicon_consumed_um": float(np.asarray(consumed_um))}


def run_flow(flow_path, manifest_path):
    with open(flow_path) as fh:
        flow = ProcessFlow.from_dict(json.load(fh))

    errors = validate_flow(flow)
    if errors:
        raise ValueError("Process validation failed: " +
                         "; ".join(f"[{e.object_id}] {e.message}" for e in errors))

    # Final-review finding: JobRunner reuses ONE work directory across
    # every run in a session (one mkdtemp() per JobRunner instance, not
    # per run), and step IDs are stable across re-runs of the same flow.
    # Writing checkpoints directly into that shared directory meant a
    # second run silently overwrote the first run's "state-{step_id}.npz"
    # files in place -- if the second run then failed partway, some
    # checkpoint files were stale (the first run's data) while others
    # were missing/new, and the still-live ProcessResultStore from the
    # first run would point at that now-mixed set of files.
    #
    # manifest_path is already guaranteed unique per run (JobRunner.start()
    # generates a fresh uuid-based run_id for it on every call), so a
    # subdirectory named after the manifest's own stem is unique per run
    # too, with no need to plumb a run_id through separately. Every
    # checkpoint this run writes lives ONLY here -- a later run's
    # checkpoints can never collide with or overwrite this run's.
    manifest_dir = os.path.dirname(os.path.abspath(manifest_path))
    manifest_stem = os.path.splitext(os.path.basename(manifest_path))[0]
    state_dir = os.path.join(manifest_dir, f"{manifest_stem}-state")
    os.makedirs(state_dir, exist_ok=True)
    state_paths = {}
    step_ids = []
    state = None

    for step in flow.steps:
        if not step.enabled:
            continue
        print(f"PYTCAD_STAGE=step_{step.id}", flush=True)
        bookkeeping = {}

        if step.operation == "substrate":
            state = _run_substrate(step, state)
        elif step.operation == "implant":
            state = _run_implant(step, state)
        elif step.operation == "anneal":
            species = _anneal_species(flow, step)
            state = _run_anneal(step, state, species)
        elif step.operation == "oxidize":
            state, bookkeeping = _run_oxidize(step, state)
        else:
            raise ValueError(f"Unknown operation '{step.operation}'")

        net_doping, ntotal = reconstruct_doping(
            state["x"], state["background"], state["species_profiles"])

        out_path = os.path.join(state_dir, f"state-{step.id}.npz")
        tmp_path = out_path + ".tmp.npz"
        payload = {"x": state["x"], "background": np.asarray(state["background"]),
                  "net_doping": net_doping, "ntotal": ntotal}
        for species, C in state["species_profiles"].items():
            payload[f"species_{species}"] = C
        for key, value in bookkeeping.items():
            payload[f"bookkeeping_{key}"] = np.asarray(value)
        np.savez(tmp_path, **payload)
        os.replace(tmp_path, out_path)

        state_paths[step.id] = out_path
        step_ids.append(step.id)

    manifest = {"step_ids": step_ids, "state_paths": state_paths}
    tmp_manifest = manifest_path + ".tmp.json"
    with open(tmp_manifest, "w") as fh:
        json.dump(manifest, fh)
    os.replace(tmp_manifest, manifest_path)
    print(f"RESULT_PATH={manifest_path}", flush=True)


def main(argv):
    if len(argv) != 3:
        print("usage: python -m gui.services.process_runner <flow.json> <manifest.json>",
              file=sys.stderr)
        return 2
    try:
        run_flow(argv[1], argv[2])
    except Exception as exc:
        payload = {"error": type(exc).__name__, "message": str(exc),
                  "traceback": traceback.format_exc()}
        print("PYTCAD_ERROR=" + json.dumps(payload), file=sys.stderr, flush=True)
        print(payload["traceback"], file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
