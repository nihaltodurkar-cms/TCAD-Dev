"""Band-edge and recombination maps of a solved result -- ONE Qt-free
implementation shared by the QML viewport (gui/visualization/
mpl_canvas_item.py) and the native app's backend service
(backend_service/, NATIVE-DESKTOP-PLAN.md 15.6 and S4b).

Every map is element-wise physics from workbench.analysis.observables
(band_diagram, recombination_rate) on the stored node values, so it has
the field's own shape at any dimensionality -- 1D curves, 2D maps, and
3D volumes alike.

Material and temperature come from the run record (what actually
produced the numbers), falling back to SILICON / 300 K -- ONE material
for the whole device. A heterostructure's per-region materials are not
used here; that limitation predates this module and is kept as it was.
"""
import numpy as np

# band_diagram's outputs, in its return order
BAND_NAMES = ("Ec", "Ev", "EFn", "EFp")
BAND_UNIT = "eV"
RECOMBINATION_UNIT = "cm^-3 s^-1"
BAND_FIELDS = ("potential", "electron_density", "hole_density")
RECOMBINATION_FIELDS = BAND_FIELDS + ("doping",)


def observable_inputs(store):
    """(x_um, psi, n, p, doping, material, T) from `store`, or None when
    there is nothing to draw yet. `doping` is None when the result has
    no doping field. Material/T come from the run record -- what actually
    produced the numbers -- falling back to the silicon defaults."""
    if store is None or not store.is_solved_result():
        return None
    names = store.available_scalars()
    for required in BAND_FIELDS:
        if required not in names:
            return None
    axes = store.mesh_axes()
    x = np.asarray(axes.axes["x"], dtype=float) * 1e4
    psi = np.asarray(store.scalar_field("potential").values, float)
    n = np.asarray(store.scalar_field("electron_density").values, float)
    p = np.asarray(store.scalar_field("hole_density").values, float)
    doping = None
    if "doping" in names:
        doping = np.asarray(store.scalar_field("doping").values, float)
    material, T = "SILICON", 300.0
    record = getattr(store, "run_record", None)
    if callable(record):
        try:
            rec = record()
            if rec is not None:
                material = rec.material or material
                T = rec.T or T
        except Exception:
            pass
    return x, psi, n, p, doping, material, T


def missing_fields(store, required):
    """The names in `required` that `store` lacks, for a named error."""
    have = set(store.available_scalars())
    return [f for f in required if f not in have]


def band_maps(inputs, names=None):
    """{name: array} for the band edges and quasi-Fermi levels [eV]
    (BAND_NAMES), each in the field's shape. `inputs` is
    observable_inputs(); `names` picks a subset (all four by default).
    The selection does not skip work: band_diagram computes all four,
    which keeps this the one implementation (its cost at viewport sizes
    is well under a millisecond -- measured, NATIVE-DESKTOP-PLAN.md 15.16)."""
    from workbench.analysis.observables import band_diagram
    _x, psi, n, p, _doping, material, T = inputs
    maps = dict(zip(BAND_NAMES, band_diagram(psi, n, p, material, T)))
    if names is None:
        return maps
    unknown = [k for k in names if k not in maps]
    if unknown:
        raise KeyError(f"unknown band map(s) {unknown} (known: {', '.join(BAND_NAMES)})")
    return {k: maps[k] for k in names}


def recombination_map(inputs):
    """Net SRH + Auger recombination R [cm^-3 s^-1] in the field's shape
    (see recombination_rate()'s own note on Ntotal). Raises ValueError
    when the result has no doping field, which R needs."""
    from workbench.analysis.observables import recombination_rate
    _x, _psi, n, p, doping, material, T = inputs
    if doping is None:
        raise ValueError("recombination needs the 'doping' field, which this result lacks")
    return recombination_rate(n, p, doping, material, T)
