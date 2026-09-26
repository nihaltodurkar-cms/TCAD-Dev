"""NATIVE-DESKTOP-PLAN.md P2-S2 (16.4, decision 4): PlotView's axis
maths equals matplotlib's own, at a GIVEN tick count.

- Linear: AutoLocator's tick_values (its nbins set), and ScalarFormatter's
  labels and offset text for those ticks on that view.
- Log: LogLocator's major (subs=(1.0,)) and minor (subs='auto') tick_values
  at a given numticks -- decade striding on wide ranges, the minor
  locator's AutoLocator fall-back on narrow ones -- and
  LogFormatterSciNotation's labels, including which minor ticks it
  labels under one decade.

Compared with matplotlib's objects themselves (a _DummyAxis carries the
view, as matplotlib's own tests do), never with a reading of its code.
The tick COUNT matplotlib derives from the axis length and font is the
native app's own rule, gated separately (test_desktop_plot.py).
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


def _linear_cases():
    rng = np.random.default_rng(20260926)
    fixed = [(0.0, 1.0), (-1.0, 1.0), (0.0, 0.6), (-0.1, 0.7), (1.0, 7.0), (-2.05, 2.05),
             (0.123456, 0.123457), (-4.05, -3.98), (1e-30, 3e-30), (1e17, 1e17 * (1 + 1e-9)),
             (5.0, 5.0), (0.0, 0.0), (-3.0, -3.0), (0.9, 1.8), (1.0, 2.7), (2.0, 2.3000000000000003),
             (0.03, 0.12), (1.3199999999999999e-08, 1.65e-08), (-1e-5, 3e-4), (0.0, 1e9),
             (99999.5, 100000.5), (1234567.0, 1234569.0), (-0.3, 0.0), (0.0, 2.5e-10),
             (1e-3, 1.0004e-3), (7.3e6, 7.30004e6), (-5e-6, -4.99e-6), (0.0, 1e6), (0.0, 999999.0)]
    cases = [(a, b, int(n)) for (a, b), n in zip(fixed, rng.integers(1, 10, len(fixed)))]
    for n in range(1, 10):          # every tick count on a plain range
        cases.append((0.0, 1.0, n))
        cases.append((-0.6, 0.35, n))
    for _ in range(90):
        kind = rng.integers(0, 6)
        if kind == 0:     # any magnitude
            a, b = sorted(rng.normal(size=2) * 10.0 ** rng.integers(-12, 19))
        elif kind == 1:   # a big offset relative to the span (the offset text)
            c = rng.normal() * 10.0 ** rng.integers(0, 18)
            a, b = sorted(c + rng.normal(size=2) * abs(c) * 10.0 ** -rng.integers(3, 12))
        elif kind == 2:   # bias sweeps
            a, b = sorted(rng.uniform(-5, 5, 2))
        elif kind == 3:   # currents
            a, b = sorted(rng.normal(size=2) * 10.0 ** rng.integers(-14, -2))
        elif kind == 4:   # times / positions
            a, b = 0.0, float(rng.uniform(0.1, 10) * 10.0 ** rng.integers(-12, 0))
        else:             # crossing zero, asymmetric
            a, b = -rng.uniform(0, 1) * 10.0 ** rng.integers(0, 6), rng.uniform(0, 1) * 10.0 ** rng.integers(0, 6)
        cases.append((float(a), float(b), int(rng.integers(1, 10))))
    return cases


def _log_cases():
    rng = np.random.default_rng(20260927)
    fixed = [(1.0, 10.0), (1.0, 1000.0), (1.0, 1e9), (1e-12, 1e-2), (1e-30, 1e20), (1e3, 1e3 * 1.5),
             (2.0, 5.0), (2.0, 5.0 * 1.0001), (0.8, 1.2), (3e-9, 7e-9), (1e-3, 2.4e-3), (5.0, 50.0),
             (1.0, 1e10), (1.0, 1e11), (0.5, 2e9), (1e-15, 1e-6), (1e-5, 3.0), (4.0, 4.0 * 10 ** 0.39),
             (4.0, 4.0 * 10 ** 0.41), (9.0, 11.0), (1e-10, 1e-10 * 2.5)]
    cases = [(a, b, int(n)) for (a, b), n in zip(fixed, rng.integers(2, 10, len(fixed)))]
    for n in range(2, 10):          # striding: every numticks on wide ranges
        cases.append((1e-25, 1e3, n))
        cases.append((3e-7, 2e8, n))
    for _ in range(90):
        lo = rng.uniform(-30, 20)
        span = float(rng.choice([rng.uniform(0.01, 0.4), rng.uniform(0.4, 1.0), rng.uniform(1, 4),
                                 rng.uniform(4, 12), rng.uniform(12, 40)]))
        cases.append((float(10 ** lo), float(10 ** (lo + span)), int(rng.integers(2, 10))))
    return cases


def _mpl_linear(a, b, n):
    from matplotlib.ticker import AutoLocator, ScalarFormatter
    loc = AutoLocator()
    loc.set_params(nbins=n)
    ticks = loc.tick_values(a, b)
    fmt = ScalarFormatter()
    fmt.create_dummy_axis()
    fmt.axis.set_view_interval(a, b)
    labels = fmt.format_ticks(ticks)
    return {"ticks": [float(t) for t in ticks], "labels": labels, "offset": fmt.get_offset()}


def _mpl_log(a, b, n):
    from matplotlib.ticker import LogFormatterSciNotation, LogLocator
    major = LogLocator(subs=(1.0,), numticks=n).tick_values(a, b)
    minor = LogLocator(subs="auto", numticks=n).tick_values(a, b)
    out = {"major": [float(t) for t in major], "minor": [float(t) for t in minor]}
    for key, locs in (("major_labels", major), ("minor_labels", minor)):
        fmt = LogFormatterSciNotation(labelOnlyBase=False)
        fmt.create_dummy_axis()
        fmt.axis.set_view_interval(a, b)
        out[key] = fmt.format_ticks(locs)
    return out


def _native(cases):
    with open(MANIFEST) as fh:
        m = json.load(fh)
    out = subprocess.run([os.path.join(BUILD, m["tools"]["plot_ticks"])], input=json.dumps(cases),
                         capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


LINEAR = _linear_cases()
LOG = _log_cases()


@pytest.fixture(scope="module")
def native_linear():
    return _native([{"kind": "linear", "vmin": a, "vmax": b, "n": n} for a, b, n in LINEAR])


@pytest.fixture(scope="module")
def native_log():
    return _native([{"kind": "log", "vmin": a, "vmax": b, "n": n} for a, b, n in LOG])


def test_the_case_lists_cover_what_16_4_names():
    assert len(LINEAR) >= 100 and len(LOG) >= 100
    decades = [np.log10(b / a) for a, b, _ in LOG]
    assert sum(d < 0.4 for d in decades) >= 5, "sub-0.4-decade views (every minor labelled)"
    assert sum(0.4 < d < 1 for d in decades) >= 5, "sub-decade views (a subset labelled)"
    assert sum(d > 10 for d in decades) >= 10, "wide views (decade striding, no minors)"
    assert any(_mpl_linear(a, b, n)["offset"].startswith("+") for a, b, n in LINEAR), "an offset case"
    assert any("e" in _mpl_linear(a, b, n)["offset"] for a, b, n in LINEAR), "a scientific case"


@pytest.mark.parametrize("i", range(len(LINEAR)), ids=[f"{a:.3g}..{b:.3g}/n{n}" for a, b, n in LINEAR])
def test_linear_ticks_and_labels_equal_matplotlib(native_linear, i):
    a, b, n = LINEAR[i]
    assert native_linear[i] == _mpl_linear(a, b, n)


@pytest.mark.parametrize("i", range(len(LOG)), ids=[f"{a:.3g}..{b:.3g}/n{n}" for a, b, n in LOG])
def test_log_ticks_and_labels_equal_matplotlib(native_log, i):
    a, b, n = LOG[i]
    assert native_log[i] == _mpl_log(a, b, n)
