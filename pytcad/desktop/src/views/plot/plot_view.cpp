#include "plot_view.hpp"

#include "axis_ticks.hpp"
#include "data/max_n_locator.hpp"
#include "theme/theme.hpp"

#include <QEvent>
#include <QFontInfo>
#include <QFontMetricsF>
#include <QMouseEvent>
#include <QPainter>
#include <QPainterPath>
#include <QWheelEvent>

#include <algorithm>
#include <cmath>
#include <limits>

namespace tcad::desktop::plot {
namespace {

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();
constexpr double kPad = 6.0;          // logical px around everything
constexpr double kMajorTick = 5.0;    // tick mark lengths, logical px (matplotlib 3.5 pt / 2 pt)
constexpr double kMinorTick = 2.5;
constexpr double kLabelGap = 3.0;     // tick mark to its label
constexpr double kMargin = 0.05;      // matplotlib's axes.xmargin / ymargin
constexpr double kSnap = 0.08;        // the QML hover's snap distance
constexpr double kDecimateFactor = 4.0;
constexpr double kZoomStep = 1.2;     // per wheel notch
constexpr qsizetype kStrokeChunk = 8;  // segments per stroked path (see the series paint)

// matplotlib's _interval_contains_close(rtol=1e-10), in axis coordinates.
bool in_view(double t, double lo, double hi) {
    const double tol = (hi - lo) * 1e-10;
    return t >= lo - tol && t <= hi + tol;
}

// matplotlib's dash patterns (lines.dashed_pattern etc.), in line widths.
void setDashes(QPen& pen, LineStyle style) {
    switch (style) {
        case LineStyle::Dashed: pen.setDashPattern({3.7, 1.6}); break;
        case LineStyle::Dotted: pen.setDashPattern({1.0, 1.65}); break;
        case LineStyle::DashDot: pen.setDashPattern({6.4, 1.6, 1.0, 1.6}); break;
        default: break;
    }
}

QString fromUtf8(const std::string& s) { return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size())); }

QString minusSigned(int e) { return e < 0 ? QString(QChar(0x2212)) + QString::number(-e) : QString::number(e); }

// A log label as plain text: "10^3", "2×10^−3" -- the part after '^' is
// drawn as a superscript.
QString logText(const LogLabel& l) {
    if (!l.shown) return {};
    if (l.decade) return QStringLiteral("10^") + minusSigned(l.exponent);
    char buf[64];
    std::snprintf(buf, sizeof buf, "%g", l.coeff);
    return QString::fromLatin1(buf) + QChar(0x00D7) + QStringLiteral("10^") + minusSigned(l.exponent);
}

QString formatX(double x) {
    const double a = std::abs(x);
    if (x == 0 || (a >= 1e-3 && a < 1e4)) return QString::asprintf("%.3f", x);
    return QString::asprintf("%.3e", x);
}

// matplotlib's _decade_less / _decade_greater of a positive value, as the
// log10 of the result: the log view of a single value.
std::pair<double, double> log_single(double t) {
    const double f = std::floor(t), c = std::ceil(t);
    return {f == t ? t - 1 : f, c == t ? t + 1 : c};
}

}  // namespace

PlotView::PlotView(QWidget* parent) : QWidget(parent) {
    setMouseTracking(true);
    setAttribute(Qt::WA_OpaquePaintEvent);
    setMinimumSize(160, 120);
    relayout();
}

void PlotView::setModel(PlotModel model) {
    model_ = std::move(model);
    cacheAxisCoordinates();
    setReadout({});
    fit();
}

Scale PlotView::scaleOf(Which w) const {
    switch (w) {
        case Which::X: return model_.x.scale;
        case Which::Y: return model_.y.scale;
        case Which::Y2: return model_.y2.scale;
    }
    return Scale::Linear;
}

void PlotView::cacheAxisCoordinates() {
    tx_.assign(model_.series.size(), {});
    ty_.assign(model_.series.size(), {});
    for (std::size_t s = 0; s < model_.series.size(); ++s) {
        const Series& ser = model_.series[s];
        const Scale ys = scaleOf(ser.axis == YAxis::Right ? Which::Y2 : Which::Y);
        const std::size_t n = std::min(ser.x.size(), ser.y.size());
        tx_[s].resize(n);
        ty_[s].resize(n);
        for (std::size_t i = 0; i < n; ++i) {
            const double tx = to_axis(ser.x[i], model_.x.scale), ty = to_axis(ser.y[i], ys);
            const bool ok = !std::isnan(tx) && !std::isnan(ty);  // a sample needs both
            tx_[s][i] = ok ? tx : kNaN;
            ty_[s][i] = ok ? ty : kNaN;
        }
    }
}

// -- view control ---------------------------------------------------------------------

void PlotView::fit() {
    for (Which w : {Which::X, Which::Y, Which::Y2}) {
        double lo = std::numeric_limits<double>::infinity(), hi = -lo;
        for (std::size_t s = 0; s < model_.series.size(); ++s) {
            const Series& ser = model_.series[s];
            if (w == Which::Y && ser.axis != YAxis::Left) continue;
            if (w == Which::Y2 && ser.axis != YAxis::Right) continue;
            const auto& t = w == Which::X ? tx_[s] : ty_[s];
            for (double v : t)
                if (!std::isnan(v)) {
                    lo = std::min(lo, v);
                    hi = std::max(hi, v);
                }
        }
        const Scale sc = scaleOf(w);
        if (!(lo <= hi)) {  // no data on this axis
            lo = 0.0;
            hi = 1.0;       // [0, 1], or [1, 10] on a log axis
        } else if (sc == Scale::Log) {
            if (lo == hi) std::tie(lo, hi) = log_single(lo);
        } else {
            std::tie(lo, hi) = mpl_nonsingular(lo, hi, 0.05, 1e-15);  // Locator.nonsingular
        }
        const double m = (hi - lo) * kMargin;  // in axis coordinates, as matplotlib's margins
        view(w) = {lo - m, hi + m};
    }
    home_ = views_;
    relayout();
    emit viewChanged();
}

void PlotView::resetView() {
    views_ = home_;
    relayout();
    emit viewChanged();
}

void PlotView::zoom(double factor) {
    if (!(factor > 0) || !std::isfinite(factor)) return;
    for (Which w : {Which::X, Which::Y, Which::Y2}) {
        AxisView& v = view(w);
        const double mid = 0.5 * (v.lo + v.hi), half = 0.5 * (v.hi - v.lo) * factor;
        // keep the span representable: never collapse or overflow
        if (!(half > std::abs(mid) * 1e-12 + 1e-300) || !(half < 1e300)) continue;
        v = {mid - half, mid + half};
    }
    relayout();
    emit viewChanged();
}

void PlotView::pan(double dx_frac, double dy_frac) {
    auto shift = [](AxisView& v, double f) {
        const double d = (v.hi - v.lo) * f;
        if (std::isfinite(v.lo + d) && std::isfinite(v.hi + d)) v = {v.lo + d, v.hi + d};
    };
    shift(view(Which::X), dx_frac);
    shift(view(Which::Y), dy_frac);
    shift(view(Which::Y2), dy_frac);
    relayout();
    emit viewChanged();
}

PlotView::Range PlotView::xView() const {
    const AxisView& v = view(Which::X);
    return {from_axis(v.lo, model_.x.scale), from_axis(v.hi, model_.x.scale)};
}

PlotView::Range PlotView::yView(YAxis axis) const {
    const Which w = axis == YAxis::Right ? Which::Y2 : Which::Y;
    const AxisView& v = view(w);
    return {from_axis(v.lo, scaleOf(w)), from_axis(v.hi, scaleOf(w))};
}

// -- geometry --------------------------------------------------------------------------

QRectF PlotView::plotRect() const { return plot_rect_; }

double PlotView::mapX(double t) const {
    const AxisView& v = view(Which::X);
    return plot_rect_.left() + (t - v.lo) / (v.hi - v.lo) * plot_rect_.width();
}

double PlotView::mapY(double t, Which w) const {
    const AxisView& v = view(w);
    return plot_rect_.bottom() - (t - v.lo) / (v.hi - v.lo) * plot_rect_.height();
}

QPointF PlotView::toPixel(double x, double y, YAxis axis) const {
    const Which w = axis == YAxis::Right ? Which::Y2 : Which::Y;
    const double tx = to_axis(x, model_.x.scale), ty = to_axis(y, scaleOf(w));
    if (std::isnan(tx) || std::isnan(ty)) return {kNaN, kNaN};
    return {mapX(tx), mapY(ty, w)};
}

std::vector<PlotView::Tick> PlotView::ticks(Which which) const { return axes_[static_cast<std::size_t>(which)].ticks; }
QString PlotView::offsetText(Which which) const { return axes_[static_cast<std::size_t>(which)].offset_text; }

namespace {

QFont tickFontOf(const QFont& base) {
    QFont f = base;
    f.setPointSizeF(base.pointSizeF() * 0.9);
    return f;
}

QFont supFontOf(const QFont& tick) {
    QFont f = tick;
    f.setPointSizeF(tick.pointSizeF() * 0.72);
    return f;
}

// The size of a tick label, with '^' starting a superscript.
QSizeF labelSize(const QString& text, const QFont& tick) {
    const QFontMetricsF fm(tick);
    const int caret = static_cast<int>(text.indexOf(QLatin1Char('^')));
    if (caret < 0) return {fm.horizontalAdvance(text), fm.height()};
    const QFontMetricsF sm(supFontOf(tick));
    const double w = fm.horizontalAdvance(text.left(caret)) + sm.horizontalAdvance(text.mid(caret + 1));
    return {w, fm.height() + fm.ascent() * 0.35};
}

bool overlaps(const QRectF& a, const QRectF& b, double gap) { return a.adjusted(-gap, -gap, gap, gap).intersects(b); }

}  // namespace

PlotView::AxisLayout PlotView::layoutAxis(Which w, double length_px) const {
    AxisLayout out;
    const AxisView& v = view(w);
    const Scale sc = scaleOf(w);
    const double dlo = from_axis(v.lo, sc), dhi = from_axis(v.hi, sc);
    const QFont tf = tickFontOf(font());
    const double font_px = std::max(1.0, QFontInfo(tf).pixelSize() > 0 ? double(QFontInfo(tf).pixelSize()) : tf.pointSizeF() * logicalDpiY() / 72.0);
    const bool is_x = w == Which::X;
    const double gap = is_x ? 4.0 : 2.0;
    // matplotlib's get_tick_space: the axis length over 3x (x) or 2x (y) the font size
    const int space = static_cast<int>(std::floor(length_px / (font_px * (is_x ? 3.0 : 2.0))));
    const int n_min = sc == Scale::Log ? 2 : 1;
    int n = std::clamp(space, n_min, 9);

    // Positions along the axis, for the overlap test (x: horizontal, y: vertical).
    auto place = [&](double t, const QString& text) -> QRectF {
        if (text.isEmpty()) return {};
        const QSizeF s = labelSize(text, tf);
        const double pos = is_x ? plot_rect_.left() + (t - v.lo) / (v.hi - v.lo) * plot_rect_.width()
                                : plot_rect_.bottom() - (t - v.lo) / (v.hi - v.lo) * plot_rect_.height();
        if (is_x) return {pos - s.width() / 2, plot_rect_.bottom() + kMajorTick + kLabelGap, s.width(), s.height()};
        if (w == Which::Y) return {plot_rect_.left() - kMajorTick - kLabelGap - s.width(), pos - s.height() / 2, s.width(), s.height()};
        return {plot_rect_.right() + kMajorTick + kLabelGap, pos - s.height() / 2, s.width(), s.height()};
    };
    auto any_overlap = [&](const std::vector<Tick>& ts) {
        for (std::size_t i = 0; i + 1 < ts.size(); ++i)
            for (std::size_t j = i + 1; j < ts.size(); ++j)
                if (!ts[i].label_rect.isEmpty() && !ts[j].label_rect.isEmpty() && overlaps(ts[i].label_rect, ts[j].label_rect, gap))
                    return true;
        return false;
    };

    for (;; --n) {
        out = {};
        if (sc == Scale::Linear) {
            const auto locs = linear_ticks(dlo, dhi, n);
            const auto labels = scalar_labels(locs, dlo, dhi);
            for (std::size_t i = 0; i < locs.size(); ++i) {
                if (!in_view(locs[i], v.lo, v.hi)) continue;
                const QString text = fromUtf8(labels.labels[i]);
                out.ticks.push_back({locs[i], text, place(locs[i], text), false});
            }
            out.offset_text = fromUtf8(labels.offset_text);
        } else {
            const auto locs = log_major_ticks(dlo, dhi, n);
            const auto labels = log_labels(locs, dlo, dhi);
            for (std::size_t i = 0; i < locs.size(); ++i) {
                const double t = std::log10(locs[i]);
                if (!in_view(t, v.lo, v.hi)) continue;
                const QString text = logText(labels[i]);
                out.ticks.push_back({locs[i], text, place(t, text), false});
            }
        }
        if (n <= n_min || !any_overlap(out.ticks)) break;
    }
    if (sc == Scale::Log) {
        // Minor ticks, minus any at a major's place (matplotlib's
        // remove_overlapping_locs, atol 1e-5 of the span); a minor label is
        // drawn only where it overlaps no label already placed.
        const auto locs = log_minor_ticks(dlo, dhi, n);
        const auto labels = log_labels(locs, dlo, dhi);
        const double tol = (v.hi - v.lo) * 1e-5;
        const std::size_t n_major = out.ticks.size();
        for (std::size_t i = 0; i < locs.size(); ++i) {
            if (!(locs[i] > 0)) continue;
            const double t = std::log10(locs[i]);
            if (!in_view(t, v.lo, v.hi)) continue;
            bool at_major = false;
            for (std::size_t k = 0; k < n_major; ++k) at_major |= std::abs(std::log10(out.ticks[k].value) - t) <= tol;
            if (at_major) continue;
            QString text = logText(labels[i]);
            QRectF r = place(t, text);
            for (const Tick& placed : out.ticks)
                if (!r.isEmpty() && !placed.label_rect.isEmpty() && overlaps(r, placed.label_rect, gap)) {
                    text.clear();
                    r = {};
                    break;
                }
            out.ticks.push_back({locs[i], text, r, true});
        }
    }
    return out;
}

void PlotView::relayout() {
    const double W = width(), H = height();
    const QFont tf = tickFontOf(font());
    const QFontMetricsF fm(tf), lm(font());
    const double title_h = model_.title.isEmpty() ? 0.0 : fm.height() + kPad;
    double left = kPad + fm.horizontalAdvance(QStringLiteral("-0.000")) + kMajorTick + kLabelGap;
    double right = kPad + (model_.has_y2 ? fm.horizontalAdvance(QStringLiteral("-0.000")) + kMajorTick + kLabelGap : 12.0);
    double top = kPad + title_h + fm.height();
    double bottom = kPad + kMajorTick + kLabelGap + fm.height() + (model_.x.label.isEmpty() ? 0.0 : lm.height() + kPad);
    if (!model_.y.label.isEmpty()) left += lm.height() + kPad;
    if (model_.has_y2 && !model_.y2.label.isEmpty()) right += lm.height() + kPad;

    for (int pass = 0; pass < 3; ++pass) {
        plot_rect_ = QRectF(left, top, std::max(10.0, W - left - right), std::max(10.0, H - top - bottom));
        axes_[0] = layoutAxis(Which::X, plot_rect_.width());
        axes_[1] = layoutAxis(Which::Y, plot_rect_.height());
        axes_[2] = model_.has_y2 ? layoutAxis(Which::Y2, plot_rect_.height()) : AxisLayout{};
        auto widest = [](const AxisLayout& a) {
            double m = 0;
            for (const Tick& t : a.ticks) m = std::max(m, t.label_rect.width());
            return m;
        };
        auto tallest = [](const AxisLayout& a) {
            double m = 0;
            for (const Tick& t : a.ticks) m = std::max(m, t.label_rect.height());
            return m;
        };
        double nl = kPad + widest(axes_[1]) + kMajorTick + kLabelGap + (model_.y.label.isEmpty() ? 0.0 : lm.height() + kPad);
        double nr = kPad + (model_.has_y2 ? widest(axes_[2]) + kMajorTick + kLabelGap + (model_.y2.label.isEmpty() ? 0.0 : lm.height() + kPad) : 0.0);
        // the last x label may stick out past the plot's right edge
        double overhang = 0;
        for (const Tick& t : axes_[0].ticks)
            if (!t.label_rect.isEmpty()) overhang = std::max(overhang, t.label_rect.right() - plot_rect_.right());
        nr = std::max(nr, kPad + std::max(overhang, 6.0));
        const bool top_offset = !axes_[1].offset_text.isEmpty() || !axes_[2].offset_text.isEmpty();
        double nt = kPad + title_h + (top_offset ? fm.height() + 2 : fm.height() / 2);
        double nb = kPad + kMajorTick + kLabelGap + std::max(tallest(axes_[0]), fm.height()) +
                    (model_.x.label.isEmpty() && axes_[0].offset_text.isEmpty() ? 0.0 : lm.height() + kPad);
        const bool stable = std::abs(nl - left) < 0.5 && std::abs(nr - right) < 0.5 && std::abs(nt - top) < 0.5 &&
                            std::abs(nb - bottom) < 0.5;
        left = nl;
        right = nr;
        top = nt;
        bottom = nb;
        if (stable && pass > 0) break;
    }
    plot_rect_ = QRectF(left, top, std::max(10.0, W - left - right), std::max(10.0, H - top - bottom));
    axes_[0] = layoutAxis(Which::X, plot_rect_.width());
    axes_[1] = layoutAxis(Which::Y, plot_rect_.height());
    axes_[2] = model_.has_y2 ? layoutAxis(Which::Y2, plot_rect_.height()) : AxisLayout{};

    title_rect_ = model_.title.isEmpty()
                      ? QRectF()
                      : QRectF(plot_rect_.center().x() - fm.horizontalAdvance(model_.title) / 2, kPad,
                               fm.horizontalAdvance(model_.title), fm.height());

    // Legend: matplotlib's loc="best" (the QML canvas's default) -- of its
    // candidate positions, in its order, the first with the least data
    // under it (vertices inside plus segments crossing), so it never hides
    // data it could avoid.
    legend_rect_ = {};
    if (model_.legend) {
        double w = 0, h = 0;
        for (const Series& s : model_.series)
            if (s.in_legend && !s.label.isEmpty()) {
                w = std::max(w, 24.0 + fm.horizontalAdvance(s.label));
                h += fm.height();
            }
        if (h > 0) legend_rect_ = bestLegendRect(QSizeF(w + 8, h + 6));
    }
}

QRectF PlotView::bestLegendRect(QSizeF size) const {
    const QRectF pr = plot_rect_.adjusted(kPad, kPad, -kPad, -kPad);
    const double l = pr.left(), r = pr.right() - size.width(), cx = pr.center().x() - size.width() / 2;
    const double t = pr.top(), b = pr.bottom() - size.height(), cy = pr.center().y() - size.height() / 2;
    // matplotlib's order: upper right, upper left, lower left, lower right,
    // right, center left, (center right = right), lower center, upper center, center
    const QPointF candidates[] = {{r, t}, {l, t}, {l, b}, {r, b}, {r, cy}, {l, cy}, {cx, b}, {cx, t}, {cx, cy}};
    // Every series' drawn points, thinned to <= ~2k per series: the count
    // only ranks nine candidates, and this runs on every pan step.
    std::vector<std::vector<Pt>> pts(model_.series.size());
    for (std::size_t s = 0; s < model_.series.size(); ++s) {
        const Which w = model_.series[s].axis == YAxis::Right ? Which::Y2 : Which::Y;
        const std::size_t n = tx_[s].size(), stride = std::max<std::size_t>(1, n / 2000);
        pts[s].reserve(n / stride + 1);
        for (std::size_t i = 0; i < n; i += stride)
            pts[s].push_back(std::isnan(tx_[s][i]) ? Pt{kNaN, kNaN} : Pt{mapX(tx_[s][i]), mapY(ty_[s][i], w)});
    }
    QRectF best;
    long long best_bad = -1;
    for (const QPointF& c : candidates) {
        const QRectF rect(c, size);
        const double x0 = rect.left(), y0 = rect.top(), x1 = rect.right(), y1 = rect.bottom();
        long long bad = 0;
        for (std::size_t s = 0; s < pts.size(); ++s) {
            const bool line = model_.series[s].line != LineStyle::None;
            const auto& ps = pts[s];
            for (std::size_t i = 0; i < ps.size(); ++i) {
                const Pt& p = ps[i];
                if (std::isnan(p.x)) continue;
                if (p.x >= x0 && p.x <= x1 && p.y >= y0 && p.y <= y1) ++bad;
                else if (line && i > 0 && !std::isnan(ps[i - 1].x) && segment_hits_rect(ps[i - 1], p, x0, y0, x1, y1))
                    ++bad;
            }
        }
        if (best_bad < 0 || bad < best_bad) {
            best_bad = bad;
            best = rect;
            if (bad == 0) break;
        }
    }
    return best;
}

// -- hover -------------------------------------------------------------------------------

void PlotView::setReadout(const QString& text) {
    if (text == readout_) return;
    readout_ = text;
    emit readoutChanged(readout_);
}

void PlotView::hoverAt(QPointF p) {
    if (model_.series.empty() || !plot_rect_.contains(p)) {
        setReadout({});
        return;
    }
    auto inv = [&](Which w, double px) {
        const AxisView& v = view(w);
        if (w == Which::X) return v.lo + (px - plot_rect_.left()) / plot_rect_.width() * (v.hi - v.lo);
        return v.lo + (plot_rect_.bottom() - px) / plot_rect_.height() * (v.hi - v.lo);
    };
    const double cx = inv(Which::X, p.x());
    std::vector<HoverSeries> hs(model_.series.size());
    for (std::size_t s = 0; s < model_.series.size(); ++s) {
        const Series& ser = model_.series[s];
        if (!ser.hoverable) continue;
        const Which w = ser.axis == YAxis::Right ? Which::Y2 : Which::Y;
        hs[s] = {&tx_[s], &ty_[s], view(Which::X).hi - view(Which::X).lo, view(w).hi - view(w).lo, inv(w, p.y())};
    }
    const auto hits = nearest_samples(hs, cx, kSnap);
    QStringList parts;
    for (const HoverHit& h : hits) {
        const Series& ser = model_.series[h.series];
        QString e = ser.label + QStringLiteral(": ") + QString::asprintf("%.3e", ser.y[h.index]);
        if (!ser.unit.isEmpty()) e += QLatin1Char(' ') + ser.unit;
        e += QStringLiteral(" @ ") + formatX(ser.x[h.index]);
        if (!model_.x_unit.isEmpty()) e += QLatin1Char(' ') + model_.x_unit;
        parts << e;
    }
    setReadout(parts.join(QStringLiteral("; ")));
}

// -- events ------------------------------------------------------------------------------

void PlotView::resizeEvent(QResizeEvent* event) {
    QWidget::resizeEvent(event);
    relayout();
}

void PlotView::changeEvent(QEvent* event) {
    QWidget::changeEvent(event);
    if (event->type() == QEvent::FontChange) {
        relayout();
        update();
    }
}

void PlotView::wheelEvent(QWheelEvent* event) {
    const double notches = event->angleDelta().y() / 120.0;
    if (notches != 0) {
        zoom(std::pow(kZoomStep, -notches));
        update();
    }
    event->accept();
}

void PlotView::mousePressEvent(QMouseEvent* event) {
    if (event->button() == Qt::LeftButton) {
        dragging_ = true;
        drag_last_ = event->position();
        setReadout({});
    }
}

void PlotView::mouseMoveEvent(QMouseEvent* event) {
    const QPointF p = event->position();
    if (dragging_) {
        const QPointF d = p - drag_last_;
        drag_last_ = p;
        // the content follows the cursor: the view moves the other way
        pan(-d.x() / plot_rect_.width(), d.y() / plot_rect_.height());
        update();
        return;
    }
    hoverAt(p);
}

void PlotView::mouseReleaseEvent(QMouseEvent* event) {
    if (event->button() == Qt::LeftButton) dragging_ = false;
}

void PlotView::mouseDoubleClickEvent(QMouseEvent*) {
    resetView();
    update();
}

void PlotView::leaveEvent(QEvent* event) {
    QWidget::leaveEvent(event);
    setReadout({});
}

// -- painting ----------------------------------------------------------------------------

void PlotView::paintEvent(QPaintEvent*) {
    QPainter p(this);
    const auto c = [&](theme::T t) { return theme::qcolor(t); };
    p.fillRect(rect(), c(theme::T::Base));
    const QFont tf = tickFontOf(font()), sf = supFontOf(tf);
    const QFontMetricsF fm(tf), lm(font());
    drawn_vertices_ = 0;

    if (model_.series.empty()) {
        p.setPen(c(theme::T::TextDim));
        p.setFont(font());
        p.drawText(rect(), Qt::AlignCenter, model_.empty_text);
        return;
    }
    p.setRenderHint(QPainter::Antialiasing, true);
    const QRectF pr = plot_rect_;
    const double dpr = devicePixelRatioF();
    // Axis lines (grid, spines, tick marks) sit on device-pixel centres, as
    // matplotlib snaps them: crisp, one device pixel wide, never smeared
    // across two half-lit pixels.
    const double hair = 1.0 / dpr;
    auto snap = [dpr](double v) { return (std::floor(v * dpr) + 0.5) / dpr; };

    // Grid at the major ticks of x and the left y.
    QColor grid = c(theme::T::Border);
    grid.setAlphaF(0.6f);  // the QML canvas draws its grid translucent (alpha 0.35 of a lighter grey)
    p.setPen(QPen(grid, hair));
    for (const Tick& t : axes_[0].ticks)
        if (!t.minor) {
            const double x = snap(mapX(to_axis(t.value, model_.x.scale)));
            p.drawLine(QPointF(x, pr.top()), QPointF(x, pr.bottom()));
        }
    for (const Tick& t : axes_[1].ticks)
        if (!t.minor) {
            const double y = snap(mapY(to_axis(t.value, model_.y.scale), Which::Y));
            p.drawLine(QPointF(pr.left(), y), QPointF(pr.right(), y));
        }

    // Series, clipped to the plot.
    p.save();
    p.setClipRect(pr);
    for (std::size_t s = 0; s < model_.series.size(); ++s) {
        const Series& ser = model_.series[s];
        const Which w = ser.axis == YAxis::Right ? Which::Y2 : Which::Y;
        const auto& tx = tx_[s];
        const auto& ty = ty_[s];
        if (ser.line != LineStyle::None) {
            QPen pen(ser.colour, ser.line_width);
            pen.setCapStyle(ser.line == LineStyle::Solid ? Qt::RoundCap : Qt::FlatCap);  // see the chunked stroke below
            pen.setJoinStyle(Qt::RoundJoin);
            setDashes(pen, ser.line);
            p.setPen(pen);
            p.setBrush(Qt::NoBrush);
            const double m = ser.line_width + 2;
            std::vector<Pt> seg;
            const double cx0 = (pr.left() - m) * dpr, cy0 = (pr.top() - m) * dpr;
            const double cx1 = (pr.right() + m) * dpr, cy1 = (pr.bottom() + m) * dpr;
            auto stroke = [&](const std::vector<Pt>& pts) {
                for (const auto& piece : clip_polyline(pts, cx0, cy0, cx1, cy1)) {
                    QPolygonF poly;
                    poly.reserve(static_cast<qsizetype>(piece.size()));
                    for (const Pt& q : piece) poly << QPointF(q.x / dpr, q.y / dpr);
                    if (ser.line == LineStyle::Solid) {
                        // In 8-segment chunks: Qt's antialiased rasterizer slows
                        // down sharply with the size of one stroked path (a noisy
                        // 1,000-point curve: 25 ms as one polyline, 5 ms chunked,
                        // measured in P2-S2). Round caps make each chunk joint a
                        // round join, as inside a chunk. A dashed line stays one
                        // polyline so its pattern runs on across the joints.
                        for (qsizetype a = 0; a + 1 < poly.size(); a += kStrokeChunk)
                            p.drawPolyline(poly.constData() + a, static_cast<int>(std::min<qsizetype>(kStrokeChunk + 1, poly.size() - a)));
                    } else {
                        p.drawPolyline(poly);
                    }
                    drawn_vertices_ += piece.size();
                }
            };
            auto flush = [&] {
                if (seg.size() >= 2) {
                    // Decimate the whole gap-free segment first (device-pixel
                    // columns), THEN clip: clipping first cuts a curve that
                    // leaves the view into many short pieces, each below the
                    // threshold, and nothing would be decimated.
                    const bool dense = static_cast<double>(seg.size()) > kDecimateFactor * pr.width() * dpr;
                    if (dense && ser.line == LineStyle::Solid) {
                        // tall columns as bars, the rest stroked (dense_columns)
                        const DenseDrawing d = dense_columns(seg);
                        for (const auto& l : d.lines) stroke(l);
                        const double half = ser.line_width / 2;
                        for (const ColumnBar& b : d.bars) {
                            if (b.col < cx0 - 1 || b.col > cx1) continue;
                            const double xc = (b.col + 0.5) / dpr;
                            p.fillRect(QRectF(xc - half, b.lo / dpr - half, ser.line_width, (b.hi - b.lo) / dpr + ser.line_width),
                                       ser.colour);
                            drawn_vertices_ += 2;
                        }
                    } else {
                        stroke(dense ? decimate_columns(seg) : seg);
                    }
                }
                seg.clear();
            };
            for (std::size_t i = 0; i < tx.size(); ++i) {
                if (std::isnan(tx[i])) {
                    flush();  // a gap: never bridged
                    continue;
                }
                seg.push_back({mapX(tx[i]) * dpr, mapY(ty[i], w) * dpr});
            }
            flush();
        }
        const bool markers = ser.markers == Markers::Always ||
                             (ser.markers == Markers::Auto && ser.x.size() <= kAutoMarkerMaxPoints);
        if (markers) {
            for (std::size_t i = 0; i < tx.size(); ++i) {
                if (std::isnan(tx[i])) continue;
                const QPointF q(mapX(tx[i]), mapY(ty[i], w));
                if (!pr.adjusted(-8, -8, 8, 8).contains(q)) continue;
                switch (ser.shape) {
                    case MarkerShape::Circle:
                        p.setPen(Qt::NoPen);
                        p.setBrush(ser.colour);
                        p.drawEllipse(q, 2.1, 2.1);  // ms=3 pt at the QML figure's 100 dpi
                        break;
                    case MarkerShape::Dot:
                        p.setPen(Qt::NoPen);
                        p.setBrush(ser.colour);
                        p.drawEllipse(q, 1.1, 1.1);
                        break;
                    case MarkerShape::Cross: {
                        p.setPen(QPen(ser.colour, 2.0));
                        const double r = 5.0;
                        p.drawLine(q + QPointF(-r, -r), q + QPointF(r, r));
                        p.drawLine(q + QPointF(-r, r), q + QPointF(r, -r));
                        break;
                    }
                }
            }
        }
    }
    p.restore();

    // Spines: left and bottom (the QML style), right when there is a y2.
    const QColor dim = c(theme::T::TextDim);
    const double sl = snap(pr.left()), sb = snap(pr.bottom()), sr = snap(pr.right());
    p.setPen(QPen(dim, hair));
    p.drawLine(QPointF(sl, sb), QPointF(sl, pr.top()));
    p.drawLine(QPointF(sl, sb), QPointF(pr.right(), sb));
    if (model_.has_y2) {
        p.setPen(QPen(model_.y2.colour.isValid() ? model_.y2.colour : dim, hair));
        p.drawLine(QPointF(sr, sb), QPointF(sr, pr.top()));
    }

    // Tick marks and labels.
    auto drawLabel = [&](const QRectF& r, const QString& text, const QColor& col) {
        p.setPen(col);
        const int caret = static_cast<int>(text.indexOf(QLatin1Char('^')));
        if (caret < 0) {
            p.setFont(tf);
            p.drawText(r, Qt::AlignCenter, text);
            return;
        }
        const QString base = text.left(caret), sup = text.mid(caret + 1);
        const double baseline = r.bottom() - fm.descent();
        p.setFont(tf);
        p.drawText(QPointF(r.left(), baseline), base);
        p.setFont(sf);
        p.drawText(QPointF(r.left() + fm.horizontalAdvance(base), baseline - fm.ascent() * 0.45), sup);
    };
    for (Which w : {Which::X, Which::Y, Which::Y2}) {
        if (!hasAxis(w)) continue;
        const AxisSpec& spec = w == Which::X ? model_.x : w == Which::Y ? model_.y : model_.y2;
        const QColor col = spec.colour.isValid() ? spec.colour : dim;
        const auto& al = axes_[static_cast<std::size_t>(w)];
        for (const Tick& t : al.ticks) {
            const double len = t.minor ? kMinorTick : kMajorTick;
            p.setPen(QPen(col, hair));
            const double ta = to_axis(t.value, scaleOf(w));
            if (w == Which::X) {
                const double x = snap(mapX(ta));
                p.drawLine(QPointF(x, sb), QPointF(x, sb + len));
            } else {
                const double y = snap(mapY(ta, w));
                const double x0 = w == Which::Y ? sl : sr;
                p.drawLine(QPointF(x0, y), QPointF(w == Which::Y ? x0 - len : x0 + len, y));
            }
            if (!t.text.isEmpty()) drawLabel(t.label_rect, t.text, col);
        }
        // offset / scientific-notation text (matplotlib's positions)
        if (!al.offset_text.isEmpty()) {
            p.setFont(tf);
            p.setPen(col);
            const double ow = fm.horizontalAdvance(al.offset_text);
            if (w == Which::X) {
                double below = pr.bottom() + kMajorTick + kLabelGap;
                for (const Tick& t : al.ticks) below = std::max(below, t.label_rect.bottom());
                p.drawText(QPointF(pr.right() - ow, below + fm.ascent()), al.offset_text);
            } else if (w == Which::Y) {
                p.drawText(QPointF(pr.left(), pr.top() - fm.descent() - 2), al.offset_text);
            } else {
                p.drawText(QPointF(pr.right() - ow, pr.top() - fm.descent() - 2), al.offset_text);
            }
        }
    }

    // Axis labels and the title.
    const QColor text = c(theme::T::Text);
    p.setFont(font());
    if (!model_.x.label.isEmpty()) {
        p.setPen(model_.x.colour.isValid() ? model_.x.colour : text);
        p.drawText(QRectF(pr.left(), height() - kPad - lm.height(), pr.width(), lm.height()), Qt::AlignCenter, model_.x.label);
    }
    auto drawVertical = [&](const QString& s, double x_centre, const QColor& col) {
        p.save();
        p.setPen(col);
        p.translate(x_centre, pr.center().y());
        p.rotate(-90);
        p.drawText(QRectF(-pr.height() / 2, -lm.height() / 2, pr.height(), lm.height()), Qt::AlignCenter, s);
        p.restore();
    };
    if (!model_.y.label.isEmpty()) drawVertical(model_.y.label, kPad + lm.height() / 2, model_.y.colour.isValid() ? model_.y.colour : text);
    if (model_.has_y2 && !model_.y2.label.isEmpty())
        drawVertical(model_.y2.label, width() - kPad - lm.height() / 2, model_.y2.colour.isValid() ? model_.y2.colour : text);
    if (!model_.title.isEmpty()) {
        p.setFont(tf);
        p.setPen(text);
        p.drawText(title_rect_, Qt::AlignCenter, model_.title);
    }

    // Legend.
    if (!legend_rect_.isEmpty()) {
        QColor bg = c(theme::T::Base);
        bg.setAlpha(210);
        p.setPen(Qt::NoPen);
        p.setBrush(bg);
        p.drawRect(legend_rect_);
        double y = legend_rect_.top() + 3;
        p.setFont(tf);
        for (const Series& s : model_.series) {
            if (!s.in_legend || s.label.isEmpty()) continue;
            const double mid = y + fm.height() / 2;
            if (s.line != LineStyle::None) {
                QPen pen(s.colour, s.line_width);
                setDashes(pen, s.line);
                p.setPen(pen);
                p.drawLine(QPointF(legend_rect_.left() + 4, mid), QPointF(legend_rect_.left() + 20, mid));
            }
            if (s.markers == Markers::Always || s.shape == MarkerShape::Cross ||
                (s.markers == Markers::Auto && s.x.size() <= kAutoMarkerMaxPoints)) {
                p.setPen(s.shape == MarkerShape::Cross ? QPen(s.colour, 2.0) : QPen(Qt::NoPen));
                p.setBrush(s.colour);
                const QPointF q(legend_rect_.left() + 12, mid);
                if (s.shape == MarkerShape::Cross) {
                    p.drawLine(q + QPointF(-3.5, -3.5), q + QPointF(3.5, 3.5));
                    p.drawLine(q + QPointF(-3.5, 3.5), q + QPointF(3.5, -3.5));
                } else {
                    p.drawEllipse(q, 2.1, 2.1);
                }
            }
            p.setPen(text);
            p.drawText(QPointF(legend_rect_.left() + 24, y + fm.ascent()), s.label);
            y += fm.height();
        }
    }
}

}  // namespace tcad::desktop::plot
