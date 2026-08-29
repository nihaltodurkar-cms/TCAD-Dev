"""Debug: check what E-field values are computed in _ii_compute_gs."""
import sys, os
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

# Setup: one-sided junction 1e16/1e19, 6um total
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
print("E-FIELD TRACE in _ii_compute_gs")
print("=" * 60)

# Solve at -40V with continuation
dev.solve_equilibrium()
print(f"\nAfter equilibrium:")
c_edge = dev.VT / (dev.LD * dev.h)
e_mag = np.abs(np.diff(dev.psi)) * c_edge
E_node = np.empty(dev.N)
E_node[0], E_node[-1] = e_mag[0], e_mag[-1]
E_node[1:-1] = 0.5 * (e_mag[:-1] + e_mag[1:])
print(f"  E_node range: [{E_node.min():.3e}, {E_node.max():.3e}] V/cm")
print(f"  E_node max location: index {E_node.argmax()}")

# Check alpha at this field
from pytcad.ionization import alpha_n, alpha_p
a_n = alpha_n(E_node)
a_p = alpha_p(E_node)
print(f"  alpha_n range: [{a_n.min():.3e}, {a_n.max():.3e}] cm^-1")
print(f"  alpha_p range: [{a_p.min():.3e}, {a_p.max():.3e}] cm^-1")

# Now solve at -40V with continuation
print("\n--- Solving at -40V with continuation ---")
for v in [10, 20, 30, 40]:
    dev.solve_bias([-v, 0.0], NewtonOptions(verbose=False))
    
    # Check field and alpha in the device
    c_edge = dev.VT / (dev.LD * dev.h)
    e_mag = np.abs(np.diff(dev.psi)) * c_edge
    E_node = np.empty(dev.N)
    E_node[0], E_node[-1] = e_mag[0], e_mag[-1]
    E_node[1:-1] = 0.5 * (e_mag[:-1] + e_mag[1:])
    
    a_n = alpha_n(E_node)
    a_p = alpha_p(E_node)
    
    J, _ = dev.current_density()
    
    print(f"  V={v:2d}V: E_max={E_node.max():8.3e} V/cm, "
          f"a_n_max={a_n.max():8.3e} cm^-1, a_p_max={a_p.max():8.3e} cm^-1, "
          f"J={J:8.3e} A/cm^2")

print("\n" + "=" * 60)
print("GATE REFERENCE: E_SWITCH = 5e5 V/cm")
print("=" * 60)
