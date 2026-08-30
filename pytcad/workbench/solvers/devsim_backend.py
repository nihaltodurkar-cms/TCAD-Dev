"""DEVSIM solver backend (M7): a GENUINE second backend behind the M3
protocol.  Builds its own DEVSIM mesh/device from the SAME DeviceSpec
JSON job the pytcad runner consumes (1D, two ohmic contacts), solves
full drift-diffusion using DEVSIM's canonical silicon physics
(devsim.python_packages.simple_physics -- Scharfetter-Gummel, Boltzmann
statistics, SRH), and emits a schema-v2 result file.

Bias support mirrors the pytcad reference backend's semantics:
  - spec.sweep  -> warm-started single-contact ramp, emitting the full
    documented sweep__* block with per-point convergence flags taken
    from devsim's own solve(info=True) verdict plus a physicality check;
  - spec.bias   -> contact biases ramped from equilibrium in fixed
    voltage steps (diode_common.py's canonical pattern), fields read at
    the target bias;
  - neither     -> equilibrium only.
Every stage's Newton history lands in converge__trace in the same JSON
shape gui.services.solver_runner writes, so RunRecord parsing and the
Physics Lab convergence view work unchanged.

The cross-backend benchmark test compares the I-V curve against the
pytcad backend on identical meshes and doping -- agreement there is the
validation gate before any UI exposure.

DEVSIM is an OPTIONAL dependency: importing this module without it
raises ImportError with an actionable message.
"""
import json
import math
import os
from datetime import datetime, timezone

import numpy as np

from .base import SolveRequest
from gui.services.solver_backend import SOLVER_RESULT_SCHEMA_VERSION


def _require_devsim():
    try:
        import devsim  # noqa: F401
        return
    except ImportError as exc:
        raise ImportError(
            "the devsim backend requires the optional 'devsim' package "
            f"(pip install devsim): {exc}") from exc


def check_devsim_compatible(spec):
    """Raise ValueError with an actionable message if `spec` is not
    something this backend can honestly solve; return None if it is.

    A SINGLE source of truth for "can devsim run this job", called by
    run() below AND by the GUI's backend selector (v0.6 Phase 2c) --
    the selector greys out "devsim" using this SAME function, wrapped
    in a try/except, rather than a separately-maintained guess that
    could silently drift from what run() actually enforces.

    The last two checks are NEW (2026-08-29): this backend never reads
    spec.models or spec.region_materials at all -- it always runs its
    own fixed canonical physics (Scharfetter-Gummel, Boltzmann, SRH)
    regardless of what either says, so a job asking for anything else
    (a non-default model config, a heterostructure) was previously
    solved SILENTLY WRONG rather than refused -- the exact "hidden
    failure" this codebase's house rule (see e.g. Device1D/2D/3D's own
    dg/impact/incomplete_ion guards) exists to catch elsewhere."""
    if spec.mesh.dimensionality != 1:
        raise ValueError(
            "the devsim backend currently solves 1D devices only")
    ohmic = [c for c in spec.contacts if c.kind == "ohmic"]
    if len(ohmic) != 2:
        raise ValueError(
            "the devsim backend needs exactly two ohmic contacts")
    if any(c.kind == "gate" for c in spec.contacts):
        raise ValueError(
            "the devsim backend does not support gate contacts")
    if spec.region_materials is not None:
        raise ValueError(
            "the devsim backend does not accept region_materials "
            "(heterostructure jobs must use the pytcad backend)")
    if spec.transient is not None:
        # M17 phase 3: this backend's run() has no transient dispatch
        # at all -- an armed transient config would otherwise be
        # silently ignored and solved as a plain bias/sweep job instead,
        # exactly the "hidden failure" this function's other checks
        # already exist to catch.
        raise ValueError(
            "the devsim backend does not support transient (time-domain) "
            "runs (use the pytcad backend)")
    from gui.services.device_spec import _default_models
    if spec.models != _default_models():
        raise ValueError(
            "the devsim backend always runs its own fixed canonical "
            "physics (Scharfetter-Gummel, Boltzmann statistics, SRH) "
            "and ignores the Physics Lab's model config entirely -- "
            "a non-default model selection would be silently solved "
            "without the requested physics, so this is refused rather "
            "than doing that quietly (use the pytcad backend for any "
            "custom model configuration)")


class DevsimBackend:
    id = "devsim"

    # bias-ramp step size [V]: small enough that each Newton solve is a
    # warm-started perturbation of the previous solution (the canonical
    # diode_common.py pattern), coarse enough to keep sweeps short.
    RAMP_STEP_V = 0.05

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
        check_devsim_compatible(spec)
        ohmic = [c for c in spec.contacts if c.kind == "ohmic"]
        bias = {c.name: float((spec.bias or {}).get(c.name, c.V))
                for c in ohmic}
        if spec.sweep is not None:
            # fail fast on an unexecutable sweep, before paying for the
            # equilibrium solve (same contract as solver_runner.run_job)
            spec.sweep.validate([c.name for c in spec.contacts])

        x = np.asarray(spec.mesh.axes["x"], dtype=float)
        doping = np.asarray(spec.doping.values, dtype=float)

        # ---- mesh: OUR nodes, verbatim ----
        import uuid
        dev, reg, mesh = ("job_" + uuid.uuid4().hex[:8], "silicon",
                          "mesh_" + uuid.uuid4().hex[:8])
        def _cleanup_devsim_state():
            """Delete this job's device and mesh.  devsim's solve() is
            PROCESS-GLOBAL (it takes no device argument), so anything
            left behind -- especially a diverged state from an earlier
            job or sweep point -- would fail every later solve in this
            process with 'Convergence failure!'."""
            import contextlib
            with contextlib.suppress(Exception):
                devsim.delete_device(device=dev)
            with contextlib.suppress(Exception):
                devsim.delete_mesh(mesh=mesh)

        try:
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
            # NOTE: devsim's solve() takes no device argument -- it solves
            # EVERY device in its process-global registry.  The run() body
            # therefore wraps everything in try/finally and deletes this
            # job's device (and mesh) on the way out: a stale diverged
            # device left behind by an earlier job would otherwise fail the
            # next job's solves with "Convergence failure!".
            devsim.solve(type="dc", absolute_error=1e10,
                         relative_error=1e-10, maximum_iterations=30)

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

            # ---- solve orchestration ------------------------------------------
            # Every solve records its Newton history into trace_steps in the
            # same dict shape ConvergenceStep.to_dict() produces on the
            # pytcad side, so converge__trace consumers cannot tell the
            # backends apart.
            trace_steps = []

            def node(name):
                return np.asarray(
                    devsim.get_node_model_values(device=dev, region=reg,
                                                 name=name), dtype=float)

            def snapshot():
                return (node("Potential").copy(), node("Electrons").copy(),
                        node("Holes").copy())

            def restore(snap):
                for name, vals in zip(("Potential", "Electrons", "Holes"),
                                      snap):
                    devsim.set_node_values(device=dev, region=reg, name=name,
                                           values=vals.tolist())

            def state_is_physical():
                n, p = node("Electrons"), node("Holes")
                return bool(np.all(np.isfinite(n)) and np.all(n >= 0.0)
                            and np.all(np.isfinite(p)) and np.all(p >= 0.0))

            def solve_recorded(stage):
                """One warm-started DC solve.  Returns devsim's own converged
                verdict ANDed with a finite/positive carrier check -- a
                solver that 'converged' onto NaN or negative densities has
                not solved anything.  On failure the last good solution is
                restored so later points do not warm-start from garbage."""
                snap = snapshot()
                try:
                    info = devsim.solve(
                        type="dc", absolute_error=1e12,
                        relative_error=1e-10, maximum_iterations=30,
                        info=True)
                    ok = bool(info.get("converged")) and state_is_physical()
                except Exception:
                    ok = False
                    info = {"converged": False, "iterations": ()}
                iters = info.get("iterations") or ()
                abs_errs = []
                for entry in iters:
                    for device_err in entry.get("devices", ()):
                        abs_errs.append(float(device_err.get("absolute_error",
                                                             0.0)))
                if any(not math.isfinite(e) for e in abs_errs):
                    abs_errs = [e if math.isfinite(e) else None
                                for e in abs_errs]
                if not ok:
                    restore(snap)
                trace_steps.append({
                    "stage": stage,
                    "iterations": [int(e.get("iteration", i))
                                   for i, e in enumerate(iters)],
                    "metrics": {"AbsError": abs_errs},
                    "converged": ok,
                })
                return ok

            def set_contact_bias(name, value):
                devsim.set_parameter(
                    device=dev,
                    name=GetContactBiasName(name), value=float(value))

            def ramp_contacts(targets, stage_prefix):
                """Ramp every contact from its present value to `targets`
                in fixed voltage steps, warm-starting each solve from the
                previous point.  Returns True only if the final target
                point converged."""
                n_steps = max(1, int(math.ceil(
                    max(abs(v) for v in targets.values()) / self.RAMP_STEP_V)))
                ok = False
                for i in range(1, n_steps + 1):
                    frac = i / n_steps
                    for cname, v_target in targets.items():
                        set_contact_bias(cname, v_target * frac)
                    ok = solve_recorded(f"{stage_prefix}" if i == n_steps
                                        else f"{stage_prefix}_ramp{i}")
                return ok

            # equilibrium drift-diffusion solve (the second of the two-stage
            # start); recorded as the "equilibrium" trace stage
            eq_ok = solve_recorded("equilibrium")

            def extract_fields(solved_bias):
                psi, n, p = node("Potential"), node("Electrons"), node("Holes")
                j_edge = (np.asarray(devsim.get_edge_model_values(
                    device=dev, region=reg, name="ElectronCurrent"))
                    + np.asarray(devsim.get_edge_model_values(
                        device=dev, region=reg, name="HoleCurrent")))
                j_node = np.empty_like(x)
                j_node[:-1] = j_edge
                j_node[-1] = j_edge[-1]
                return {
                    "dimensionality": np.array(1),
                    "solved_bias": np.array(bool(solved_bias)),
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

            def mean_current():
                j_edge = (np.asarray(devsim.get_edge_model_values(
                    device=dev, region=reg, name="ElectronCurrent"))
                    + np.asarray(devsim.get_edge_model_values(
                        device=dev, region=reg, name="HoleCurrent")))
                return float(j_edge[0])

            result = None
            sweep_meta = None
            if spec.sweep is not None:
                sw = spec.sweep
                # Snapshot the equilibrium state BEFORE the sweep mutates the
                # device: if every point diverges, this honestly-labeled
                # solved_bias=False snapshot is what gets stored -- never a
                # diverged nonphysical field set (mirrors run_sweep's
                # fallback contract).
                fallback_fields = extract_fields(solved_bias=False)
                voltages = sw.voltages()
                currents = []
                flags = []
                fields = None
                for i, V in enumerate(voltages):
                    set_contact_bias(sw.contact, V)
                    ok = solve_recorded(f"sweep:{i}")
                    flags.append(ok)
                    # the writer records the measured value even at a
                    # diverged point; applying NaN is the STORE's documented
                    # job (see the grammar header in solver_backend.py)
                    currents.append(mean_current())
                    if ok:
                        fields = extract_fields(solved_bias=True)
                result = fields if fields is not None else fallback_fields
                sweep_meta = {"contact": sw.contact, "start": sw.start,
                              "stop": sw.stop, "step": sw.step,
                              "dimensionality": 1}
                result["sweep__voltage"] = np.asarray(voltages, dtype=float)
                result["sweep__converged"] = np.asarray(flags, dtype=bool)
                result["unit__sweep_current"] = np.array("A/cm^2")
                result["sweep__meta"] = np.array(json.dumps(sweep_meta))
                result["sweep__current__device"] = np.asarray(currents,
                                                              dtype=float)
            elif any(abs(v) > 1e-12 for v in bias.values()):
                ramp_contacts(bias, stage_prefix="bias")
                result = extract_fields(solved_bias=True)
            else:
                result = extract_fields(solved_bias=bool(eq_ok))

            # No terminal__<contact>__value/unit here: those keys are the
            # 2D/3D per-contact convention ("A/cm"/"A"); Device1D has no
            # terminal registry and the 1D current convention is the total
            # current density above.

            # M17 phase 3: stamped from the live constant, not a
            # hardcoded literal, so this backend's version tracks
            # solver_backend.py's automatically -- it emits no
            # transient__* keys (that's pytcad-backend-only, gated by
            # DeviceSpec.transient/check_devsim_compatible), so an
            # unbumped devsim result is still fully valid under
            # whatever the CURRENT version number is, additive as ever.
            result["result__schema"] = np.array(SOLVER_RESULT_SCHEMA_VERSION)
            result["geom__kind"] = np.array("structured_rectilinear")
            result["mesh__shape"] = np.array([x.size])
            result["nodes__count"] = np.array(int(x.size))
            result["nodes__coords"] = x.reshape(-1, 1)
            result["record__meta"] = np.array(json.dumps({
                "schema_version": SOLVER_RESULT_SCHEMA_VERSION,
                "backend": "devsim",
                "created_utc": datetime.now(timezone.utc)
                                     .isoformat(timespec="seconds"),
                "dimensionality": 1,
                "material": spec.material,
                "T": spec.T,
                "models": {"engine": "devsim.simple_physics drift-diffusion"},
                "numerics": {"ramp_step_v": self.RAMP_STEP_V,
                             "maximum_iterations": 30},
                "sweep": sweep_meta,
            }))
            result["converge__trace"] = np.array(
                json.dumps(trace_steps))

            tmp_path = request.out_npz_path + ".tmp.npz"
            np.savez(tmp_path, **result)
            os.replace(tmp_path, request.out_npz_path)
        finally:
            _cleanup_devsim_state()

