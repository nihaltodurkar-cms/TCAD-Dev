"""Debug M15: trace frozen generation with continuation."""
import sys, os, warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from gui.services.device_spec import (
    DeviceSpec, MeshSpec, DopingSpec, ContactSpec
)
from gui.services.solver_runner import (
    build_mesh, build_doping, build_device
)
from pytcad import NewtonOptions

# Setup: one-sided junction 1e16/1e19, 6um total (like the tests)
x = np.linspace(0.0, 6e-4, 80)
doping = np.where(x < 3e-4, -1e16, 1e19)

spec_on = DeviceSpec(
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
            "impact": True},
)

mesh_obj = build_mesh(spec_on.mesh)
doping_arr, ntotal = build_doping(spec_on.doping, spec_on.mesh.shape())
dev = build_device(spec_on, mesh_obj, doping_arr, ntotal)

print("=" * 60)
print("TRACE: Frozen generation with continuation ramp")
print("=" * 60)

# Step 1: Equilibrium
print("\n--- Step 1: Equilibrium ---")
dev.solve_equilibrium()
print(f"psi range: [{dev.psi.min():.4f}, {dev.psi.max():.4f}]")

# Step 2: Ramp reverse bias with continuation
print("\n--- Step 2: Ramp from 0V to -40V with continuation ---")
voltages = np.arange(0.0, 41.0, 2.0)
for v in voltages:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        dev.solve_bias([-v, 0.0], NewtonOptions(verbose=False))
        warns = [str(w.message) for w in caught if "did not converge" in str(w.message)]
    
    J, spread = dev.current_density()
    alpha_n_max = dev._ii_alpha_n_cache.max() if hasattr(dev, '_ii_alpha_n_cache') else 0.0
    
    print(f"  V={v:3.0f}V: J={J:8.3e} A/cm^2, "
          f"alpha_n_max={alpha_n_max:8.3e}, warns={len(warns)}, spread={spread:.1e}")

print("\n" + "=" * 60)
print("TRACE: Direct solve at -40V (no continuation)")
print("=" * 60)

# Step 3: Direct solve at -40V (no continuation)
dev2 = build_device(spec_on, mesh_obj, doping_arr, ntotal)
dev2.solve_equilibrium()

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    dev2.solve_bias([-40.0, 0.0], NewtonOptions(verbose=False))
    warns = [str(w.message) for w in caught if "did not converge" in str(w.message)]

J2, spread2 = dev2.current_density()
alpha_n_max2 = dev2._ii_alpha_n_cache.max() if hasattr(dev2, '_ii_alpha_n_cache') else 0.0

print(f"Direct solve at -40V:")
print(f"  J={J2:8.3e} A/cm^2, "
      f"alpha_n_max={alpha_n_max2:8.3e}, warns={len(warns)}, spread={spread2:.1e}")
