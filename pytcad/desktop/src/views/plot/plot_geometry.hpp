// PlotView's geometry, Qt-free (NATIVE-DESKTOP-PLAN.md 16.2):
//
// - the one log rule (decision 8): a log axis shows |v| on a true log
//   scale; an exact 0, NaN or inf is not displayable and leaves a gap;
// - clipping a polyline to a rectangle (so a zoomed-in view never hands
//   the painter coordinates millions of pixels away);
// - per-pixel-column min/max decimation, drawing only: it never bridges
//   a gap (a gap already split the polyline) and hover never reads it;
// - the hover search (decision 9): the nearest finite sample by
//   normalised distance in displayed coordinates.
#pragma once

#include <cmath>
#include <cstddef>
#include <limits>
#include <vector>

namespace tcad::desktop::plot {

enum class Scale { Linear, Log };

// The displayed (axis) coordinate of a data value: v, or log10|v| on a log
// axis. NaN when the value is not displayable there.
inline double to_axis(double v, Scale s) {
    if (!std::isfinite(v)) return std::numeric_limits<double>::quiet_NaN();
    if (s == Scale::Linear) return v;
    if (v == 0.0) return std::numeric_limits<double>::quiet_NaN();
    return std::log10(std::abs(v));
}
inline double from_axis(double t, Scale s) { return s == Scale::Linear ? t : std::pow(10.0, t); }

struct Pt {
    double x, y;
};

// Clips the polyline (finite points) to [x0, x1] x [y0, y1] with
// Liang-Barsky per edge: the visible pieces, each a polyline of >= 2 points.
std::vector<std::vector<Pt>> clip_polyline(const std::vector<Pt>& pts, double x0, double y0, double x1, double y1);

// Whether any part of segment a->b lies in [x0, x1] x [y0, y1] (no allocation).
bool segment_hits_rect(const Pt& a, const Pt& b, double x0, double y0, double x1, double y1);

// Per-pixel-column decimation of one polyline (x in device pixels): each
// run of consecutive points in one column becomes its first, its min and
// max (in order of occurrence) and its last point. Exact at pixel scale:
// the drawn envelope of every column is unchanged.
std::vector<Pt> decimate_columns(const std::vector<Pt>& pts);

// A dense solid line, drawn cheaply and exactly at pixel scale. Qt's
// antialiased stroker is slow on tall zigzags (a dense column is a
// vertical scribble: 91 ms for 2,092 vertices, measured in P2-S2), but
// what such a column draws is simply its vertical extent. So, per device-
// pixel column of the polyline (x in device px):
// - a column whose points spread over more than `bar_px` vertically (and
//   has >= 3 of them) becomes a BAR covering its min..max and the edge
//   coming into it from the ADJACENT column's last point (an edge from
//   further away is a line of its own);
// - every other column keeps its first, min, max and last point (as
//   decimate_columns) in a polyline, stroked normally -- cheap, since the
//   column is short; a polyline stops at the point before a bar and
//   resumes from the bar's last point.
struct ColumnBar {
    double col;     // floor(x) of the column, device px
    double lo, hi;  // the y range it covers, device px
};
struct DenseDrawing {
    std::vector<std::vector<Pt>> lines;  // each >= 2 points
    std::vector<ColumnBar> bars;
};
DenseDrawing dense_columns(const std::vector<Pt>& pts, double bar_px = 2.0);

// One hoverable series for the search: its samples' displayed coordinates
// (NaN = not displayable, skipped), the current view's span on each of its
// axes, and the cursor's y in ITS y-axis's coordinates (a right-hand axis
// has its own).
struct HoverSeries {
    const std::vector<double>* tx = nullptr;
    const std::vector<double>* ty = nullptr;
    double span_x = 1.0, span_y = 1.0;
    double cy = 0.0;
};
struct HoverHit {
    std::size_t series = 0, index = 0;
    double score = 0.0;
};
// Every sample at the smallest score |dx|/span_x + |dy|/span_y (ties: all
// of them, in series order), or nothing when that score exceeds max_score.
std::vector<HoverHit> nearest_samples(const std::vector<HoverSeries>& series, double cx, double max_score = 0.08);

}  // namespace tcad::desktop::plot
