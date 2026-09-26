"""P0 frame-time harness (NATIVE-DESKTOP-PLAN.md section 6): the native
app vs today's matplotlib viewport, on the same result files.

    python desktop/bench/run_bench.py [--out results.json] [--native-only]

--native-only skips the matplotlib baseline (recorded in P0, section
14.3; minutes per run at 1M nodes) -- for S2's before/after timing.

Datasets: three solved examples (1D diode, 2D MOSFET 136x55, 3D
resistor) plus two synthetic structured grids of about 1M nodes each
(1000x1000 2D, 100^3 3D) in the real result grammar, for scale.
Unstructured meshes arrive with P1's unstructured FieldView.

The native app opens a real window (GPU frames need a real GL surface);
the matplotlib baseline runs offscreen in its own process (Agg is CPU
rendering either way). Prints a markdown table; --out saves raw JSON.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from gui.services import examples  # noqa: E402
from gui.services.solver_runner import run_job  # noqa: E402

BUILD = os.path.join(ROOT, "build", "desktop")
HERE = os.path.dirname(os.path.abspath(__file__))


def _solve(d, name):
    job, out = os.path.join(d, name + ".json"), os.path.join(d, name + ".npz")
    with open(job, "w") as fh:
        json.dump(examples.EXAMPLES[name]().to_dict(), fh)
    with contextlib.redirect_stdout(io.StringIO()):
        run_job(job, out)
    return out


def _layers_3d(axes, grids, fields):
    """What a 3D result's interior layers need (NATIVE-DESKTOP-PLAN.md
    15.19), in the grammar solver_runner writes: a smooth, non-uniform
    current density; a 5-point sweep with snapshots of every field
    (sweep__snapshot__*, mesh__shape); two structure regions splitting x."""
    zz, yy, xx = (g / g.max() for g in grids)   # (Nz, Ny, Nx), x fastest
    volts = [0.0, 0.1, 0.2, 0.3, 0.4]
    out = {
        "vector__current_density__x": 1e3 * (1.2 + np.sin(2 * np.pi * yy)),
        "vector__current_density__y": 3e2 * np.cos(np.pi * xx),
        "vector__current_density__z": 2e2 * np.sin(np.pi * zz),
        "unit__current_density": np.array("A/cm^2"),
        "sweep__voltage": np.array(volts),
        "sweep__converged": np.ones(len(volts), dtype=bool),
        "sweep__current__right": 1e-6 * np.array(volts),
        "unit__sweep_current": np.array("A"),
        "sweep__meta": np.array(json.dumps({"contact": "right", "dimensionality": 3})),
        "sweep__snapshot__voltages": np.array(json.dumps(volts)),
        "mesh__shape": np.array(grids[0].shape),
    }
    for idx in range(len(volts)):
        out[f"sweep__snapshot__field__potential__{idx}"] = fields["field__potential"] * (1 + 0.25 * idx)
        out[f"sweep__snapshot__field__electron_density__{idx}"] = fields["field__electron_density"] * (1 + idx)
    x, y, z = axes["x"], axes["y"], axes["z"]
    xm = x[len(x) // 2]
    out["structure_regions__meta"] = np.array(json.dumps([
        {"name": "left", "box": [float(x[0]), float(xm), float(y[0]), float(y[-1]), float(z[0]), float(z[-1])]},
        {"name": "right", "box": [float(xm), float(x[-1]), float(y[0]), float(y[-1]), float(z[0]), float(z[-1])]}]))
    return out


def _synthetic(d, name, shape_xyz):
    """A structured result in the real grammar: smooth fields on a
    graded mesh, sized for scale rather than physics."""
    axes = {a: np.cumsum(np.linspace(1.0, 3.0, n)) * 1e-7 for a, n in zip("xyz", shape_xyz)}
    names = "xyz"[: len(shape_xyz)]
    grids = np.meshgrid(*[axes[a] for a in reversed(names)], indexing="ij")
    r = sum(g / g.max() for g in grids)
    arrays = {"result__schema": np.int64(3), "solved_bias": np.array("{}"),
              "dimensionality": np.int64(len(shape_xyz)),
              "field__potential": np.sin(3 * r), "unit__potential": np.array("V"),
              "field__electron_density": 1e10 * np.exp(8 * np.cos(2 * r)),
              "unit__electron_density": np.array("cm^-3")}
    for a in names:
        arrays[f"axis_{a}"] = axes[a]
    if len(shape_xyz) == 3:
        arrays.update(_layers_3d(axes, grids, arrays))
    out = os.path.join(d, name + ".npz")
    np.savez(out, **arrays)
    return out


def _native(path, frames):
    with open(os.path.join(BUILD, "desktop_runtime.json")) as fh:
        manifest = json.load(fh)
    env = dict(os.environ, PATH=manifest["runtime_bin"] + os.pathsep + os.environ["PATH"])
    out = subprocess.run([os.path.join(BUILD, "tcad_desktop.exe"), "--bench", path,
                          "--frames", str(frames)], capture_output=True, text=True,
                         env=env, timeout=900)
    if out.returncode:
        raise RuntimeError(out.stdout + out.stderr)
    return json.loads(out.stdout)


def _baseline(path, frames):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", OPENBLAS_NUM_THREADS="1")
    out = subprocess.run([sys.executable, os.path.join(HERE, "baseline_mpl.py"), path,
                          "--frames", str(frames)], capture_output=True, text=True,
                         env=env, timeout=3600)
    if out.returncode:
        raise RuntimeError(out.stderr[-2000:])
    return json.loads(out.stdout.strip().splitlines()[-1])


def main():
    d = tempfile.mkdtemp(prefix="tcad_bench_")
    sets = [("diode_1d", _solve(d, "diode_1d"), 120, 30),
            ("mosfet_2d (136x55)", _solve(d, "mosfet_2d"), 120, 30),
            ("resistor_3d", _solve(d, "resistor_3d"), 120, None),
            ("synthetic 2D 1000x1000", _synthetic(d, "grid2d", (1000, 1000)), 60, 5),
            ("synthetic 3D 100^3", _synthetic(d, "grid3d", (100, 100, 100)), 60, None)]
    results = []
    native_only = "--native-only" in sys.argv
    for label, path, nf, bf in sets:
        native = _native(path, nf)
        base = _baseline(path, bf) if bf and not native_only else None
        results.append({"dataset": label, "native": native, "baseline": base})

    def cell(r, key, stat="p95_ms"):
        v = r.get(key) if r else None
        if v is None:
            return "-"
        return f"{v[stat]:.1f}" if isinstance(v, dict) else f"{v:.3f}"

    print("| dataset | metric | native p50 | native p95 | matplotlib p50 | matplotlib p95 |")
    print("|---|---|---|---|---|---|")
    for r in results:
        n, b = r["native"], r["baseline"]
        for key in ("pan", "zoom", "orbit", "field_switch", "contours_on", "mesh_lines_toggle",
                    "slice_drag", "iso_level", "volume_orbit", "volume_orbit_drag", "playback_step", "streamline_rebuild",
                    "glyph_rebuild", "crop_change", "exploded_toggle",
                    "dock_float_redock", "layout_restore", "reset_layout"):
            if key in n or (b and key in b):
                print(f"| {r['dataset']} | {key} | {cell(n, key, 'p50_ms')} | {cell(n, key)} | "
                      f"{cell(b, key, 'p50_ms')} | {cell(b, key)} |")
        print(f"| {r['dataset']} | hover lookup (ms) | {cell(n, 'hover_lookup_ms')} | | "
              f"{cell(b, 'hover_lookup_ms')} | |")
        if "open_result_ms" in n:
            print(f"| {r['dataset']} | open result (ms) | {n['open_result_ms']:.1f} | | | |")
        if "cold_start_to_first_frame_ms" in n:
            print(f"| {r['dataset']} | cold start to first frame (ms) | "
                  f"{n['cold_start_to_first_frame_ms']:.0f} | | | |")
    # Where the time goes (section 15.11 Step 0): p95 per phase.
    print("\n| dataset | field switch: decode | fill | range | pipeline update | render "
          "| hover: pick p95 | snap+format p95 | hover p95 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in results:
        n = r["native"]
        ph, hp = n.get("field_switch_phases"), n.get("hover_phases")
        if not ph:
            continue
        cols = [f"{ph[k]['p95_ms']:.2f}" for k in ("decode", "fill", "range", "pipeline_update", "render")]
        cols += [f"{hp['pick']['p95_ms']:.3f}", f"{hp['snap_format']['p95_ms']:.3f}",
                 f"{n['hover_lookup']['p95_ms']:.3f}"]
        print(f"| {r['dataset']} | " + " | ".join(cols) + " |")
    first = results[0]["native"]
    print(f"\nGPU: {first.get('gl_renderer')}; viewport {first.get('viewport_device_px')} device px, "
          f"DPR {first.get('device_pixel_ratio')}")
    if "--out" in sys.argv:
        with open(sys.argv[sys.argv.index("--out") + 1], "w") as fh:
            json.dump(results, fh, indent=2)


if __name__ == "__main__":
    main()
