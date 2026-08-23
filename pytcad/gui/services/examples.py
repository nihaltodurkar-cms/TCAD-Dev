"""Built-in example structures, expressed as DeviceSpecs.

Note what this module does NOT do: it does not teach solver_runner about
MOSFETs.  build_mosfet() is called here, once, purely to get a
ready-made Device2D whose mesh/doping/contacts are then read off into a
GENERIC DeviceSpec.  The subprocess only ever sees that generic spec, so
adding examples later never accumulates special cases at the process
boundary (design spec section 12).

build_mosfet() runs no solver -- it only constructs -- so this is fast
and safe to call on the UI thread.
"""
import numpy as np

from pytcad.mosfet import build_mosfet
from pytcad.device2d import DirichletBC, GateBC

from .device_spec import MeshSpec, DopingSpec, ContactSpec, DeviceSpec


def _spec_from_device2d(dev, bias=None):
    """Read a constructed Device2D back out into a generic DeviceSpec."""
    contacts = []
    for name, bc in dev.bcs.items():
        nodes = {"i": np.asarray(bc.i, dtype=int).ravel().tolist(),
                 "j": np.asarray(bc.j, dtype=int).ravel().tolist()}
        if isinstance(bc, GateBC):
            # kappa = eps_ox*LD/(eps_s*tox) -- invert it to recover tox_cm,
            # so the spec stays a physical description rather than a
            # snapshot of pytcad's internal scaling.
            from pytcad.constants import EPS0
            from pytcad.moscap import EPS_OX_R
            tox_cm = (EPS_OX_R * EPS0) * dev.LD / (dev.eps * bc.kappa)
            contacts.append(ContactSpec(name=name, kind="gate", nodes=nodes,
                                        V=bc.Vg, tox_cm=tox_cm, Vfb=bc.Vfb))
        elif isinstance(bc, DirichletBC):
            contacts.append(ContactSpec(name=name, kind="ohmic",
                                        nodes=nodes, V=bc.V))
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=2,
                      axes={"x": dev.mesh.x.tolist(), "y": dev.mesh.y.tolist()}),
        doping=DopingSpec(kind="array", values=dev.doping.tolist(),
                          ntotal=dev.Ntot.tolist()),
        contacts=contacts,
        bias=bias,
    )


def mosfet_example_spec():
    """A 2D n-channel MOSFET at a single bias point.

    Geometry matches examples/04_mosfet_idvg.py (the validated structure
    whose source/drain tails do not merge under the gate), at a coarser
    nx/ny: ~7.7k nodes solves in about a second, which is long enough to
    demonstrate a non-blocking UI and short enough to stay pleasant.

    Chosen over the 1D diode because it exercises ohmic contacts AND a
    gate, covering more of the ContactSpec path for one extra step.
    """
    dev = build_mosfet(Lg=6e-5, Lsd=3e-5, depth=2e-5, Na=1e17, Nsd_peak=1e19,
                       tox_cm=5e-7, gate="n+poly", sigma_y=5e-6, sigma_lat=1e-6,
                       nx=80, ny=40)
    return _spec_from_device2d(dev, bias={"drain": 0.05, "gate": 1.0,
                                          "source": 0.0, "body": 0.0})


EXAMPLES = {"mosfet_2d": mosfet_example_spec}


from .structure_model import BoundarySpec, ContactModel, GateModel, MeshModel, RegionSpec, StructureModel


def mosfet_example_structure():
    """A second, honestly-simpler representative MOSFET, built from
    uniform rectangular regions to exercise the Structure/Mesh workbench.
    Deliberately NOT a rectangular decomposition of build_mosfet()'s
    smooth Gaussian/erfc profile -- see the design spec section 17.5.

    Geometry: 1.2e-4 cm wide (matching mosfet_example_spec's domain),
    2e-5 cm deep. Source: x in [0, 3e-5]. Gate: x in [3e-5, 9e-5].
    Drain: x in [9e-5, 1.2e-4]. Channel background covers the full width;
    source/drain regions are listed after it so they overwrite it in
    their own x-range (see rasterize_doping's list-order rule).
    """
    width_cm, height_cm = 1.2e-4, 2e-5
    Lsd, Lg = 3e-5, 6e-5

    structure = StructureModel(width_cm=width_cm, height_cm=height_cm, regions=[
        RegionSpec("channel", "Channel", 0.0, width_cm, 0.0, height_cm, -1e17),
        RegionSpec("source", "Source", 0.0, Lsd, 0.0, height_cm, 1e19),
        RegionSpec("drain", "Drain", Lsd + Lg, width_cm, 0.0, height_cm, 1e19),
    ], contacts=[
        ContactModel("source_c", "source", BoundarySpec("top", 0.0, Lsd), V=0.0),
        ContactModel("drain_c", "drain", BoundarySpec("top", Lsd + Lg, width_cm), V=0.05),
        ContactModel("body_c", "body", BoundarySpec("bottom"), V=0.0),
    ], gates=[
        GateModel("gate", "gate", BoundarySpec("top", Lsd, Lsd + Lg),
                  tox_cm=5e-7, gate_type="n+poly", vfb_mode="computed", V=1.0),
    ])
    mesh = MeshModel(nx=80, ny=40, grading="uniform")
    return structure, mesh


STRUCTURE_EXAMPLES = {"mosfet_2d_structure": mosfet_example_structure}
