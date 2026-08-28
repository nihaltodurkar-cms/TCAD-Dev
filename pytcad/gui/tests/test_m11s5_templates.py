"""M11-S5: HBT/HEMT parametric templates + structure-model materials.

Completes the M11 arc: per-region materials now ride the WHOLE authored
path -- StructureModel regions carry a material key, to_device_spec()
emits region_materials for every non-silicon region, the domain
round-trip is lossless (the M11-S4 data-loss guard is GONE), and the
HBT/HEMT templates build on top of that to solve real heterostructure
devices end-to-end through the backend.

Gates:
  T1  hbt/hemt templates exist, build, validate, and carry non-silicon
      region materials,
  T2  authored-path spec_from_domain emits region_materials with the
      right boxes (mesh-aligned rectangles),
  T3  domain -> structure -> domain round-trip preserves region
      materials exactly (the former data-loss case),
  T4  both templates SOLVE at equilibrium through the pytcad backend,
  T5  the HEMT band diagram shows the conduction-band step at the
      AlGaAs/GaAs interface (the physics reason the template exists).
"""
import json
import os
import sys
import tempfile

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from workbench.core.templates import get_template, list_templates
from workbench.adapters.spec import spec_from_domain, \
    structure_from_domain


def _tmp_spec(domain):
    d = tempfile.mkdtemp()
    out = os.path.join(d, "out.npz")
    job = os.path.join(d, "job.json")
    spec_from_domain(domain).to_json(job)
    return job, out


# ---------------------------------------------------------------- T1
def test_templates_exist_and_carry_materials():
    assert {"hbt", "hemt"} <= set(list_templates())
    for tid in ("hbt", "hemt"):
        dev = get_template(tid).build()
        mats = {r.material.upper() for r in dev.regions}
        assert "AL0.3GA0.7AS" in mats or "GAAS" in mats, \
            f"{tid}: no heterostructure materials on its regions"
        assert any(m.upper() != "SILICON" for m in mats), \
            f"{tid}: expected at least one non-silicon region"
        dev.validate()          # library keys resolve


def test_template_params_are_validated():
    t = get_template("hemt")
    with pytest.raises(ValueError, match="unknown parameter"):
        t.build({"bogus": 1.0})
    with pytest.raises(ValueError, match=">= 1e-08|must be >="):
        t.build({[p.name for p in t.params if p.name.endswith("_cm")][0]:
                 1e-12})


# ---------------------------------------------------------------- T2
def test_authored_spec_emits_region_materials():
    """T2: the authored path now EMITS region_materials (boxes are the
    region rectangles, clamped to the domain extent)."""
    dev = get_template("hemt").build({"nx": 30, "ny": 24})
    spec = spec_from_domain(dev)
    rm = spec.region_materials
    assert rm, "authored path emitted no region_materials"
    by_mat = {e["material"]: e["box"] for e in rm}
    assert "AL0.3GA0.7AS" in by_mat
    x0, x1, y0, y1 = by_mat["AL0.3GA0.7AS"]
    assert 0 <= x0 < x1 <= dev.width_cm + 1e-18
    assert 0 <= y0 < y1 <= dev.height_cm + 1e-18
    # the barrier box's y-range must sit ABOVE the GaAs channel's
    gaas_boxes = [e["box"] for e in rm if e["material"] == "GAAS"]
    assert gaas_boxes, "expected a GaAS region below the barrier"
    assert min(b[3] for b in gaas_boxes) <= y0


# ---------------------------------------------------------------- T3
def test_domain_roundtrip_preserves_region_materials():
    """T3: the former data-loss case -- domain -> structure -> domain --
    now carries per-region materials EXACTLY."""
    dev = get_template("hbt").build({"nx": 24, "ny": 20})
    structure, mesh_model = structure_from_domain(dev)
    # the rebuilt StructureModel regions know their materials
    assert all(hasattr(r, "material") for r in structure.regions)
    rmap = {r.id: r.material for r in structure.regions}
    for r in dev.regions:
        assert rmap[r.id].upper() == r.material.upper(), \
            f"region {r.id} lost its material in the round-trip"


# ---------------------------------------------------------------- T4
@pytest.mark.parametrize("tid", ["hemt", "hbt"])
def test_templates_solve_end_to_end(tid):
    """T4: template -> spec -> backend run -> finite, schema-valid npz."""
    from workbench.solvers.base import SolveRequest, get_backend
    dev = get_template(tid).build({"nx": 26, "ny": 20})
    job, out = _tmp_spec(dev)
    get_backend("pytcad").run(SolveRequest(job_json_path=job,
                                           out_npz_path=out))
    f = np.load(out)
    pot = f["field__potential"]
    n = f["field__electron_density"]
    assert np.isfinite(pot).all() and (pot != 0).any()
    assert np.isfinite(n).all() and (n > 0).all()


# ---------------------------------------------------------------- T5
def test_hemt_band_step_at_interface():
    """T5: the solved HEMT shows the AlGaAs/GaAs conduction-band step:
    electron affinity differs by 0.85*x eV (x=0.3 -> ~0.26 eV), visible
    as a discontinuity in Ec = -psi*VT - chi between adjacent columns
    straddling the interface."""
    from pytcad import Device2D, Models
    from pytcad.mesh2d import Mesh2D
    dev = get_template("hemt").build({"nx": 40, "ny": 32})
    spec = spec_from_domain(dev)
    assert spec.region_materials
    # rebuild the core directly from the spec pieces for band access
    from pytcad import NewtonOptions
    from gui.services.solver_runner import build_device, build_doping, \
        build_mesh
    mesh = build_mesh(spec.mesh)
    doping, ntotal = build_doping(spec.doping, spec.mesh.shape())
    core = build_device(spec, mesh, doping, ntotal)
    Ny, Nx = core.Ny, core.Nx
    # minimal registration: the bottom body contact suffices for an
    # equilibrium solve
    core.add_contact("body", i=list(range(Nx)),
                     j=[Ny - 1] * Nx, V=0.0)
    core.solve_equilibrium(NewtonOptions(tol_update=1e-11,
                                         max_iter=300))
    chi = np.array([m.chi for m in core.mats]).reshape(core.Ny, core.Nx)
    Ec = -core.psi * core.VT - chi
    # The buffer/channel/barrier layers are stacked along y (each region
    # spans the full x-width -- see _build_hemt in workbench/core/
    # templates.py), so chi is constant along x and steps between rows
    # along y. Find the interface ROW (axis=0), not column: diffing
    # along axis=1 (the previous, buggy version of this test) compares
    # chi within a single uniform row and is always exactly zero,
    # regardless of whether the real band step exists.
    dchi = np.abs(np.diff(chi, axis=0))
    j, i = np.unravel_index(int(np.argmax(dchi)), dchi.shape)
    step = abs(Ec[j + 1, i] - Ec[j, i])
    assert step >= 0.15, \
        f"T5 FAIL: conduction-band step at interface {step:.4f} eV"


# ------------------------------------------------- GUI editor surface
def _gapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication
    return QGuiApplication.instance() or QGuiApplication([])


def test_region_material_editor_binds_and_edits():
    """The DopingEditor gains a material combobox fed from the library;
    choosing an entry edits Region.material through the controller with
    undo support, and to_device_spec() reflects it."""
    gapp = _gapp()
    from gui import app as gui_app
    engine, controller = gui_app.create_engine(gapp)
    try:
        root = engine.rootObjects()[0]
        assert root.findChild(object, "regionMaterialBox") is not None, \
            "missing regionMaterialBox combobox"

        names = controller.materialNames
        assert "SILICON" in names and "GAAS" in names

        controller.loadStructureExample("mosfet_2d_structure")
        rid = controller.structure.regions[0].id
        controller.setRegionMaterial(rid, "gaas")   # case-insensitive
        assert controller.structure.regions[0].material == "GAAS"
        assert controller.isDirty is True

        spec = controller.structure.to_device_spec(
            controller.mesh_model)
        assert spec.region_materials, \
            "edited material did not reach region_materials"
        assert spec.region_materials[0]["material"] == "GAAS"

        # unknown key refuses loudly
        with pytest.raises(KeyError, match="UNOBTANIUM"):
            controller.setRegionMaterial(rid, "UNOBTANIUM")

        # undo restores the previous (canonical default) material
        controller.undo()
        assert controller.structure.regions[0].material == "SILICON"
    finally:
        engine.deleteLater()
