// The view modes of an open result, and the PlotModel of each curve mode
// (NATIVE-DESKTOP-PLAN.md 16.3, P2-S3), built from ResultModel's typed
// accessors (P2-S1). Labels, titles, colours, markers and empty-state
// texts are gui/visualization/mpl_canvas_item.py's (_draw_series,
// _draw_cv, _draw_transient, _draw_ac, _draw_convergence, the 1D branches
// of _build_figure / _draw_bands / _draw_recombination), with the plan's
// deliberate changes:
// - decision 8's one log rule: a log y-axis shows |y| and an exact zero
//   leaves a gap, so the 1D field's log view is a true log axis (QML drew
//   log10 on a linear axis, zeros at -30) and R is passed signed, not |R|;
// - decision 5 and 9: every curve hovers, convergence included, and the
//   readout names the raw, signed value.
#pragma once

#include "data/line_cut.hpp"
#include "data/result_model.hpp"
#include "plot_model.hpp"

#include <QString>

#include <string>
#include <vector>

namespace tcad::desktop::plot {

enum class ViewMode {
    FieldMap,       // FieldView: the 2D/3D map (not a curve)
    Cut,            // 2D: the map AND a line cut through it (P2-S4, decision 7)
    Field,          // a 1D field against x
    Curves,         // an I-V sweep, one channel (QML "series")
    CV,             // a capacitance sweep (moscap_runner)
    Transient,      // every channel against time
    AC,             // C(f) left, G(f) right, log frequency
    Convergence,    // the run record's trace
    Bands,          // 1D: Ec, Ev, EFn, EFp through the backend
    Recombination,  // 1D: R through the backend
};

QString modeName(ViewMode m);  // "Field map", "Curves", "C-V", ...
QString modeKey(ViewMode m);   // stable: "field_map", "field", "series", "cv", ...
bool isCurveMode(ViewMode m);  // the PlotView is shown: everything but FieldMap
bool showsMap(ViewMode m);     // the FieldView is shown: FieldMap and Cut
// Modes whose y-axis the user can switch to log (QML: the 1D field and
// the sweep). Convergence and recombination are always log; AC's log is
// on x.
bool hasLogToggle(ViewMode m);
// The backend's derived kind a mode needs ("bands" / "recombination"), "" if none.
QString derivedKind(ViewMode m);

// The modes `r` can show, in menu order. A curve block that fails to read
// (ResultSchemaError on access, as the store raises) is still offered:
// its mode then shows the error instead of a curve.
std::vector<ViewMode> availableModes(const ResultModel& r);
// Field map (2D/3D) or Field (1D); a capacitance sweep defaults to C-V.
ViewMode defaultMode(const ResultModel& r);

// The sweep's channel names, archive order ("" when none or unreadable).
std::vector<std::string> sweepChannels(const ResultModel& r);

// -- overlays (P2-S5, 16.2 / finding 3) ---------------------------------------------
// A sweep from ANOTHER result file drawn over the open one's, in Curves or
// C-V mode: one comparison (dashed, QML's "all models off" / "other
// backend" curve) and a family of any size (solid, one colour each). Each
// is drawn on its OWN voltages (finding 12: QML reused the primary's).
struct OverlayCurve {
    enum class Kind { Comparison, Family };
    Kind kind = Kind::Family;
    QString label;     // legend and readout; the file name by default, editable
    QString path;      // where it was read from (the sweep is decoded at add time)
    SweepSeries sweep;
};

// "" when `overlay` can be drawn over `primary` for `channel`; otherwise
// the first mismatch, named: the swept contact, the quantity (current /
// capacitance), the unit, or the channel.
QString overlayMismatch(const SweepSeries& primary, const SweepSeries& overlay, const std::string& channel);

// -- the models --------------------------------------------------------------------
// Each never throws: an unreadable block becomes the model's empty text.
PlotModel fieldModel(const ResultModel& r, const std::string& field, bool log);
// With overlays: the family (solid, colours 1, 2, ...) then the comparison
// (dashed), each on its own voltages, and a legend. An overlay without the
// channel is not drawn (MainWindow lists it as unusable).
PlotModel seriesModel(const ResultModel& r, const std::string& channel, bool log,
                      const std::vector<OverlayCurve>& overlays = {});
PlotModel cvModel(const ResultModel& r, bool log, const std::vector<OverlayCurve>& overlays = {});
PlotModel transientModel(const ResultModel& r, bool log);
PlotModel acModel(const ResultModel& r);
PlotModel convergenceModel(const ResultModel& r);
// The same drawing from trace steps (P3-S5: the Telemetry dock draws the
// live PYTCAD_PROGRESS newton records with it, so a finished run's live plot
// is its Convergence plot). No step with a metric: a message model saying
// `empty_text`.
PlotModel convergenceModel(const std::vector<TraceStep>& trace, const QString& empty_text);
// `derived` is the backend's map for the open result (nullptr: still computing).
PlotModel bandsModel(const ResultModel* derived);
PlotModel recombinationModel(const ResultModel* derived);
// What a mode shows when it cannot draw (a failed backend call, ...).
PlotModel messageModel(const QString& text);

// P2-S6: `m` unchanged when at least one sample of one series can be
// shown on its axes (finite, and non-zero on a log axis -- decision 8);
// otherwise a message keeping the title (e.g. a sweep where no point
// converged), rather than empty axes over an invented 0-1 range.
PlotModel nothingToPlot(PlotModel m);

// _draw_cut: a line cut through `field` of `source` (the map the FieldView
// shows: a stored field or a backend-derived map), at node `index` of the
// cut axis (y for Horizontal, x for Vertical; clamped to the axis).
// Decision 8's log rule. The title names the node actually used.
PlotModel cutModel(const ResultModel& source, const std::string& field, CutOrientation orientation,
                   std::size_t index, bool log);

}  // namespace tcad::desktop::plot
