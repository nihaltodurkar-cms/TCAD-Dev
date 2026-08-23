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

from ..services.structure_model import rasterize_doping

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
        self._structure = None
        self._mesh_model = None
        self._mode = "doping"

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

    @Slot(object, object)
    def setStructureSource(self, structure, mesh_model):
        # Deliberately does NOT touch self._mode: ViewportPanel.setViewMode()
        # always calls setMode(mode) immediately before this, for every mode
        # (structure/mesh/doping) that needs structure data. An earlier
        # version hardcoded self._mode = "structure" here, which silently
        # clobbered setMode("mesh")'s choice back to "structure" on every
        # call -- the live Mesh viewport was rendering the structure diagram,
        # not a mesh grid, and no headless test caught it because tests call
        # setStructureSource() before setMode(), the opposite order QML uses.
        self._structure = structure
        self._mesh_model = mesh_model
        self.fit()

    @Slot(str)
    def setMode(self, mode):
        self._mode = mode
        self.update()

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
        if self._mode in ("structure", "mesh") and self._structure is not None:
            self._xlim = (0.0, self._structure.width_cm * 1e4)
            self._ylim = (0.0, self._structure.height_cm * 1e4)
            self._home = (self._xlim, self._ylim)
            self.viewChanged.emit()
            self.update()
            return
        # Doping mode before any solve has no ResultStore yet -- fit to the
        # structure's own extent instead. Once a store exists (post-solve)
        # it takes priority below, same as it always has.
        if self._mode == "doping" and self._store is None and self._structure is not None:
            self._xlim = (0.0, self._structure.width_cm * 1e4)
            self._ylim = (0.0, self._structure.height_cm * 1e4)
            self._home = (self._xlim, self._ylim)
            self.viewChanged.emit()
            self.update()
            return
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

        if self._mode == "structure" and self._structure is not None:
            self._draw_structure(ax)
            fig.tight_layout()
            return fig
        if self._mode == "mesh" and self._mesh_model is not None:
            self._draw_mesh(ax)
            fig.tight_layout()
            return fig
        # Doping mode with a structure but no solve yet: rasterize the
        # structure's own regions instead of falling back to "No project
        # loaded". Once a solve produces a ResultStore, that takes over
        # via the normal field-rendering path below -- unchanged.
        if self._mode == "doping" and self._store is None and self._structure is not None and self._mesh_model is not None:
            self._draw_doping_preview(ax)
            fig.tight_layout()
            return fig

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

    def _draw_structure(self, ax):
        s = self._structure
        for region in s.regions:
            colour = "#c0392b" if region.net_doping_cm3 > 0 else "#2980b9"
            ax.add_patch(__import__("matplotlib").patches.Rectangle(
                (region.x_min * 1e4, region.y_min * 1e4),
                (region.x_max - region.x_min) * 1e4,
                (region.y_max - region.y_min) * 1e4,
                facecolor=colour, alpha=0.35, edgecolor=colour, linewidth=1.2))
            ax.text((region.x_min + region.x_max) / 2 * 1e4,
                    (region.y_min + region.y_max) / 2 * 1e4,
                    region.name, ha="center", va="center", fontsize=8)
        for contact in s.contacts:
            self._draw_boundary(ax, contact.boundary, "#27ae60", contact.name)
        for gate in s.gates:
            self._draw_boundary(ax, gate.boundary, "#8e44ad", gate.name)
        ax.set_xlim(0.0, s.width_cm * 1e4)
        ax.set_ylim(s.height_cm * 1e4, 0.0)
        ax.set_xlabel("x [um]"); ax.set_ylabel("y [um]")
        if self._xlim:
            ax.set_xlim(*self._xlim)
        if self._ylim:
            ax.set_ylim(self._ylim[1], self._ylim[0])

    def _draw_boundary(self, ax, boundary, colour, label):
        s = self._structure
        w, h = s.width_cm * 1e4, s.height_cm * 1e4
        lo = (boundary.range_lo * 1e4) if boundary.range_lo is not None else None
        hi = (boundary.range_hi * 1e4) if boundary.range_hi is not None else None
        if boundary.edge in ("top", "bottom"):
            x0, x1 = (lo if lo is not None else 0.0), (hi if hi is not None else w)
            y = 0.0 if boundary.edge == "top" else h
            ax.plot([x0, x1], [y, y], color=colour, linewidth=3, solid_capstyle="butt")
            ax.text((x0 + x1) / 2, y, label, color=colour, fontsize=7, va="bottom")
        else:
            y0, y1 = (lo if lo is not None else 0.0), (hi if hi is not None else h)
            x = 0.0 if boundary.edge == "left" else w
            ax.plot([x, x], [y0, y1], color=colour, linewidth=3, solid_capstyle="butt")
            ax.text(x, (y0 + y1) / 2, label, color=colour, fontsize=7, ha="left")

    def _draw_mesh(self, ax):
        mesh_spec = self._mesh_model.to_mesh_spec(
            self._structure.width_cm if self._structure else 1.0,
            self._structure.height_cm if self._structure else 1.0)
        x = [v * 1e4 for v in mesh_spec.axes["x"]]
        y = [v * 1e4 for v in mesh_spec.axes["y"]]
        for xv in x:
            ax.plot([xv, xv], [y[0], y[-1]], color="#555555", linewidth=0.5)
        for yv in y:
            ax.plot([x[0], x[-1]], [yv, yv], color="#555555", linewidth=0.5)
        ax.set_xlim(x[0], x[-1]); ax.set_ylim(y[-1], y[0])
        ax.set_xlabel("x [um]"); ax.set_ylabel("y [um]")

    def _draw_doping_preview(self, ax):
        """Pre-solve doping heatmap straight from the structure's regions,
        via the same rasterize_doping() that to_device_spec() uses -- so
        this preview is exactly what a solve would use, not an approximation."""
        mesh_spec = self._mesh_model.to_mesh_spec(
            self._structure.width_cm, self._structure.height_cm)
        doping = rasterize_doping(self._structure, mesh_spec)
        x = np.asarray(mesh_spec.axes["x"], dtype=float) * 1e4
        y = np.asarray(mesh_spec.axes["y"], dtype=float) * 1e4
        mesh = ax.pcolormesh(x, y, self._maybe_log(doping), shading="nearest", cmap="RdBu_r")
        cbar = ax.figure.colorbar(mesh, ax=ax)
        label = "Net doping [cm^-3]"
        cbar.set_label(f"log10 |{label}|" if self._log else label)
        ax.set_xlabel("x [um]"); ax.set_ylabel("y [um]")
        ax.invert_yaxis()
        if self._xlim:
            ax.set_xlim(*self._xlim)
        if self._ylim:
            ax.set_ylim(self._ylim[1], self._ylim[0])

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
