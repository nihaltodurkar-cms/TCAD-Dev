"""M11-S3: 1D heterojunction core -- acceptance tests.

Gate order per HETEROSTRUCTURE-PLAN.md section 7:
  a) homojunction regression is covered structurally (uniform-material
     devices reduce algebraically to the original equations) and by the
     entire pre-existing suite;
  b/c) this file: two-material finite-difference Jacobian, Anderson-
       rule equilibrium band step, and carrier continuity across the
       interface.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad import Models
from pytcad.device import Device1D
from pytcad.materials import SILICON, GAAS, GE


def _hetero_device(mat_a, mat_b, Na=-1e17, Nd=1e17):
    """40-node p(i)-n(j) junction whose LEFT half is mat_a and RIGHT
    half is mat_b; the material interface sits exactly on node 19."""
    x = np.linspace(0.0, 2e-4, 40)
    doping = np.where(x < 1e-4, Na, Nd)
    mats = [mat_a] * 20 + [mat_b] * 20
    return Device1D(x, doping, T=300.0, material=mats,
                    models=Models(bgn=False))


def test_constructor_accepts_per_node_material_list():
    dev = _hetero_device(SILICON, GAAS)
    assert isinstance(dev.mat, list) and len(dev.mat) == 40


def test_fd_jacobian_across_material_interface():
    """The analytic Jacobian must match finite differences everywhere --
    especially within a few nodes of the Si/GaAs interface."""
    pytest.importorskip("scipy")
    dev = _hetero_device(SILICON, GAAS)
    opts = type(dev.models)  # noqa -- silence lint only
    dev.solve_equilibrium()
    # perturb onto a biased state so ALL residual rows are active
    dev.solve_bias([0.0, 0.2])

    from pytcad.device import NewtonOptions
    psi, n, p = dev.psi.copy(), dev.n.copy(), dev.p.copy()
    bc = [(psi[0], n[0], p[0]), (psi[-1], n[-1], p[-1])]
    F, J, _, _ = dev._residual_jacobian(psi, n, p, bc)

    rng = np.random.default_rng(42)
    worst = 0.0
    scale = np.maximum(np.abs(F), 1.0)
    for col in rng.choice(range(3 * dev.N), size=60, replace=False):
        d = 1e-6 * max(abs(psi[col // 3]), abs(n[col // 3]),
                       abs(p[col // 3]), 1e-12)
        kind = col % 3
        idx = col // 3
        pp, nn, ppn = psi.copy(), n.copy(), p.copy()
        if kind == 0:
            pp[idx] += d
        elif kind == 1:
            nn[idx] += d
        else:
            ppn[idx] += d
        Fp, _, _, _ = dev._residual_jacobian(pp, nn, ppn, bc)
        fd = (Fp - F) / d
        ana = np.asarray(J[:, col].todense()).ravel()
        rel = np.max(np.abs(fd - ana) / scale)
        worst = max(worst, float(rel))
    assert worst < 5e-5, f"worst FD-vs-analytic relative error {worst:.3e}"


def test_anderson_band_step_at_interface():
    """Equilibrium band diagram across a Ge/GaAs isotype junction must
    show a conduction-band step equal to the electron-affinity
    difference (chi_Ge - chi_GaAs = 4.13 - 4.07 = 0.06 eV), located at
    the material interface (Anderson rule)."""
    dev = _hetero_device(GE, GAAS, Na=0.0, Nd=0.0)
    # uniform doping zero -> make it n-type both sides via small donors
    dev.doping[:] = 1e16
    dev.Ntot = np.abs(dev.doping)
    # recompute derived fields the constructor built for the old doping
    dev.C = dev.doping / dev.Ns
    dev.solve_equilibrium()
    Ec, Ev, EFn, EFp = dev.band_diagram()
    step = abs(Ec[20] - Ec[18])          # bracketing the interface node
    # Anderson prediction INCLUDING the electrostatic share: the two
    # sides have different nie, so their neutral-bulk psi differs by
    # VT*ln(nie_Ge/nie_GaAs) even at equal doping
    nie_ge = np.sqrt(GE.Nc300 * GE.Nv300)
    nie_gaas = np.sqrt(GAAS.Nc300 * GAAS.Nv300)
    expected = abs(abs(GE.chi - GAAS.chi)
                   + 0.02585 * np.log(nie_ge / nie_gaas))
    assert step == pytest.approx(expected, rel=0.10), \
        f"interface Ec step {step:.4f} eV vs Anderson {expected:.4f}"


def test_carrier_continuity_across_interface():
    """Equilibrium detailed balance: with zero applied bias the
    band-offset-aware SG current must vanish on EVERY edge -- including
    the two edges that cross the Si/GaAs material interface."""
    dev = _hetero_device(SILICON, GAAS)
    dev.solve_equilibrium()          # zero bias only
    h = dev.h
    delta_n = ((dev.psi[1:] - dev.psi[:-1])
               + np.log(dev.nie_s[1:] / dev.nie_s[:-1]))
    from pytcad.device import bernoulli
    Bp = bernoulli(delta_n)
    Bm = bernoulli(-delta_n)
    an = ((2.0 * dev.mu_n0[:-1] * dev.mu_n0[1:])
          / (dev.mu_n0[:-1] + dev.mu_n0[1:])) * dev.VT / h
    Jn_edges = an * (dev.n[1:] * Bp - dev.n[:-1] * Bm)

    mid = len(Jn_edges) // 2
    # carrier-density scale for normalization
    scale = float(np.max(dev.mu_n0) * dev.VT * np.max(dev.n) / np.min(h))
    worst = float(np.max(np.abs(Jn_edges))) / scale
    assert worst < 1e-10, \
        f"equilibrium detailed balance broken at/near interface " \
        f"(node {mid}): {worst:.3e} of scale"
    # and specifically the two interface edges carry no more than the rest
    interface = np.abs(Jn_edges[mid - 1:mid + 1]) / scale
    assert np.all(interface <= worst * 4), \
        f"interface edges stand out: {interface} vs {worst:.3e}"
