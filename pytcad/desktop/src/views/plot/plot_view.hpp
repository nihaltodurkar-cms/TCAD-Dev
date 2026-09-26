// PlotView: the native app's curve view (NATIVE-DESKTOP-PLAN.md 5.2 and
// 16.2). A QWidget painted with QPainter at device pixels (HiDPI), with
// theme tokens only.
//
// - Axes: linear or log x and y, and an optional right-hand y-axis.
//   Ticks and labels are matplotlib's (axis_ticks.hpp, contract-tested);
//   the tick COUNT is this view's own rule: matplotlib's heuristic (the
//   axis length over 3x the font size for x, 2x for y) in logical pixels,
//   lowered until no two major labels overlap; minor log labels that
//   would overlap a placed label are skipped.
// - Series: NaN is a gap; a log axis shows |v| and an exact 0 leaves a
//   gap (decision 8); markers when a series has <= 40 points; per-pixel-
//   column min/max decimation above 4x the plot width in device pixels
//   (drawing only), a dense solid line's tall columns filled as bars
//   (plot_geometry.hpp, dense_columns: Qt's wide-pen stroker is too slow
//   on them).
// - View control in each axis's own coordinates (decision 8's log10|v|
//   on a log axis): fit per model with matplotlib's 5% margins, zoom about
//   the centre (wheel), pan (drag), reset. A log axis can never reach a
//   non-positive limit.
// - Hover (decision 9): the nearest finite sample of any hoverable series
//   by normalised distance in displayed coordinates, normalised by the
//   CURRENT view; nothing past 0.08. Readout (decision 3):
//   "label: 1.234e-05 A/cm^2 @ 0.500 V"; tied series all listed.
// - Legend: matplotlib's loc="best" candidates and order, placed where the
//   least data is under it. Axis lines snap to device-pixel centres.
#pragma once

#include "plot_model.hpp"
#include "theme/tokens.hpp"

#include <QPointF>
#include <QRectF>
#include <QString>
#include <QWidget>

#include <array>
#include <vector>

namespace tcad::desktop::plot {

class PlotView : public QWidget {
    Q_OBJECT

public:
    explicit PlotView(QWidget* parent = nullptr);

    // Replaces what is drawn and fits the view to it.
    void setModel(PlotModel model);
    const PlotModel& model() const { return model_; }

    // -- view control, all in each axis's own coordinates ------------------------
    void fit();
    void resetView();                         // back to the last fit
    void zoom(double factor);                 // < 1 zooms in, about the centre
    void pan(double dx_frac, double dy_frac); // by fractions of the current span (+x right, +y up)

    struct Range {
        double lo, hi;  // in DATA units (a log axis: both > 0)
    };
    Range xView() const;
    Range yView(YAxis axis = YAxis::Left) const;

    // What mouse movement does; exposed for tests. Empty text: nothing snapped.
    void hoverAt(QPointF logical_pos);
    QString readout() const { return readout_; }

    // -- geometry, in logical pixels; for tests and the bench -------------------
    QRectF plotRect() const;
    // Where a data point is drawn; (NaN, NaN) when it is not displayable.
    QPointF toPixel(double x, double y, YAxis axis = YAxis::Left) const;
    struct Tick {
        double value;       // data units
        QString text;       // "" = not labelled
        QRectF label_rect;  // logical px; empty when not labelled
        bool minor;
    };
    enum class Which { X, Y, Y2 };
    std::vector<Tick> ticks(Which which) const;
    QString offsetText(Which which) const;
    QRectF titleRect() const { return title_rect_; }
    QRectF legendRect() const { return legend_rect_; }
    std::size_t lastDrawnVertices() const { return drawn_vertices_; }  // after decimation

signals:
    void readoutChanged(const QString& text);
    void viewChanged();

protected:
    void paintEvent(QPaintEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;
    void wheelEvent(QWheelEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void mouseDoubleClickEvent(QMouseEvent* event) override;  // reset
    void leaveEvent(QEvent* event) override;
    void changeEvent(QEvent* event) override;

private:
    struct AxisView {
        double lo = 0.0, hi = 1.0;  // axis coordinates (log10 on a log axis)
    };
    struct AxisLayout {
        std::vector<Tick> ticks;
        QString offset_text;
    };

    Scale scaleOf(Which w) const;
    AxisView& view(Which w) { return views_[static_cast<std::size_t>(w)]; }
    const AxisView& view(Which w) const { return views_[static_cast<std::size_t>(w)]; }
    bool hasAxis(Which w) const { return w != Which::Y2 || model_.has_y2; }
    void cacheAxisCoordinates();
    void relayout();
    AxisLayout layoutAxis(Which w, double length_px) const;
    QRectF bestLegendRect(QSizeF size) const;
    void setReadout(const QString& text);
    double mapX(double t) const;             // axis coordinate -> logical px
    double mapY(double t, Which w) const;

    PlotModel model_;
    std::array<AxisView, 3> views_{};
    std::array<AxisView, 3> home_{};
    // Displayed coordinates of every sample (NaN = not displayable), per series.
    std::vector<std::vector<double>> tx_, ty_;
    std::array<AxisLayout, 3> axes_{};
    QRectF plot_rect_, title_rect_, legend_rect_;
    QString readout_;
    bool dragging_ = false;
    QPointF drag_last_;
    std::size_t drawn_vertices_ = 0;
};

}  // namespace tcad::desktop::plot
