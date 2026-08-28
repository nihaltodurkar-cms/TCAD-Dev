import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QGuiApplication


def _pump(rounds=10):
    """Drain BOTH ordinary posted events and QEvent.DeferredDelete
    (deleteLater()) events. Plain processEvents() calls are not reliably
    enough on their own to flush a deleteLater() posted moments earlier --
    Qt tracks the event-loop "level" a deleteLater() was issued at and can
    defer the actual C++ destruction past a single processEvents() call,
    which is exactly the gap that let torn-down QQuickWindow/MplCanvasItem
    state survive into a LATER test's scenegraph sync (see the crash
    analysis on _close_qml_engines_after_each_test below). Explicitly
    asking for DeferredDelete delivery on every round closes that gap.
    """
    app = QCoreApplication.instance()
    for _ in range(rounds):
        QCoreApplication.processEvents()
        if app is not None:
            app.sendPostedEvents(None, QEvent.DeferredDelete)


def _close_all_top_level_windows():
    """Destroy (and let Qt tear down) every top-level window still alive --
    not just ones this session tracked via create_engine(): a generic
    sweep is the only way to also catch a window created some other way
    (directly, or by a test that predates this fixture), and is cheap
    since an offscreen headless suite has no real windows a user is
    looking at to disturb.

    Uses QWindow.destroy(), not .close(): Main.qml's onClosing handler
    sets close.accepted = false and pops a confirmation dialog whenever
    appController.isDirty is true (see Main.qml) -- and most GUI tests
    leave the controller dirty (loadStructureExample, addRegion, etc. all
    mark the undo stack dirty). close() would therefore silently do
    nothing for most of these windows, leaving them alive for Python's
    GC to collect at an arbitrary later point -- exactly the unsafe path
    this fixture exists to avoid. destroy() bypasses the QML close/
    confirm-dialog logic entirely (it's what close() calls internally
    once a close event is actually accepted) while still running Qt's
    normal window-teardown protocol -- there is no "unsaved changes" the
    test suite needs to protect here.
    """
    app = QGuiApplication.instance()
    if app is None:
        return
    for window in list(app.topLevelWindows()):
        window.destroy()
    _pump()


# Must run before any test file's own gapp/qapp fixture. Qt's application
# singleton is fixed by whichever subclass constructs it first -- a bare
# QCoreApplication built first (e.g. by a Qt-object-only test) can never be
# upgraded to a screen-capable QGuiApplication afterward, so any later
# QQuickWindow creation fails with "Cannot create window: no screens
# available". Forcing QGuiApplication here, ahead of collection-order or
# -k-selection accidents, makes every later `X.instance() or X([])` call
# receive this same capable instance regardless of which file runs first.
@pytest.fixture(scope="session", autouse=True)
def _qt_application():
    app = QGuiApplication.instance() or QGuiApplication([])
    yield app
    # Session teardown: a hard-debug pass found the crash below firing
    # AFTER the very last test's own teardown had already run (between
    # pytest printing the final "100%" progress line and its "N passed"
    # summary) -- i.e. during whatever runs when this fixture itself
    # finalizes and QGuiApplication is about to go away, not mid-test.
    # Any window whose deleteLater() hadn't fully drained yet by then is
    # exactly what QGuiApplication's own destructor would otherwise have
    # to clean up abruptly. Sweep once more, here, before that happens.
    _close_all_top_level_windows()


# Every test that exercises the real QML tree calls gui.app.create_engine()
# to get a fresh QQmlApplicationEngine + Main.qml window, and none of them
# ever close or delete it -- across the dozen files that do this (see
# test_structure_panels.py's own comment on the finding: "the offscreen
# test suite accumulates many live QQuickWindow/MplCanvasItem instances
# across gui/tests/ in one process; one test function too many pushed it
# over into a native Qt scenegraph crash during a later test's repaint").
# That comment worked around the crash in one test by reusing an existing
# engine instead of creating another; it did not stop the underlying
# accumulation, which a hard-debug pass reproduced independently (a native
# __cxa_deleted_virtual abort inside QQuickPaintedItem::updatePaintNode,
# roughly 1 run in 3 for the full `gui/tests/` suite).
#
# Root cause: a QQuickWindow (Main.qml's root object) left for Python's
# refcounting GC to collect is destroyed at an arbitrary point outside
# Qt's own window-teardown protocol (QWindow.close() -> hide the platform
# window -> let any in-flight scenegraph sync/paint-node update settle
# -> only then free the C++ object). Skip that protocol and a paint-node
# update already scheduled via MplCanvasItem.update() (itself scheduled by
# perfectly ordinary calls like setStore()/fit() during the test) can still
# be sitting in Qt's dirty-item list when the window's C++ object is torn
# down; a later scenegraph sync (during a DIFFERENT test's window, sharing
# this same process-wide QGuiApplication and render loop) walks that list
# and calls into a vtable that has already run its derived-class
# destructor -- exactly what __cxa_deleted_virtual signals.
#
# Fix: after every test, close every top-level window still alive (not
# just ones created via create_engine() -- a generic sweep also catches a
# window made any other way) and drain BOTH ordinary and DeferredDelete
# events before the next test's create_engine() gets to pile another
# window on top of whatever this one leaves behind. A first attempt at
# this fix tracked engines individually (via a monkeypatched
# gui.app.create_engine) and called plain processEvents() a fixed number
# of times; that reduced but did not eliminate the crash -- it recurred
# once in 3 full-suite reruns, and every recurrence landed at the very
# END of the session (after the last test's own dots printed, before
# pytest's "N passed" summary), which is what pointed at incompletely-
# drained deleteLater() calls surviving all the way to QGuiApplication's
# own teardown (see _qt_application's session-end sweep above) rather
# than at any single test's cleanup being the gap.
@pytest.fixture(autouse=True)
def _close_qml_windows_after_each_test():
    yield
    _close_all_top_level_windows()
