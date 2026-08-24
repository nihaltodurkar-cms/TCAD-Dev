"""DEVSIM solver backend (M7): a GENUINE second backend behind the M3
protocol.  Builds its own DEVSIM mesh/device from the SAME DeviceSpec
JSON job the pytcad runner consumes (1D, two ohmic contacts), solves
full drift-diffusion equilibrium using DEVSIM's canonical silicon
physics (devsim.python_packages.simple_physics -- Scharfetter-Gummel,
Boltzmann statistics, SRH), and emits a schema-v2 result file.

Equilibrium-only slice for this milestone: spec.bias is recorded in the
provenance but not ramped.  The cross-backend benchmark test compares
the equilibrium solution against the pytcad backend on identical meshes
and doping -- agreement there is the validation gate before any UI
exposure.

DEVSIM is an OPTIONAL dependency: importing this module without it
raises ImportError with an actionable message.
"""
import json
import os

import numpy as np

from .base import SolveRequest


def _require_devsim():
    try:
        import devsim  # noqa: F401
        return
    except ImportError as exc:
        raise ImportError(
            "the devsim backend requires the optional 'devsim' package "
            f"(pip install devsim): {exc}") from exc


class DevsimBackend:
    id = "devsim"

    def run(self, request: SolveRequest) -> None:
        _require_devsim()
        import devsim
        from devsim.python_packages.model_create import CreateSolution
        from devsim.python_packages.simple_physics import (
            CreateSiliconDriftDiffusion,
            CreateSiliconDriftDiffusionAtContact,
            CreateSiliconPotentialOnly,
            CreateSiliconPotentialOnlyContact,
            GetContactBiasName,
            SetSiliconParameters,
        )

        from gui.services.device_spec import DeviceSpec

        spec = DeviceSpec.from_json(request.job_json_path)
        if spec.mesh.dimensionality != 1:
            raise ValueError(
                "the devsim backend currently solves 1D devices only")
        ohmic = [c for c in spec.contacts if c.kind == "ohmic"]
        if len(ohmic) != 2:
            raise ValueError(
                "the devsim backend needs exactly two ohmic contacts")

        x = np.asarray(spec.mesh.axes["x"], dtype=float)
        doping = np.asarray(spec.doping.values, dtype=float)

        # ---- mesh: OUR nodes, verbatim ----
        import uuid
        dev, reg, mesh = ("job_" + uuid.uuid4().hex[:8], "silicon",
                          "mesh_" + uuid.uuid4().hex[:8])
        devsim.create_1d_mesh(mesh=mesh)
        # ps equals the FULL segment length on every line, so the mesh
        # contains EXACTLY our spec nodes -- no extra interpolation nodes
        prev = None
        for i, pos in enumerate(x):
            if i == 0:
                spacing = float(x[1] - x[0])
            elif i == len(x) - 1:
                spacing = float(x[-1] - x[-2])
            else:
                spacing = float(pos - prev)
            devsim.add_1d_mesh_line(mesh=mesh, pos=float(pos),
                                    ps=max(spacing, 1e-14), tag=f"n{i}")
            prev = pos
        devsim.add_1d_contact(mesh=mesh, name=ohmic[0].name, tag="n0",
                              material="metal")
        devsim.add_1d_contact(mesh=mesh, name=ohmic[1].name,
                              tag=f"n{len(x)-1}", material="metal")
        devsim.add_1d_region(mesh=mesh, material="Si", region=reg,
                             tag1="n0", tag2=f"n{len(x)-1}")
        devsim.finalize_mesh(mesh=mesh)
        devsim.create_device(mesh=mesh, device=dev)

        SetSiliconParameters(dev, reg, 300)
        devsim.node_solution(device=dev, region=reg, name="Donors")
        devsim.node_solution(device=dev, region=reg, name="Acceptors")
        devsim.set_node_values(device=dev, region=reg, name="Donors",
                               values=np.maximum(doping, 0.0).tolist())
        devsim.set_node_values(device=dev, region=reg, name="Acceptors",
                               values=np.maximum(-doping, 0.0).tolist())
        devsim.node_model(device=dev, region=reg, name="NetDoping",
                          equation="Donors-Acceptors")

        CreateSolution(device=dev, region=reg, name="Potential")
        CreateSiliconPotentialOnly(device=dev, region=reg)
        for c in devsim.get_contact_list(device=dev):
            devsim.set_parameter(
                device=dev, name=GetContactBiasName(c), value=0.0)
            CreateSiliconPotentialOnlyContact(dev, reg, c)
        devsim.solve(type="dc", absolute_error=1e10, relative_error=1e-10,
                     maximum_iterations=30)

        # full drift-diffusion equilibrium on top of the potential-only
        # solution (canonical two-stage start)
        CreateSolution(device=dev, region=reg, name="Electrons")
        CreateSolution(device=dev, region=reg, name="Holes")
        devsim.set_node_values(device=dev, region=reg, name="Electrons",
                               init_from="IntrinsicElectrons")
        devsim.set_node_values(device=dev, region=reg, name="Holes",
                               init_from="IntrinsicHoles")
        CreateSiliconDriftDiffusion(device=dev, region=reg)
        for c in devsim.get_contact_list(device=dev):
            CreateSiliconDriftDiffusionAtContact(dev, reg, c)
        devsim.solve(type="dc", absolute_error=1e12, relative_error=1e-10,
                     maximum_iterations=30)

        # ---- extract into the shared grammar ----
        def node(name):
            return np.asarray(
                devsim.get_node_model_values(device=dev, region=reg,
                                             name=name), dtype=float)

        psi = node("Potential")
        n = node("Electrons")
        p = node("Holes")
        j_edge = (np.asarray(devsim.get_edge_model_values(
            device=dev, region=reg, name="ElectronCurrent"))
            + np.asarray(devsim.get_edge_model_values(
                device=dev, region=reg, name="HoleCurrent")))
        j_node = np.empty_like(x)
        j_node[:-1] = j_edge
        j_node[-1] = j_edge[-1]

        result = {
            "dimensionality": np.array(1),
            "solved_bias": np.array(True),
            "axis_x": x,
            "field__potential": psi,
            "unit__potential": np.array("V"),
            "field__electron_density": n,
            "unit__electron_density": np.array("cm^-3"),
            "field__hole_density": p,
            "unit__hole_density": np.array("cm^-3"),
            "field__doping": doping,
            "unit__doping": np.array("cm^-3"),
            "vector__current_density__x": j_node,
            "unit__current_density": np.array("A/cm^2"),
        }
        for c in ohmic:
            result[f"terminal__{c.name}__value"] = np.array(0.0)
            result[f"terminal__{c.name}__unit"] = np.array("A/cm^2")

        result["result__schema"] = np.array(2)
        result["geom__kind"] = np.array("structured_rectilinear")
        result["mesh__shape"] = np.array([x.size])
        result["nodes__count"] = np.array(int(x.size))
        result["nodes__coords"] = x.reshape(-1, 1)
        result["record__meta"] = np.array(json.dumps({
            "schema_version": 2,
            "backend": "devsim",
            "created_utc": "",
            "dimensionality": 1,
            "material": spec.material,
            "T": spec.T,
            "models": {"engine": "devsim.simple_physics drift-diffusion"},
            "numerics": {},
            "sweep": None,
        }))

        tmp_path = request.out_npz_path + ".tmp.npz"
        np.savez(tmp_path, **result)
        os.replace(tmp_path, request.out_npz_path)
