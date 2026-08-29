"""GUI-only process flow model.  No Qt import, no mutable-array state --
mirrors structure_model.py's own header convention.  See design spec
docs/superpowers/specs/2026-08-23-gui-v0.3-process-workbench-design.md
section 5 and 7.

reconstruct_doping() is the ONE place net_doping/ntotal are computed
from a (background, species_profiles) pair -- process_runner.py, the
Process -> Device handoff, and the Derived Quantities panel all call
this, never a second hand-written formula (design section 21's audit).
"""
from dataclasses import dataclass, field, asdict
import copy
import json
import uuid

import math

import numpy as np

from pytcad.process import DOPANT_TYPE


def reconstruct_doping(x, background, species_profiles):
    """x: ndarray (cm), used only for shape -- correct even with an empty
    species_profiles (right after a `substrate` step).
    background: float, cm^-3, signed.
    species_profiles: {species: ndarray (cm^-3), ...} -- unsigned
    concentrations, exactly what process.implant()/diffuse_numeric() return.
    Returns (net_doping, ntotal), both ndarray shaped like x."""
    x = np.asarray(x, dtype=float)
    net = np.full_like(x, background, dtype=float)
    ntotal = np.full_like(x, abs(background), dtype=float)
    for species, C in species_profiles.items():
        C = np.asarray(C, dtype=float)
        net = net + DOPANT_TYPE[species] * C
        ntotal = ntotal + C
    return net, ntotal


@dataclass
class ProcessStep:
    id: str
    name: str
    operation: str              # "substrate" | "implant" | "anneal" | "oxidize"
    enabled: bool = True
    parameters: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


@dataclass
class ProcessFlow:
    steps: list = field(default_factory=list)

    def add_step(self, step):
        self.steps.append(step)

    def remove_step(self, step_id):
        self.steps = [s for s in self.steps if s.id != step_id]

    def find_step(self, step_id):
        return next((s for s in self.steps if s.id == step_id), None)

    def move_step(self, step_id, offset):
        """Same clamped-offset contract as StructureModel.move_region."""
        idx = next((k for k, s in enumerate(self.steps) if s.id == step_id), None)
        if idx is None:
            return
        new_idx = max(0, min(len(self.steps) - 1, idx + offset))
        if new_idx == idx:
            return
        step = self.steps.pop(idx)
        self.steps.insert(new_idx, step)

    def duplicate_step(self, step_id):
        original = self.find_step(step_id)
        if original is None:
            return None
        dup = ProcessStep(id=uuid.uuid4().hex[:8], name=original.name + " (copy)",
                          operation=original.operation, enabled=original.enabled,
                          parameters=copy.deepcopy(original.parameters))
        idx = self.steps.index(original)
        self.steps.insert(idx + 1, dup)
        return dup

    def to_dict(self):
        return {"steps": [s.to_dict() for s in self.steps]}

    @classmethod
    def from_dict(cls, d):
        return cls(steps=[ProcessStep.from_dict(s) for s in d.get("steps", [])])

    def to_json(self, path):
        """Mirrors DeviceSpec.to_json's exact contract (gui/services/
        device_spec.py) -- this is what lets AppController hand a
        ProcessFlow straight to JobRunner.start() (it calls
        `spec.to_json(job_path)` generically on whatever it is given),
        retiring the _ProcessFlowJob adapter that used to bridge the gap
        because this method didn't exist yet."""
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh)

    @classmethod
    def from_json(cls, path):
        with open(path) as fh:
            return cls.from_dict(json.load(fh))


# Validation
from .structure_model import ValidationError
from pytcad.process import _IMPLANT_TABLE, DIFFUSIVITY


def _implant_energy_range(species):
    table = _IMPLANT_TABLE.get(species)
    if table is None:
        return None
    energies = sorted(table)
    return energies[0], energies[-1]


def validate_flow(flow):
    errors = []
    enabled_steps = [s for s in flow.steps if s.enabled]

    if not enabled_steps or enabled_steps[0].operation != "substrate":
        errors.append(ValidationError(
            "Flow must start with an enabled Initialize Substrate step"))

    # A real wafer is only initialized once: process_runner._run_substrate
    # resets species_profiles to {} every time it runs, so a second
    # enabled substrate step silently wipes out everything implanted
    # before it -- any anneal step referencing a species implanted before
    # that reset then KeyErrors in process_runner._anneal_species (species
    # no longer present in the freshly-reset species_profiles dict).
    # Rejecting more than one enabled substrate step up front is simpler
    # and more honest than trying to make later steps resilient to a
    # mid-flow re-initialization that doesn't correspond to anything a
    # real process actually does.
    enabled_substrate_steps = [s for s in enabled_steps if s.operation == "substrate"]
    if len(enabled_substrate_steps) > 1:
        errors.append(ValidationError(
            "Only one enabled Initialize Substrate step is allowed per "
            "flow -- a real wafer is only initialized once"))

    last_implant_species = None
    steps = flow.steps
    for i, step in enumerate(steps):
        p = step.parameters
        if step.operation == "substrate":
            if p.get("length_cm", 0.0) <= 0:
                errors.append(ValidationError("Length must be > 0", step.id))
            if p.get("background_doping_cm3", 0.0) == 0:
                errors.append(ValidationError(
                    "Background doping must be nonzero", step.id))
            mesh = p.get("mesh", {})
            if mesh.get("h_min_cm", 0.0) <= 0:
                errors.append(ValidationError("Mesh h_min must be > 0", step.id))
            if mesh.get("h_max_cm", 0.0) < mesh.get("h_min_cm", 0.0):
                errors.append(ValidationError("Mesh h_max must be >= h_min", step.id))
            if mesh.get("ratio", 0.0) <= 1.0:
                errors.append(ValidationError("Mesh ratio must be > 1.0", step.id))

        elif step.operation == "implant":
            species = p.get("species")
            if species not in _IMPLANT_TABLE:
                errors.append(ValidationError(
                    f"Species '{species}' is not supported for implantation "
                    f"(available: {list(_IMPLANT_TABLE)})", step.id))
            else:
                lo, hi = _implant_energy_range(species)
                energy = p.get("energy_keV", 0.0)
                if not (lo <= energy <= hi):
                    errors.append(ValidationError(
                        f"Energy {energy} keV is outside the tabulated range "
                        f"for {species} ({lo}-{hi} keV)", step.id))
            if p.get("dose_cm2", 0.0) <= 0:
                errors.append(ValidationError("Dose must be > 0", step.id))
            # v0.5.0 M6: OPTIONAL ion-implanter window.  Absent -> the
            # implant covers the whole domain exactly as before.
            rng = p.get("x_range_cm")
            if rng is not None:
                ok = (isinstance(rng, (list, tuple)) and len(rng) == 2 and
                      all(isinstance(v, (int, float)) and math.isfinite(v)
                          for v in rng) and float(rng[0]) < float(rng[1]))
                if not ok:
                    errors.append(ValidationError(
                        f"x_range_cm must be [lo, hi] with lo < hi "
                        f"(finite numbers), got {rng!r}", step.id))
                elif rng[0] < 0:
                    errors.append(ValidationError(
                        f"x_range_cm lo must be >= 0, got {rng[0]!r}",
                        step.id))
            tilt = p.get("tilt_deg", 0.0)
            if not (0.0 <= tilt < 90.0):
                errors.append(ValidationError(
                    f"Tilt {tilt} deg must be in [0, 90) -- process.implant scales "
                    "Rp by cos(tilt), which is zero or negative at or above "
                    "90 deg", step.id))
            # a window beyond the substrate would silently no-op the
            # whole implant -- reject it instead
            if step.enabled and rng is not None and ok:
                length = next((st.parameters.get("length_cm")
                               for st in reversed(steps[:i + 1])
                               if st.operation == "substrate"), None)
                if length is not None and float(rng[1]) > float(length):
                    errors.append(ValidationError(
                        f"x_range_cm hi {float(rng[1]):g} exceeds the "
                        f"substrate length {float(length):g} -- the whole "
                        "implant would land outside the device",
                        step.id))
            if step.enabled:
                last_implant_species = species

        elif step.operation == "anneal":
            if p.get("temperature_C", -1000.0) <= -273.15:
                errors.append(ValidationError(
                    "Temperature must be above absolute zero", step.id))
            if p.get("time_s", 0.0) <= 0:
                errors.append(ValidationError("Time must be > 0", step.id))
            if step.enabled and last_implant_species is None:
                errors.append(ValidationError(
                    "No preceding enabled Implant step to diffuse", step.id))

        elif step.operation == "oxidize":
            if p.get("temperature_C", -1000.0) <= -273.15:
                errors.append(ValidationError(
                    "Temperature must be above absolute zero", step.id))
            if p.get("time_hours", 0.0) <= 0:
                errors.append(ValidationError("Time must be > 0", step.id))
            if p.get("ambient") not in ("dry", "wet"):
                errors.append(ValidationError(
                    "Ambient must be 'dry' or 'wet'", step.id))

        else:
            errors.append(ValidationError(f"Unknown operation '{step.operation}'", step.id))

    return errors
