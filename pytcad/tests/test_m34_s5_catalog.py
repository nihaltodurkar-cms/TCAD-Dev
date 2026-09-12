"""M34-S5: the two M34 models are registered, travel through the GUI's
wire format, and run as real jobs.

The Physics Lab builds its toggles from ModelCatalog and the subprocess
runner builds `Models(**spec.models)` (gui/services/solver_runner.py),
so registering a model IS its GUI exposure; these gates check the pieces
that make that true and drive a real job through solver_runner -- the
same code the GUI's subprocess runs.
"""
import os
import sys
import warnings

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from pytcad import Models
from workbench.core.catalog import ModelCatalog
from gui.services import solver_runner
from gui.services.device_spec import (
    ContactSpec, DeviceSpec, DopingSpec, MeshSpec, SweepSpec, _default_models)

KEYS = ("btbt_nonlocal", "impact_nonlocal")


def test_registered_off_by_default_with_complete_metadata():
    for key in KEYS:
        assert key in ModelCatalog.list()
        info = ModelCatalog.describe(key)
        assert info.enabled_by_default is False
        assert info.equations and info.references
        assert info.applicability and info.limitations


def test_catalog_default_is_the_wire_format_and_builds_models():
    assert ModelCatalog.default_config() == _default_models()
    m = Models(**_default_models())
    assert m.btbt_nonlocal is False and m.impact_nonlocal is False


def test_validate_enforces_the_impact_dependency():
    cfg = dict(_default_models(), impact_nonlocal=True)
    with pytest.raises(ValueError, match="needs it"):
        ModelCatalog.validate(cfg)
    ModelCatalog.validate(dict(cfg, impact=True))          # accepted


def _spec_1d(x, doping, models, sweep):
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[
            ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
            ContactSpec(name="right", kind="ohmic",
                        nodes={"i": [x.size - 1]}, V=0.0)],
        bias={"right": 0.0},
        models=dict(_default_models(), **models),
        sweep=sweep)


def _run(spec):
    mesh_obj = solver_runner.build_mesh(spec.mesh)
    doping, ntotal = solver_runner.build_doping(spec.doping, spec.mesh.shape())
    device = solver_runner.build_device(spec, mesh_obj, doping, ntotal)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        device.solve_equilibrium()
        _fields, series = solver_runner.run_sweep(device, spec)
    return device, series


def test_btbt_nonlocal_job_runs_through_the_wire_format():
    """A tunnel diode job with btbt_nonlocal on, reverse-swept by the
    runner: every point converges and tunnel paths exist."""
    from pytcad.mesh import graded_mesh
    x = graded_mesh(1.0e-5, [5.0e-6], h_min=1e-8, h_max=2e-7)
    dop = np.where(x < 5.0e-6, -5e19, 5e19)
    spec = _spec_1d(x, dop, {"btbt_nonlocal": True, "bgn": False},
                    SweepSpec(contact="left", start=0.0, stop=-2.0, step=-0.5))
    device, series = _run(spec)
    assert device.models.btbt_nonlocal is True
    assert bool(series["sweep__converged"].all())
    assert device._btbt_nl_paths.n_paths > 0


def test_impact_nonlocal_job_runs_through_the_wire_format():
    """M15's one-sided junction with impact + impact_nonlocal on,
    reverse-swept by the runner: every point converges and the solver
    integrated a live ionization source."""
    from pytcad.mesh import graded_mesh
    x = graded_mesh(6.0e-4, [3.0e-4], h_min=2e-8, h_max=4e-6)
    dop = np.where(x < 3.0e-4, -1e16, 1e19)
    spec = _spec_1d(x, dop, {"impact": True, "impact_nonlocal": True,
                             "bgn": False},
                    SweepSpec(contact="left", start=0.0, stop=-10.0, step=-2.0))
    device, series = _run(spec)
    assert device.models.impact_nonlocal is True
    assert bool(series["sweep__converged"].all())
    assert device._ii_gs_cache is not None and device._ii_gs_cache.max() > 0


def test_2d_jobs_accept_btbt_nonlocal_and_impact_nonlocal():
    """M34-S6c ported the nonlocal effective field onto the 2D grid
    (pytcad/ii_nonlocal_grid.py) -- Device2D now accepts the flag given
    its precondition (impact=True), same as Device1D."""
    x = np.linspace(0.0, 2e-5, 11)
    y = np.linspace(0.0, 1e-5, 6)
    mesh = MeshSpec(dimensionality=2, axes={"x": x.tolist(), "y": y.tolist()})
    doping = DopingSpec(kind="array",
                        values=np.full((y.size, x.size), 1e17).tolist())

    def build(models):
        spec = DeviceSpec(mesh=mesh, doping=doping,
                          models=dict(_default_models(), **models))
        mesh_obj = solver_runner.build_mesh(spec.mesh)
        dop, ntot = solver_runner.build_doping(spec.doping, spec.mesh.shape())
        return solver_runner.build_device(spec, mesh_obj, dop, ntot)

    assert build({"btbt_nonlocal": True, "bgn": False}).models.btbt_nonlocal
    assert build({"impact": True,
                 "impact_nonlocal": True}).models.impact_nonlocal
    with pytest.raises(ValueError, match="impact=True"):
        build({"impact_nonlocal": True})
