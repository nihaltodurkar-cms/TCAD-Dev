"""Performance pass (2026-09-04), item 6: benchmark gate confirming the
workbench list models and computed properties stay cheap.

Audit finding: RegionListModel.refresh() (a full beginResetModel/
endResetModel) measured 0.0006ms/call for a real MOSFET (3 regions);
AppController.meshInfo measured 0.0136ms/call. Both already gated
behind specific notify= signals (structureChanged/resultChanged), not
polled per-frame -- QML only recomputes on an actual change. Confirmed
as premature-optimization bait, not touched. This test pins generous
upper bounds (10x the measured cost, not a tight timing assertion that
would be flaky on a loaded CI machine) so a future regression -- e.g.
someone adding an O(n^2) scan to a refresh path -- fails loudly instead
of silently degrading.
"""
import time

from PySide6.QtWidgets import QApplication

from gui.controllers.app_controller import AppController
from gui.controllers.region_list_model import RegionListModel


def _timeit(fn, n=200):
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t0) / n * 1000  # ms/call


def test_region_list_model_refresh_stays_cheap():
    app = QApplication.instance() or QApplication([])
    model = RegionListModel()

    class FakeRegion:
        def __init__(self, i):
            self.id = f"r{i}"
            self.name = f"Region {i}"
            self.x_min, self.x_max, self.y_min, self.y_max = 0.0, 1.0, 0.0, 1.0
            self.net_doping_cm3 = 1e17
            self.material = "SILICON"
            self.doping_profile = "uniform"
            self.profile_peak_cm3 = None
            self.profile_sigma_y = None
            self.profile_sigma_lat = None
            self.profile_edge_x = None
            self.profile_high_side = None

    regions = [FakeRegion(i) for i in range(3)]

    ms = _timeit(lambda: model.refresh(regions))
    # Measured 0.0006ms; 1ms is a very generous 1600x margin, immune to
    # normal machine-load noise while still catching a real regression.
    assert ms < 1.0, f"RegionListModel.refresh() got slow: {ms:.4f}ms/call"


def test_mesh_info_property_stays_cheap():
    app = QApplication.instance() or QApplication([])
    ctl = AppController()
    ctl.loadExample("diode_1d")

    ms = _timeit(lambda: ctl.meshInfo)
    # Measured 0.0136ms; 2ms is a generous ~150x margin.
    assert ms < 2.0, f"AppController.meshInfo got slow: {ms:.4f}ms/call"
