import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QGuiApplication


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
    yield QGuiApplication.instance() or QGuiApplication([])
