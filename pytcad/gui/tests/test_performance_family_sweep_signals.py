"""Performance pass (2026-09-04), item 7: regression gate confirming
the family (batch) sweep's signal traffic stays cheap.

Audit finding: FamilySweepController uses its own familyChanged signal
exclusively -- confirmed by reading the source, not just the emit
sites' names: _start_next() emits familyChanged() exactly ONCE, only
once self._queue is empty (i.e. after the LAST curve in the batch
finishes), not once per curve and not the heavier resultChanged/
structureChanged AppController fires elsewhere (which would re-trigger
every QML binding keyed off those -- meshStats, fieldNames, every list
model). This test runs a real (fast) 2-point family sweep on diode_1d
and counts actual signal emissions, rather than trusting the source
reading alone.
"""
import time

from PySide6.QtWidgets import QApplication

from gui.controllers.app_controller import AppController


def test_family_sweep_fires_family_changed_once_not_per_curve():
    app = QApplication.instance() or QApplication([])
    ctl = AppController()
    ctl.loadExample("diode_1d")
    ctl.run()
    for _ in range(300):
        app.processEvents()
        time.sleep(0.01)
        if not ctl.busy:
            break
    assert ctl.hasResult, "base solve did not complete in time for this test"

    fs = ctl.familySweep
    family_changed_count = [0]
    result_changed_count = [0]
    structure_changed_count = [0]
    fs.familyChanged.connect(lambda: family_changed_count.__setitem__(
        0, family_changed_count[0] + 1))
    ctl.resultChanged.connect(lambda: result_changed_count.__setitem__(
        0, result_changed_count[0] + 1))
    ctl.structureChanged.connect(lambda: structure_changed_count.__setitem__(
        0, structure_changed_count[0] + 1))

    fs.configureFamily("anode", 0.0, 0.1, 0.1)  # 2 stepped points on anode
    fs.runFamily("cathode", 0.0, 0.2, 0.1)  # sweep cathode within each curve
    for _ in range(600):
        app.processEvents()
        time.sleep(0.01)
        if len(fs.curves) >= 2 or family_changed_count[0] > 0:
            break

    assert len(fs.curves) == 2, f"expected 2 curves, got {len(fs.curves)}"
    assert family_changed_count[0] == 1, (
        f"expected familyChanged to fire exactly once per completed "
        f"family run, fired {family_changed_count[0]} times"
    )
    assert result_changed_count[0] == 0, (
        "family sweep must not fire the heavier resultChanged signal -- "
        f"it fired {result_changed_count[0]} times"
    )
    assert structure_changed_count[0] == 0, (
        "family sweep must not fire the heavier structureChanged signal -- "
        f"it fired {structure_changed_count[0]} times"
    )
