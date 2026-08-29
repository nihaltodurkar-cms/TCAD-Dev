"""DeviceSpec is the GUI/backend boundary: it must survive a JSON
round-trip exactly, because it is written to a file in the GUI process
and read back in the solver subprocess."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np

from gui.services.device_spec import MeshSpec, DopingSpec, ContactSpec, DeviceSpec


def _sample_spec():
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=2,
                      axes={"x": [0.0, 1e-5, 2e-5], "y": [0.0, 1e-5]}),
        doping=DopingSpec(kind="array", values=[[1e17, -1e17, -1e17],
                                                [1e17, -1e17, -1e17]]),
        contacts=[
            ContactSpec(name="source", kind="ohmic", nodes={"i": [0], "j": [0]}, V=0.0),
            ContactSpec(name="gate", kind="gate", nodes={"i": [1], "j": [0]},
                        tox_cm=5e-7, Vfb=-0.9),
        ],
        bias={"source": 0.0, "gate": 1.0},
    )


def test_round_trip_preserves_everything(tmp_path):
    spec = _sample_spec()
    path = str(tmp_path / "job.json")
    spec.to_json(path)
    back = DeviceSpec.from_json(path)

    assert back.mesh.dimensionality == 2
    assert back.mesh.axes["x"] == [0.0, 1e-5, 2e-5]
    assert np.allclose(back.doping.values, spec.doping.values)
    assert [c.name for c in back.contacts] == ["source", "gate"]
    assert back.contacts[1].kind == "gate"
    assert back.contacts[1].tox_cm == 5e-7
    assert back.contacts[1].Vfb == -0.9
    assert back.bias == {"source": 0.0, "gate": 1.0}
    assert back.material == "SILICON"
    assert back.T == 300.0
    assert back.models["srh"] is True


def test_defaults_are_sane():
    spec = DeviceSpec(mesh=MeshSpec(dimensionality=1, axes={"x": [0.0, 1.0]}),
                      doping=DopingSpec(kind="array", values=[1e17, 1e17]))
    assert spec.bias is None            # None means "equilibrium only"
    assert spec.contacts == []
    assert spec.models["field_mobility"] is False


def test_mesh_spec_shape_helper():
    m2 = MeshSpec(dimensionality=2, axes={"x": [0.0, 1.0, 2.0], "y": [0.0, 1.0]})
    assert m2.shape() == (2, 3)          # (Ny, Nx)
    m3 = MeshSpec(dimensionality=3,
                  axes={"x": [0.0, 1.0, 2.0], "y": [0.0, 1.0], "z": [0.0, 1.0, 2.0, 3.0]})
    assert m3.shape() == (4, 2, 3)       # (Nz, Ny, Nx)
    m1 = MeshSpec(dimensionality=1, axes={"x": [0.0, 1.0, 2.0]})
    assert m1.shape() == (3,)
