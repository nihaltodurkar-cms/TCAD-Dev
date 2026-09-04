"""Performance pass (2026-09-04), item 8: regression gate confirming
gui/services/viewer3d.py's pyvista/pyvistaqt import stays lazy.

Audit finding: `import gui.app` never reaches viewer3d.py -- confirmed
absent from a `python3 -X importtime -c "import gui.app"` trace. This
is already correct, existing design (viewer3d.py imports pyvista at
its own module level, but nothing in gui.app's own import chain
imports viewer3d itself until the user actually opens the 3D viewer),
not something this pass changed. This test locks that in as a
regression gate, the same pattern as
test_performance_lazy_imports.py's cupy check for pytcad.linsolve.
"""
import os
import subprocess
import sys


def test_importing_gui_app_does_not_import_pyvista():
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; import gui.app; "
         "print('pyvista' in sys.modules, 'pyvistaqt' in sys.modules)"],
        capture_output=True, text=True, timeout=30, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False False", (
        "importing gui.app pulled pyvista/pyvistaqt into sys.modules -- "
        "the 3D viewer's lazy-import design this test guards against"
    )
