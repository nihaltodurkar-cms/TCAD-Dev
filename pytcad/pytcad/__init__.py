"""PyTCAD -- a compact, readable TCAD toolkit for semiconductor work.

Two halves, mirroring commercial TCAD (Sentaurus Process/Device, Silvaco
Athena/Atlas):

    pytcad.process  -- implantation, diffusion, oxidation  ->  a doping profile
    pytcad.device   -- self-consistent drift-diffusion      ->  I-V, C-V, bands

The core is 1D. A 2D extension (`device2d.Device2D`, `mesh2d.Mesh2D`,
`mosfet.build_mosfet`/`id_vg_sweep`) adds full drift-diffusion on a
tensor-product mesh, including a real MOSFET Id-Vg transfer curve. See
README.md for the physics, the assumptions, and where this tool stops
being trustworthy.
"""

from .constants import Q, KB, KB_EV, EPS0, thermal_voltage
from .materials import (
    SILICON, Semiconductor, mobility_caughey_thomas, mobility_field,
    bandgap_narrowing_slotboom, nie_effective, recombination,
)
from .mesh import uniform_mesh, graded_mesh, merge_mesh, debye_length, check_mesh
from .mesh2d import Mesh2D, control_volume_widths, check_mesh2d
from .device import Device1D, Models, NewtonOptions, bernoulli, dbernoulli
from .device2d import Device2D, DirichletBC, GateBC
from .moscap import MOSCapacitor, flatband_voltage
from .mosfet import mosfet_doping, build_mosfet, id_vg_sweep
from . import process

__version__ = "0.1.0"

__all__ = [
    "Q", "KB", "KB_EV", "EPS0", "thermal_voltage",
    "SILICON", "Semiconductor", "mobility_caughey_thomas", "mobility_field",
    "bandgap_narrowing_slotboom", "nie_effective", "recombination",
    "uniform_mesh", "graded_mesh", "merge_mesh", "debye_length", "check_mesh",
    "Mesh2D", "control_volume_widths", "check_mesh2d",
    "Device1D", "Models", "NewtonOptions", "bernoulli", "dbernoulli",
    "Device2D", "DirichletBC", "GateBC",
    "MOSCapacitor", "flatband_voltage", "process",
    "mosfet_doping", "build_mosfet", "id_vg_sweep",
]
