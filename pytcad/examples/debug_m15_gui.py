"""Debug M15 impact ionization through the GUI pipeline.

Tests the full flow: DeviceSpec -> build_mesh -> build_device -> 
solve_bias (with impact=True) -> extract_result -> verify current.
"""
import sys, os, json, warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from gui.services.device_spec import (
    DeviceSpec, MeshSpec, DopingSpec, ContactSpec, SweepSpec
)
from gui.services.solver_runner import (
    build_mesh, build_doping, build_device, extract_result, apply_bias, run_sweep
)
from pytcad import NewtonOptions

# ------------------------------------------------------------------ setup
x = np.linspace(0.0, 2e-4, 40)
doping = np.where(x < 1e-4, -1e16, 1e19)

spec = DeviceSpec(
    mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
    doping=DopingSpec(kind="array", values=doping.tolist()),
    contacts=[
        ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
        ContactSpec(name="right", kind="ohmic", nodes={"i": [x.size - 1]}, V=0.0),
    ],
    bias={"right": 0.0},
    models={"doping_mobility": True, "field_mobility": False,
            "srh": True, "auger": True, "bgn": False,
            "fd": False, "incomplete_ion": False,
            "impact": False},  # Start with impact OFF
)

print("=" * 60)
print("TEST 1: GUI pipeline WITHOUT impact ionization")
print("=" * 60)

mesh_obj = build_mesh(spec.mesh)
doping_arr, ntotal = build_doping(spec.doping, spec.mesh.shape())
device = build_device(spec, mesh_obj, doping_arr, ntotal)
device.solve_equilibrium()

# Need to solve at a bias point first to get Jn/Jp
device.solve_bias([0.0, 0.0], NewtonOptions())
J_eq, _ = device.current_density()
print(f"Equilibrium current: {J_eq:.3e} A/cm^2")

# Forward bias
device.solve_bias([0.5, 0.0], NewtonOptions())
J_fwd, spread = device.current_density()
print(f"Forward bias 0.5V: J={J_fwd:.3e} A/cm^2 (spread {spread:.1e})")

# Reverse bias
device.solve_bias([-5.0, 0.0], NewtonOptions())
J_rev, spread = device.current_density()
print(f"Reverse bias -5V: J={J_rev:.3e} A/cm^2 (spread {spread:.1e})")

# Now enable impact ionization and re-solve
print("\n" + "=" * 60)
print("TEST 2: Enable impact ionization, solve at -5V")
print("=" * 60)
spec.models["impact"] = True
device2 = build_device(spec, mesh_obj, doping_arr, ntotal)
device2.solve_equilibrium()
device2.solve_bias([-5.0, 0.0], NewtonOptions())

J_imp, spread = device2.current_density()
print(f"Impact ON, -5V: J={J_imp:.3e} A/cm^2 (spread {spread:.1e})")
print(f"Impact ON, gs cache present: {device2._ii_gs_cache is not None}")
if device2._ii_gs_cache is not None:
    print(f"  gs max: {device2._ii_gs_cache.max():.3e}")
    print(f"  gs min: {device2._ii_gs_cache.min():.3e}")

print("\n" + "=" * 60)
print("TEST 3: Ramp reverse bias with impact ON (continuation)")
print("=" * 60)
device3 = build_device(spec, mesh_obj, doping_arr, ntotal)
device3.solve_equilibrium()

for v in np.arange(1.0, 41.0, 5.0):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        device3.solve_bias([-v, 0.0], NewtonOptions())
        warns = [str(w.message) for w in caught if "did not converge" in str(w.message)]
    J, _ = device3.current_density()
    gs_max = device3._ii_gs_cache.max() if device3._ii_gs_cache is not None else 0.0
    print(f"  V={v:3d}V: J={J:.3e} A/cm^2, gs_max={gs_max:.3e}, warnings={len(warns)}")

print("\n" + "=" * 60)
print("TEST 4: Full GUI sweep with impact ON")
print("=" * 60)
spec.sweep = SweepSpec(contact="left", start=0.0, stop=0.4, step=0.1)
device4 = build_device(spec, mesh_obj, doping_arr, ntotal)
device4.solve_equilibrium()

fields, series = run_sweep(device4, spec, NewtonOptions())
print(f"Sweep voltages: {series['sweep__voltage']}")
print(f"Converged flags: {series['sweep__converged']}")
print(f"Currents: {series['sweep__current__device']}")

print("\n" + "=" * 60)
print("TEST 5: High reverse bias sweep (breakdown region)")
print("=" * 60)
spec.sweep = SweepSpec(contact="left", start=1.0, stop=30.0, step=2.0)
device5 = build_device(spec, mesh_obj, doping_arr, ntotal)
device5.solve_equilibrium()

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    fields, series = run_sweep(device5, spec, NewtonOptions())
    
print(f"Voltages: {series['sweep__voltage']}")
print(f"Converged: {series['sweep__converged']}")
print(f"Currents: {series['sweep__current__device']}")
conv_warns = [str(w.message) for w in caught if "did not converge" in str(w.message)]
print(f"Convergence warnings: {len(conv_warns)}")
if conv_warns:
    for w in conv_warns[:3]:
        print(f"  - {w}")

print("\n" + "=" * 60)
print("TEST 6: Verify J_impact > J_no_impact at -10V")
print("=" * 60)
# Device without impact
spec_off = DeviceSpec(
    mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
    doping=DopingSpec(kind="array", values=doping.tolist()),
    contacts=spec.contacts,
    bias={"right": 0.0},
    models={"doping_mobility": True, "field_mobility": False,
            "srh": True, "auger": True, "bgn": False,
            "fd": False, "incomplete_ion": False,
            "impact": False},
)
dev_off = build_device(spec_off, mesh_obj, doping_arr, ntotal)
dev_off.solve_equilibrium()
dev_off.solve_bias([-10.0, 0.0], NewtonOptions(max_iter=300))
J_off, _ = dev_off.current_density()

# Device with impact
spec_on = DeviceSpec(
    mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
    doping=DopingSpec(kind="array", values=doping.tolist()),
    contacts=spec.contacts,
    bias={"right": 0.0},
    models={"doping_mobility": True, "field_mobility": False,
            "srh": True, "auger": True, "bgn": False,
            "fd": False, "incomplete_ion": False,
            "impact": True},
)
dev_on = build_device(spec_on, mesh_obj, doping_arr, ntotal)
dev_on.solve_equilibrium()
dev_on.solve_bias([-10.0, 0.0], NewtonOptions(max_iter=300))
J_on, _ = dev_on.current_density()

print(f"J_off (impact=False): {J_off:.3e} A/cm^2")
print(f"J_on  (impact=True):  {J_on:.3e} A/cm^2")
print(f"Ratio J_on/J_off: {abs(J_on/J_off):.3f}")
print(f"PASS: {abs(J_on) > abs(J_off)}")
