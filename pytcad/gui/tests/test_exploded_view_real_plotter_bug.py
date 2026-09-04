"""Regression tests for two real, pre-existing bugs in exploded view
found by actually exercising a REAL pyvista Plotter -- not the test
suite's own FakeInteractor mock every other exploded-view test uses
(test_viewer3d.py's own module docstring explains why: building a real
pyvistaqt.QtInteractor needs a live GL surface, which every prior test
avoided by faking the interactor entirely). That mock happened to hide
both bugs below, because it coincidentally provided an API surface the
real plotter class does not.

Uses pyvista's own OFF_SCREEN rendering (OSMesa/EGL software rendering,
no live window needed) instead of the fake, so these tests exercise the
REAL Plotter.add_mesh/remove_actor/reset_camera methods production code
actually calls.

Bug 1 -- AttributeError crash on every real run: _remove_monolithic_
surface() used to scan `self.plotter.added`, an attribute that exists
ONLY on the test suite's FakeInteractor (a recording mock), not on a
real pyvistaqt.QtInteractor/pv.Plotter. Confirmed directly: toggling
"Exploded view" against a real plotter raised
`AttributeError: '...' object has no attribute 'added'` from inside the
checkbox's own Qt slot -- regardless of whether region data existed.
Fixed by tracking the monolithic-surface actor directly (self.
_monolithic_surface_actor), the same pattern _iso_actor/_volume_actor
already use elsewhere in this file.

Bug 2 -- default/range invisible at real device scale: self.
_exploded_separation defaulted to a hardcoded 0.5 cm, and the spinbox's
own range was 0.01-10.0 cm. Every device this app ships spans roughly
1e-5 to 2e-4 cm total, so a z_offset of idx*0.5 pushed exploded regions
2,500x-50,000x farther apart than the device itself -- reset_camera()
zoomed out until each region was sub-pixel, so exploded view LOOKED
like a no-op (checkbox checks, nothing visible) even once bug 1 was
fixed and real region data existed. Confirmed by rendering an actual
screenshot before and after: the "before" fix render showed nothing but
the color-bar legend; after scaling the default/range from the device's
own self.grid.length, the three regions render as clearly distinct,
separated blocks. Fixed by computing the default (and the spinbox's
range/step) from self.grid.length instead of a fixed constant.
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pyvista as pv
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from gui.services import examples
from gui.services.result_store import NpzResultStore
from gui.services.solver_runner import run_job
from gui.services import viewer3d

pv.OFF_SCREEN = True


@pytest.fixture(scope="module")
def gapp():
    yield QApplication.instance() or QApplication([])


class RealOffscreenInteractor:
    """Wraps a REAL pv.Plotter(off_screen=True) behind QtInteractor's
    API surface (add_mesh/remove_actor/reset_camera/close) -- unlike
    test_viewer3d.py's FakeInteractor, this is the actual pyvista
    Plotter class production code runs against, just rendering to an
    off-screen buffer instead of a live window (this sandbox's Xwayland
    session cannot host VTK's own raw-X11 on-screen render window --
    confirmed directly, unrelated to anything under test here)."""

    def __init__(self, parent=None):
        self._p = pv.Plotter(off_screen=True, window_size=[800, 600])
        self.interactor = QWidget(parent)

    def add_mesh(self, *a, **k):
        return self._p.add_mesh(*a, **k)

    def remove_actor(self, *a, **k):
        return self._p.remove_actor(*a, **k)

    def reset_camera(self):
        return self._p.reset_camera()

    def close(self):
        return self._p.close()

    def screenshot(self, path):
        return self._p.screenshot(path)


@pytest.fixture()
def mosfet_3d_store(tmp_path):
    spec = examples.mosfet_3d_example_spec()
    job = str(tmp_path / "job.json")
    out = str(tmp_path / "out.npz")
    spec.to_json(job)
    run_job(job, out)
    return NpzResultStore(out)


def test_exploded_view_toggle_does_not_crash_against_a_real_plotter(
        gapp, mosfet_3d_store, monkeypatch):
    monkeypatch.setattr(viewer3d, "QtInteractor", RealOffscreenInteractor)
    win = viewer3d.Viewer3DWindow(mosfet_3d_store)

    win._exploded_toggle.setCheckState(Qt.Checked)   # bug 1: used to raise
    assert win._exploded_view is True
    assert len(win._region_actors) == 3

    win._exploded_toggle.setCheckState(Qt.Unchecked)  # restore path
    assert win._exploded_view is False
    assert win._region_actors == []

    win._exploded_toggle.setCheckState(Qt.Checked)   # toggle back on
    assert win._exploded_view is True
    assert len(win._region_actors) == 3


def test_exploded_view_default_separation_is_visible_at_device_scale(
        gapp, mosfet_3d_store, monkeypatch):
    """bug 2: the default must put regions apart by an amount
    comparable to the device's OWN size, not a fixed constant that
    dwarfs it -- assert the ratio directly rather than re-deriving the
    exact formula, so this stays a behavioral guard, not a change-
    detector on the constant."""
    monkeypatch.setattr(viewer3d, "QtInteractor", RealOffscreenInteractor)
    win = viewer3d.Viewer3DWindow(mosfet_3d_store)

    ratio = win._exploded_separation / win.grid.length
    assert 0.01 < ratio < 1.0, (
        f"default separation ({win._exploded_separation} cm) is not "
        f"comparable to the device size ({win.grid.length} cm) -- "
        f"ratio={ratio}")

    # the spinbox range must actually reach values usable at this
    # device's scale, not floor out well above it
    assert win._exploded_sep_spin.minimum() < win.grid.length


def test_exploded_view_regions_are_visually_separated_along_z(
        gapp, mosfet_3d_store, monkeypatch):
    """Beyond "no crash" and "sane default": the actual rendered region
    actors must occupy DIFFERENT z-ranges (that's the entire point of
    "exploded") -- reads pyvista's own actor bounds, not a screenshot
    pixel check, for a robust headless assertion."""
    monkeypatch.setattr(viewer3d, "QtInteractor", RealOffscreenInteractor)
    win = viewer3d.Viewer3DWindow(mosfet_3d_store)
    win._exploded_toggle.setCheckState(Qt.Checked)

    z_centers = []
    for actor in win._region_actors:
        b = actor.GetBounds()   # (xmin,xmax,ymin,ymax,zmin,zmax)
        z_centers.append((b[4] + b[5]) / 2.0)
    assert len(set(round(z, 12) for z in z_centers)) == 3, (
        f"regions were not actually separated along z: {z_centers}")
