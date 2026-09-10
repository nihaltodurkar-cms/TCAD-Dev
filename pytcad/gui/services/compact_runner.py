"""M38 Phase 4: compact-model extraction as a subprocess entry point.

    python -m gui.services.compact_runner <job.json> <out.json>

Same stdout/atomic-write contract as `process_runner.py`: a JSON
manifest out (`RESULT_PATH=`, `.tmp.json` + os.replace), not an npz --
a fitted parameter set is not sweep/mesh data, so it does not go
through `ResultStore`. Builds a REAL `Device1D` p-n diode or
`Device2D` n-MOSFET directly from scalar geometry, sweeps it, and fits
`workbench.compact.extract_diode`/`extract_mosfet1` to the result --
the same construction the library's own G1-TCAD/G2-TCAD gates use in
`tests/test_m38_compact_model.py`.

Plan: `M38-PHASE4-PLAN.md`.
"""
import json
import os
import sys

import numpy as np


def _run_diode(p):
    from pytcad import Device1D, Models, NewtonOptions
    from pytcad.mesh import graded_mesh
    from workbench.compact import extract_diode, to_netlist

    L = float(p["L_um"]) * 1e-4
    xj = float(p["xj_um"]) * 1e-4
    Na = float(p["Na"])
    Nd = float(p["Nd"])
    x = graded_mesh(L, [xj], h_min=1.0e-8, h_max=1.0e-6, ratio=1.12)
    doping = np.where(x < xj, -Na, Nd)

    dev = Device1D(x, doping, T=300.0, models=Models(bgn=False, auger=True))
    V = np.arange(float(p["v_start"]), float(p["v_stop"]) + 1e-9,
                  abs(float(p["v_step"])))
    J = dev.iv_sweep(V, verbose=False)

    v_window = None
    if p.get("v_fit_min") is not None and p.get("v_fit_max") is not None:
        v_window = (float(p["v_fit_min"]), float(p["v_fit_max"]))

    params = extract_diode(V, J, float(p["scale"]), v_window=v_window)
    netlist = to_netlist(params)
    J_fit = np.where(V > 0.0,
                     params.Is * np.expm1(V / (params.N * params.VT))
                     / params.scale, 0.0)
    return {
        "kind": "diode",
        "converged": bool(params.converged),
        "scale": params.scale,
        "params": {"Is": params.Is, "N": params.N, "VT": params.VT,
                    "rms_log_error": params.rms_log_error,
                    "n_points": params.n_points,
                    "v_min": params.v_min, "v_max": params.v_max},
        "netlist": netlist,
        "curve": {"v": V.tolist(), "i_tcad": np.asarray(J).tolist(),
                   "i_fit": J_fit.tolist()},
    }


def _run_mosfet(p):
    from pytcad.device import NewtonOptions
    from pytcad.mosfet import build_mosfet, id_vg_sweep
    from workbench.compact import (
        IdVdCurve, IdVgCurve, extract_mosfet1, mosfet1_current, to_netlist,
    )

    # sigma_y/sigma_lat/nx/ny default to the exact values
    # `tests/test_m38_compact_model.py`'s own G2-TCAD fixture uses
    # (sharper junctions than build_mosfet's own Lg/4 default) --
    # measured to give a clean, monotonic Id-Vg/Id-Vd family; a caller
    # may override them but the defaults are a validated geometry, not
    # a guess.
    dev = build_mosfet(
        Lg=float(p["Lg_um"]) * 1e-4, Lsd=float(p["Lsd_um"]) * 1e-4,
        depth=float(p["depth_um"]) * 1e-4, Na=float(p["Na"]),
        Nsd_peak=float(p["Nsd_peak"]), tox_cm=float(p["tox_nm"]) * 1e-7,
        sigma_y=float(p.get("sigma_y_um", 0.05)) * 1e-4,
        sigma_lat=float(p.get("sigma_lat_um", 0.05)) * 1e-4,
        nx=int(p.get("nx", 48)), ny=int(p.get("ny", 28)))
    opts = NewtonOptions()
    dev.solve_equilibrium(opts)

    vg = np.arange(float(p["vg_start"]), float(p["vg_stop"]) + 1e-9,
                   abs(float(p["vg_step"])))
    vds_lin = float(p["vds_lin"])
    ig = []
    for v in vg:
        dev.solve_bias({"drain": vds_lin, "gate": float(v)}, opts)
        ig.append(dev.terminal_current("drain"))
    ig = np.array(ig)

    vd = np.arange(float(p["vd_start"]), float(p["vd_stop"]) + 1e-9,
                   abs(float(p["vd_step"])))
    vgs_sat = float(p["vgs_sat"])
    idd = []
    for v in vd:
        dev.solve_bias({"drain": float(v), "gate": vgs_sat}, opts)
        idd.append(dev.terminal_current("drain"))
    idd = np.array(idd)

    params = extract_mosfet1(IdVgCurve(vg, ig, vds_lin),
                             IdVdCurve(vd, idd, vgs_sat), float(p["scale"]))
    netlist = to_netlist(params)
    ig_fit = mosfet1_current(vg, np.full_like(vg, vds_lin), params.Vt0,
                             params.kp_WL, params.lam, "n") / params.scale
    idd_fit = mosfet1_current(np.full_like(vd, vgs_sat), vd, params.Vt0,
                              params.kp_WL, params.lam, "n") / params.scale
    return {
        "kind": "mosfet1",
        "converged": bool(params.converged),
        "scale": params.scale,
        "params": {"Vt0": params.Vt0, "kp_WL": params.kp_WL,
                    "lam": params.lam, "kind": params.kind,
                    "rel_rms_error": params.rel_rms_error,
                    "n_points": params.n_points,
                    "vov_min": params.vov_min},
        "netlist": netlist,
        "curve": {"vg": vg.tolist(), "ig_tcad": ig.tolist(),
                   "ig_fit": ig_fit.tolist(),
                   "vd": vd.tolist(), "id_tcad": idd.tolist(),
                   "id_fit": idd_fit.tolist()},
    }


def run_job(job_path, out_path):
    with open(job_path) as fh:
        p = json.load(fh)

    kind = p.get("kind")
    if kind == "diode":
        manifest = _run_diode(p)
    elif kind == "mosfet1":
        manifest = _run_mosfet(p)
    else:
        raise ValueError(f"unknown compact-model kind {kind!r}")

    tmp_path = out_path + ".tmp.json"
    with open(tmp_path, "w") as fh:
        json.dump(manifest, fh)
    os.replace(tmp_path, out_path)
    print(f"RESULT_PATH={out_path}", flush=True)


def main(argv):
    if len(argv) != 3:
        print("usage: python -m gui.services.compact_runner "
              "<job.json> <out.json>", file=sys.stderr)
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
