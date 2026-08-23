"""Matplotlib-backed viewport as a pure Qt Quick item.

Renders a Figure through the Agg backend into an RGBA buffer, wraps that
in a QImage, and paints it -- no QWidget bridging anywhere, so the whole
UI stays Qt Quick.

VTK/PyVista are deliberately absent: v0.1's viewport is 2D only, and a
real 3D scientific renderer is its own design decision for the version
that needs it.  Nothing here blocks that later -- the viewport talks to
the ResultStore interface, so a 3D item can be swapped in beside it.
"""
import matplotlib
matplotlib.use("Agg")

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Property, QObject, Signal, Slot, Qt
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickPaintedItem

_MIN_POSITIVE = 1e-30


class MplCanvasItem(QQuickPaintedItem):
    viewChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFlag(QQuickPaintedItem.ItemHasContents, True)
        self._store = None
        self._field = ""
        self._log = False
        self._home = None          # (xlim, ylim) from the last fit()
        self._xlim = None
        self._ylim = None
        self._buf = None           # keep the Agg buffer alive while QImage uses it

    # -- data ---------------------------------------------------------
    @Slot(object, str)
    def setStore(self, store, field=""):
        self._store = store
        names = store.available_scalars() if store else []
        self._field = field or (names[0] if names else "")
        self._home = None
        self.fit()

    @Slot(str)
    def setField(self, name):
        self._field = name
        self.update()

    @Slot(QObject)
    def bindController(self, controller):
        """Follow an AppController's current store/field automatically."""
        def refresh():
            self.setStore(controller.currentStore(), controller.currentField)
        controller.resultChanged.connect(refresh)
        controller.fieldChanged.connect(
            lambda: self.setField(controller.currentField))
        refresh()

    @Property(bool, notify=viewChanged)
    def logScale(self):
        return self._log

    @logScale.setter
    def logScale(self, value):
        self._log = bool(value)
        self.update()

    # -- view control -------------------------------------------------
    @Slot()
    def fit(self):
        if self._store is None:
            self._xlim = self._ylim = None
        else:
            axes = self._store.mesh_axes()
            x = np.asarray(axes.axes["x"], dtype=float) * 1e4     # cm -> um
            self._xlim = (float(x.min()), float(x.max()))
            if "y" in axes.axes:
                y = np.asarray(axes.axes["y"], dtype=float) * 1e4
                self._ylim = (float(y.min()), float(y.max()))
            else:
                self._ylim = None
            self._home = (self._xlim, self._ylim)
        self.viewChanged.emit()
        self.update()

    @Slot()
    def resetView(self):
        if self._home is None:
            self.fit()
            return
        self._xlim, self._ylim = self._home
        self.viewChanged.emit()
        self.update()

    @Slot(float)
    def zoom(self, factor):
        """factor < 1 zooms in, > 1 zooms out, about the view centre."""
        def scaled(lim):
            if lim is None:
                return None
            lo, hi = lim
            mid, half = 0.5 * (lo + hi), 0.5 * (hi - lo) * factor
            return (mid - half, mid + half)
        self._xlim = scaled(self._xlim)
        self._ylim = scaled(self._ylim)
        self.viewChanged.emit()
        self.update()

    @Slot(float, float)
    def pan(self, dx_frac, dy_frac):
        """Shift the view by a fraction of the current span."""
        if self._xlim is not None:
            lo, hi = self._xlim
            d = (hi - lo) * dx_frac
            self._xlim = (lo + d, hi + d)
        if self._ylim is not None:
            lo, hi = self._ylim
            d = (hi - lo) * dy_frac
            self._ylim = (lo + d, hi + d)
        self.viewChanged.emit()
        self.update()

    def axisLimits(self):
        return (self._xlim, self._ylim)

    # -- rendering ----------------------------------------------------
    def _build_figure(self, width_px, height_px):
        dpi = 100.0
        fig = Figure(figsize=(max(width_px, 1) / dpi, max(height_px, 1) / dpi),
                     dpi=dpi)
        ax = fig.add_subplot(111)

        if self._store is None:
            ax.text(0.5, 0.5, "No project loaded", ha="center", va="center")
            ax.set_axis_off()
            return fig

        try:
            field = self._store.scalar_field(self._field)
        except KeyError:
            ax.text(0.5, 0.5, f"'{self._field}' is not available\nfor this view",
                    ha="center", va="center")
            ax.set_axis_off()
            return fig

        axes = self._store.mesh_axes()
        x = np.asarray(axes.axes["x"], dtype=float) * 1e4          # um
        values = np.asarray(field.values, dtype=float)

        if axes.dimensionality == 1:
            ax.plot(x, self._maybe_log(values))
            ax.set_xlabel("x [um]")
            ax.set_ylabel(f"{field.name} [{field.unit}]")
            if self._xlim:
                ax.set_xlim(*self._xlim)
        else:
            y = np.asarray(axes.axes["y"], dtype=float) * 1e4
            if axes.dimensionality == 3:
                # v0.1 shows the central z-plane; a real 3D viewer is a
                # later version's job.
                values = values[values.shape[0] // 2]
            mesh = ax.pcolormesh(x, y, self._maybe_log(values), shading="nearest")
            cbar = fig.colorbar(mesh, ax=ax)
            label = f"{field.name} [{field.unit}]"
            cbar.set_label(f"log10 |{label}|" if self._log else label)
            ax.set_xlabel("x [um]")
            ax.set_ylabel("y [um]")
            ax.invert_yaxis()          # y increases into the substrate
            if self._xlim:
                ax.set_xlim(*self._xlim)
            if self._ylim:
                ax.set_ylim(self._ylim[1], self._ylim[0])
        fig.tight_layout()
        return fig

    def _maybe_log(self, values):
        if not self._log:
            return values
        return np.log10(np.maximum(np.abs(values), _MIN_POSITIVE))

    @Slot(result=object)
    def renderToImage(self):
        w = max(int(self.width()), 1)
        h = max(int(self.height()), 1)
        fig = self._build_figure(w, h)
        canvas = FigureCanvasAgg(fig)
        canvas.draw()
        # hold a reference: QImage wraps this memory without copying
        self._buf = canvas.buffer_rgba()
        rw, rh = canvas.get_width_height()
        return QImage(self._buf, rw, rh, QImage.Format_RGBA8888)

    def paint(self, painter):
        img = self.renderToImage()
        if not img.isNull():
            painter.drawImage(self.boundingRect(), img)
