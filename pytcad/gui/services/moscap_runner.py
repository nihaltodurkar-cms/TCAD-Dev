"""C-V solver job: MOSCapacitor.cv_sweep as a subprocess entry point.

    python -m gui.services.moscap_runner <job.json> <out.npz>

Same contract as solver_runner: DeviceSpec-free JSON job in, schema-v2
npz out (validated on load by the ordinary ResultStore).  The x axis of
the result IS the swept gate voltage; the single sweep channel carries
the small-signal capacitance in F/cm^2.
"""
import json
import os
import sys
import traceback

import numpy as np

from gui.services.solver_backend import (
    GEOM_STRUCTURED, SOLVER_RESULT_SCHEMA_VERSION,
)


def run_job(job_path, out_path):
    with open(job_path) as fh:
        p = json.load(fh)

    from pytcad import MOSCapacitor
    mos = MOSCapacitor(Nsub=float(p["nsub_cm3"]),
                       tox_cm=float(p["tox_nm"]) * 1e-7,
                       gate=p.get("gate", "n+poly"),
                       Qf=float(p.get("qf_cm2", 0.0)),
                       T=float(p.get("T", 300.0)))
    vg = np.arange(float(p["vstart"]), float(p["vstop"]) + 1e-9,
                   abs(float(p["vstep"])))
    _phis, _qg, c = mos.cv_sweep(vg)
    c = np.asarray(c, dtype=float)

    result = {
        "dimensionality": np.array(1),
        "solved_bias": np.array(True),
        "axis_x": vg,
        "field__capacitance": c,
        "unit__capacitance": np.array("F/cm^2"),
        "field__gate_charge": np.asarray(_qg, dtype=float),
        "unit__gate_charge": np.array("C/cm^2"),
        "result__schema": np.array(SOLVER_RESULT_SCHEMA_VERSION),
        "geom__kind": np.array(GEOM_STRUCTURED),
        "mesh__shape": np.array([vg.size]),
        "nodes__count": np.array(int(vg.size)),
        "nodes__coords": vg.reshape(-1, 1),
        "sweep__voltage": vg,
        "sweep__converged": np.ones(vg.size, dtype=bool),
        "sweep__current__device": c,
        "unit__sweep_current": np.array("F/cm^2"),
        "sweep__meta": np.array(json.dumps({
            "contact": "gate", "start": float(vg[0]),
            "stop": float(vg[-1]), "step": float(p["vstep"]),
            "dimensionality": 1, "quantity": "capacitance",
        })),
        "record__meta": np.array(json.dumps({
            "schema_version": SOLVER_RESULT_SCHEMA_VERSION,
            "backend": "moscap",
            "created_utc": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
            "dimensionality": 1,
            "material": "SILICON",
            "T": float(p.get("T", 300.0)),
            "models": {"engine": "MOSCapacitor quasi-static C-V"},
            "numerics": {},
            "sweep": {"contact": "gate", "dimensionality": 1},
        })),
    }
    tmp = out_path + ".tmp.npz"
    np.savez(tmp, **result)
    os.replace(tmp, out_path)
    print(f"RESULT_PATH={out_path}", flush=True)


def main(argv):
    if len(argv) != 3:
        print("usage: python -m gui.services.moscap_runner "
              "<job.json> <out.npz>", file=sys.stderr)
        return 2
    try:
        run_job(argv[1], argv[2])
    except Exception as exc:
        payload = {"error": type(exc).__name__, "message": str(exc),
                   "traceback": __import__("traceback").format_exc()}
        print("PYTCAD_ERROR=" + json.dumps(payload), file=sys.stderr,
              flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
