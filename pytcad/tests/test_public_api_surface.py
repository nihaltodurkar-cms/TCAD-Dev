"""The public API surface, pinned.

Architecture_Master_Plan.md section 42 asks for a small stable public API
separated from internal implementation, so the rest can evolve without
locking anything in prematurely.

Scope note, deliberate: section 42 names an *aspirational* vocabulary
(`Simulation`, `Problem`, `Field`, `PhysicsModel`, `Solver`, `Results`,
`Configuration`) that does not exist in the tree yet.  Inventing eight
abstract types that nothing uses, purely to match a list, would be worse
than not doing it -- those names should be defined when the C++ engine
actually needs them (M31 P5), against real call sites.

What IS worth freezing today is what already exists and what other code
already depends on.  This test does that: `pytcad.__all__` is a
contract, and it changes only on purpose.  Adding a name is a deliberate
edit here; REMOVING one is a breaking change to every notebook, example
and GUI service that imports it.
"""
import importlib

import pytcad

# The surface as of M31 P1.  Update deliberately, never to make a test pass.
FROZEN = frozenset({
    # constants
    "Q", "KB", "KB_EV", "EPS0", "thermal_voltage",
    # materials
    "SILICON", "Semiconductor", "mobility_caughey_thomas", "mobility_field",
    "bandgap_narrowing_slotboom", "nie_effective", "recombination",
    # meshes
    "uniform_mesh", "graded_mesh", "merge_mesh", "debye_length", "check_mesh",
    "Mesh2D", "control_volume_widths", "check_mesh2d",
    "Mesh3D", "check_mesh3d",
    # devices + solver options
    "Device1D", "Models", "NewtonOptions", "bernoulli", "dbernoulli",
    "Device2D", "DirichletBC", "GateBC",
    "Device3D", "DirichletBC3D", "GateBC3D",
    # capacitor / process / submodules
    "MOSCapacitor", "flatband_voltage", "process", "process2d", "ted",
    "mc_implant", "schottky",
    # device builders and characterization
    "mosfet_doping", "build_mosfet", "id_vg_sweep",
    "build_finfet3d", "id_vg_sweep_3d",
    "extract_vth_constant_current", "extract_subthreshold_swing", "extract_dibl",
    "circuit", "hydrodynamic",
})


def test_public_surface_has_not_shrunk():
    """Removing a name breaks every downstream importer."""
    missing = FROZEN - set(pytcad.__all__)
    assert not missing, (
        f"names removed from pytcad.__all__: {sorted(missing)}. "
        f"This is a breaking change -- if intended, update FROZEN here "
        f"in the same commit and say so in the message.")


def test_public_surface_additions_are_declared():
    """Growth is fine, but it should be a decision, not a drift."""
    added = set(pytcad.__all__) - FROZEN
    assert not added, (
        f"names added to pytcad.__all__ without updating this test: "
        f"{sorted(added)}")


def test_every_exported_name_actually_resolves():
    """__all__ must not advertise something that no longer exists."""
    broken = [n for n in pytcad.__all__ if not hasattr(pytcad, n)]
    assert not broken, f"exported but missing: {broken}"


def test_relocated_primitives_are_still_reachable_by_their_old_paths():
    """M31 P1 moved these out of device.py/device2d.py.

    The move is behavior-only: five modules imported them by private name,
    so every old path must keep resolving to the SAME object.
    """
    from pytcad import contacts, device, device2d, kernels
    for name in ("D0_REF", "bernoulli", "dbernoulli",
                 "fd_density", "fd_ddensity_deta"):
        assert getattr(device, name) is getattr(kernels, name), name
    assert device2d._ohmic_values is contacts.ohmic_values
    assert contacts._ohmic_values is contacts.ohmic_values


def test_the_engine_is_not_part_of_the_public_surface():
    """`_core` is an implementation detail reached through `_accel`."""
    assert "_core" not in pytcad.__all__
    assert "_accel" not in pytcad.__all__
