// What a PlotView draws (NATIVE-DESKTOP-PLAN.md 16.2): a list of series
// and the axes they sit on. The curve modes (P2-S3) build one of these
// from a result; PlotView never reads a result itself.
#pragma once

#include "plot_geometry.hpp"

#include <QColor>
#include <QString>

#include <vector>

namespace tcad::desktop::plot {

enum class YAxis { Left, Right };
enum class LineStyle { Solid, Dashed, Dotted, DashDot, None };  // matplotlib's '-', '--', ':', '-.'
enum class Markers { Auto, Always, Never };  // Auto: markers when the series has <= 40 points (the QML rule)
enum class MarkerShape { Circle, Dot, Cross };

inline constexpr std::size_t kAutoMarkerMaxPoints = 40;

struct Series {
    QString label;             // legend and readout
    std::vector<double> x, y;  // the same length; NaN is a gap, never interpolated
    QColor colour;             // from theme::seriesColour / dataColour
    LineStyle line = LineStyle::Solid;
    Markers markers = Markers::Auto;
    MarkerShape shape = MarkerShape::Circle;
    double line_width = 1.5;   // logical pixels
    YAxis axis = YAxis::Left;
    QString unit;              // the y value's unit, for the readout
    bool in_legend = true;
    bool hoverable = true;
};

struct AxisSpec {
    QString label;
    Scale scale = Scale::Linear;
    QColor colour;  // tick labels and label; invalid = the theme's text colours
};

struct PlotModel {
    QString title;
    AxisSpec x, y, y2;
    bool has_y2 = false;       // a right-hand y-axis (AC's G)
    QString x_unit;            // for the readout
    std::vector<Series> series;
    bool legend = true;
    QString empty_text;        // drawn instead of axes when there is no series
};

}  // namespace tcad::desktop::plot
