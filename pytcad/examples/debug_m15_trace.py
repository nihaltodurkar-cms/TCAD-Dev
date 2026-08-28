"""Debug M15: trace frozen generation source computation."""
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

# Setup: one-sided junction 1e16/1e19
x = np.linspace(0.0, 2e-4, 40)
doping = np.where(x < 1e-4, -1e16, 1e19)

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

print("\n" + "=" * 60)
print("TRACE: Frozen generation source computation")
print("=" * 60)

# Step 1: Equilibrium
print("\n--- Step 1: Equilibrium ---")
dev.solve_equilibrium()
print(f"psi range: [{dev.psi.min():.4f}, {dev.psi.max():.4f}]")
print(f"n range: [{dev.n.min():.6f}, {dev.n.max():.6f}] (scaled)")
print(f"p range: [{dev.p.min():.6f}, {dev.p.max():.6f}] (scaled)")

# Step 2: Solve at -5V with impact ON and verbose output
print("\n--- Step 2: Solve at -5V with impact ON ---")
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    dev.solve_bias([-5.0, 0.0], NewtonOptions(verbose=True))
    warns = [str(w.message) for w in caught]
    print(f"\nWarnings: {len(warns)}")
    for w in warns[:3]:
        print(f"  - {w}")

J, spread = dev.current_density()
print(f"\nAfter solve:")
print(f"  J = {J:.3e} A/cm^2 (spread {spread:.1e})")
print(f"  self.Jn = {dev.Jn}")
print(f"  self.Jp = {dev.Jp}")
print(f"  _ii_gs_cache present: {dev._ii_gs_cache is not None}")
if dev._ii_gs_cache is not None:
    print(f"  _ii_gs_cache max: {dev._ii_gs_cache.max():.3e}")
    print(f"  _ii_gs_cache min: {dev._ii_gs_cache.min():.3e}")
    print(f"  _ii_gs_cache nonzero: {np.count_nonzero(dev._ii_gs_cache)}")
    # Show gs profile near junction
    x_j = 20  # approximate junction location
    print(f"  gs around junction (nodes {x_j-3}:{x_j+3}): {dev._ii_gs_cache[x_j-3:x_j+3]}")

# Check alpha cache
print(f"\nAlpha cache:")
if hasattr(dev, '_ii_alpha_n_cache'):
    print(f"  alpha_n max: {dev._ii_alpha_n_cache.max():.3e}")
    print(f"  alpha_p max: {dev._ii_alpha_p_cache.max():.3e}")
