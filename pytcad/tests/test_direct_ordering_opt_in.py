"""NewtonOptions.direct_ordering: an OPT-IN SuperLU column ordering for
structured Device2D.solve_bias's direct Newton solve.

Default None is the exact pre-existing call, spsolve(Jd.tocsc(), rhs)
with no permc_spec argument, so nothing moves off-path. Measured end to
end (Windows, 2026-09-25, full benchmark sizes): MMD_AT_PLUS_A is 1.6x
faster on B3 and 1.4x on B6, but 3.7x SLOWER on B10 (nonlocal BTBT) and
240x SLOWER on B8 (unstructured) -- which is why it is opt-in only and
read by structured Device2D alone.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

import pytcad.device2d as d2
from pytcad import NewtonOptions
from pytcad.mosfet import build_mosfet

BIAS = {"gate": 1.0, "drain": 0.1, "source": 0.0, "body": 0.0}


def _mosfet():
    dev = build_mosfet(Lg=0.5e-4, Lsd=0.5e-4, depth=0.6e-4, Na=1e17,
                       Nsd_peak=1e20, tox_cm=3e-7, nx=41, ny=25)
    dev.solve_equilibrium()
    return dev


def _spy(monkeypatch):
    seen = []
    real = d2.spsolve

    def spy(A, b, *a, **k):
        seen.append(dict(k))
        return real(A, b, *a, **k)

    monkeypatch.setattr(d2, "spsolve", spy)
    return seen


def test_do1_default_is_none():
    assert NewtonOptions().direct_ordering is None


@pytest.mark.parametrize("bad", ["colamd", "METIS", 3, ""])
def test_do2_unknown_ordering_refused(bad):
    with pytest.raises(ValueError, match="direct_ordering"):
        NewtonOptions(direct_ordering=bad)


def test_do3_default_passes_no_permc_spec(monkeypatch):
    """Off-path bit-identity: the default makes the exact same scipy
    call as before the field existed."""
    dev = _mosfet()
    seen = _spy(monkeypatch)
    dev.solve_bias(BIAS, NewtonOptions(linsolve="direct"))
    assert dev.last_converged
    assert seen and all(k == {} for k in seen), seen


def test_do4_opt_in_ordering_reaches_spsolve_and_agrees(monkeypatch):
    ref = _mosfet()
    ref.solve_bias(BIAS, NewtonOptions(linsolve="direct"))

    dev = _mosfet()
    seen = _spy(monkeypatch)
    dev.solve_bias(BIAS, NewtonOptions(linsolve="direct",
                                       direct_ordering="MMD_AT_PLUS_A"))
    assert dev.last_converged
    assert seen and all(k == {"permc_spec": "MMD_AT_PLUS_A"} for k in seen)
    # Scaled by each field's max, not node-wise: a different LU ordering
    # moves round-off, and minority densities here reach ~1e-20 of the
    # field max (p in the n+ regions), 17 decades below what a double
    # resolves in relative terms. Measured: max|dp|/max|p| = 3.6e-16
    # while node-wise relative p differs by 5x at those nodes.
    for name in ("psi", "n", "p"):
        a, b = np.ravel(getattr(dev, name)), np.ravel(getattr(ref, name))
        assert np.max(np.abs(a - b)) / np.max(np.abs(b)) < 1e-12, name
    for c in ("drain", "source"):
        ia, ib = dev.terminal_current(c), ref.terminal_current(c)
        assert abs(ia - ib) <= 1e-10 * abs(ib), c
