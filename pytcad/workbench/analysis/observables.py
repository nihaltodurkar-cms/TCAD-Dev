"""Observables: the analysis vocabulary shared by every solver backend.

An observable takes PLAIN ARRAYS (what any backend's RunResult carries
as node-centered fields / sweep series) and returns plain arrays or
scalars.  Math that already exists in gui.services.sweep_derived is
delegated to, never reimplemented -- today's GUI readouts are the
numerical ground truth and parity with them is pinned by tests.

band_diagram() mirrors pytcad.device.Device1D.band_diagram()'s exact
conventions (eV, vacuum reference, Boltzmann QFLs) but consumes
physical-unit arrays -- psi in volts, n/p in cm^-3 -- instead of scaled
solver state.
"""
import numpy as np

from pytcad.constants import KB_EV

from ..core.materials import LIBRARY
from gui.services import sweep_derived


def current_extremes(channels):
    """(Imax, Imin) per the GUI's own convention.  Delegates."""
    return sweep_derived.current_extremes(channels)


def on_off_ratio(channels):
    """Ion/Ioff transfer-curve ratio.  Delegates."""
    return sweep_derived.on_off_ratio(channels)


def threshold_voltage_max_gm(voltages, currents, vds=0.0):
    """Max-gm extrapolated threshold (+Vds/2 correction).  Delegates."""
    return sweep_derived.threshold_voltage_max_gm(voltages, currents,
                                                  vds=vds)


def gm_curve(voltages, currents):
    """Transconductance dId/dVg [A/V] by central differences on the
    swept channel's current series.  NaN inputs (diverged sweep points)
    stay NaN in their neighborhood -- honest gaps, never interpolated."""
    return np.gradient(np.asarray(currents, dtype=float),
                       np.asarray(voltages, dtype=float))


def band_diagram(psi_V, n, p, material="SILICON", T=300.0):
    """Conduction/valence band edges + quasi-Fermi levels [eV] from
    physical-unit arrays.  Exact mirror of Device1D.band_diagram():
        Ec  = -psi - chi
        Ev  = Ec - Eg(T)
        EFn = Ec + VT ln(n/Nc(T))
        EFp = Ev - VT ln(p/Nv(T))
    """
    mat = LIBRARY.get(material)
    psi = np.asarray(psi_V, dtype=float)
    n_arr = np.maximum(np.asarray(n, dtype=float), 1e-30)
    p_arr = np.maximum(np.asarray(p, dtype=float), 1e-30)
    VT = KB_EV * T                               # thermal voltage [eV]
    Ec = -psi - mat.chi
    Ev = Ec - mat.Eg(T)
    EFn = Ec + VT * np.log(n_arr / mat.Nc(T))
    EFp = Ev - VT * np.log(p_arr / mat.Nv(T))
    return Ec, Ev, EFn, EFp


OBSERVABLES = {
    "current_extremes": current_extremes,
    "on_off_ratio": on_off_ratio,
    "threshold_voltage_max_gm": threshold_voltage_max_gm,
    "gm_curve": gm_curve,
    "band_diagram": band_diagram,
}
