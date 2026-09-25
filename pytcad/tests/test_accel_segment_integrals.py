"""Compiled WKB segment integrals (_core.segment_integrals) -- the hot
spot of nonlocal-BTBT evaluation (B10 profile, 2026-09-25: 5.2s of a
14.6s solve in btbt.segment_integrals, where _kane_alpha_c is evaluated
8 times per segment on the same 3 points).

btbt.segment_integrals stays as the published-math reference; the kernel
must reproduce it BIT-FOR-BIT (np.array_equal), which the fused C++ loop
earns by mirroring numpy's operation order exactly -- same rule as
CLAUDE.md's "where transcendentals live" note.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad import _accel, btbt, nonlocal_path

pytestmark = pytest.mark.skipif(not _accel.HAVE_ACCEL,
                                reason="pytcad._core not built")

EG_SI = 1.12 * btbt.Q_SI


def _adversarial(rng, n=20000):
    """Random segments plus every edge the Python code branches on:
    flat (|db-da| < 1e-10), both ends outside the gap, ends exactly at
    0/0.5/1, turning-point neighbours, a midpoint below 1e-30, L = 0."""
    da = rng.uniform(-0.5, 1.5, n)
    db = rng.uniform(-0.5, 1.5, n)
    L = rng.uniform(0.0, 5e-9, n)
    k = n // 10
    db[:k] = da[:k]                                   # exactly flat
    db[k:2 * k] = da[k:2 * k] + rng.uniform(-9e-11, 9e-11, k)   # nearly flat
    special = np.array([0.0, 1.0, 0.5, 1e-17, 1 - 1e-16, -1e-300, 1e-31,
                        2e-30, 1 + 1e-15, -0.0, 0.25, 0.75])
    m = special.size
    da[2 * k:2 * k + m * m] = np.repeat(special, m)
    db[2 * k:2 * k + m * m] = np.tile(special, m)
    L[2 * k + m * m:2 * k + m * m + 50] = 0.0
    return da, db, L


def _compiled(da, db, L, Eg_J, mr_kg):
    return nonlocal_path._segment_integrals(da, db, L, Eg_J, mr_kg,
                                            btbt.HBAR_SI)


@pytest.mark.parametrize("mr_ratio", [0.16, 0.08, 0.35])
def test_si1_bit_identical_to_reference(mr_ratio):
    rng = np.random.default_rng(1234)
    da, db, L = _adversarial(rng)
    mr = mr_ratio * btbt.M0_SI
    ref = btbt.segment_integrals(da, db, L, EG_SI, mr)
    got = _compiled(da, db, L, EG_SI, mr)
    names = ("Ik", "Iik", "dIk_da", "dIk_db", "dIik_da", "dIik_db")
    for name, r, g in zip(names, ref, got):
        assert g.shape == r.shape and g.dtype == np.float64, name
        bad = ~((r == g) | (np.isnan(r) & np.isnan(g)))
        assert not bad.any(), (
            f"{name}: {bad.sum()} of {r.size} differ, e.g. da={da[bad][:3]} "
            f"db={db[bad][:3]} ref={r[bad][:3]} got={g[bad][:3]}")


def test_si2_empty_and_mismatched_inputs():
    z = np.zeros(0)
    out = _compiled(z, z, z, EG_SI, 0.16 * btbt.M0_SI)
    assert all(o.shape == (0,) for o in out)
    with pytest.raises(ValueError):
        _accel.core.segment_integrals(np.zeros(3), np.zeros(2), np.zeros(3),
                                      3.0, EG_SI, 1e-31, btbt.HBAR_SI)


def test_si3_refuses_u_not_above_one():
    """eq (9)'s u = m0/(2 mr) > 1 precondition, same refusal as the
    Python reference's _kane_u."""
    one = np.array([0.2]), np.array([0.8]), np.array([1e-9])
    with pytest.raises(ValueError, match="mr < m0/2"):
        _compiled(*one, EG_SI, 0.6 * btbt.M0_SI)


def test_si4_device_evaluate_identical_through_kernel(monkeypatch):
    """A real nonlocal-BTBT device (B10's geometry, quick size): every
    PathEval field from the compiled path equals the pure-Python oracle
    (_evaluate_py, which calls btbt.segment_integrals itself)."""
    from benchmarks import cases
    import pytcad.device2d as d2
    dev, run = cases.get("B10").build("quick")
    run()
    psi = np.ravel(dev.psi)
    got = dev._btbt_nl_eval(psi)
    monkeypatch.setattr(d2, "_nl_evaluate", nonlocal_path._evaluate_py)
    ref = dev._btbt_nl_eval(psi)
    for f in ("G", "Ik", "Iik", "length", "fmin", "fmax", "ddep_val"):
        assert np.array_equal(getattr(got, f), getattr(ref, f)), f
    for f in ("dG", "dep"):
        a, b = getattr(got, f), getattr(ref, f)
        assert (a != b).nnz == 0, f
