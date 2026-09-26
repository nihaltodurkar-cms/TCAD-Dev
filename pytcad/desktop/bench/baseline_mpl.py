"""Baseline: frame times of TODAY's viewport (gui/visualization/
mpl_canvas_item.py) on a result file, measured the same way as the
native app's --bench (NATIVE-DESKTOP-PLAN.md section 6).

    python desktop/bench/baseline_mpl.py <result.npz> [--frames N]

Prints one JSON object. Runs offscreen: MplCanvasItem renders through
matplotlib's Agg (CPU) backend whatever the platform plugin, so the
offscreen numbers are the numbers a user gets.
"""
import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from gui.services.result_store import NpzResultStore  # noqa: E402
from gui.visualization.mpl_canvas_item import MplCanvasItem  # noqa: E402

W, H = 1200, 800


def _stats(ms):
    ms = sorted(ms)
    pick = lambda p: ms[min(len(ms) - 1, int(p * (len(ms) - 1) + 0.5))]  # noqa: E731
    return {"n": len(ms), "p50_ms": pick(0.5), "p95_ms": pick(0.95), "max_ms": ms[-1]}


def _timed(n, step):
    out = []
    for i in range(n):
        t = time.perf_counter()
        step(i)
        out.append((time.perf_counter() - t) * 1e3)
    return out


def measure(path, frames=30):
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    t = time.perf_counter()
    store = NpzResultStore(path)
    names = store.available_scalars()
    item = MplCanvasItem()
    item.setWidth(W)
    item.setHeight(H)
    item.setMode("doping")
    item.setStore(store, names[0])
    item.renderToImage()
    out = {"file": path, "open_and_first_render_ms": (time.perf_counter() - t) * 1e3,
           "dimensionality": store.mesh_axes().dimensionality}
    item.renderToImage()

    def pan(i):
        item.pan(0.01 if (i // 10) % 2 == 0 else -0.01, 0.0)
        item.renderToImage()

    def zoom(i):
        item.zoom(0.97 if (i // 10) % 2 == 0 else 1 / 0.97)
        item.renderToImage()

    def switch(i):
        item.setField(names[i % len(names)])
        item.renderToImage()

    out["pan"] = _stats(_timed(frames, pan))
    out["zoom"] = _stats(_timed(frames, zoom))
    out["field_switch"] = _stats(_timed(max(len(names) * 2, 8), switch))
    xs = np.random.default_rng(12345).uniform(0, W, 2000)
    t = time.perf_counter()
    for x in xs:
        item.hoverAt(float(x), 0.5 * H)
    out["hover_lookup_ms"] = (time.perf_counter() - t) * 1e3 / len(xs)
    return out


if __name__ == "__main__":
    frames = int(sys.argv[sys.argv.index("--frames") + 1]) if "--frames" in sys.argv else 30
    print(json.dumps(measure(sys.argv[1], frames)))
