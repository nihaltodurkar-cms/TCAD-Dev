// PlotView gates (NATIVE-DESKTOP-PLAN.md 16.4, P2-S2): the REAL widget,
// rendered with grab() at the process's display scale (the Python runner,
// gui/tests/test_desktop_plot.py, runs this at QT_SCALE_FACTOR 1, 1.5
// and 2), probed pixel by pixel -- no golden images (section 15.5).
//
// With TCAD_PLOT_BENCH=<out.json> the bench runs too (a real, shown
// window): pan/zoom frames at 1,000 and 100,000 points and hover lookups.
#include "theme/theme.hpp"
#include "views/plot/axis_ticks.hpp"
#include "views/plot/plot_geometry.hpp"
#include "views/plot/plot_view.hpp"

#include <QApplication>
#include <QElapsedTimer>
#include <QFile>
#include <QImage>
#include <QRandomGenerator>
#include <QtTest/QtTest>

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <memory>
#include <numeric>

using namespace tcad::desktop;
using namespace tcad::desktop::plot;
using Which = PlotView::Which;

namespace {

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

QImage render(PlotView& v) { return v.grab().toImage().convertToFormat(QImage::Format_ARGB32); }

// The image pixel under a logical point.
QPoint dev(const QImage& img, QPointF p) {
    const double dpr = img.devicePixelRatio();
    return {std::clamp(static_cast<int>(std::floor(p.x() * dpr)), 0, img.width() - 1),
            std::clamp(static_cast<int>(std::floor(p.y() * dpr)), 0, img.height() - 1)};
}

int dist(QColor a, QColor b) { return std::abs(a.red() - b.red()) + std::abs(a.green() - b.green()) + std::abs(a.blue() - b.blue()); }

// Some pixel within `r` device pixels of the logical point has colour `c`.
bool colourNear(const QImage& img, QPointF p, QColor c, int r = 1, int tol = 90) {
    const QPoint q = dev(img, p);
    for (int dy = -r; dy <= r; ++dy)
        for (int dx = -r; dx <= r; ++dx) {
            const int x = q.x() + dx, y = q.y() + dy;
            if (x < 0 || y < 0 || x >= img.width() || y >= img.height()) continue;
            if (dist(img.pixelColor(x, y), c) <= tol) return true;
        }
    return false;
}

Series line(QString label, std::vector<double> x, std::vector<double> y, std::size_t colour) {
    Series s;
    s.label = std::move(label);
    s.x = std::move(x);
    s.y = std::move(y);
    s.colour = theme::seriesColour(colour);
    s.unit = QStringLiteral("A/cm^2");
    return s;
}

std::vector<double> linspace(double a, double b, std::size_t n) {
    std::vector<double> v(n);
    for (std::size_t i = 0; i < n; ++i) v[i] = n == 1 ? a : a + (b - a) * static_cast<double>(i) / static_cast<double>(n - 1);
    return v;
}

PlotModel model(std::vector<Series> s, Scale xs = Scale::Linear, Scale ys = Scale::Linear) {
    PlotModel m;
    m.title = QStringLiteral("probe plot");
    m.x = {QStringLiteral("bias [V]"), xs, {}};
    m.y = {QStringLiteral("current [A/cm^2]"), ys, {}};
    m.x_unit = QStringLiteral("V");
    m.series = std::move(s);
    return m;
}

std::unique_ptr<PlotView> view(PlotModel m, int w = 600, int h = 360) {
    auto v = std::make_unique<PlotView>();
    v->resize(w, h);
    v->setModel(std::move(m));
    return v;
}

QString sci(double v) { return QString::asprintf("%.3e", v); }

}  // namespace

class TestPlot : public QObject {
    Q_OBJECT

private slots:
    // -- geometry, Qt-free ------------------------------------------------------------

    void clipKeepsTheInsideAndSplitsAtExits() {
        const std::vector<Pt> pts{{-10, 5}, {5, 5}, {15, 5}, {15, 20}, {5, 20}, {5, 8}};
        const auto pieces = clip_polyline(pts, 0, 0, 10, 10);
        QCOMPARE(pieces.size(), std::size_t{2});
        QCOMPARE(pieces[0].front().x, 0.0);  // entered at the left edge
        QCOMPARE(pieces[0].back().x, 10.0);  // left through the right edge
        QCOMPARE(pieces[1].front().y, 10.0); // re-entered from the bottom edge (y = 10)
        QCOMPARE(pieces[1].back().y, 8.0);
    }

    void decimationKeepsEachColumnsEnvelopeInOrder() {
        std::vector<Pt> pts;
        for (int i = 0; i < 1000; ++i) pts.push_back({i / 100.0, std::sin(i * 0.37) * 10});
        const auto d = decimate_columns(pts);
        QVERIFY(d.size() <= 40);
        for (int col = 0; col < 10; ++col) {
            double lo = 1e9, hi = -1e9, dlo = 1e9, dhi = -1e9;
            for (const Pt& p : pts)
                if (std::floor(p.x) == col) lo = std::min(lo, p.y), hi = std::max(hi, p.y);
            for (const Pt& p : d)
                if (std::floor(p.x) == col) dlo = std::min(dlo, p.y), dhi = std::max(dhi, p.y);
            QCOMPARE(dlo, lo);
            QCOMPARE(dhi, hi);
        }
        for (std::size_t i = 1; i < d.size(); ++i) QVERIFY(d[i].x >= d[i - 1].x);  // order kept
    }

    void denseColumnsCoverEveryPointAndEveryEdge() {
        // noisy stretches (bars), smooth stretches (strokes) and the joins between them
        std::vector<Pt> pts;
        for (int i = 0; i < 20000; ++i) {
            const double x = i * 0.02;  // 50 points per column
            const bool noisy = (i / 3000) % 2 == 0;
            pts.push_back({x, 100 + 40 * std::sin(x * 0.05) + (noisy ? 15 * std::sin(i * 1.7) : 0.0)});
        }
        const DenseDrawing d = dense_columns(pts);
        QVERIFY(!d.bars.empty() && !d.lines.empty());
        auto seg_dist = [](const Pt& p, const Pt& a, const Pt& b) {
            const double dx = b.x - a.x, dy = b.y - a.y, l2 = dx * dx + dy * dy;
            const double t = l2 > 0 ? std::clamp(((p.x - a.x) * dx + (p.y - a.y) * dy) / l2, 0.0, 1.0) : 0.0;
            return std::hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
        };
        auto covered = [&](const Pt& p) {
            for (const ColumnBar& b : d.bars)
                if (std::floor(p.x) == b.col && p.y >= b.lo - 1e-9 && p.y <= b.hi + 1e-9) return true;
            for (const auto& l : d.lines)
                for (std::size_t k = 0; k + 1 < l.size(); ++k)
                    if (std::abs(l[k].x - p.x) < 2 && seg_dist(p, l[k], l[k + 1]) <= 1.0) return true;
            return false;
        };
        for (std::size_t i = 0; i < pts.size(); i += 7) QVERIFY2(covered(pts[i]), qPrintable(QString::number(i)));
        for (std::size_t i = 0; i + 1 < pts.size(); ++i)  // every edge between columns: its end in the new column
            if (std::floor(pts[i].x) != std::floor(pts[i + 1].x)) {
                const Pt mid{std::floor(pts[i + 1].x) + 1e-9, pts[i].y + (pts[i + 1].y - pts[i].y) * 0.5};
                QVERIFY2(covered(mid) || covered(pts[i + 1]), qPrintable(QString::number(i)));
            }
        std::size_t drawn = d.bars.size() * 2;
        for (const auto& l : d.lines) drawn += l.size();
        QVERIFY(drawn < pts.size() / 5);

        // A dense cluster, a jump across 100 empty columns, another dense
        // cluster: the long edge between them is drawn (found by mutation in
        // P2-S2: it was lost when the column it lands in is a bar).
        std::vector<Pt> jump;
        for (int i = 0; i < 3000; ++i) jump.push_back({i * 0.02, 50 + 20 * std::sin(i * 1.3)});
        for (int i = 0; i < 3000; ++i) jump.push_back({160 + i * 0.02, 300 + 20 * std::sin(i * 1.3)});
        const DenseDrawing dj = dense_columns(jump);
        const Pt a = jump[2999], b = jump[3000];
        for (double t = 0.05; t < 1.0; t += 0.05) {
            const Pt m{a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t};
            bool on = false;
            for (const auto& l : dj.lines)
                for (std::size_t k = 0; k + 1 < l.size() && !on; ++k) on = seg_dist(m, l[k], l[k + 1]) <= 1.0;
            QVERIFY2(on, qPrintable(QStringLiteral("the jump edge is missing at t=%1").arg(t)));
        }
    }

    void hoverSearchSkipsGapsAndReportsTies() {
        const std::vector<double> tx{0, 1, 2, 3}, ty{0, kNaN, 2, 3}, ty2{0, 5, 2, 3};
        std::vector<HoverSeries> hs{{&tx, &ty, 3, 3, 1.0}};
        // nearest-in-x would be the NaN sample; the finite ones are further
        auto hits = nearest_samples(hs, 1.0);
        QCOMPARE(hits.size(), std::size_t{0});  // 1/3 + 1/3 > 0.08: nothing, never the gap
        hs[0].cy = 0.05;
        hits = nearest_samples(hs, 0.05);
        QCOMPARE(hits.size(), std::size_t{1});
        QCOMPARE(hits[0].index, std::size_t{0});
        hs.push_back({&tx, &ty2, 3, 3, 0.05});  // an identical sample in a second series
        hits = nearest_samples(hs, 0.05);
        QCOMPARE(hits.size(), std::size_t{2});
        QCOMPARE(hits[1].series, std::size_t{1});
    }

    // -- image probes -----------------------------------------------------------------

    void everySeriesDrawsInItsColourAtItsSamples() {
        const auto x = linspace(0, 1, 20);
        std::vector<double> a(20), b(20), c(20);
        for (int i = 0; i < 20; ++i) a[i] = 1.0 + 0.1 * i, b[i] = -1.0 - 0.1 * i, c[i] = 5.0 * std::sin(i);
        auto v = view(model({line("a", x, a, 0), line("b", x, b, 1), line("c", x, c, 2)}));
        const QImage img = render(*v);
        for (std::size_t s = 0; s < 3; ++s)
            for (std::size_t i = 0; i < 20; ++i) {
                const auto& ser = v->model().series[s];
                QVERIFY2(colourNear(img, v->toPixel(ser.x[i], ser.y[i]), ser.colour),
                         qPrintable(QStringLiteral("series %1 sample %2").arg(s).arg(i)));
            }
    }

    void aNanSampleLeavesAGap() {
        const auto x = linspace(0, 1, 21);
        std::vector<double> y(21, 1.0);
        for (int i = 0; i < 21; ++i) y[i] = 1.0 + 0.02 * i;
        y[10] = kNaN;
        auto v = view(model({line("gap", x, y, 0)}));
        const QImage img = render(*v);
        const QColor col = v->model().series[0].colour;
        // the stretch from sample 9 to 11 is not drawn: probe its middle half
        const QPointF a = v->toPixel(x[9], y[9]), b = v->toPixel(x[11], y[11]);
        for (double t = 0.3; t <= 0.7; t += 0.05) {
            const QPointF p = a + (b - a) * t;
            QVERIFY2(!colourNear(img, p, col, 1, 60), qPrintable(QStringLiteral("line through the gap at t=%1").arg(t)));
        }
        QVERIFY(colourNear(img, v->toPixel(x[8] * 0.5 + x[9] * 0.5, y[8] * 0.5 + y[9] * 0.5), col));  // but drawn elsewhere
    }

    void aNanBlockLeavesAGapWhenDecimated() {
        const std::size_t n = 100000;
        const auto x = linspace(0, 1, n);
        std::vector<double> y(n);
        for (std::size_t i = 0; i < n; ++i) y[i] = std::sin(static_cast<double>(i) * 0.001) + 0.3 * std::sin(static_cast<double>(i) * 0.7);
        for (std::size_t i = 48000; i < 52000; ++i) y[i] = kNaN;  // 4% of the width
        auto v = view(model({line("dense", x, y, 0)}));
        const QImage img = render(*v);
        QVERIFY2(v->lastDrawnVertices() < n / 4, "decimation ran");
        const QColor col = v->model().series[0].colour;
        const QRectF pr = v->plotRect();
        const double xm = v->toPixel(0.5, 0.0).x();
        for (double yy = pr.top() + 2; yy < pr.bottom() - 2; yy += 0.5)
            QVERIFY2(!colourNear(img, {xm, yy}, col, 0, 60), qPrintable(QStringLiteral("line across the gap at y=%1").arg(yy)));
        // the decimated envelope still covers every raw sample (seeded: a failure reproduces)
        QRandomGenerator seeded(20260926);
        auto* rng = &seeded;
        for (int k = 0; k < 300; ++k) {
            std::size_t i = static_cast<std::size_t>(rng->bounded(static_cast<int>(n)));
            if (std::isnan(y[i])) continue;
            // this curve fills every legend position, so the legend covers some of it
            // (matplotlib's "best" would too); its placement has its own gate
            if (v->legendRect().adjusted(-2, -2, 2, 2).contains(v->toPixel(x[i], y[i]))) continue;
            if (!colourNear(img, v->toPixel(x[i], y[i]), col, 1)) {
                img.save(QDir::temp().filePath(QStringLiteral("tcad_plot_probe_fail.png")));  // for diagnosis
                const QPointF p = v->toPixel(x[i], y[i]);
                qWarning("sample %zu at (%.2f, %.2f), dpr %.2f", i, p.x(), p.y(), img.devicePixelRatio());
            }
            QVERIFY2(colourNear(img, v->toPixel(x[i], y[i]), col, 1), qPrintable(QStringLiteral("sample %1 not covered").arg(i)));
        }
    }

    void markersAppearAtFortyPointsOrFewer() {
        for (std::size_t n : {std::size_t{20}, std::size_t{40}, std::size_t{41}}) {
            const auto x = linspace(0, 1, n);
            std::vector<double> y(n, 1.0);
            y[0] = 0.0;  // not a single-value axis
            auto v = view(model({line("m", x, y, 0)}));
            const QImage img = render(*v);
            const QColor col = v->model().series[0].colour;
            int marked = 0;
            for (std::size_t i = 2; i + 2 < n; ++i) {
                const QPointF p = v->toPixel(x[i], 1.0);
                // 1.6 logical px above the centre: inside a marker (radius 2.1), outside the line (half-width 0.75)
                if (colourNear(img, p + QPointF(0, -1.6), col, 0, 90)) ++marked;
            }
            if (n <= 40) QVERIFY2(marked >= static_cast<int>(n) - 5, qPrintable(QStringLiteral("n=%1: %2 markers").arg(n).arg(marked)));
            else QVERIFY2(marked == 0, qPrintable(QStringLiteral("n=%1: %2 markers").arg(n).arg(marked)));
        }
    }

    void logAxisShowsMagnitudesAndGapsAtZero() {
        const std::vector<double> x{0, 1, 2, 3, 4, 5};
        const std::vector<double> y{1, -10, 100, 0, 1000, 1e4};
        Series fam = line("family", x, {-2, -20, -200, -2000, 0, -2e5}, 1);  // a family curve: all negative
        auto v = view(model({line("primary", x, y, 0), fam}, Scale::Linear, Scale::Log));
        const QImage img = render(*v);
        const QColor col = v->model().series[0].colour, fcol = v->model().series[1].colour;
        QVERIFY(colourNear(img, v->toPixel(1, 10), col));    // -10 at its magnitude
        QVERIFY(std::isnan(v->toPixel(3, 0).x()));           // 0 is not displayable
        const QPointF a = v->toPixel(2, 100), b = v->toPixel(4, 1000);
        QVERIFY(!colourNear(img, a + (b - a) * 0.5, col, 1, 60));  // no line through the zero
        QVERIFY(colourNear(img, v->toPixel(2, 200), fcol));   // the family is drawn at |v| too
        QVERIFY(colourNear(img, v->toPixel(3, 2000), fcol));
        for (const auto& t : v->ticks(Which::Y)) QVERIFY(t.value > 0);
        QVERIFY(v->yView().lo > 0);
    }

    void aRightAxisSeriesSitsOnTheRightScale() {
        const auto f = std::vector<double>{1, 10, 100, 1e3, 1e4, 1e5};
        PlotModel m = model({line("C", f, {1e-8, 1.1e-8, 1.2e-8, 1.3e-8, 1.4e-8, 1.5e-8}, 0),
                             line("G", f, {1e-3, 2e-3, 5e-3, 1e-2, 3e-2, 1e-1}, 1)},
                            Scale::Log, Scale::Linear);
        m.has_y2 = true;
        m.y2 = {QStringLiteral("G [S/cm^2]"), Scale::Linear, theme::seriesColour(1)};
        m.series[1].axis = YAxis::Right;
        auto v = view(std::move(m));
        const QImage img = render(*v);
        const QColor g = v->model().series[1].colour;
        for (std::size_t i = 0; i < 6; ++i) {
            QVERIFY(colourNear(img, v->toPixel(f[i], v->model().series[1].y[i], YAxis::Right), g));
            QVERIFY(v->plotRect().contains(v->toPixel(f[i], v->model().series[1].y[i], YAxis::Right)));
        }
        QVERIFY(!v->ticks(Which::Y2).empty());
        // on the left scale G would be far outside the plot
        QVERIFY(!v->plotRect().contains(v->toPixel(f[5], 1e-1, YAxis::Left)));
    }

    void ticksAreTheLocatorsAndAreDrawnWhereTheySay() {
        const auto x = linspace(-0.37, 2.9, 30);
        std::vector<double> y(30);
        for (int i = 0; i < 30; ++i) y[i] = 3e-9 * i * i;
        auto v = view(model({line("t", x, y, 0)}));
        const QImage img = render(*v);
        const auto xr = v->xView();
        const auto ticks = v->ticks(Which::X);
        QVERIFY(ticks.size() >= 3);
        bool found = false;  // some nbins reproduces them exactly: the port, not naive steps
        for (int n = 1; n <= 9 && !found; ++n) {
            std::vector<double> want;
            for (double t : linear_ticks(xr.lo, xr.hi, n))
                if (t >= xr.lo - (xr.hi - xr.lo) * 1e-10 && t <= xr.hi + (xr.hi - xr.lo) * 1e-10) want.push_back(t);
            std::vector<double> got;
            for (const auto& t : ticks) got.push_back(t.value);
            found = got == want;
        }
        QVERIFY(found);
        const QColor dim = theme::qcolor(theme::T::TextDim);
        for (const auto& t : ticks) {
            const double px = v->toPixel(t.value, y[0]).x();
            QVERIFY2(colourNear(img, {px, v->plotRect().bottom() + 3}, dim, 1, 60), qPrintable(QString::number(t.value)));
            QVERIFY(!t.text.isEmpty());
        }
        // 3e-9 * 29^2 = 2.5e-6, past the power limit -5: matplotlib's "1e-6" offset text
        QCOMPARE(v->offsetText(Which::Y), QStringLiteral("1e−6"));
    }

    void legendAndTitleArePresent() {
        const auto x = linspace(0, 1, 50);
        auto v = view(model({line("first", x, x, 0), line("second", x, std::vector<double>(50, 0.5), 1)}));
        const QImage img = render(*v);
        auto inked = [&](const QRectF& r, QColor c) {
            int k = 0;
            for (double yy = r.top(); yy < r.bottom(); yy += 0.5)
                for (double xx = r.left(); xx < r.right(); xx += 0.5) k += colourNear(img, {xx, yy}, c, 0, 120) ? 1 : 0;
            return k;
        };
        const QColor text = theme::qcolor(theme::T::Text);
        QVERIFY(!v->titleRect().isEmpty() && inked(v->titleRect(), text) > 10);
        QVERIFY(!v->legendRect().isEmpty() && inked(v->legendRect(), text) > 10);
        QVERIFY(inked(v->legendRect(), v->model().series[0].colour) > 3);  // its line sample
        // loc="best": the upper left is free of data, so nothing is under the legend
        for (const auto& ser : v->model().series)
            for (std::size_t i = 0; i < ser.x.size(); ++i) QVERIFY(!v->legendRect().contains(v->toPixel(ser.x[i], ser.y[i])));
        QVERIFY(v->legendRect().left() < v->plotRect().center().x());
    }

    void tickLabelsNeverOverlap() {
        struct Case {
            Scale xs, ys;
            double x0, x1, y0, y1;
        };
        const Case cases[] = {{Scale::Linear, Scale::Linear, -1.23456, 7.5, 1e-9, 3e-7},
                              {Scale::Linear, Scale::Log, 0, 2, 1e-12, 1e-2},
                              {Scale::Log, Scale::Linear, 1, 1e9, -5, 5},
                              {Scale::Log, Scale::Log, 2, 7, 3e-5, 8e-5},        // sub-decade: minor labels
                              {Scale::Linear, Scale::Linear, 1e17, 1e17 * (1 + 1e-9), 99999.5, 100000.5},
                              {Scale::Log, Scale::Log, 1e-30, 1e20, 1, 1e40}};
        const QSize sizes[] = {{300, 200}, {600, 360}, {1200, 800}, {250, 600}, {900, 220}};
        for (const Case& c : cases)
            for (QSize sz : sizes) {
                auto v = view(model({line("s", {c.x0, c.x1}, {c.y0, c.y1}, 0)}, c.xs, c.ys), sz.width(), sz.height());
                for (Which w : {Which::X, Which::Y}) {
                    std::vector<QRectF> rs;
                    for (const auto& t : v->ticks(w))
                        if (!t.label_rect.isEmpty()) rs.push_back(t.label_rect);
                    QVERIFY2(rs.size() >= 1, "at least one label");
                    for (std::size_t i = 0; i < rs.size(); ++i) {
                        QVERIFY2(QRectF(v->rect()).contains(rs[i]), "label inside the widget");
                        for (std::size_t j = i + 1; j < rs.size(); ++j)
                            QVERIFY2(!rs[i].intersects(rs[j]),
                                     qPrintable(QStringLiteral("overlap at %1x%2, axis %3").arg(sz.width()).arg(sz.height()).arg(int(w))));
                    }
                }
            }
    }

    // -- hover ------------------------------------------------------------------------

    void hoverNamesEverySampleItIsPointedAt() {
        const auto x = linspace(0, 2, 25);
        std::vector<double> y(25);
        for (int i = 0; i < 25; ++i) y[i] = 1e-6 * std::exp(i * 0.3);
        auto v = view(model({line("device", x, y, 0)}));
        for (int i = 0; i < 25; ++i) {
            v->hoverAt(v->toPixel(x[i], y[i]));
            QCOMPARE(v->readout(), QStringLiteral("device: %1 A/cm^2 @ %2 V").arg(sci(y[i])).arg(QString::asprintf("%.3f", x[i])));
        }
        v->hoverAt(v->plotRect().topLeft() + QPointF(3, 3));  // far from every sample
        QCOMPARE(v->readout(), QString());
    }

    void hoverIgnoresNanSamples() {
        // The QML defect (16.1 finding 5): a NaN disabled its cut-off.
        const auto x = linspace(0, 1, 11);
        std::vector<double> y(11);
        for (int i = 0; i < 11; ++i) y[i] = x[i] * x[i];
        y[5] = kNaN;
        auto v = view(model({line("device", x, y, 0)}));
        v->hoverAt(v->toPixel(0.0, 0.95));  // near x=0, far above the curve
        QCOMPARE(v->readout(), QString());
        v->hoverAt(v->toPixel(0.5, 0.25));  // where the NaN sample would be
        QVERIFY(!v->readout().contains(QStringLiteral("nan"), Qt::CaseInsensitive));
        v->hoverAt(v->toPixel(x[4], y[4]));  // exactly that sample, and no NaN one beside it
        QCOMPARE(v->readout(), QStringLiteral("device: %1 A/cm^2 @ %2 V").arg(sci(y[4])).arg(QString::asprintf("%.3f", x[4])));
    }

    void hoverReadsRawSamplesOfADecimatedSeries() {
        const std::size_t n = 100000;
        const auto x = linspace(0, 1, n);
        std::vector<double> y(n);
        for (std::size_t i = 0; i < n; ++i) y[i] = std::sin(static_cast<double>(i) * 0.0003) + 1e-3 * static_cast<double>(i % 7);
        auto v = view(model({line("dense", x, y, 0)}));
        for (std::size_t i : {std::size_t{17}, std::size_t{33333}, std::size_t{77777}, n - 1}) {
            v->hoverAt(v->toPixel(x[i], y[i]));
            const QString r = v->readout();
            QVERIFY(!r.isEmpty());
            // the reported pair is a real sample within a pixel of the cursor
            const double rx = r.section(QStringLiteral(" @ "), 1).section(QLatin1Char(' '), 0, 0).toDouble();
            const double ry = r.section(QStringLiteral(": "), 1).section(QLatin1Char(' '), 0, 0).toDouble();
            bool real = false;
            for (std::size_t k = (i > 2000 ? i - 2000 : 0); k < std::min(n, i + 2000) && !real; ++k)
                real = sci(y[k]) == QString::asprintf("%.3e", ry) && std::abs(x[k] - rx) < 1e-3;
            QVERIFY2(real, qPrintable(r));
            // the readout prints x to 3 decimals: 1e-3 of this axis is ~0.6 px
            QVERIFY(std::abs(v->toPixel(rx, ry).x() - v->toPixel(x[i], y[i]).x()) <= 2.0);
        }
    }

    void hoverWorksOnLogXAndBothAcAxes() {
        const auto f = std::vector<double>{1, 10, 100, 1e3, 1e4, 1e5, 1e6};
        std::vector<double> C(7), G(7);
        for (int i = 0; i < 7; ++i) C[i] = 1e-8 * (1 + 0.05 * i), G[i] = 1e-6 * std::pow(3.0, i);
        PlotModel m = model({line("C", f, C, 0), line("G", f, G, 1)}, Scale::Log, Scale::Linear);
        m.has_y2 = true;
        m.y2 = {QStringLiteral("G"), Scale::Log, {}};
        m.series[1].axis = YAxis::Right;
        m.series[0].unit = QStringLiteral("F/cm^2");
        m.series[1].unit = QStringLiteral("S/cm^2");
        m.x_unit = QStringLiteral("Hz");
        auto v = view(std::move(m));
        for (int i = 0; i < 7; ++i) {
            v->hoverAt(v->toPixel(f[i], C[i]));
            QVERIFY2(v->readout().contains(QStringLiteral("C: ") + sci(C[i]) + QStringLiteral(" F/cm^2")), qPrintable(v->readout()));
            v->hoverAt(v->toPixel(f[i], G[i], YAxis::Right));
            QVERIFY2(v->readout().contains(QStringLiteral("G: ") + sci(G[i]) + QStringLiteral(" S/cm^2")), qPrintable(v->readout()));
        }
    }

    void hoverListsEveryTiedSeries() {
        const auto x = linspace(0, 1, 10);
        std::vector<double> y(10);
        for (int i = 0; i < 10; ++i) y[i] = 0.3 * i;
        Series b = line("EFp", x, y, 3);
        b.unit = QStringLiteral("eV");
        Series a = line("EFn", x, y, 2);
        a.unit = QStringLiteral("eV");
        auto v = view(model({a, b}));
        v->hoverAt(v->toPixel(x[4], y[4]));
        QVERIFY2(v->readout().startsWith(QStringLiteral("EFn: ")) && v->readout().contains(QStringLiteral("; EFp: ")), qPrintable(v->readout()));
    }

    // -- view control -----------------------------------------------------------------

    void fitShowsEverySample() {
        const std::vector<Scale> scales{Scale::Linear, Scale::Log};
        for (Scale xs : scales)
            for (Scale ys : scales) {
                const auto x = linspace(1, 50, 30);
                std::vector<double> y(30);
                for (int i = 0; i < 30; ++i) y[i] = std::pow(10.0, i * 0.5 - 7);
                auto v = view(model({line("s", x, y, 0)}, xs, ys));
                for (int i = 0; i < 30; ++i) QVERIFY(v->plotRect().contains(v->toPixel(x[i], y[i])));
            }
    }

    void zoomAndPanStayPositiveOnLogAxesAndResetReturnsToFit() {
        const std::vector<double> f{1e2, 1e5, 1e9};
        auto v = view(model({line("s", f, {1e-12, 1e-9, 1e-3}, 0)}, Scale::Log, Scale::Log));
        const auto x0 = v->xView(), y0 = v->yView();
        v->zoom(10.0);
        v->pan(1.0, 1.0);
        v->pan(-3.0, -3.0);
        for (const auto r : {v->xView(), v->yView()}) {
            QVERIFY2(r.lo > 0 && r.hi > r.lo && std::isfinite(r.hi), qPrintable(QStringLiteral("%1 %2").arg(r.lo).arg(r.hi)));
        }
        v->resetView();
        QCOMPARE(v->xView().lo, x0.lo);
        QCOMPARE(v->yView().hi, y0.hi);
        // zooming in about the centre keeps the centre (in log coordinates)
        const double cx = std::sqrt(x0.lo * x0.hi);
        v->zoom(0.25);
        QVERIFY(std::abs(std::log10(std::sqrt(v->xView().lo * v->xView().hi)) - std::log10(cx)) < 1e-9);
    }

    void anEmptyModelShowsItsEmptyText() {
        PlotModel m;
        m.empty_text = QStringLiteral("No sweep yet");
        auto v = view(std::move(m));
        const QImage img = render(*v);
        const QColor dim = theme::qcolor(theme::T::TextDim);
        int inked = 0;
        const QPointF c = v->rect().center();
        for (double dx = -60; dx < 60; dx += 0.5)
            for (double dy = -8; dy < 8; dy += 0.5) inked += colourNear(img, c + QPointF(dx, dy), dim, 0, 60) ? 1 : 0;
        QVERIFY(inked > 20);
        v->hoverAt(c);
        QCOMPARE(v->readout(), QString());
    }

    void renderIsAtTheDisplayScale() {
        auto v = view(model({line("s", {0, 1}, {0, 1}, 0)}));
        const QImage img = render(*v);
        const double dpr = img.devicePixelRatio();
        QCOMPARE(img.width(), static_cast<int>(std::lround(600 * dpr)));
        const QByteArray want = qgetenv("QT_SCALE_FACTOR");
        if (!want.isEmpty()) QCOMPARE(dpr, want.toDouble());
    }

    // Renders for a person to look at (TCAD_PLOT_SNAPSHOT=<dir>); no assertion.
    void snapshots() {
        const QByteArray dir = qgetenv("TCAD_PLOT_SNAPSHOT");
        if (dir.isEmpty()) QSKIP("set TCAD_PLOT_SNAPSHOT=<dir> to save renders");
        const QDir out(QString::fromLocal8Bit(dir));
        {  // I-V on log y with a family and a dashed comparison
            const auto x = linspace(-0.5, 0.8, 27);
            std::vector<double> a(27), b(27), c(27);
            for (int i = 0; i < 27; ++i)
                a[i] = 1e-12 * (std::exp(x[i] / 0.02585) - 1), b[i] = 3 * a[i], c[i] = 0.3 * a[i];
            a[20] = kNaN;
            Series cmp = line("all models off", x, c, 0);
            cmp.colour = theme::dataColour(theme::DataColour::Comparison);
            cmp.line = LineStyle::Dashed;
            auto v = view(model({line("device", x, a, 0), line("step 2", x, b, 1), cmp}, Scale::Linear, Scale::Log), 640, 400);
            render(*v).save(out.filePath(QStringLiteral("iv_log.png")));
        }
        {  // AC: log x, C left, G right (log)
            std::vector<double> f, C, G;
            for (int i = 0; i <= 60; ++i) {
                f.push_back(std::pow(10.0, i * 0.15));
                C.push_back(1e-8 / (1 + std::pow(f.back() / 1e6, 2)));
                G.push_back(1e-9 * f.back() / (1 + f.back() / 1e7));
            }
            PlotModel m = model({line("C", f, C, 0), line("G", f, G, 1)}, Scale::Log, Scale::Linear);
            m.title = QStringLiteral("anode AC sweep");
            m.x.label = QStringLiteral("frequency [Hz]");
            m.y = {QStringLiteral("C [F/cm^2]"), Scale::Linear, theme::seriesColour(0)};
            m.has_y2 = true;
            m.y2 = {QStringLiteral("G [S/cm^2]"), Scale::Log, theme::seriesColour(1)};
            m.series[1].axis = YAxis::Right;
            m.legend = false;
            render(*view(std::move(m), 640, 400)).save(out.filePath(QStringLiteral("ac.png")));
        }
        {  // a sub-decade log view: minor labels
            auto v = view(model({line("s", linspace(2, 7, 30), linspace(3e-5, 8e-5, 30), 2)}, Scale::Log, Scale::Log), 640, 400);
            render(*v).save(out.filePath(QStringLiteral("subdecade.png")));
        }
        {  // an offset axis
            auto v = view(model({line("s", linspace(1e17, 1e17 * (1 + 1e-9), 30), linspace(99999.5, 100000.5, 30), 4)}), 640, 400);
            render(*v).save(out.filePath(QStringLiteral("offset.png")));
        }
    }

    // -- bench (only with TCAD_PLOT_BENCH) --------------------------------------------

    void bench() {
        const QByteArray out_path = qgetenv("TCAD_PLOT_BENCH");
        if (out_path.isEmpty()) QSKIP("set TCAD_PLOT_BENCH=<out.json> to run the bench");
        nlohmann::ordered_json report = nlohmann::ordered_json::object();
        auto pct = [](std::vector<double> ms, double q) {
            std::sort(ms.begin(), ms.end());
            return ms[static_cast<std::size_t>(std::min<double>(ms.size() - 1, std::floor(q * (ms.size() - 1) + 0.5)))];
        };
        for (std::size_t n : {std::size_t{1000}, std::size_t{100000}}) {
            const auto x = linspace(0, 1, n);
            std::vector<double> y(n);
            for (std::size_t i = 0; i < n; ++i) y[i] = std::sin(static_cast<double>(i) * 6.0 / static_cast<double>(n) * 10) + 0.2 * std::sin(static_cast<double>(i));
            PlotView v;
            v.resize(1200, 800);
            v.setModel(model({line("bench", x, y, 0)}));
            v.show();
            QVERIFY(QTest::qWaitForWindowExposed(&v));
            // A frame: the view change (which relays out the axes) plus the
            // paint, rendered into a device-resolution image -- the analogue
            // of the P1 bench's VTK Render() + finish, which also leaves the
            // window system's present out. repaint()'s wall time, which
            // includes that flush to the screen, is reported beside it.
            const double dpr = v.devicePixelRatioF();
            QImage target(QSize(static_cast<int>(std::lround(v.width() * dpr)), static_cast<int>(std::lround(v.height() * dpr))),
                          QImage::Format_ARGB32_Premultiplied);
            target.setDevicePixelRatio(dpr);
            std::vector<double> pan_ms, zoom_ms, hover_ms, change_ms, paint_ms, repaint_ms;
            QElapsedTimer t;
            auto frame = [&](auto&& change, std::vector<double>& total) {
                t.start();
                change();
                const double c = t.nsecsElapsed() / 1e6;
                t.start();
                v.render(&target);
                const double p = t.nsecsElapsed() / 1e6;
                change_ms.push_back(c);
                paint_ms.push_back(p);
                total.push_back(c + p);
            };
            for (int k = 0; k < 120; ++k) frame([&] { v.pan(k % 2 ? 0.01 : -0.01, k % 2 ? 0.005 : -0.005); }, pan_ms);  // the view stays on the data
            for (int k = 0; k < 120; ++k) frame([&] { v.zoom(k % 2 ? 1.1 : 1 / 1.1); }, zoom_ms);
            for (int k = 0; k < 60; ++k) {
                t.start();
                v.pan(k % 2 ? 0.01 : -0.01, 0.0);
                v.repaint();
                repaint_ms.push_back(t.nsecsElapsed() / 1e6);
            }
            auto* rng = QRandomGenerator::global();
            const QRectF pr = v.plotRect();
            for (int k = 0; k < 2000; ++k) {
                const QPointF p(pr.left() + rng->generateDouble() * pr.width(), pr.top() + rng->generateDouble() * pr.height());
                t.start();
                v.hoverAt(p);
                hover_ms.push_back(t.nsecsElapsed() / 1e6);
            }
            report[std::to_string(n)] = {{"pan_p95_ms", pct(pan_ms, 0.95)}, {"pan_p50_ms", pct(pan_ms, 0.5)},
                                         {"zoom_p95_ms", pct(zoom_ms, 0.95)}, {"zoom_p50_ms", pct(zoom_ms, 0.5)},
                                         {"change_p95_ms", pct(change_ms, 0.95)}, {"paint_p95_ms", pct(paint_ms, 0.95)},
                                         {"repaint_wall_p50_ms", pct(repaint_ms, 0.5)}, {"repaint_wall_p95_ms", pct(repaint_ms, 0.95)},
                                         {"hover_p95_ms", pct(hover_ms, 0.95)}, {"hover_max_ms", pct(hover_ms, 1.0)},
                                         {"drawn_vertices", v.lastDrawnVertices()}, {"pan_frames_ms", pan_ms}, {"dpr", v.devicePixelRatioF()},
                                         {"size", {v.width(), v.height()}}};
        }
        QFile f(QString::fromLocal8Bit(out_path));
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.write(QByteArray::fromStdString(report.dump(2)));
    }
};

QTEST_MAIN(TestPlot)
#include "test_plot.moc"
