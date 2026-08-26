"""M1 acceptance tests: Domain Core + Model Catalog (ARCHITECTURE.md M1).

The contract under test:
  - workbench.core holds pure-data domain objects (Region, ContactDef,
    DomainDevice), a MaterialLibrary, and a ModelCatalog whose metadata
    describes the physics the solver actually implements.
  - DeviceSpec REMAINS the wire/project format; DomainDevice is its
    derived domain representation.  Behavioral equivalence is proven on
    both shipped examples:
      example 1 (mosfet_2d):   spec -> domain -> spec   == original spec
      example 2 (mosfet_2d_structure): structure -> domain ->
             structure -> existing builder == existing builder directly
  - No numerical behavior changes: the adapters DELEGATE to the existing
    builders rather than reimplementing them.
"""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from gui.services.device_spec import DeviceSpec, _default_models
from gui.services.examples import EXAMPLES, STRUCTURE_EXAMPLES
from gui.services.structure_model import MeshModel, StructureModel

from workbench.adapters import spec as spec_adapter
from workbench.core.catalog import ModelCatalog
from workbench.core.device import DomainDevice
from workbench.core.materials import LIBRARY


# ----------------------------------------------------------------------
#  equivalence, example 1: v0.1 array-doping spec round-trips exactly
# ----------------------------------------------------------------------
def test_example1_domain_roundtrip_equals_original_spec():
    original = EXAMPLES["mosfet_2d"]()

    domain = spec_adapter.domain_from_device_spec(original)
    rebuilt = spec_adapter.spec_from_domain(domain)

    assert isinstance(rebuilt, DeviceSpec)
    assert rebuilt == original, \
        "domain->spec round-trip changed the device"


def test_example1_roundtrip_is_stable():
    original = EXAMPLES["mosfet_2d"]()
    once = spec_adapter.domain_from_device_spec(original)
    twice = spec_adapter.domain_from_device_spec(
        spec_adapter.spec_from_domain(once))
    assert twice == once


# ----------------------------------------------------------------------
#  equivalence, example 2: region-authored device goes through the
#  EXISTING builder -- output must be identical by construction
# ----------------------------------------------------------------------
def test_example2_region_path_matches_direct_builder():
    structure, mesh_model = STRUCTURE_EXAMPLES["mosfet_2d_structure"]()
    direct = structure.to_device_spec(mesh_model)

    domain = spec_adapter.domain_from_structure(structure, mesh_model)
    via_domain = spec_adapter.spec_from_domain(domain)

    assert via_domain == direct, \
        "region path through the domain core changed the solved device"


def test_example2_domain_roundtrip_preserves_workbench_objects():
    structure, mesh_model = STRUCTURE_EXAMPLES["mosfet_2d_structure"]()
    domain = spec_adapter.domain_from_structure(structure, mesh_model)

    structure2, mesh_model2 = spec_adapter.structure_from_domain(domain)
    assert structure2 == structure
    assert mesh_model2 == mesh_model


# ----------------------------------------------------------------------
#  domain validation
# ----------------------------------------------------------------------
def _valid_authored_device():
    domain = spec_adapter.domain_from_structure(
        *STRUCTURE_EXAMPLES["mosfet_2d_structure"]())
    domain.id, domain.name = "t1", "Test device"
    return domain


def test_validate_accepts_both_shipped_shapes():
    spec_adapter.domain_from_device_spec(EXAMPLES["mosfet_2d"]()).validate()
    _valid_authored_device().validate()


def test_validate_requires_mesh_hint_on_region_path():
    d = _valid_authored_device()
    d.mesh_nx = None
    with pytest.raises(ValueError, match="mesh_nx"):
        d.validate()


def test_validate_rejects_gate_without_tox():
    d = _valid_authored_device()
    gate = next(c for c in d.contacts if c.kind == "gate")
    gate.tox_cm = None
    with pytest.raises(ValueError, match="tox"):
        d.validate()


def test_validate_rejects_unknown_dimensionality():
    d = _valid_authored_device()
    d.dimensionality = 4
    with pytest.raises(ValueError, match="dimensionality"):
        d.validate()


# ----------------------------------------------------------------------
#  ModelCatalog: metadata completeness + config validation
# ----------------------------------------------------------------------
def test_catalog_keys_match_the_solver_models_flags():
    assert set(ModelCatalog.list()) == {
        "doping_mobility", "field_mobility", "srh", "auger", "bgn",
        "fd", "incomplete_ion"}
    # the catalog's default config IS the wire-format default
    assert ModelCatalog.default_config() == _default_models()


def test_catalog_describe_metadata_is_complete():
    for key in ModelCatalog.list():
        info = ModelCatalog.describe(key)
        assert info.title and info.key == key
        assert info.equations, f"{key}: no equations documented"
        assert info.references, f"{key}: no references documented"
        assert info.applicability, f"{key}: no applicability note"
        # parameters must name real Semiconductor fields they consume
        from pytcad.materials import SILICON
        for param in info.parameters:
            assert hasattr(SILICON, param), \
                f"{key}: parameter '{param}' is not a Semiconductor field"


def test_field_mobility_honestly_documents_its_limit():
    info = ModelCatalog.describe("field_mobility")
    assert "1D" in info.applicability and "NotImplementedError" in \
        (info.limitations or "")


def test_catalog_validate_accepts_default_and_rejects_junk():
    ModelCatalog.validate(ModelCatalog.default_config())     # ok
    with pytest.raises(ValueError, match="unknown physics model"):
        ModelCatalog.validate({"quantum_tunneling": True})
    with pytest.raises(ValueError, match="must be true or false"):
        ModelCatalog.validate({"srh": "yes"})
    with pytest.raises(ValueError, match="must be a dict"):
        ModelCatalog.validate(["srh"])


# ----------------------------------------------------------------------
#  MaterialLibrary
# ----------------------------------------------------------------------
def test_library_serves_silicon_and_reports_unknowns():
    assert "SILICON" in LIBRARY.names()
    si = LIBRARY.get("SILICON")
    assert si.eps_r == 11.7 and si.chi == 4.05
    # M11-S1: Ge/GaAs/InGaAs/AlGaAS are registered (known != solvable)
    for name in ("GE", "GAAS", "INGAAS", "AL0.3GA0.7AS"):
        assert name in LIBRARY.names(), name
    assert LIBRARY.get("GaAs").eps_r == 12.9
    with pytest.raises(KeyError, match="Unobtainium"):
        LIBRARY.get("Unobtainium")


def test_library_summary_contains_educational_landmarks():
    s = LIBRARY.summary("SILICON")
    assert s["eps_r"] == 11.7
    assert 1.0 < s["Eg300"] < 1.3
    assert 0.0 < s["ni300"] < 1e11          # sane silicon ni at 300 K
    assert s["mu_n_max"] > s["mu_p_max"]    # electrons move faster


# ----------------------------------------------------------------------
#  layering: the workbench core/adapters stay Qt-free
# ----------------------------------------------------------------------
def test_workbench_modules_never_import_qt():
    import inspect
    for mod in (spec_adapter, __import__("workbench.core.device",
                                          fromlist=["x"]),
                __import__("workbench.core.catalog", fromlist=["x"]),
                __import__("workbench.core.materials", fromlist=["x"]),
                __import__("workbench.core.region", fromlist=["x"])):
        src = inspect.getsource(inspect.getmodule(mod))
        assert "PySide6" not in src and "PyQt" not in src, \
            f"{mod!r} module must stay Qt-free"


# ----------------------------------------------------------------------
#  behavior: physics-config changes must actually reach the built spec
# ----------------------------------------------------------------------
def test_model_flag_change_propagates_to_built_spec():
    d = spec_adapter.domain_from_device_spec(EXAMPLES["mosfet_2d"]())
    d.models["auger"] = False
    rebuilt = spec_adapter.spec_from_domain(d)
    assert rebuilt.models["auger"] is False, \
        "domain model config did not survive into the wire format"


def test_model_flag_change_propagates_on_region_path():
    domain = spec_adapter.domain_from_structure(
        *STRUCTURE_EXAMPLES["mosfet_2d_structure"]())
    domain.models["bgn"] = False
    rebuilt = spec_adapter.spec_from_domain(domain)
    assert rebuilt.models == dict(domain.models), \
        "authored-path models were not taken from the DomainDevice"


def test_region_path_rejects_unsolvable_material_honestly():
    from pytcad.materials import Semiconductor
    LIBRARY.register("SiGe", Semiconductor(name="SiGe"))   # known, NOT solvable
    try:
        structure, mesh_model = STRUCTURE_EXAMPLES["mosfet_2d_structure"]()
        domain = spec_adapter.domain_from_structure(structure, mesh_model)
        domain.regions[0].material = "SiGe"
        # domain layer ACCEPTS known materials since M11-S1...
        domain.validate()
        # ...while the adapter keeps refusing honestly: the refusal is
        # a DATA-LOSS guard now (M11-S4: the cores solve hetero devices,
        # but the structure-model round-trip cannot carry per-region
        # materials yet), not a capability gap
        with pytest.raises(ValueError, match="silently dropped"):
            spec_adapter.spec_from_domain(domain)
    finally:
        LIBRARY._materials.pop("SiGe", None)


def test_validate_rejects_unknown_material_key():
    domain = spec_adapter.domain_from_structure(
        *STRUCTURE_EXAMPLES["mosfet_2d_structure"]())
    domain.regions[0].material = "Unobtainium"
    with pytest.raises(ValueError, match="unknown material"):
        domain.validate()


# ----------------------------------------------------------------------
#  regressions: material handling at the domain/spec boundary
# ----------------------------------------------------------------------
def test_imported_material_is_not_silently_replaced():
    """The IMPORTED branch must thread dev.material like every other
    field -- hardcoding 'SILICON' silently rewrote foreign labels."""
    original = EXAMPLES["mosfet_2d"]()
    original.material = "Silicon"
    domain = spec_adapter.domain_from_device_spec(original)
    assert domain.material == "Silicon"
    assert spec_adapter.spec_from_domain(domain) == original, \
        "round-trip silently changed spec.material"


def test_structure_label_resolves_against_the_library():
    """StructureModel's legacy label 'Silicon' must be a legal
    DomainDevice.material: the library lookup contract has to hold for
    real shipped data, not just hardcoded literals."""
    domain = spec_adapter.domain_from_structure(
        *STRUCTURE_EXAMPLES["mosfet_2d_structure"]())
    assert domain.material == "Silicon"          # verbatim, no data loss
    LIBRARY.get(domain.material)                 # must not raise


def test_library_lookup_is_case_insensitive():
    assert LIBRARY.get("Silicon").eps_r == LIBRARY.get("SILICON").eps_r
    assert LIBRARY.get("silicon").name == "Silicon"


def test_validate_rejects_unknown_domain_material():
    domain = spec_adapter.domain_from_structure(
        *STRUCTURE_EXAMPLES["mosfet_2d_structure"]())
    domain.material = "Unobtainium"
    with pytest.raises(ValueError, match="unknown material"):
        domain.validate()


def test_adapters_fail_fast_on_foreign_material_at_import():
    original = EXAMPLES["mosfet_2d"]()
    original.material = "Unobtania"
    with pytest.raises(ValueError, match="unknown material"):
        spec_adapter.domain_from_device_spec(original)


# ----------------------------------------------------------------------
#  regressions: boundary-boundary bugs found by adversarial probing
# ----------------------------------------------------------------------
def test_3d_doping_arrays_do_not_alias_between_domain_and_spec():
    spec = EXAMPLES["mosfet_2d"]()
    spec.mesh.dimensionality = 3
    spec.mesh.axes["y"] = [0.0, 1e-4]
    spec.mesh.axes["z"] = [0.0, 1e-4]
    spec.doping.values = [[[1.0, 2.0]], [[3.0, 4.0]]]
    domain = spec_adapter.domain_from_device_spec(spec)
    domain.explicit_doping[0][0][0] = 999.0
    assert spec.doping.values[0][0][0] == 1.0, \
        "mutation leaked through a shallow copy into the wire format"


def test_gate_without_resolved_vfb_imports_cleanly():
    from gui.services.device_spec import ContactSpec, DopingSpec, MeshSpec
    spec = DeviceSpec(
        mesh=MeshSpec(dimensionality=2, axes={"x": [0.0, 1e-4],
                                              "y": [0.0, 1e-4]}),
        doping=DopingSpec(kind="array", values=[[0.0, 0.0]]),
        contacts=[
            ContactSpec(name="l", kind="ohmic", nodes={"i": [0], "j": [0]}),
            ContactSpec(name="g", kind="gate", nodes={"i": [1], "j": [0]},
                        tox_cm=5e-7, Vfb=None),
        ],
    )
    domain = spec_adapter.domain_from_device_spec(spec)   # must not raise
    rebuilt = spec_adapter.spec_from_domain(domain)
    gate = next(c for c in rebuilt.contacts if c.kind == "gate")
    assert gate.Vfb is None


def test_region_path_refuses_conflicting_explicit_bias():
    domain = spec_adapter.domain_from_structure(
        *STRUCTURE_EXAMPLES["mosfet_2d_structure"]())
    structure, _ = spec_adapter.structure_from_domain(domain)
    direct = structure.to_device_spec(MeshModel(nx=domain.mesh_nx,
                                                ny=domain.mesh_ny))
    conflicting = {k: v + 1.0 for k, v in direct.bias.items()}
    domain.bias = conflicting
    with pytest.raises(ValueError, match="conflicts"):
        spec_adapter.spec_from_domain(domain)


def test_imported_path_requires_complete_axes():
    from gui.services.device_spec import DopingSpec, MeshSpec
    bad = DeviceSpec(mesh=MeshSpec(dimensionality=2, axes={"x": [0., 1e-4]}),
                     doping=DopingSpec(kind="array", values=[[0., 0.]]))
    with pytest.raises(ValueError, match="axes"):
        spec_adapter.domain_from_device_spec(bad)
