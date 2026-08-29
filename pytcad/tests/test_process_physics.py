"""Backend coverage for pytcad.process.junction_depth / silicon_consumed.

These functions are already used correctly by examples/02_process_flow.py
but had no dedicated unit tests. Additive-only: no changes to pytcad/.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from pytcad import process


def test_junction_depth_finds_the_sign_change():
    x = np.linspace(0.0, 1e-4, 1001)
    net = np.where(x < 3e-5, 1e18, -1e16)   # n-on-p, junction near x=3e-5
    xj = process.junction_depth(x, net)
    assert len(xj) == 1
    assert abs(xj[0] - 3e-5) < 5e-7


def test_junction_depth_empty_for_no_sign_change():
    x = np.linspace(0.0, 1e-4, 101)
    net = np.full_like(x, 1e17)
    assert len(process.junction_depth(x, net)) == 0


def test_silicon_consumed_matches_the_0_44_factor():
    assert abs(process.silicon_consumed(1.0) - 0.44) < 1e-12
    assert np.allclose(process.silicon_consumed(np.array([0.0, 2.0])), [0.0, 0.88])
