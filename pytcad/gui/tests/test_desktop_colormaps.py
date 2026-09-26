"""NATIVE-DESKTOP-PLAN.md P1 S5b: the native app colours a value exactly
as the QML viewport (matplotlib) does.

1. The tables: tcad_theme_dump --colormaps equals matplotlib's
   cmap(i / 255) for viridis, plasma, inferno and RdBu_r, all 256
   entries.
2. The indexing: tcad_desktop --lut-probe (VTK's own vtkLookupTable over
   [lo, hi]) gives each value the colour matplotlib's cmap(Normalize(lo,
   hi)(v)) gives. The values are random, the range ends, out-of-range
   values (clamped to the end colours in both), and exact bin
   boundaries.

NaN is left out: matplotlib draws it in its "bad" colour (transparent)
and VTK in its NaN colour. No result field carries NaN; the grammar's
sweep NaNs are curves, not maps.
"""
import json
import os
import subprocess

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILD = os.path.join(ROOT, "build", "desktop")
MANIFEST = os.path.join(BUILD, "desktop_runtime.json")

pytestmark = pytest.mark.skipif(
    not os.path.isfile(MANIFEST),
    reason="native desktop app not built (powershell -File desktop\\build.ps1)")

MAPS = ["viridis", "plasma", "inferno", "RdBu_r"]


def _manifest():
    with open(MANIFEST) as fh:
        return json.load(fh)


def _run(tool, *args):
    m = _manifest()
    env = dict(os.environ, PATH=m["runtime_bin"] + os.pathsep + os.environ.get("PATH", ""))
    env.pop("QT_QPA_PLATFORM", None)
    out = subprocess.run([os.path.join(BUILD, m["tools"][tool]), *map(str, args)],
                         capture_output=True, text=True, env=env, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_tables_equal_matplotlib():
    import matplotlib
    tables = _run("theme_dump", "--colormaps")
    assert list(tables) == MAPS
    for name in MAPS:
        want = matplotlib.colormaps[name](np.arange(256) / 255.0)[:, :3]
        got = np.asarray(tables[name])
        assert got.shape == (256, 3)
        assert np.max(np.abs(got - want)) < 1e-12, name


@pytest.mark.parametrize("name", MAPS)
@pytest.mark.parametrize("lo,hi", [(0.0, 1.0), (-3.5, 12.25), (1e10, 1e18), (-1e-7, 2e-7), (5.0, 5.0)],
                         ids=["unit", "mixed", "huge", "tiny", "constant-field"])
def test_vtk_lookup_colours_values_as_matplotlib_does(name, lo, hi):
    import matplotlib
    from matplotlib.colors import Normalize
    rng = np.random.default_rng(abs(hash((name, lo, hi))) % 2**32)
    span = hi - lo
    values = np.concatenate([
        rng.uniform(lo, hi, 300),
        [lo, hi, lo - span, hi + span],                    # ends, and clamping
        lo + span * (np.arange(1, 256) / 256.0),           # exact bin boundaries
    ])
    got = np.asarray(_run("desktop", "--lut-probe", name, repr(lo), repr(hi), *[repr(float(v)) for v in values]))
    want = matplotlib.colormaps[name](Normalize(lo, hi)(values))[:, :3]
    # vtkLookupTable stores its table as bytes, so it answers in 8-bit
    # colours: the exact comparison is matplotlib's colour rounded to 8
    # bits (measured: rounding, not truncation) -- which is also all a
    # screen shows. An off-by-one index would still show up here.
    got8 = np.rint(got * 255).astype(int)
    want8 = np.rint(want * 255).astype(int)
    assert np.allclose(got * 255, got8, atol=1e-6), "VTK colours are not whole 8-bit levels any more"
    bad = np.nonzero(np.any(got8 != want8, axis=1))[0]
    assert len(bad) == 0, [(float(values[i]), got8[i].tolist(), want8[i].tolist()) for i in bad[:5]]
