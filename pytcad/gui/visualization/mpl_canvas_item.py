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
from ..services.result_store import extract_line_cut

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
        self._process_store = None
        self._sweep = None             # result_store.SweepResult (v0.4)
        self._sweep_channel = ""
        self._cv = None                # result_store.SweepResult (v0.6 C-V mode)
        self._transient = None         # result_store.TransientResult (M17 phase 3)
        self._contours = False         # v0.6 Phase 2a: contour overlay toggle
        self._cut_orientation = "horizontal"   # v0.6 Phase 2b: line-cut mode
        self._cut_position_cm = 0.0
        self._comparison_label = "all models off"   # v0.6 Phase 2d default
        self._mode = "doping"
        self._dark = True
        # last rendered state, for the hover readout
        self._ax = None
        self._fig = None
        self._series = []
        self._readout = ""
        self._readout_unit = ""

    # -- theme & hover readout ------------------------------------------
    @Slot(bool)
    def applyTheme(self, dark):
        """Mirror the QML design system's light/dark choice into the
        matplotlib rendering."""
        if self._dark != bool(dark):
            self._dark = bool(dark)
            self.update()

    @Property(str, notify=viewChanged)
    def readout(self):
        return self._readout

    @Slot()
    def clearReadout(self):
        self._readout = ""
        self.update()

    @Slot(float, float)
    def hoverAt(self, x_px, y_px):
        """Map widget pixels -> data coords through the live Axes
        transform and snap to the nearest plotted sample.  Purely
        derived from what was actually rendered -- never fake."""
        ax = self._ax
        if ax is None or not self._series or self._fig is None:
            return
        # Qt's pointer origin is TOP-left; matplotlib's display space is
        # BOTTOM-left. Convert before inverting the data transform.
        fig_h_px = self._fig.get_figheight() * self._fig.dpi
        inv = ax.transData.inverted()
        try:
            dx, dy = inv.transform_point(
                (float(x_px), fig_h_px - float(y_px)))
        except Exception:
            return
        best = None
        tiny = 1e-30
        for xs, ys, label in self._series:
            if xs is None or len(xs) == 0:
                continue
            xs_a = np.asarray(xs, dtype=float)
            # snap on what is DISPLAYED: a log axis plots log10(|y|),
            # so vertical proximity must be judged there -- while the
            # readout still reports the physical value
            ys_disp = np.log10(np.maximum(np.abs(ys), tiny)) \
                if self._log else np.asarray(ys, dtype=float)
            idx = int(np.argmin(np.abs(xs_a - dx)))
            span_x = (float(np.max(xs_a) - np.min(xs_a))) or 1.0
            span_y = (float(np.max(ys_disp) - np.min(ys_disp))) or 1.0
            score = abs(float(xs_a[idx]) - dx) / span_x + \
                    abs(float(ys_disp[idx]) - dy) / span_y
            if best is None or score < best[0]:
                best = (score, label, float(xs[idx]), float(ys[idx]))
        if best is None or best[0] > 0.08:
            if self._readout:
                self._readout = ""
                self.update()
            return
        _, label, xv, yv = best
        text = f"{label}: {yv:.3e} @ {xv:.2f} {self._readout_unit}".rstrip()
        if text != self._readout:
            self._readout = text
            self.update()

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

    @Slot(object, str)
    def setProcessSource(self, store, step_id):
        # Deliberately does NOT touch self._mode -- see setStructureSource()
        # above for why: ViewportPanel.setViewMode() always calls setMode()
        # immediately before this, and a previous version's setStructureSource
        # silently clobbering self._mode back to its own mode caused a real,
        # previously-shipped bug (Mesh viewport rendering the Structure
        # diagram, undetected because the old tests called setStructureSource
        # before setMode -- the reverse of the real QML order). Same trap,
        # same fix, applied here before it can happen again.
        self._process_store = store
        # step_id may legitimately be "" -- e.g. ViewportPanel switching to
        # "process" mode before any step has been clicked in ProcessPanel's
        # list -- in which case ProcessResultStore's own constructor default
        # (the flow's last step) should stand rather than raising KeyError("").
        if store is not None and step_id:
            store.select_step(step_id)
        self.fit()

    @Slot(str)
    def setMode(self, mode):
        self._mode = mode
        self.update()

    # -- sweep series (v0.4) ------------------------------------------
    @Slot(object)
    def setSweepSource(self, sweep):
        """Data source for "series" mode: a result_store.SweepResult.
        Deliberately does NOT touch self._mode -- ViewportPanel.setViewMode()
        calls setMode() itself, immediately before this (see the trap
        documented on setStructureSource above)."""
        self._sweep = sweep
        names = list(sweep.channels) if sweep is not None else []
        if self._sweep_channel not in names:
            self._sweep_channel = names[0] if names else ""
        self.fit()

    @Slot(str)
    def setSweepChannel(self, name):
        if self._sweep is None or name in self._sweep.channels:
            self._sweep_channel = name
            self.update()

    # -- model on/off comparison overlay (M9) --------------------------
    @Slot(object)
    def setComparisonSource(self, sweep):
        """The all-models-OFF run's SweepResult, overlaid dashed in
        "series" mode.  Does NOT touch self._mode (same contract as
        every other source setter)."""
        self._comparison_sweep = sweep
        self.update()

    @Slot(result=bool)
    def hasComparisonSource(self):
        return getattr(self, "_comparison_sweep", None) is not None

    @Slot(str)
    def setComparisonLabel(self, label):
        """v0.6 Phase 2d: the SAME overlay slot above is reused for the
        backend comparison (AppController.runBackendComparison) -- one
        dashed overlay at a time, whichever ran most recently, rather
        than a second rendering path. Defaults to "all models off" so
        the M9 model-comparison call sites (which never call this) are
        unaffected."""
        self._comparison_label = str(label)
        self.update()

    # -- batch family overlay ------------------------------------------
    @Slot("QVariant")
    def setFamilySource(self, curves):
        """List of {label, stepped_value, voltages, currents, converged}
        dicts from FamilySweepController -- drawn as a multi-curve
        family in "series" mode, one solid line per stepped value."""
        self._family_curves = curves or []
        self.update()

    @Slot(result=int)
    def familyCurveCount(self):
        return len(getattr(self, "_family_curves", []))

    @Slot(result=list)
    def availableSweepChannels(self):
        return list(self._sweep.channels) if self._sweep is not None else []

    # -- C-V sweep (v0.6 Phase 1a) ----------------------------------------
    @Slot(object)
    def setCvSource(self, sweep):
        """Data source for "cv" mode: a result_store.SweepResult from
        CVController.cvResultForQml (or None before the first C-V run).
        Does NOT touch self._mode, like every other source setter --
        ViewportPanel.setViewMode() drives the mode."""
        self._cv = sweep
        self.fit()

    def _draw_cv(self, ax):
        """Gate-voltage vs. small-signal capacitance -- a dedicated mode
        rather than reusing "series"/Curves: an I-V SweepResult and a C-V
        SweepResult share the same dataclass shape by construction (both
        go through the standard job -> subprocess -> schema-v2 pipeline),
        but "series" mode's axis labels and title are written in terms of
        a swept CONTACT's CURRENT ("gate bias [V]" / "device [A/cm^2]"-
        style wording) -- technically not wrong for C-V's data (contact=
        "gate", channel="device"), but not honestly labeled as
        capacitance either. This keeps C-V's own labels unambiguous."""
        sweep = self._cv
        if sweep is None or not sweep.channels:
            ax.text(0.5, 0.5, "No C-V sweep yet\n"
                    "(run one in the Voltage sweep panel's C-V section)",
                    ha="center", va="center")
            ax.set_axis_off()
            return
        Vg = np.asarray(sweep.voltages, dtype=float)
        channel = next(iter(sweep.channels))
        C = np.asarray(sweep.channels[channel], dtype=float)
        marker = "-o" if Vg.size <= 40 else "-"
        ax.plot(Vg, C, marker, lw=1.5, ms=3, color=self._series_color(0))
        self._remember_series(ax, [(Vg, C, "C")], unit=sweep.unit)
        n_bad = int((~np.asarray(sweep.converged, dtype=bool)).sum())
        note = f"  ({n_bad} point(s) did not converge)" if n_bad else ""
        ax.set_xlabel("Vg [V]")
        ax.set_ylabel(f"C [{sweep.unit}]")
        ax.set_title(f"C-V sweep{note}", fontsize=9)
        ax.grid(True, alpha=0.3)
        if self._xlim:
            ax.set_xlim(*self._xlim)

    # -- transient (time-domain) run (M17 phase 3) -----------------------
    @Slot(object)
    def setTransientSource(self, result):
        """Data source for "transient" mode: a
        result_store.TransientResult (or None). A dedicated mode rather
        than reusing "series"/"cv" -- same reasoning those two already
        give for staying separate from each other: a transient's x-axis
        is TIME, not a swept bias, and unlike "series"/"cv" it draws
        EVERY channel at once (both named contacts at 1D, every ohmic
        contact at 2D) rather than one selected channel plus an
        optional family/comparison overlay -- there's no single
        "the" device current in a transient state to pick by default.
        Does NOT touch self._mode, like every other source setter --
        ViewportPanel.setViewMode() drives the mode."""
        self._transient = result
        self.fit()

    def _draw_transient(self, ax):
        result = getattr(self, "_transient", None)
        if result is None or not result.channels:
            ax.text(0.5, 0.5, "No transient run yet\n"
                    "(arm and run one in the Transient panel)",
                    ha="center", va="center")
            ax.set_axis_off()
            return
        t = np.asarray(result.times, dtype=float)
        series = []
        for k, (name, vals) in enumerate(sorted(result.channels.items())):
            I = np.asarray(vals, dtype=float)
            marker = "-o" if t.size <= 40 else "-"
            ax.plot(t, I, marker, lw=1.3, ms=2.5,
                    color=self._series_color(k), label=name)
            series.append((t, I, name))
        self._remember_series(ax, series, unit=result.unit)
        ax.legend(fontsize=8, frameon=False)
        ax.set_xlabel("t [s]")
        ax.set_ylabel(f"current [{result.unit}]")
        ax.set_title(f"{result.contact} transient", fontsize=9)
        if self._xlim:
            ax.set_xlim(*self._xlim)

    # -- convergence history (v0.5.0 M4) ---------------------------------
    @Slot(object)
    def setConvergenceSource(self, record):
        """Data source for "convergence" mode: a solver_backend.RunRecord
        (or None).  Does NOT touch self._mode, like every other source
        setter -- ViewportPanel.setViewMode() drives the mode."""
        self._convergence_record = record
        self.fit()

    def _draw_convergence(self, ax):
        record = getattr(self, "_convergence_record", None)
        steps = list(record.trace) if record is not None and record.trace else []
        if not steps:
            ax.text(0.5, 0.5, "No convergence record\n"
                    "(solve a device with schema-v2 results)",
                    ha="center", va="center")
            ax.set_axis_off()
            return
        stage_colours = {"equilibrium": "#61bd6d", "bias": "#d9a441"}
        seen = {}
        offset = 0
        has_rejected = any(not step.converged for step in steps)
        for step in steps:
            residuals = [np.nan if v is None else float(v)
                         for v in next(iter(step.metrics.values()), [])]
            base = step.stage.split(":")[0]
            colour = stage_colours.get(base, "#4a90d9")
            legend_label = base if base not in seen else None
            seen[base] = True
            xs = list(range(offset, offset + len(residuals)))
            ax.semilogy(xs, residuals, marker=".", color=colour,
                        label=legend_label, linewidth=1.0, markersize=3)
            if not step.converged and residuals:
                last_x = xs[-1]
                last_y = residuals[-1]
                ax.plot(last_x, last_y, marker="x", color="#e74c3c",
                        markersize=8, markeredgewidth=2,
                        label="rejected" if has_rejected else None)
                has_rejected = False  # only label once
            offset += len(residuals)
        ax.set_xlabel("cumulative Newton iteration")
        ax.set_ylabel("residual (first metric)")
        ax.legend(fontsize=8, frameon=False)
        ax.grid(True, alpha=0.3)

    @Property(bool, notify=viewChanged)
    def logScale(self):
        return self._log

    @logScale.setter
    def logScale(self, value):
        self._log = bool(value)
        self.update()

    @Property(bool, notify=viewChanged)
    def contours(self):
        return self._contours

    @contours.setter
    def contours(self, value):
        self._contours = bool(value)
        self.update()

    def _maybe_contour(self, ax, x, y, values):
        """Overlay a handful of contour lines on the SAME (x, y, values)
        triple a 2D field mode's pcolormesh just rendered -- purely
        additive: `values` may already be log-transformed by the caller
        (self._maybe_log), matching what the colour map actually shows,
        rather than re-deriving a second transform here. A degenerate
        (constant) field draws no lines -- matplotlib's own behavior,
        not something this wraps or hides."""
        if not self._contours:
            return
        ax.contour(x, y, values, levels=8, colors="white",
                  linewidths=0.6, alpha=0.7)

    # -- line cut (v0.6 Phase 2b) -----------------------------------------
    @Slot(str)
    def setCutOrientation(self, orientation):
        self._cut_orientation = str(orientation)
        self.update()

    @Slot(float)
    def setCutPositionUm(self, value_um):
        self._cut_position_cm = float(value_um) * 1e-4
        self.update()

    def _draw_cut(self, ax):
        """A 1D slice through the CURRENT field mode's 2D data, extracted
        by extract_line_cut() (gui/services/result_store.py -- gated
        there directly, not just via this render) and plotted through
        the same ax.plot/_remember_series primitives "series"/Curves
        mode uses, rather than a second line-plot renderer. A dedicated
        mode (not literally SweepResult + _draw_series) because a
        spatial cut's axes -- a coordinate in um, not a swept contact's
        voltage -- would be dishonestly labeled through that path (the
        same reasoning "cv" mode used over reusing "series" verbatim)."""
        if self._store is None:
            ax.text(0.5, 0.5, "No project loaded", ha="center", va="center")
            ax.set_axis_off()
            return
        try:
            field = self._store.scalar_field(self._field)
            axes = self._store.mesh_axes()
            coord, values, actual_cm = extract_line_cut(
                axes, field, self._cut_orientation, self._cut_position_cm)
        except (KeyError, ValueError) as exc:
            ax.text(0.5, 0.5, f"Cannot cut this field:\n{exc}",
                    ha="center", va="center", wrap=True)
            ax.set_axis_off()
            return
        coord_um = np.asarray(coord, dtype=float) * 1e4
        values = np.asarray(values, dtype=float)
        y = self._maybe_log(values) if self._log else values
        ax.plot(coord_um, y, "-o" if coord_um.size <= 40 else "-",
                lw=1.5, ms=3, color=self._series_color(0))
        along_axis = "x" if self._cut_orientation == "horizontal" else "y"
        cut_axis = "y" if self._cut_orientation == "horizontal" else "x"
        ax.set_xlabel(f"{along_axis} [um]")
        ax.set_ylabel(f"{field.name} [{field.unit}]")
        ax.set_title(f"cut at {cut_axis}={actual_cm * 1e4:.4g} um "
                     f"(nearest node)", fontsize=9)
        ax.grid(True, alpha=0.3)
        self._remember_series(ax, [(coord_um, values, field.name)],
                              unit=field.unit)

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
        if self._mode == "process" and self._process_store is not None:
            state = self._process_store.state_for(self._process_store.selected_step_id)
            x_um = state["x"] * 1e4
            self._xlim = (float(x_um.min()), float(x_um.max()))
            self._ylim = None
            self._home = (self._xlim, self._ylim)
            self.viewChanged.emit()
            self.update()
            return
        if self._mode == "series" and self._sweep is not None:
            V = np.asarray(self._sweep.voltages, dtype=float)
            lo, hi = (float(V.min()), float(V.max())) if V.size else (0.0, 1.0)
            if hi == lo:
                hi = lo + 1.0
            self._xlim = (lo, hi)
            self._ylim = None
            self._home = (self._xlim, self._ylim)
            self.viewChanged.emit()
            self.update()
            return
        if self._mode == "cv" and self._cv is not None:
            Vg = np.asarray(self._cv.voltages, dtype=float)
            lo, hi = (float(Vg.min()), float(Vg.max())) if Vg.size else (0.0, 1.0)
            if hi == lo:
                hi = lo + 1.0
            self._xlim = (lo, hi)
            self._ylim = None
            self._home = (self._xlim, self._ylim)
            self.viewChanged.emit()
            self.update()
            return
        if self._mode == "transient" and self._transient is not None:
            t = np.asarray(self._transient.times, dtype=float)
            lo, hi = (float(t.min()), float(t.max())) if t.size else (0.0, 1.0)
            if hi == lo:
                hi = lo + 1.0
            self._xlim = (lo, hi)
            self._ylim = None
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
        self._style_axes(fig, ax)

        self._fig = fig
        # hover readout state: cleared per render, repopulated by the
        # draw paths that support it
        self._ax = None
        self._series = []
        if self._mode == "structure" and self._structure is not None:
            self._draw_structure(ax)
            fig.tight_layout()
            return fig
        if self._mode == "mesh" and self._mesh_model is not None:
            self._draw_mesh(ax)
            fig.tight_layout()
            return fig
        if self._mode == "process" and self._process_store is not None:
            self._draw_process(ax)
            fig.tight_layout()
            return fig
        if self._mode == "bands":
            self._draw_bands(ax)
            fig.tight_layout()
            return fig
        if self._mode == "recombination":
            self._draw_recombination(ax)
            fig.tight_layout()
            return fig
        if self._mode == "convergence":
            self._draw_convergence(ax)
            fig.tight_layout()
            return fig
        if self._mode == "cv":
            self._draw_cv(ax)
            fig.tight_layout()
            return fig
        if self._mode == "transient":
            self._draw_transient(ax)
            fig.tight_layout()
            return fig
        if self._mode == "cut":
            self._draw_cut(ax)
            fig.tight_layout()
            return fig
        if self._mode == "series":
            if self._sweep is not None:
                self._draw_series(ax)
            else:
                # Final review M-3: falling through to field rendering here
                # showed a stale doping map under "Curves" before any swept
                # run -- a placeholder is the honest empty state.
                ax.text(0.5, 0.5, "No sweep yet\n"
                        "(arm one in the Voltage sweep panel and Run)",
                        ha="center", va="center")
                ax.set_axis_off()
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
            y = self._maybe_log(values) if self._log else values
            ax.plot(x, y, color=self._series_color(0), lw=1.6)
            ax.set_xlabel("x [um]")
            ax.set_ylabel(f"{field.name} [{field.unit}]")
            self._remember_series(ax, [(x, values, field.name)],
                                  unit=field.unit)
            if self._xlim:
                ax.set_xlim(*self._xlim)
        else:
            y = np.asarray(axes.axes["y"], dtype=float) * 1e4
            if axes.dimensionality == 3:
                # v0.1 shows the central z-plane; a real 3D viewer is a
                # later version's job.
                values = values[values.shape[0] // 2]
            plotted = self._maybe_log(values)
            mesh = ax.pcolormesh(x, y, plotted, shading="nearest")
            self._maybe_contour(ax, x, y, plotted)
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

    def _style_axes(self, fig, ax):
        """Mirror the QML design system into matplotlib: neutral panel
        surface, dimmed grid/spines, readable tick sizes."""
        dark = self._dark
        fg = "#dde3e9" if dark else "#1a2129"
        dim = "#8d99a5" if dark else "#5a6572"
        panel = "#1f242b" if dark else "#ffffff"
        grid = "#343c46" if dark else "#d5dbe1"
        fig.patch.set_facecolor(panel)
        ax.set_facecolor(panel)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("bottom", "left"):
            ax.spines[side].set_color(dim)
        ax.tick_params(colors=dim, labelsize=9, which="both")
        for lbl in (ax.xaxis.label, ax.yaxis.label):
            lbl.set_color(fg)
            lbl.set_fontsize(10)
        ax.grid(True, color=grid, alpha=0.35, linewidth=0.6)
        ax.set_axisbelow(True)

    def _series_color(self, index):
        palette = ("#4a90d9", "#61bd6d", "#d9a441", "#e05c56",
                   "#9b59b6", "#1abc9c", "#e67e22")
        return palette[index % len(palette)]

    def _remember_series(self, ax, series, unit=""):
        self._ax = ax
        self._series = series
        self._readout_unit = unit

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
        plotted = self._maybe_log(doping)
        mesh = ax.pcolormesh(x, y, plotted, shading="nearest", cmap="RdBu_r")
        self._maybe_contour(ax, x, y, plotted)
        cbar = ax.figure.colorbar(mesh, ax=ax)
        label = "Net doping [cm^-3]"
        cbar.set_label(f"log10 |{label}|" if self._log else label)
        ax.set_xlabel("x [um]"); ax.set_ylabel("y [um]")
        ax.invert_yaxis()
        if self._xlim:
            ax.set_xlim(*self._xlim)
        if self._ylim:
            ax.set_ylim(self._ylim[1], self._ylim[0])

    def _draw_process(self, ax):
        """Log-scale doping vs. depth, mirroring examples/02_process_flow.py's
        own plotting convention: net doping plus each species profile
        present in the currently-selected checkpoint."""
        state = self._process_store.state_for(self._process_store.selected_step_id)
        x_um = state["x"] * 1e4
        net_doping = np.abs(state["net_doping"])
        ax.semilogy(x_um, net_doping, "-", label="|net doping|", lw=1.5)
        species_max = 0.0
        for species, C in state["species_profiles"].items():
            ax.semilogy(x_um, C, "--", label=species, lw=1.0)
            if len(C):
                species_max = max(species_max, float(np.max(C)))
        ax.set_xlabel("depth [um]")
        ax.set_ylabel("cm^-3")
        ax.legend(fontsize=8)
        # Task 15 (real-display verification) finding: a Gaussian implant
        # tail (pytcad's own moment-based profile) underflows toward zero
        # far from its peak -- e.g. ~1e-312, a subnormal float, not a real
        # concentration -- and matplotlib's default semilogy autoscale
        # happily stretched the y-axis down to include it, squashing the
        # actual physically meaningful 1e15-1e20 cm^-3 range into a sliver
        # at the top of the plot (confirmed with a real process run: the
        # rendered axis ran from ~1e33 to ~1e-311). examples/02_process_
        # flow.py -- the script this method's own docstring says it
        # mirrors -- avoids exactly this with a fixed set_ylim(1e15, 1e21);
        # this computes the equivalent floor/ceiling from the real data
        # (background doping level) instead of hardcoding one flow's numbers.
        floor = max(abs(float(state["background"])), 1.0) * 1e-2
        peak = max(float(np.max(net_doping)) if len(net_doping) else floor,
                   species_max, floor * 10)
        ax.set_ylim(floor, peak * 3)
        if self._xlim:
            ax.set_xlim(*self._xlim)

    # -- M9 observables (workbench/analysis) ---------------------------
    def _observable_fields(self):
        """(x_um, psi, n, p, doping, material, T) from the current store,
        or None when there is nothing to draw yet.  Material/T come from
        the run record -- what actually produced the numbers -- falling
        back to the silicon defaults."""
        store = self._store
        if store is None or not store.is_solved_result():
            return None
        names = store.available_scalars()
        for required in ("potential", "electron_density", "hole_density"):
            if required not in names:
                return None
        axes = store.mesh_axes()
        x = np.asarray(axes.axes["x"], dtype=float) * 1e4
        psi = np.asarray(store.scalar_field("potential").values, float)
        n = np.asarray(store.scalar_field("electron_density").values, float)
        p = np.asarray(store.scalar_field("hole_density").values, float)
        doping = None
        if "doping" in names:
            doping = np.asarray(store.scalar_field("doping").values, float)
        material, T = "SILICON", 300.0
        record = getattr(store, "run_record", None)
        if callable(record):
            try:
                rec = record()
                if rec is not None:
                    material = rec.material or material
                    T = rec.T or T
            except Exception:
                pass
        return x, psi, n, p, doping, material, T

    def _draw_bands(self, ax):
        """Band diagram (Ec/Ev/EFn/EFp) via workbench.analysis -- the
        same arrays any backend stores, the same conventions as the
        core's band_diagram().  1D results plot against depth; higher
        dimensionality gets an honest placeholder (a 2D+ band MAP is a
        later slice)."""
        data = self._observable_fields()
        if data is None:
            ax.text(0.5, 0.5, "No solved result yet\n"
                    "(solve a device to see its bands)",
                    ha="center", va="center")
            ax.set_axis_off()
            return
        x, psi, n, p, _doping, material, T = data
        axes = self._store.mesh_axes()
        if axes.dimensionality != 1:
            # 2D/3D: render the conduction-band-edge MAP (E_c = -psi-chi).
            # Element-wise physics, same conventions as the 1D curves.
            if axes.dimensionality != 2:
                ax.text(0.5, 0.5, "3D band maps: a later version",
                        ha="center", va="center")
                ax.set_axis_off()
                return
            from workbench.core.materials import LIBRARY
            mat = LIBRARY.get(material)
            y = np.asarray(axes.axes["y"], dtype=float) * 1e4
            Ec = -psi - mat.chi
            mesh = ax.pcolormesh(x, y, Ec, shading="nearest",
                                 cmap="viridis")
            self._maybe_contour(ax, x, y, Ec)
            fig_cbar = ax.figure.colorbar(mesh, ax=ax)
            fig_cbar.set_label("Ec [eV]")
            ax.set_xlabel("x [um]"); ax.set_ylabel("y [um]")
            ax.invert_yaxis()
            if self._xlim:
                ax.set_xlim(*self._xlim)
            if self._ylim:
                ax.set_ylim(self._ylim[1], self._ylim[0])
            return
        from workbench.analysis.observables import band_diagram
        Ec, Ev, EFn, EFp = band_diagram(psi, n, p, material, T)
        for arr, style, lbl in ((Ec, "-", "Ec"), (Ev, "-", "Ev"),
                                (EFn, "--", "EFn"), (EFp, "--", "EFp")):
            ax.plot(x, arr, style, label=lbl,
                    color=self._series_color(["Ec","Ev","EFn","EFp"].index(lbl)))
        ax.set_xlabel("depth [um]")
        ax.set_ylabel("energy [eV]")
        ax.legend(fontsize=8, frameon=False)
        self._remember_series(
            ax, [(x, Ec, "Ec"), (x, Ev, "Ev"),
                 (x, EFn, "EFn"), (x, EFp, "EFp")], unit="eV")
        if self._xlim:
            ax.set_xlim(*self._xlim)

    def _draw_recombination(self, ax):
        """Net recombination rate R(x) computed by workbench.analysis
        from the stored carrier densities (see recombination_rate()'s
        honesty note about Ntotal)."""
        data = self._observable_fields()
        if data is None or data[4] is None:
            ax.text(0.5, 0.5, "No solved result yet\n"
                    "(solve a device to see recombination)",
                    ha="center", va="center")
            ax.set_axis_off()
            return
        x, _psi, n, p, doping, material, T = data
        axes = self._store.mesh_axes()
        if axes.dimensionality != 1:
            if axes.dimensionality != 2:
                ax.text(0.5, 0.5, "3D recombination maps: a later version",
                        ha="center", va="center")
                ax.set_axis_off()
                return
            from workbench.analysis.observables import recombination_rate
            R = recombination_rate(n, p, doping, material, T)
            y = np.asarray(axes.axes["y"], dtype=float) * 1e4
            logR = np.log10(np.maximum(np.abs(R), 1e-30))
            mesh = ax.pcolormesh(x, y, logR, shading="nearest", cmap="inferno")
            self._maybe_contour(ax, x, y, logR)
            cbar = ax.figure.colorbar(mesh, ax=ax)
            cbar.set_label("log10 |R| [cm^-3 s^-1]")
            ax.set_xlabel("x [um]"); ax.set_ylabel("y [um]")
            ax.invert_yaxis()
            if self._xlim:
                ax.set_xlim(*self._xlim)
            if self._ylim:
                ax.set_ylim(self._ylim[1], self._ylim[0])
            return
        from workbench.analysis.observables import recombination_rate
        R = recombination_rate(n, p, doping, material, T)
        ax.semilogy(x, np.abs(R), lw=1.6, color=self._series_color(3))
        ax.set_xlabel("depth [um]")
        ax.set_ylabel("|R| [cm^-3 s^-1]")
        self._remember_series(ax, [(x, np.abs(R), "|R|")],
                              unit="cm^-3 s^-1")
        if self._xlim:
            ax.set_xlim(*self._xlim)

    def _draw_series(self, ax):
        """Sweep curve: current vs. swept-contact voltage.

        Non-converged points arrive from SweepResult as NaN and are
        plotted as-is -- matplotlib breaks the line at NaN, which is the
        honest rendering (a gap), never interpolation or substitution.
        Log mode plots |I| because a log axis can only show magnitude;
        zero/negative points simply do not appear on it rather than being
        clipped onto the axis edge with fabricated values."""
        sw = self._sweep
        if self._sweep_channel not in sw.channels:
            ax.text(0.5, 0.5, f"'{self._sweep_channel}' is not available\n"
                              "for this sweep", ha="center", va="center")
            ax.set_axis_off()
            return
        V = np.asarray(sw.voltages, dtype=float)
        I = np.asarray(sw.channels[self._sweep_channel], dtype=float)
        marker = "-o" if V.size <= 40 else "-"
        if self._log:
            ax.semilogy(V, np.abs(I), marker, lw=1.5, ms=3,
                        color=self._series_color(0))
            ylabel = f"|{self._sweep_channel}| [{sw.unit}]"
        else:
            ax.plot(V, I, marker, lw=1.5, ms=3, color=self._series_color(0))
            ylabel = f"{self._sweep_channel} [{sw.unit}]"
        self._remember_series(ax, [(V, I, self._sweep_channel)],
                              unit=sw.unit)
        n_bad = int((~np.asarray(sw.converged, dtype=bool)).sum())
        note = f"  ({n_bad} point(s) did not converge)" if n_bad else ""
        ax.set_xlabel(f"{sw.contact} bias [V]")
        ax.set_ylabel(ylabel)
        # batch family: one line per stepped value, real solver output
        family = getattr(self, "_family_curves", []) or []
        for k, curve in enumerate(family):
            fv = np.asarray(curve.get("voltages", []), dtype=float)
            fi = np.asarray(curve.get("currents", []), dtype=float)
            if fv.size == 0:
                continue
            fmarker = "-o" if fv.size <= 40 else "-"
            colour = self._series_color(1 + k)
            ax.plot(fv, fi, fmarker, lw=1.1, ms=2.5, color=colour,
                    alpha=0.9, label=curve.get("label", ""))
        if family:
            ax.legend(fontsize=7, frameon=False)
        # M9: overlay the comparison sweep, dashed, when present and
        # covering the same contact/channel -- "all models off" (M9) or
        # "other backend" (v0.6 Phase 2d), whichever set the source
        # most recently (self._comparison_label defaults to the M9
        # wording, so that call site's behavior is unchanged).
        comp = getattr(self, "_comparison_sweep", None)
        if comp is not None and self._sweep_channel in comp.channels:
            Ic = np.asarray(comp.channels[self._sweep_channel], dtype=float)
            style = "--" if len(V) > 40 else "--o"
            label = self._comparison_label
            if self._log:
                ax.semilogy(V, np.abs(Ic), style, lw=1.2, ms=3,
                            color="#9b59b6", label=label)
            else:
                ax.plot(V, Ic, style, lw=1.2, ms=3,
                        color="#9b59b6", label=label)
            ax.legend(fontsize=8)
        ax.set_title(f"{sw.contact} sweep{note}", fontsize=9)
        if self._xlim:
            ax.set_xlim(*self._xlim)

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
