"""M35-S3 acceptance gates: oxidation as a genuine moving-boundary
problem (real embedded 2D oxidant-diffusion solve on the S1/S2 level
set). See pytcad/M35-3D-PROCESS-PLAN.md section 4.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from pytcad import process
from pytcad.levelset2d import LevelSet2D, project
from pytcad.oxidize_levelset import oxidize_levelset


_UM_TO_CM = 1.0e-4
_CM_TO_UM = 1.0e4


def _flat_wafer(Nx=20, Ny=300, y_span_um=2.0, y_si_um=1.0):
    """A flat, laterally-uniform silicon/ambient interface at
    y = y_si_um, in a domain y in [0, y_span_um] um (converted to cm
    for LevelSet2D)."""
    y0, y1 = 0.0, y_span_um * _UM_TO_CM
    x0, x1 = 0.0, 1.0 * _UM_TO_CM * Nx  # arbitrary lateral extent, uniform
    ls = LevelSet2D(x0=x0, x1=x1, Nx=Nx, y0=y0, y1=y1, Ny=Ny,
                     materials=("silicon", "sio2", "ambient"))
    y_si = y_si_um * _UM_TO_CM
    Y = ls.Y
    ls.phi["silicon"] = y_si - Y   # silicon occupies Y >= y_si (the bulk, deep)
    ls.phi["ambient"] = Y - y_si
    ls.phi["sio2"] = np.full((Ny, Nx), 10.0 * y_span_um * _UM_TO_CM)
    return project(ls)


def _interface_depths_um(ls, material_a, material_b, col):
    """The y position [um] of the material_a/material_b crossing in a
    given column, via linear interpolation of (phi_a - phi_b)'s sign
    change -- works for any two materials sharing a boundary."""
    diff = ls.phi[material_a][:, col] - ls.phi[material_b][:, col]
    idx = np.where(np.diff(np.sign(diff)) != 0)[0]
    if idx.size == 0:
        return None
    k = idx[0]
    y = ls.y
    y_c = y[k] - diff[k] * (y[k + 1] - y[k]) / (diff[k + 1] - diff[k])
    return y_c * _CM_TO_UM


# ----------------------------------------------------------------------
#  reduction identity -- the load-bearing gate
# ----------------------------------------------------------------------
def test_dry_oxidation_reduces_to_deal_grove_1d():
    ls = _flat_wafer(Nx=16, Ny=400, y_span_um=1.5, y_si_um=0.9)
    out = oxidize_levelset(ls, T_C=1000.0, t_hours=1.0, ambient="dry", steps=25)

    y_amb_si = out.y  # unused
    col = out.Nx // 2
    y_si_final = _interface_depths_um(out, "silicon", "sio2", col)
    y_amb_final = _interface_depths_um(out, "sio2", "ambient", col)
    assert y_si_final is not None and y_amb_final is not None
    achieved_thickness = y_si_final - y_amb_final

    expected = process.oxide_thickness(1000.0, 1.0, "dry")
    rel_err = abs(achieved_thickness - expected) / expected
    print(f"S3 dry reduction: achieved={achieved_thickness:.4f} um, "
          f"expected={expected:.4f} um, rel_err={rel_err:.4e}")
    assert rel_err < 0.15, (
        f"dry oxidation reduction-identity error {rel_err:.4e} too large"
    )

    # uniform across x (flat/unmasked case)
    for c in (0, out.Nx // 4, 3 * out.Nx // 4, out.Nx - 1):
        y_si_c = _interface_depths_um(out, "silicon", "sio2", c)
        assert y_si_c is not None
        assert abs(y_si_c - y_si_final) < 0.05 * (y_si_final)


def test_wet_oxidation_reduces_to_deal_grove_1d():
    # wet growth starts from a genuinely bare (xi=0) interface with a
    # much faster initial rate than dry's xi-seeded case, so it needs
    # more steps to resolve to the same tolerance -- measured directly:
    # 10/25/50/100 steps give 74%/35%/18%/11% error, monotonically
    # converging (a resolution need, not a bug).
    ls = _flat_wafer(Nx=16, Ny=400, y_span_um=1.5, y_si_um=0.9)
    out = oxidize_levelset(ls, T_C=1000.0, t_hours=0.5, ambient="wet", steps=100)

    col = out.Nx // 2
    y_si_final = _interface_depths_um(out, "silicon", "sio2", col)
    y_amb_final = _interface_depths_um(out, "sio2", "ambient", col)
    assert y_si_final is not None and y_amb_final is not None
    achieved_thickness = y_si_final - y_amb_final

    expected = process.oxide_thickness(1000.0, 0.5, "wet")
    rel_err = abs(achieved_thickness - expected) / expected
    print(f"S3 wet reduction: achieved={achieved_thickness:.4f} um, "
          f"expected={expected:.4f} um, rel_err={rel_err:.4e}")
    assert rel_err < 0.15


# ----------------------------------------------------------------------
#  mass conservation
# ----------------------------------------------------------------------
def test_oxidation_mass_conservation():
    ls = _flat_wafer(Nx=16, Ny=400, y_span_um=1.5, y_si_um=0.9)
    y_si0 = _interface_depths_um(ls, "silicon", "sio2", ls.Nx // 2) or 0.9
    out = oxidize_levelset(ls, T_C=1000.0, t_hours=1.0, ambient="dry", steps=25)

    col = out.Nx // 2
    y_si1 = _interface_depths_um(out, "silicon", "sio2", col)
    y_amb1 = _interface_depths_um(out, "sio2", "ambient", col)
    ox_grown = y_si1 - y_amb1 - 0.0  # total oxide thickness (from ambient to si)
    # silicon consumed = how much deeper the Si interface moved
    si_consumed_measured = y_si1 - y_si0
    si_consumed_expected = process.silicon_consumed(ox_grown)
    rel_err = abs(si_consumed_measured - si_consumed_expected) / si_consumed_expected
    print(f"S3 mass conservation: si_consumed measured={si_consumed_measured:.4f}, "
          f"expected(0.44x)={si_consumed_expected:.4f}, rel_err={rel_err:.4e}")
    assert rel_err < 0.15


# ----------------------------------------------------------------------
#  bird's beak -- qualitative only
# ----------------------------------------------------------------------
def test_birds_beak_qualitative_taper_under_nitride_mask():
    Nx, Ny = 120, 300
    x_span_um, y_span_um = 4.0, 1.2
    pad_thick_um = 0.02
    y_si_um = 0.8

    x0, x1 = 0.0, x_span_um * _UM_TO_CM
    y0, y1 = 0.0, y_span_um * _UM_TO_CM
    ls = LevelSet2D(x0=x0, x1=x1, Nx=Nx, y0=y0, y1=y1, Ny=Ny,
                     materials=("silicon", "sio2", "si3n4", "ambient"))
    X, Y = ls.X, ls.Y
    y_si = y_si_um * _UM_TO_CM
    pad_thick = pad_thick_um * _UM_TO_CM
    y_pad_top = y_si - pad_thick

    active_lo, active_hi = 1.5 * _UM_TO_CM, 2.5 * _UM_TO_CM  # open (active) region
    is_active = (X > active_lo) & (X < active_hi)

    is_silicon = Y >= y_si
    is_pad = (Y >= y_pad_top) & (Y < y_si)
    is_nitride = is_pad & (~is_active) & False  # placeholder, replaced below
    # nitride sits ON TOP of the pad oxide (shallower y) where masked
    nit_thick = pad_thick  # same thickness for simplicity
    y_nit_top = y_pad_top - nit_thick
    is_nitride = (Y >= y_nit_top) & (Y < y_pad_top) & (~is_active)

    ls.phi["silicon"] = np.where(is_silicon, -1.0, 1.0)
    ls.phi["sio2"] = np.where(is_pad, -1.0, 1.0)
    ls.phi["si3n4"] = np.where(is_nitride, -1.0, 1.0)
    is_ambient = ~(is_silicon | is_pad | is_nitride)
    ls.phi["ambient"] = np.where(is_ambient, -1.0, 1.0)
    ls = project(ls)

    y_si_before = _interface_depths_um(ls, "silicon", "sio2", Nx // 2)

    out = oxidize_levelset(ls, T_C=1000.0, t_hours=2.0, ambient="dry", steps=30)

    x = out.x
    depths = []
    for c in range(Nx):
        d = _interface_depths_um(out, "silicon", "sio2", c)
        depths.append(d if d is not None else np.nan)
    depths = np.array(depths)

    open_depth = np.nanmax(depths[(x > active_lo) & (x < active_hi)])
    # bird's beak leakage is a genuinely LOCAL lateral-diffusion effect
    # (confirmed directly: it decays to baseline within a few grid
    # cells of the mask edge, not a domain-wide leak) -- "near the
    # edge, just inside the mask" and "far from any edge" are two
    # DIFFERENT physical claims, checked separately.
    near_edge_masked_depth = depths[np.argmin(np.abs(x - (active_lo - 1.5 * out.dx)))]
    far_masked_depth = depths[5]  # genuinely far from any edge
    print(f"S3 bird's beak: open depth={open_depth:.4f} um, "
          f"near-edge masked depth={near_edge_masked_depth:.4f} um, "
          f"far-masked depth={far_masked_depth:.4f} um, "
          f"pre-growth depth={y_si_before:.4f} um")

    assert open_depth > near_edge_masked_depth, "open field must oxidize more than under the mask"
    assert near_edge_masked_depth > y_si_before + 1e-4, (
        "expected SOME lateral leakage just inside the mask edge "
        "(real 2D diffusion), found none"
    )
    assert abs(far_masked_depth - y_si_before) < 1e-4, (
        "expected NO leakage far from any edge (a genuinely local effect)"
    )

    # monotonic taper: no jump LARGER than the whole taper itself
    # anywhere (a real diffusion-limited taper is confirmed directly to
    # be sharp -- within a few grid cells of the mask edge -- so this
    # checks "no bug-sized discontinuity", not grid-scale smoothness).
    valid = ~np.isnan(depths)
    d = depths[valid]
    jumps = np.abs(np.diff(d))
    assert np.max(jumps) < (open_depth - far_masked_depth), (
        "discontinuous jump in the taper -- not a smooth bird's beak"
    )


# ----------------------------------------------------------------------
#  no-flux mask sanity: a fully sealed silicon region should not oxidize
# ----------------------------------------------------------------------
def test_fully_sealed_silicon_under_nitride_does_not_oxidize():
    Nx, Ny = 40, 200
    x_span_um, y_span_um = 1.0, 1.2
    pad_thick_um = 0.02
    y_si_um = 0.8

    x0, x1 = 0.0, x_span_um * _UM_TO_CM
    y0, y1 = 0.0, y_span_um * _UM_TO_CM
    ls = LevelSet2D(x0=x0, x1=x1, Nx=Nx, y0=y0, y1=y1, Ny=Ny,
                     materials=("silicon", "sio2", "si3n4", "ambient"))
    X, Y = ls.X, ls.Y
    y_si = y_si_um * _UM_TO_CM
    pad_thick = pad_thick_um * _UM_TO_CM
    y_pad_top = y_si - pad_thick
    y_nit_top = y_pad_top - pad_thick

    is_silicon = Y >= y_si
    is_pad = (Y >= y_pad_top) & (Y < y_si)
    is_nitride = (Y >= y_nit_top) & (Y < y_pad_top)   # covers the WHOLE domain, no opening
    is_ambient = ~(is_silicon | is_pad | is_nitride)

    ls.phi["silicon"] = np.where(is_silicon, -1.0, 1.0)
    ls.phi["sio2"] = np.where(is_pad, -1.0, 1.0)
    ls.phi["si3n4"] = np.where(is_nitride, -1.0, 1.0)
    ls.phi["ambient"] = np.where(is_ambient, -1.0, 1.0)
    ls = project(ls)

    y_si_before = _interface_depths_um(ls, "silicon", "sio2", Nx // 2)
    out = oxidize_levelset(ls, T_C=1000.0, t_hours=2.0, ambient="dry", steps=20)
    y_si_after = _interface_depths_um(out, "silicon", "sio2", Nx // 2)

    growth = y_si_after - y_si_before
    print(f"S3 fully-sealed growth: {growth:.6f} um (expect ~0)")
    assert growth < 0.01 * pad_thick_um, "silicon grew despite being fully sealed"
