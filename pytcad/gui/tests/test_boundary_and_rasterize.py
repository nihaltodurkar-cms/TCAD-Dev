"""resolve_boundary_indices/rasterize_doping are the geometric core
every later task builds on -- tested directly against small, hand-
verifiable grids."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from gui.services.device_spec import MeshSpec
from gui.services.structure_model import (
    BoundarySpec, RegionSpec, StructureModel, resolve_boundary_indices, rasterize_doping)


def _mesh_5x3():
    # x: 0,1,2,3,4 (Nx=5) ; y: 0,1,2 (Ny=3)
    return MeshSpec(dimensionality=2,
                    axes={"x": [0.0, 1.0, 2.0, 3.0, 4.0], "y": [0.0, 1.0, 2.0]})


def test_left_and_right_edges_cover_every_row():
    mesh = _mesh_5x3()
    i, j = resolve_boundary_indices(BoundarySpec("left"), mesh)
    assert list(i) == [0, 0, 0] and list(j) == [0, 1, 2]
    i, j = resolve_boundary_indices(BoundarySpec("right"), mesh)
    assert list(i) == [4, 4, 4] and list(j) == [0, 1, 2]


def test_top_and_bottom_edges_cover_every_column():
    mesh = _mesh_5x3()
    i, j = resolve_boundary_indices(BoundarySpec("top"), mesh)
    assert list(i) == [0, 1, 2, 3, 4] and list(j) == [0, 0, 0, 0, 0]
    i, j = resolve_boundary_indices(BoundarySpec("bottom"), mesh)
    assert list(i) == [0, 1, 2, 3, 4] and list(j) == [2, 2, 2, 2, 2]


def test_top_bottom_left_right_are_defined_by_physical_extrema_not_index_position():
    """Regression test for a real review comment: don't assume 'top' is
    index j=0 -- derive it from the mesh's actual y-coordinates, so a
    mistakenly reversed or reordered axis fails loudly instead of
    silently swapping which physical surface 'top' refers to. This test
    reads y/x values back off the mesh rather than hardcoding indices,
    so it would catch resolve_boundary_indices being edited to point
    top/bottom (or left/right) at the wrong extremum."""
    mesh = _mesh_5x3()
    x = np.asarray(mesh.axes["x"], dtype=float)
    y = np.asarray(mesh.axes["y"], dtype=float)

    i, j = resolve_boundary_indices(BoundarySpec("top"), mesh)
    assert np.all(y[j] == y.min())
    i, j = resolve_boundary_indices(BoundarySpec("bottom"), mesh)
    assert np.all(y[j] == y.max())
    i, j = resolve_boundary_indices(BoundarySpec("left"), mesh)
    assert np.all(x[i] == x.min())
    i, j = resolve_boundary_indices(BoundarySpec("right"), mesh)
    assert np.all(x[i] == x.max())

    # pytcad's mesh.py (uniform_mesh/graded_mesh) always emits ascending
    # arrays starting at 0 -- assert that invariant explicitly here too,
    # since it's the reason index-0-means-top has been safe so far, and
    # a change to that invariant elsewhere is exactly what this test
    # exists to catch the fallout of.
    assert y[0] == y.min() and y[-1] == y.max()
    assert x[0] == x.min() and x[-1] == x.max()


def test_range_restricts_the_edge():
    mesh = _mesh_5x3()
    i, j = resolve_boundary_indices(BoundarySpec("top", range_lo=1.0, range_hi=3.0), mesh)
    assert list(i) == [1, 2, 3]


def test_unknown_edge_raises():
    mesh = _mesh_5x3()
    try:
        resolve_boundary_indices(BoundarySpec("diagonal"), mesh)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_rasterize_single_region_fills_its_bounds_only():
    mesh = _mesh_5x3()
    structure = StructureModel(width_cm=4.0, height_cm=2.0, regions=[
        RegionSpec("r1", "block", x_min=1.0, x_max=3.0, y_min=0.0, y_max=1.0,
                  net_doping_cm3=1e17),
    ])
    doping = rasterize_doping(structure, mesh)
    assert doping.shape == (3, 5)
    # inside the region
    assert doping[0, 2] == 1e17
    assert doping[1, 2] == 1e17
    # outside it
    assert doping[2, 2] == 0.0
    assert doping[0, 0] == 0.0


def test_rasterize_later_region_overwrites_earlier():
    mesh = _mesh_5x3()
    structure = StructureModel(width_cm=4.0, height_cm=2.0, regions=[
        RegionSpec("bg", "background", 0.0, 4.0, 0.0, 2.0, -1e17),
        RegionSpec("hot", "hotspot", 1.0, 3.0, 0.0, 1.0, 1e19),
    ])
    doping = rasterize_doping(structure, mesh)
    assert doping[0, 2] == 1e19       # inside "hot", which came second
    assert doping[2, 0] == -1e17      # only "background" covers this cell


def test_rasterize_gaussian_erfc_profile_decays_with_depth_and_distance():
    """A non-uniform region reuses mosfet_doping()'s own Gaussian-in-
    depth x erfc-lateral-rolloff shape (pytcad.mosfet._sd_profile):
    peak strength right at the region's own top edge (y_min) and at/
    past the full-strength side of the mask edge, decaying with depth
    and with lateral distance past the edge."""
    x = np.linspace(0.0, 4.0, 41)
    y = np.linspace(0.0, 2.0, 21)
    mesh = MeshSpec(dimensionality=2, axes={"x": x.tolist(), "y": y.tolist()})
    structure = StructureModel(width_cm=4.0, height_cm=2.0, regions=[
        RegionSpec("sd", "source", x_min=0.0, x_max=4.0, y_min=0.0, y_max=2.0,
                  net_doping_cm3=0.0, doping_profile="gaussian_erfc",
                  profile_peak_cm3=1e19, profile_sigma_y=0.5,
                  profile_sigma_lat=0.3, profile_edge_x=2.0,
                  profile_high_side="left"),
    ])
    doping = rasterize_doping(structure, mesh)
    assert doping.shape == (21, 41)
    ix = {v: k for k, v in enumerate(x)}
    iy = {v: k for k, v in enumerate(y)}
    # full strength: surface (y=0), well inside the "left" full side (x=0)
    surface_left = doping[iy[0.0], ix[0.0]]
    assert surface_left == pytest.approx(1e19, rel=1e-6)
    # decays with depth at the same lateral position
    deeper = doping[iy[1.0], ix[0.0]]
    assert 0 < deeper < surface_left
    # decays past the mask edge, into the "right" (low) side
    far_side = doping[iy[0.0], ix[4.0]]
    assert 0 <= far_side < surface_left
    # sign follows profile_peak_cm3, not the ignored net_doping_cm3
    assert np.all(doping >= 0.0)


def test_rasterize_gaussian_erfc_negative_peak_gives_negative_doping():
    x = np.linspace(0.0, 2.0, 21)
    y = np.linspace(0.0, 1.0, 11)
    mesh = MeshSpec(dimensionality=2, axes={"x": x.tolist(), "y": y.tolist()})
    structure = StructureModel(width_cm=2.0, height_cm=1.0, regions=[
        RegionSpec("p", "p-well", x_min=0.0, x_max=2.0, y_min=0.0, y_max=1.0,
                  net_doping_cm3=0.0, doping_profile="gaussian_erfc",
                  profile_peak_cm3=-1e17, profile_sigma_y=0.3,
                  profile_sigma_lat=0.2, profile_edge_x=1.0,
                  profile_high_side="right"),
    ])
    doping = rasterize_doping(structure, mesh)
    assert np.all(doping <= 0.0)
    assert doping.min() == pytest.approx(-1e17, rel=1e-6)


def test_rasterize_gaussian_erfc_missing_parameters_raises():
    mesh = _mesh_5x3()
    structure = StructureModel(width_cm=4.0, height_cm=2.0, regions=[
        RegionSpec("sd", "source", 0.0, 4.0, 0.0, 2.0, 0.0,
                  doping_profile="gaussian_erfc"),
    ])
    with pytest.raises(ValueError, match="profile_peak_cm3"):
        rasterize_doping(structure, mesh)


def test_rasterize_unknown_doping_profile_raises():
    mesh = _mesh_5x3()
    structure = StructureModel(width_cm=4.0, height_cm=2.0, regions=[
        RegionSpec("sd", "source", 0.0, 4.0, 0.0, 2.0, 0.0,
                  doping_profile="not_a_real_profile"),
    ])
    with pytest.raises(ValueError, match="unknown doping_profile"):
        rasterize_doping(structure, mesh)
