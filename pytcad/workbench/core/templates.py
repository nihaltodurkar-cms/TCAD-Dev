"""Parametric device templates (M5): the Device Builder's vocabulary.

A template is pure domain-core code: named parameters with defaults and
validated ranges, and a build() that produces an AUTHORED DomainDevice.
Adapters then route it through the EXISTING StructureModel.to_device_spec()
builder -- templates never construct specs themselves, so everything the
workbench already validates about region-authored devices applies
unchanged.

The NMOS template's DEFAULTS are pinned by test to reproduce the shipped
mosfet_2d_structure example exactly.
"""
import math
from dataclasses import dataclass

from .device import Boundary, ContactDef, DomainDevice, Region


@dataclass(frozen=True)
class TemplateParam:
    name: str
    label: str
    unit: str
    default: float
    lo: float = None            # inclusive bounds; None = unbounded
    hi: float = None
    integer: bool = False       # reject 40.5 instead of silently coercing


@dataclass(frozen=True)
class DeviceTemplate:
    id: str
    title: str
    description: str
    params: tuple               # TemplateParam tuple
    _build: object              # (values dict) -> DomainDevice

    def build(self, values=None):
        """Merge defaults with `values`, validate, and build."""
        values = dict(values or {})
        known = {p.name for p in self.params}
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValueError(
                f"unknown parameter(s) {unknown} for template "
                f"'{self.id}' (known: {sorted(known)})")
        merged = {}
        for p in self.params:
            v = values.get(p.name, p.default)
            if not isinstance(v, (int, float)) or \
                    isinstance(v, bool) or not math.isfinite(v):
                raise ValueError(
                    f"parameter '{p.name}' must be a finite number, got "
                    f"{v!r}")
            if p.integer and float(v) != int(v):
                raise ValueError(
                    f"parameter '{p.name}' must be a whole number, got "
                    f"{v}")
            if p.lo is not None and v < p.lo:
                raise ValueError(
                    f"parameter '{p.name}' must be >= {p.lo}, got {v}")
            if p.hi is not None and v > p.hi:
                raise ValueError(
                    f"parameter '{p.name}' must be <= {p.hi}, got {v}")
            merged[p.name] = float(v)
        dev = self._build(merged)
        dev.validate()
        return dev


# ----------------------------------------------------------------------
#  builders
# ----------------------------------------------------------------------
def _build_pn_diode(v):
    w, h = v["length_cm"], v["height_cm"]
    mid = w / 2.0
    return DomainDevice(
        id="pn_diode", name="P-N diode",
        dimensionality=2, width_cm=w, height_cm=h,
        # safe coercion: TemplateParam(integer=True) already rejected
        # fractional values, so this cannot truncate anything
        mesh_nx=int(v["nx"]), mesh_ny=int(v["ny"]),
        regions=[
            Region("p_side", "P side", 0.0, mid, 0.0, h, v["na_cm3"]),
            Region("n_side", "N side", mid, w, 0.0, h, v["nd_cm3"]),
        ],
        contacts=[
            ContactDef(id="p_c", name="p", kind="ohmic", V=v["v_p"],
                       boundary=Boundary(edge="left")),
            ContactDef(id="n_c", name="n", kind="ohmic", V=v["v_n"],
                       boundary=Boundary(edge="right")),
        ],
    )


def _build_mos_capacitor(v):
    w, h = v["length_cm"], v["height_cm"]
    return DomainDevice(
        id="mos_capacitor", name="MOS capacitor",
        dimensionality=2, width_cm=w, height_cm=h,
        # safe coercion: TemplateParam(integer=True) already rejected
        # fractional values, so this cannot truncate anything
        mesh_nx=int(v["nx"]), mesh_ny=int(v["ny"]),
        regions=[
            Region("sub", "Substrate", 0.0, w, 0.0, h, v["na_cm3"]),
        ],
        contacts=[
            ContactDef(id="body_c", name="body", kind="ohmic", V=0.0,
                       boundary=Boundary(edge="bottom")),
            ContactDef(id="gate", name="gate", kind="gate", V=0.0,
                       boundary=Boundary(edge="top"),
                       tox_cm=v["tox_cm"], gate_type="n+poly",
                       vfb_mode="computed", vfb_manual=None),
        ],
    )


def _build_nmos(v):
    lsd, lg, h = v["lsd_cm"], v["lg_cm"], v["depth_cm"]
    w = 2.0 * lsd + lg
    return DomainDevice(
        id="nmos", name="NMOS transistor",
        # 'Silicon' matches the shipped example's legacy display label;
        # the equivalence golden requires object equality, and the
        # MaterialLibrary resolves labels case-insensitively.
        material="Silicon",
        dimensionality=2, width_cm=w, height_cm=h,
        mesh_nx=80, mesh_ny=40,
        regions=[
            Region("channel", "Channel", 0.0, w, 0.0, h, v["na_channel_cm3"]),
            Region("source", "Source", 0.0, lsd, 0.0, h, v["nsd_cm3"]),
            Region("drain", "Drain", lsd + lg, w, 0.0, h, v["nsd_cm3"]),
        ],
        contacts=[
            ContactDef(id="source_c", name="source", kind="ohmic", V=0.0,
                       boundary=Boundary(edge="top", range_lo=0.0,
                                          range_hi=lsd)),
            ContactDef(id="drain_c", name="drain", kind="ohmic", V=0.05,
                       boundary=Boundary(edge="top", range_lo=lsd + lg,
                                          range_hi=w)),
            ContactDef(id="body_c", name="body", kind="ohmic", V=0.0,
                       boundary=Boundary(edge="bottom")),
            ContactDef(id="gate", name="gate", kind="gate", V=1.0,
                       boundary=Boundary(edge="top", range_lo=lsd,
                                          range_hi=lsd + lg),
                       tox_cm=v["tox_cm"], gate_type="n+poly",
                       vfb_mode="computed", vfb_manual=None),
        ],
    )


def _build_hemt(v):
    """AlGaAs/GaAs HEMT (M11-S5): layered buffer / channel / barrier
    stack with a Schottky gate between top-surface source/drain ohmics.
    The 2DEG physics emerges from the conduction-band step at the
    AlGaAs/GaAs interface (Anderson offsets via ln(nie) deltas)."""
    w = v["width_cm"]
    tb, tc, tbar = (v["t_buffer_cm"], v["t_channel_cm"],
                    v["t_barrier_cm"])
    h = tb + tc + tbar
    y_ch_lo, y_ch_hi = tb, tb + tc
    lg = v["lg_cm"]
    ls = max((w - lg) / 2.0, 0.0)
    return DomainDevice(
        id="hemt", name="AlGaAs/GaAs HEMT",
        dimensionality=2, width_cm=w, height_cm=h,
        mesh_nx=int(v["nx"]), mesh_ny=int(v["ny"]),
        regions=[
            Region("buffer", "GaAs buffer", 0.0, w, 0.0, tb,
                   v["nd_buffer_cm3"], "GAAS"),
            Region("channel", "GaAs channel", 0.0, w, y_ch_lo, y_ch_hi,
                   v["nd_channel_cm3"], "GAAS"),
            Region("barrier", "Al0.3Ga0.7As barrier", 0.0, w, y_ch_hi, h,
                   v["nd_barrier_cm3"], "AL0.3GA0.7AS"),
        ],
        contacts=[
            ContactDef(id="source_c", name="source", kind="ohmic", V=0.0,
                       boundary=Boundary(edge="top", range_lo=0.0,
                                          range_hi=ls)),
            ContactDef(id="drain_c", name="drain", kind="ohmic",
                       V=v["v_ds"],
                       boundary=Boundary(edge="top", range_lo=ls + lg,
                                          range_hi=w)),
            ContactDef(id="gate_c", name="gate", kind="gate", V=0.0,
                       boundary=Boundary(edge="top", range_lo=ls,
                                          range_hi=ls + lg),
                       tox_cm=v["tox_cm"], gate_type="n+poly",
                       vfb_mode="manual", vfb_manual=-0.8),
            ContactDef(id="substrate_c", name="substrate", kind="ohmic",
                       V=0.0, boundary=Boundary(edge="bottom")),
        ],
    )


def _build_hbt(v):
    """AlGaAs/GaAs n-p-n HBT (M11-S5): wide-gap emitter over a thin p+
    GaAs base and an n collector.  Emitter contact on top, base contact
    on the left edge restricted to the base layer's y-range, collector
    on the bottom."""
    w = v["width_cm"]
    te, tb, tc = (v["t_emitter_cm"], v["t_base_cm"],
                  v["t_collector_cm"])
    h = te + tb + tc
    y_base_lo, y_base_hi = tc, tc + tb          # base layer band
    we = min(max(w * 0.5, 0.0), w)              # emitter stripe width
    x_e_lo, x_e_hi = (w - we) / 2.0, (w + we) / 2.0
    return DomainDevice(
        id="hbt", name="AlGaAs/GaAs HBT",
        dimensionality=2, width_cm=w, height_cm=h,
        mesh_nx=int(v["nx"]), mesh_ny=int(v["ny"]),
        regions=[
            Region("collector", "GaAs collector", 0.0, w, 0.0, tc,
                   v["nd_collector_cm3"], "GAAS"),
            Region("base", "GaAs base", 0.0, w, y_base_lo, y_base_hi,
                   -abs(v["na_base_cm3"]), "GAAS"),
            Region("emitter", "Al0.3Ga0.7As emitter", x_e_lo, x_e_hi,
                   y_base_hi, h, abs(v["nd_emitter_cm3"]),
                   "AL0.3GA0.7AS"),
        ],
        contacts=[
            ContactDef(id="emitter_c", name="emitter", kind="ohmic",
                       V=0.0,
                       boundary=Boundary(edge="top", range_lo=x_e_lo,
                                          range_hi=x_e_hi)),
            ContactDef(id="base_c", name="base", kind="ohmic", V=0.0,
                       boundary=Boundary(edge="left",
                                         range_lo=y_base_lo,
                                         range_hi=y_base_hi)),
            ContactDef(id="collector_c", name="collector", kind="ohmic",
                       V=0.0, boundary=Boundary(edge="bottom")),
        ],
    )


_T = lambda *a, **k: DeviceTemplate(*a, **k)

TEMPLATES = {
    "pn_diode": _T(
        "pn_diode", "P-N diode",
        "Abrupt junction formed by two uniformly doped rectangles.",
        (
            TemplateParam("length_cm", "Length", "cm", 1e-4, lo=1e-7),
            TemplateParam("height_cm", "Height", "cm", 2e-5, lo=1e-7),
            TemplateParam("na_cm3", "P-side doping (Na)", "cm^-3",
                          -1e18, lo=-1e21, hi=1e21),
            TemplateParam("nd_cm3", "N-side doping (Nd)", "cm^-3",
                          1e18, lo=-1e21, hi=1e21),
            TemplateParam("v_p", "P contact bias", "V", 0.0, lo=-50, hi=50),
            TemplateParam("v_n", "N contact bias", "V", 0.0, lo=-50, hi=50),
            TemplateParam("nx", "Mesh nx", "nodes", 40, lo=8, hi=400,
                          integer=True),
            TemplateParam("ny", "Mesh ny", "nodes", 10, lo=6, hi=400,
                          integer=True),
        ),
        _build_pn_diode),
    "mos_capacitor": _T(
        "mos_capacitor", "MOS capacitor",
        "Uniform substrate with a poly gate over oxide; the classic C-V "
        "teaching structure.",
        (
            TemplateParam("length_cm", "Length", "cm", 1e-4, lo=1e-7),
            TemplateParam("height_cm", "Height", "cm", 2e-5, lo=1e-7),
            TemplateParam("na_cm3", "Substrate doping (Na)", "cm^-3",
                          -1e16, lo=-1e21, hi=1e21),
            TemplateParam("tox_cm", "Oxide thickness", "cm",
                          1e-6, lo=1e-9, hi=1e-4),
            TemplateParam("nx", "Mesh nx", "nodes", 40, lo=8, hi=400,
                          integer=True),
            TemplateParam("ny", "Mesh ny", "nodes", 20, lo=6, hi=400,
                          integer=True),
        ),
        _build_mos_capacitor),
    # Defaults are PINDED by test to equal gui/services/examples.py's
    # mosfet_2d_structure exactly -- the equivalence golden.
    "nmos": _T(
        "nmos", "NMOS transistor",
        "Source / gated channel / drain with body contact; matches the "
        "shipped MOSFET example at default parameters.",
        (
            TemplateParam("lsd_cm", "Source/drain length", "cm",
                          3e-5, lo=1e-7),
            TemplateParam("lg_cm", "Gate length", "cm", 6e-5, lo=1e-7),
            TemplateParam("depth_cm", "Junction depth", "cm",
                          2e-5, lo=1e-7),
            TemplateParam("na_channel_cm3", "Channel doping", "cm^-3",
                          -1e17, lo=-1e21, hi=1e21),
            TemplateParam("nsd_cm3", "S/D doping", "cm^-3",
                          1e19, lo=-1e21, hi=1e21),
            TemplateParam("tox_cm", "Oxide thickness", "cm",
                          5e-7, lo=1e-9, hi=1e-4),
        ),
        _build_nmos),
    # M11-S5: heterostructure templates
    "hemt": _T(
        "hemt", "AlGaAs/GaAs HEMT",
        "GaAs buffer / channel / Al0.3Ga0.7As barrier stack with a "
        "Schottky gate between top-surface source/drain ohmics; the "
        "2DEG emerges from the conduction-band step at the interface.",
        (
            TemplateParam("width_cm", "Device width", "cm",
                          5e-5, lo=1e-6),
            TemplateParam("t_buffer_cm", "Buffer thickness", "cm",
                          5e-6, lo=1e-8),
            TemplateParam("t_channel_cm", "Channel thickness", "cm",
                          2e-6, lo=1e-8),
            TemplateParam("t_barrier_cm", "Barrier thickness", "cm",
                          3e-6, lo=1e-8),
            TemplateParam("lg_cm", "Gate length", "cm",
                          1.5e-5, lo=1e-6),
            TemplateParam("nd_buffer_cm3", "Buffer doping (Nd)", "cm^-3",
                          1e14, lo=-1e21, hi=1e21),
            TemplateParam("nd_channel_cm3", "Channel doping (Nd)", "cm^-3",
                          1e15, lo=-1e21, hi=1e21),
            TemplateParam("nd_barrier_cm3", "Barrier doping (Nd)", "cm^-3",
                          1e18, lo=-1e21, hi=1e21),
            TemplateParam("tox_cm", "Gate oxide thickness", "cm",
                          2e-6, lo=1e-9, hi=1e-4),
            TemplateParam("v_ds", "Drain bias", "V", 0.0, lo=-20, hi=20),
            TemplateParam("nx", "Mesh nx", "nodes", 40, lo=8, hi=400,
                          integer=True),
            TemplateParam("ny", "Mesh ny", "nodes", 30, lo=8, hi=400,
                          integer=True),
        ),
        _build_hemt),
    "hbt": _T(
        "hbt", "AlGaAs/GaAs HBT",
        "Wide-gap n-AlGaAs emitter over a thin p+ GaAs base and an n "
        "GaAs collector; base ohmic on the left edge of the base layer.",
        (
            TemplateParam("width_cm", "Device width", "cm",
                          6e-5, lo=1e-6),
            TemplateParam("t_emitter_cm", "Emitter thickness", "cm",
                          4e-6, lo=1e-8),
            TemplateParam("t_base_cm", "Base thickness", "cm",
                          1.5e-6, lo=1e-8),
            TemplateParam("t_collector_cm", "Collector thickness", "cm",
                          6e-6, lo=1e-8),
            TemplateParam("nd_emitter_cm3", "Emitter doping (Nd)", "cm^-3",
                          5e17, lo=-1e21, hi=1e21),
            TemplateParam("na_base_cm3", "Base doping magnitude (Na)",
                          "cm^-3", 5e18, lo=0.0, hi=1e21),
            TemplateParam("nd_collector_cm3", "Collector doping (Nd)",
                          "cm^-3", 1e16, lo=-1e21, hi=1e21),
            TemplateParam("nx", "Mesh nx", "nodes", 26, lo=8, hi=400,
                          integer=True),
            TemplateParam("ny", "Mesh ny", "nodes", 24, lo=8, hi=400,
                          integer=True),
        ),
        _build_hbt),
}


def list_templates():
    return sorted(TEMPLATES)


def get_template(template_id):
    try:
        return TEMPLATES[template_id]
    except KeyError:
        raise KeyError(
            f"unknown device template '{template_id}' (available: "
            f"{', '.join(list_templates())})") from None
