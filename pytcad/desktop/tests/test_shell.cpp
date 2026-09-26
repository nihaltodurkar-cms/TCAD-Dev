// Shell end-to-end tests (NATIVE-DESKTOP-PLAN.md section 15.13, S3b and
// S3f): the REAL MainWindow, shown in a real window, driven with QTest
// and synthesized input events.
//
// Test data comes from gui/tests/test_desktop_shell.py through
// TCAD_TEST_DATA: mosfet_2d.npz and resistor_3d.npz (solved), corrupt.npz,
// schema99.npz, notes.txt, layers3d.npz (S6: a synthetic 3D result with a
// current density, sweep snapshots and regions), and a copy of mosfet_2d.npz inside a
// directory named with non-ASCII characters. P2-S3's curve modes: diode_1d.npz
// and its I-V sweep, transient and AC runs (diode_1d_iv/_transient/_ac.npz),
// a C-V sweep (cv.npz), and the I-V run with one step marked rejected
// (diode_1d_rejected.npz). Every window uses its own
// settings file in a temporary directory -- never the user's.
#include "shell/app_settings.hpp"
#include "shell/display_panel.hpp"
#include "shell/info_panel.hpp"
#include "shell/main_window.hpp"
#include "shell/playback_panel.hpp"
#include "shell/plot_panel.hpp"
#include "shell/view3d_panel.hpp"
#include "views/colormaps.hpp"
#include "data/contour_levels.hpp"
#include "data/line_cut.hpp"
#include "data/npz.hpp"
#include "data/result_model.hpp"
#include "views/field/field_view.hpp"
#include "views/plot/curve_modes.hpp"
#include "views/plot/plot_view.hpp"
#include "theme/theme.hpp"

#include <DockManager.h>
#include <DockWidget.h>
#include <DockWidgetTab.h>

#include <QAction>
#include <QCheckBox>
#include <QDoubleSpinBox>
#include <QPushButton>
#include <QSlider>
#include <QSpinBox>
#include <QComboBox>
#include <QLineEdit>
#include <QListWidgetItem>
#include <QRadioButton>
#include <QApplication>
#include <QDir>
#include <QDropEvent>
#include <QElapsedTimer>
#include <QMenu>
#include <QMouseEvent>
#include <QFile>
#include <QLabel>
#include <QLineF>
#include <QListWidget>
#include <QMessageBox>
#include <QMimeData>
#include <QRegularExpression>
#include <QSettings>
#include <QStatusBar>
#include <QStyle>
#include <QStyleHints>
#include <QSurfaceFormat>
#include <QTemporaryDir>
#include <QToolBar>
#include <QUrl>
#include <QVTKOpenGLNativeWidget.h>
#include <QtTest/QtTest>
#include <vtkCamera.h>
#include <vtkIdTypeArray.h>
#include <vtkLookupTable.h>
#include <vtkMapper.h>
#include <vtkPiecewiseFunction.h>
#include <vtkPolyData.h>
#include <vtkProperty.h>
#include <vtkVolume.h>
#include <vtkVolumeProperty.h>
#include <vtkRenderer.h>
#include <vtkScalarBarActor.h>
#include <vtkTextProperty.h>
#include <vtkActor.h>
#include <vtkTextActor.h>

#include <algorithm>
#include <cmath>
#include <functional>
#include <memory>
#include <set>
#include <utility>

using tcad::desktop::AppSettings;
using tcad::desktop::FieldView;
using tcad::desktop::MainWindow;
using tcad::desktop::ColorMap;
using tcad::desktop::SurfaceMode;
using tcad::desktop::SweepSnapshots;
using tcad::desktop::VolumePreset;
using tcad::desktop::colorMapName;
using tcad::desktop::lut_input;
using tcad::desktop::volumePresetSpec;
using tcad::desktop::plot::PlotView;
using tcad::desktop::plot::ViewMode;

// A named widget of one of the window's panels. Searched from the PANEL:
// ADS takes the widgets of non-current tabs out of the window's object
// tree (a tabbed dock's hidden page has no parent), so a search from the
// window finds only the current tab's. (moc cannot take a template inside
// the class's slots, hence file scope.)
template <class T>
T* child(QWidget* panel, const char* name) {
    T* c = panel->findChild<T*>(name);
    if (!c) qWarning("no child %s", name);
    return c;
}

class TestShell : public QObject {
    Q_OBJECT

    QTemporaryDir tmp_;

    static QString data(const QString& name) {
        return QDir(qEnvironmentVariable("TCAD_TEST_DATA")).absoluteFilePath(name);
    }
    QString ini(const QString& name) const { return tmp_.filePath(name); }

    static std::unique_ptr<MainWindow> shown(const QString& ini_path) {
        auto w = std::make_unique<MainWindow>(AppSettings::atFile(ini_path));
        w->show();
        if (!QTest::qWaitForWindowExposed(w.get())) return nullptr;
        return w;
    }

    static QList<QWidget*> errorBoxes() {
        QList<QWidget*> out;
        for (QWidget* w : QApplication::topLevelWidgets())
            if (w->objectName() == "ErrorBox" && w->isVisible()) out << w;
        return out;
    }

    static void drop(MainWindow* w, const QList<QUrl>& urls) {
        QMimeData mime;
        mime.setUrls(urls);
        const QPointF at(w->width() / 2.0, w->height() / 2.0);
        QDragEnterEvent enter(at.toPoint(), Qt::CopyAction, &mime, Qt::LeftButton, Qt::NoModifier);
        QApplication::sendEvent(w, &enter);
        QDropEvent ev(at, Qt::CopyAction, &mime, Qt::LeftButton, Qt::NoModifier);
        QApplication::sendEvent(w, &ev);
    }

    // Section 15.13 rev. 8: two ADS states with the same STRUCTURE (which
    // dock where, orientation, visibility, floating) but not necessarily
    // the same splitter pixel sizes, which depend on the window size when
    // each state was taken. Prints both in full when they differ.
    static bool sameStructure(const QByteArray& a, const QByteArray& b, bool report = true) {
        static const QRegularExpression sizes("<Sizes>[^<]*</Sizes>");
        QString sa = QString::fromUtf8(a), sb = QString::fromUtf8(b);
        sa.remove(sizes);
        sb.remove(sizes);
        if (sa == sb || !report) return sa == sb;
        qWarning("layout A: %s", a.constData());
        qWarning("layout B: %s", b.constData());
        return false;
    }

    // Rows of the Fields list that are the result's own fields (a header
    // and the derived maps follow them -- S5g).
    static QList<qsizetype> fieldRows(MainWindow* w) {
        QList<qsizetype> rows;
        for (int i = 0; i < w->fieldList()->count(); ++i)
            if (w->fieldList()->item(i)->data(Qt::UserRole).toString() == "field") rows << i;
        return rows;
    }
    static QListWidgetItem* derivedItem(MainWindow* w, const QString& name) {
        for (int i = 0; i < w->fieldList()->count(); ++i) {
            QListWidgetItem* it = w->fieldList()->item(i);
            if (it->text() == name && it->data(Qt::UserRole).toString() == "derived") return it;
        }
        return nullptr;
    }
    static void selectItem(MainWindow* w, QListWidgetItem* it) {
        QListWidget* list = w->fieldList();
        QTest::mouseClick(list->viewport(), Qt::LeftButton, {}, list->visualItemRect(it).center());
    }
    static void selectField(MainWindow* w, const QString& name) {
        for (qsizetype r : fieldRows(w))
            if (w->fieldList()->item(static_cast<int>(r))->text() == name) selectItem(w, w->fieldList()->item(static_cast<int>(r)));
    }

    // The readout ("name: 1.234e+05 unit @ x=.., y=.. um") names the RAW
    // value, in the view's source result, of a node at the printed
    // coordinates -- not the displayed (log, normalised) value (M51).
    static bool readoutIsRawNodeValue(FieldView* v, const QString& readout) {
        static const QRegularExpression re("^[^:]+: (\\S+) .*@ x=([^,]+), y=(\\S+) um$");
        const QRegularExpressionMatch m = re.match(readout);
        if (!m.hasMatch()) return false;
        const auto values = v->fieldSource()->scalar(v->field()).values;
        const std::size_t nx = v->axisUm(0).size(), ny = v->axisUm(1).size();
        for (std::size_t j = 0; j < ny; ++j) {
            if (QString::asprintf("%.2f", v->axisUm(1)[j]) != m.captured(3)) continue;
            for (std::size_t i = 0; i < nx; ++i)
                if (QString::asprintf("%.2f", v->axisUm(0)[i]) == m.captured(2) &&
                    QString::asprintf("%.3e", values[j * nx + i]) == m.captured(1))
                    return true;
        }
        return false;
    }

    // Distinct colours in a framebuffer grab: a blank or failed frame has 1.
    static int distinctColours(FieldView* v) {
        const QImage img = v->grabFramebuffer();
        std::set<QRgb> colours;
        for (int y = 0; y < img.height(); y += 7)
            for (int x = 0; x < img.width(); x += 7) colours.insert(img.pixel(x, y));
        return static_cast<int>(colours.size());
    }

    // Shared: the MOSFET (a 2D result with every field), open in a window.
    std::unique_ptr<MainWindow> mosfet(const char* name) {
        auto w = shown(ini(name));
        if (w && !w->tryOpen(data("mosfet_2d.npz"))) return nullptr;
        return w;
    }
    // Every displayed patch equals lut_input(transform(raw), norm): exact.
    static bool displayedIs(FieldView* v, const std::function<double(double)>& transform) {
        const std::vector<double> raw = v->fieldSource()->scalar(v->field()).values;
        vtkIdTypeArray* ids = v->displayedNodeIds();
        vtkDoubleArray* shown_values = v->displayedScalars();
        for (vtkIdType k = 0; k < ids->GetNumberOfValues(); ++k) {
            const double want = lut_input(transform(raw[static_cast<std::size_t>(ids->GetValue(k))]), v->normRange()[0],
                                          v->normRange()[1]);
            if (shown_values->GetValue(k) != want) return false;
        }
        return ids->GetNumberOfValues() > 0;
    }


    // -- curve modes (P2-S3, NATIVE-DESKTOP-PLAN.md 16.3) ---------------------
    // One test per curve mode, on real 1D runs; the modes a result cannot
    // show are absent; switching views keeps the GL context and is fast.
    // PlotView itself (ticks, gaps, log rule, hover rule) is gated by
    // test_plot.cpp; these gate what each mode feeds it.

    std::unique_ptr<MainWindow> opened(const char* ini_name, const char* file) {
        auto w = shown(ini(ini_name));
        if (w && !w->tryOpen(data(file))) return nullptr;
        return w;
    }
    static QList<ViewMode> comboModes(MainWindow* w) {
        QList<ViewMode> out;
        for (int i = 0; i < w->viewModeCombo()->count(); ++i)
            out << static_cast<ViewMode>(w->viewModeCombo()->itemData(i).toInt());
        return out;
    }
    // Chooses a mode the way a user does: the toolbar combo.
    static bool chooseMode(MainWindow* w, ViewMode m) {
        QComboBox* combo = w->viewModeCombo();
        const int i = combo->findData(static_cast<int>(m));
        if (i < 0) return false;
        combo->setCurrentIndex(i);
        emit combo->activated(i);
        return w->viewMode() == m;
    }
    static QAction* logAction(MainWindow* w) {
        for (QAction* a : w->findChildren<QAction*>())
            if (a->text() == "Log scale") return a;
        return nullptr;
    }
    static QString statusReadout(MainWindow* w) { return w->findChild<QLabel*>("Readout")->text(); }
    // The mouse onto sample i of series s (a synthesized move: QTest::mouseMove
    // moves the real cursor). Returns the plot's readout.
    static QString hoverSample(PlotView* p, std::size_t s, std::size_t i) {
        const auto& ser = p->model().series[s];
        const QPointF at = p->toPixel(ser.x[i], ser.y[i], ser.axis);
        QMouseEvent move(QEvent::MouseMove, at, p->mapToGlobal(at), Qt::NoButton, Qt::NoButton, Qt::NoModifier);
        QApplication::sendEvent(p, &move);
        return p->readout();
    }
    // Decision 3's readout entry for sample i of series s, from the RAW values.
    static QString entry(const PlotView* p, std::size_t s, std::size_t i) {
        const auto& m = p->model();
        const auto& ser = m.series[s];
        const double x = ser.x[i], a = std::abs(x);
        QString e = ser.label + ": " + QString::asprintf("%.3e", ser.y[i]);
        if (!ser.unit.isEmpty()) e += " " + ser.unit;
        e += " @ " + ((x == 0 || (a >= 1e-3 && a < 1e4)) ? QString::asprintf("%.3f", x) : QString::asprintf("%.3e", x));
        if (!m.x_unit.isEmpty()) e += " " + m.x_unit;
        return e;
    }
    // TCAD_SHELL_SNAPSHOT=<dir>: saves the whole window as <name>.png, to look at.
    static void snapshot(MainWindow* w, const QString& name) {
        const QString dir = qEnvironmentVariable("TCAD_SHELL_SNAPSHOT");
        if (dir.isEmpty()) return;
        QApplication::processEvents();
        w->grab().save(QDir(dir).filePath(name + ".png"));
    }
    static std::vector<double> um(const std::vector<double>& cm) {
        std::vector<double> out(cm.size());
        for (std::size_t i = 0; i < cm.size(); ++i) out[i] = cm[i] * 1e4;
        return out;
    }
    // The plot is the visible view and the FieldView is hidden (and vice versa).
    static bool plotShown(MainWindow* w) { return w->plotView()->isVisible() && !w->fieldView()->isVisible(); }
    static bool mapShown(MainWindow* w) { return w->fieldView()->isVisible() && !w->plotView()->isVisible(); }

    // -- overlays (P2-S5, NATIVE-DESKTOP-PLAN.md 16.3) ----------------------------
    // Sweeps from other result files over the open one's: a comparison
    // (dashed) and a family (one colour each), each on its OWN voltages,
    // refused -- naming the mismatch -- when the contact, quantity, unit or
    // channel differ.
    using Kind = tcad::desktop::plot::OverlayCurve::Kind;

    static std::unique_ptr<MainWindow> curvesOf(QTemporaryDir& tmp, const char* ini_name) {
        auto w = shown(tmp.filePath(ini_name));
        if (!w || !w->tryOpen(data("diode_1d_iv.npz"))) return nullptr;
        return chooseMode(w.get(), ViewMode::Curves) ? std::move(w) : nullptr;
    }
    static tcad::desktop::SweepSeries sweepOf(const char* file) {
        const auto npz = tcad::desktop::NpzFile::open(data(file).toStdWString());
        return tcad::desktop::ResultModel::from_npz(npz).sweep();
    }

    // -- P2-S6 hardening (NATIVE-DESKTOP-PLAN.md 16.3) -----------------------------

    // Distance (logical px) from `pt` to series t's polyline as drawn.
    static double distanceToSeries(PlotView* p, std::size_t t, QPointF pt) {
        const auto& s = p->model().series[t];
        double best = 1e300;
        QPointF prev;
        bool have_prev = false;
        for (std::size_t i = 0; i < s.x.size(); ++i) {
            const QPointF q = p->toPixel(s.x[i], s.y[i], s.axis);
            if (!std::isfinite(q.x()) || !std::isfinite(q.y())) {
                have_prev = false;
                continue;
            }
            best = std::min(best, QLineF(pt, q).length());
            if (have_prev && s.line != tcad::desktop::plot::LineStyle::None) {
                const QPointF d = q - prev;
                const double len2 = d.x() * d.x() + d.y() * d.y();
                if (len2 > 0) {
                    const double u = std::clamp(((pt - prev).x() * d.x() + (pt - prev).y() * d.y()) / len2, 0.0, 1.0);
                    best = std::min(best, QLineF(pt, prev + u * d).length());
                }
            }
            prev = q;
            have_prev = true;
        }
        return best;
    }

    // Image probe of the plot as drawn: the render is at the display scale,
    // and each series' colour is drawn at one of its samples that no other
    // series comes within 4 logical px of (samples of dashed/dotted lines are
    // probed only where markers are drawn). Returns the number of series
    // probed; `why` names the first failure.
    static int probeSeriesColours(PlotView* p, QString* why) {
        const QImage img = p->grab().toImage();
        const double dpr = p->devicePixelRatioF();
        if (img.width() != qRound(p->width() * dpr) || img.height() != qRound(p->height() * dpr)) {
            *why = QString("render %1x%2 is not %3x%4 at dpr %5")
                       .arg(img.width()).arg(img.height()).arg(p->width()).arg(p->height()).arg(dpr);
            return -1;
        }
        const auto& m = p->model();
        int probed = 0;
        for (std::size_t s = 0; s < m.series.size(); ++s) {
            const auto& ser = m.series[s];
            const bool markers = ser.markers == tcad::desktop::plot::Markers::Always ||
                                 (ser.markers == tcad::desktop::plot::Markers::Auto &&
                                  ser.x.size() <= tcad::desktop::plot::kAutoMarkerMaxPoints);
            if (!markers && ser.line != tcad::desktop::plot::LineStyle::Solid) continue;
            bool done = false;
            for (std::size_t i = 0; i < ser.x.size() && !done; ++i) {
                const QPointF q = p->toPixel(ser.x[i], ser.y[i], ser.axis);
                if (!std::isfinite(q.x()) || !p->plotRect().adjusted(3, 3, -3, -3).contains(q)) continue;
                bool clear = true;
                for (std::size_t o = 0; o < m.series.size() && clear; ++o)
                    if (o != s && distanceToSeries(p, o, q) < 4.0) clear = false;
                if (!clear) continue;
                const QColor want = ser.colour;
                const int cx = qRound(q.x() * dpr), cy = qRound(q.y() * dpr);
                for (int dy = -1; dy <= 1 && !done; ++dy)
                    for (int dx = -1; dx <= 1 && !done; ++dx) {
                        const QColor got = img.pixelColor(cx + dx, cy + dy);
                        if (std::abs(got.red() - want.red()) + std::abs(got.green() - want.green()) +
                                std::abs(got.blue() - want.blue()) <= 40)
                            done = true;
                    }
                if (!done) {
                    *why = QString("series '%1' sample %2: colour %3 not drawn near (%4, %5)")
                               .arg(ser.label).arg(i).arg(want.name()).arg(q.x()).arg(q.y());
                    return -1;
                }
            }
            if (done) ++probed;
        }
        return probed;
    }

    // Adversarial files (P2-S6): each opens, each mode shows it without
    // inventing data, and hover never reports a NaN.
    static QString hoverEverywhere(PlotView* p) {
        QString seen;
        for (int y = 0; y < p->height(); y += 17)
            for (int x = 0; x < p->width(); x += 17) {
                p->hoverAt(QPointF(x, y));
                if (p->readout().contains("nan", Qt::CaseInsensitive)) return p->readout();
            }
        return {};
    }

private slots:
    void initTestCase() {
        QVERIFY2(!qEnvironmentVariable("TCAD_TEST_DATA").isEmpty(), "set TCAD_TEST_DATA");
        QVERIFY(QFileInfo::exists(data("mosfet_2d.npz")));
        QVERIFY(tmp_.isValid());
    }

    void cleanup() {
        for (QWidget* w : errorBoxes()) w->close();
    }

    // -- opening -------------------------------------------------------------
    void opensAResult() {
        auto w = shown(ini("open.ini"));
        QVERIFY(w);
        QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
        QVERIFY(w->result());
        QCOMPARE(fieldRows(w.get()).size(), static_cast<qsizetype>(w->result()->scalar_names().size()));
        QVERIFY(w->lastError().isEmpty());
        QVERIFY(errorBoxes().isEmpty());
    }

    void failedOpenKeepsTheCurrentResult_data() {
        QTest::addColumn<QString>("file");
        QTest::addColumn<QString>("needle");
        QTest::newRow("missing") << "no_such_result.npz" << "File not found";
        QTest::newRow("not-npz") << "notes.txt" << "Not a PyTCAD result";
        QTest::newRow("corrupt") << "corrupt.npz" << "Could not open";
        QTest::newRow("schema-99") << "schema99.npz" << "schema version 99";
    }
    void failedOpenKeepsTheCurrentResult() {
        QFETCH(QString, file);
        QFETCH(QString, needle);
        auto w = shown(ini("fail.ini"));
        QVERIFY(w);
        QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
        const auto* before = w->result();
        const QString before_path = w->resultPath();
        QVERIFY(!w->tryOpen(data(file)));
        QVERIFY2(w->lastError().contains(needle), qPrintable(w->lastError()));
        QCOMPARE(w->result(), before);  // the same model object: nothing was swapped
        QCOMPARE(w->resultPath(), before_path);
        QVERIFY(w->statusBar()->currentMessage().contains(needle));
        const auto boxes = errorBoxes();
        QCOMPARE(boxes.size(), 1);
        QCOMPARE(boxes.front()->windowModality(), Qt::NonModal);  // the window stays usable
    }

    void nonAsciiPathOpens() {
        auto w = shown(ini("unicode.ini"));
        QVERIFY(w);
        const QString path = data(QString::fromUtf8("\xC2\xB5m \xE2\x82\xAC \xF0\x9F\x98\x80/mosfet_2d.npz"));
        QVERIFY2(QFileInfo::exists(path), qPrintable(path));
        QVERIFY2(w->tryOpen(path), qPrintable(w->lastError()));
    }

    // -- drag and drop -------------------------------------------------------
    void dropOpensOneResultAndNamesBadDrops() {
        auto w = shown(ini("drop.ini"));
        QVERIFY(w);
        drop(w.get(), {QUrl::fromLocalFile(data("resistor_3d.npz"))});
        QVERIFY2(w->result() && w->result()->dimensionality() == 3, qPrintable(w->lastError()));
        const auto* shown_model = w->result();

        drop(w.get(), {QUrl::fromLocalFile(data("mosfet_2d.npz")), QUrl::fromLocalFile(data("resistor_3d.npz"))});
        QVERIFY(w->lastError().contains("one result file at a time"));
        QCOMPARE(w->result(), shown_model);

        drop(w.get(), {QUrl::fromLocalFile(data("notes.txt"))});
        QVERIFY(w->lastError().contains("Not a PyTCAD result"));
        QCOMPARE(w->result(), shown_model);
    }

    void dragOfNonFilesIsRefused() {
        auto w = shown(ini("drag.ini"));
        QVERIFY(w);
        QMimeData mime;
        mime.setUrls({QUrl("https://example.com/result.npz")});
        QDragEnterEvent enter(QPoint(10, 10), Qt::CopyAction, &mime, Qt::LeftButton, Qt::NoModifier);
        enter.setAccepted(false);
        QApplication::sendEvent(w.get(), &enter);
        QVERIFY(!enter.isAccepted());
    }

    // -- recent files --------------------------------------------------------
    void recentFilesDeduplicateCaseInsensitivelyAndCap() {
        auto w = shown(ini("recent.ini"));
        QVERIFY(w);
        QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
        QVERIFY(w->tryOpen(data("resistor_3d.npz")));
        QVERIFY(w->tryOpen(data("mosfet_2d.npz").toUpper()));  // same file on Windows
        const QStringList recent = w->settings().recentFiles();
        QCOMPARE(recent.size(), 2);
        QVERIFY(tcad::desktop::samePath(recent[0], data("mosfet_2d.npz")));  // most recent first
        QVERIFY(tcad::desktop::samePath(recent[1], data("resistor_3d.npz")));
        for (int i = 0; i < 15; ++i) w->settings().addRecent(tmp_.filePath(QString("r%1.npz").arg(i)));
        QCOMPARE(w->settings().recentFiles().size(), AppSettings::kMaxRecent);
    }

    void recentEntryOfADeletedFileIsRemoved() {
        auto w = shown(ini("recent_deleted.ini"));
        QVERIFY(w);
        const QString copy = tmp_.filePath("gone.npz");
        QVERIFY(QFile::copy(data("mosfet_2d.npz"), copy));
        QVERIFY(w->tryOpen(copy));
        QVERIFY(w->settings().recentFiles().contains(QDir::cleanPath(QFileInfo(copy).absoluteFilePath())));
        QVERIFY(QFile::remove(copy));
        QVERIFY(!w->tryOpen(copy));
        QVERIFY(w->lastError().contains("File not found"));
        for (const QString& p : w->settings().recentFiles()) QVERIFY(!tcad::desktop::samePath(p, copy));
    }

    void recentFilesSurviveARestart() {
        const QString path = ini("recent_restart.ini");
        {
            auto w = shown(path);
            QVERIFY(w);
            QVERIFY(w->tryOpen(data("resistor_3d.npz")));
            w->close();
        }
        auto w2 = shown(path);
        QVERIFY(w2);
        QCOMPARE(w2->settings().recentFiles().size(), 1);
        QVERIFY(tcad::desktop::samePath(w2->settings().recentFiles().front(), data("resistor_3d.npz")));
    }

    // -- layout --------------------------------------------------------------
    void layoutSurvivesARestart() {
        const QString path = ini("layout.ini");
        QByteArray moved;
        {
            auto w = shown(path);
            QVERIFY(w);
            w->dockManager()->addDockWidget(ads::RightDockWidgetArea, w->fieldsDock());  // move it
            w->resize(1100, 700);
            QApplication::processEvents();
            moved = w->dockManager()->saveState();
            QVERIFY(!sameStructure(moved, w->defaultLayout(), false));  // really moved, not just resized
            w->close();
        }
        auto w2 = shown(path);
        QVERIFY(w2);
        QCOMPARE(w2->dockManager()->saveState(), moved);
        QCOMPARE(w2->size(), QSize(1100, 700));
        QVERIFY(w2->lastError().isEmpty());
        w2->resetLayout();
        QApplication::processEvents();
        QVERIFY(sameStructure(w2->dockManager()->saveState(), w2->defaultLayout()));
        QVERIFY2(w2->fieldsDock()->width() >= 150, qPrintable(QString::number(w2->fieldsDock()->width())));
    }

    void corruptSavedLayoutFallsBackToTheDefault() {
        const QString path = ini("corrupt_layout.ini");
        {
            QSettings s(path, QSettings::IniFormat);
            s.setValue("layout/version", AppSettings::kLayoutVersion);
            s.setValue("layout/geometry", QByteArray("not a geometry"));
            s.setValue("layout/docks", QByteArray("<QtAdvancedDockingSystem this is not a layout"));
        }
        auto w = shown(path);
        QVERIFY(w);
        QVERIFY(sameStructure(w->dockManager()->saveState(), w->defaultLayout()));
        QVERIFY2(w->fieldsDock()->width() >= 150, qPrintable(QString::number(w->fieldsDock()->width())));
        QVERIFY2(w->lastError().contains("could not be read"), qPrintable(w->lastError()));
        QVERIFY(w->tryOpen(data("mosfet_2d.npz")));  // and the window works
    }

    void savedLayoutOfAnotherVersionIsIgnored() {
        const QString path = ini("future_layout.ini");
        QByteArray moved;
        {
            auto w = shown(path);
            QVERIFY(w);
            w->dockManager()->addDockWidget(ads::RightDockWidgetArea, w->fieldsDock());
            QApplication::processEvents();
            moved = w->dockManager()->saveState();
            w->close();
        }
        {
            QSettings s(path, QSettings::IniFormat);
            s.setValue("layout/version", AppSettings::kLayoutVersion + 98);
        }
        auto w2 = shown(path);
        QVERIFY(w2);
        QVERIFY(sameStructure(w2->dockManager()->saveState(), w2->defaultLayout()));
        QVERIFY(w2->lastError().isEmpty());  // not an error: just not ours
    }

    void readOnlySettingsStillRun() {
        const QString path = ini("readonly.ini");
        {
            QSettings s(path, QSettings::IniFormat);
            s.setValue("recent/files", QStringList());
        }
        QVERIFY(QFile::setPermissions(path, QFile::ReadOwner | QFile::ReadUser));
        {
            auto w = shown(path);
            QVERIFY(w);
            QVERIFY2(w->statusBar()->currentMessage().contains("read-only"),
                     qPrintable(w->statusBar()->currentMessage()));
            QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
            w->close();  // saving fails quietly; no crash
        }
        QVERIFY(QFile::setPermissions(path, QFile::ReadOwner | QFile::WriteOwner | QFile::ReadUser | QFile::WriteUser));
    }

    // -- docking with a live GL view -----------------------------------------
    void floatAndRedockKeepsTheViewRendering() {
        auto w = shown(ini("float.ini"));
        QVERIFY(w);
        QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
        w->fieldView()->renderNow();
        QVERIFY(distinctColours(w->fieldView()) > 10);

        QElapsedTimer t;
        t.start();
        w->fieldsDock()->setFloating();
        QApplication::processEvents();
        QVERIFY(w->fieldsDock()->isFloating());
        w->dockManager()->addDockWidget(ads::LeftDockWidgetArea, w->fieldsDock());
        QApplication::processEvents();
        qInfo("float + re-dock: %.1f ms", static_cast<double>(t.nsecsElapsed()) / 1e6);
        QVERIFY(!w->fieldsDock()->isFloating());

        w->fieldView()->renderNow();
        QVERIFY2(distinctColours(w->fieldView()) > 10, "the view no longer renders after float + re-dock");
    }

    // -- info panel (S3d) ----------------------------------------------------
    void infoPanelDescribesTheOpenResult() {
        auto w = shown(ini("info.ini"));
        QVERIFY(w);
        auto* info = w->infoPanel();
        QVERIFY(w->infoDock()->isVisible() || !w->infoDock()->isClosed());
        QCOMPARE(info->topLevelItemCount(), 0);  // nothing open yet

        QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
        const auto* m = w->result();
        QCOMPARE(info->value("Mesh", "Dimensionality"), QString("2D"));
        const auto n = m->node_counts();
        QVERIFY2(info->value("Mesh", "Nodes").endsWith(QLocale::c().toString(static_cast<qulonglong>(n[0] * n[1]))),
                 qPrintable(info->value("Mesh", "Nodes")));
        QCOMPARE(info->value("File", "Schema"), QString::number(m->schema_version()));
        QCOMPARE(info->value("Run", "Bias solved"), m->solved_bias() ? QString("yes") : QString("no (equilibrium only)"));
        QVERIFY(m->record());
        QCOMPARE(info->value("Run", "backend"), QString::fromStdString((*m->record())["backend"].get<std::string>()));
        for (const auto& name : m->scalar_names())
            QCOMPARE(info->value("Fields", QString::fromStdString(name)), QString::fromStdString(m->scalar(name).unit));
        QVERIFY(!m->terminal_names().empty());
        for (const auto& name : m->terminal_names()) {
            const auto t = m->terminal(name);
            QCOMPARE(info->value("Terminals", QString::fromStdString(name)),
                     QString("%1 %2").arg(t.value, 0, 'e', 4).arg(QString::fromStdString(t.unit)));
        }

        // a second result replaces the description; a failed open keeps it
        QVERIFY(w->tryOpen(data("resistor_3d.npz")));
        QCOMPARE(info->value("Mesh", "Dimensionality"), QString("3D"));
        QVERIFY(!info->value("Mesh", "z range").isEmpty());
        QVERIFY(!w->tryOpen(data("corrupt.npz")));
        QCOMPARE(info->value("Mesh", "Dimensionality"), QString("3D"));
    }

    // -- S5: 2D map parity (NATIVE-DESKTOP-PLAN.md 15.17) ----------------------
    void fieldListSeparatesDerivedMaps() {
        auto w = shown(ini("s5_list.ini"));
        QVERIFY(w);
        QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
        QCOMPARE(fieldRows(w.get()).size(), static_cast<qsizetype>(w->result()->scalar_names().size()));
        for (const char* n : {"Ec", "Ev", "EFn", "EFp", "R"}) {
            QListWidgetItem* it = derivedItem(w.get(), n);
            QVERIFY2(it, n);
            QVERIFY(it->flags() & Qt::ItemIsEnabled);
        }
        QVERIFY(w->displayDock());
        w->resetLayout();  // Display is tabbed with Info
        QApplication::processEvents();
        QCOMPARE(w->displayDock()->dockAreaWidget(), w->infoDock()->dockAreaWidget());
    }

    void derivedEntryNeedsItsFields() {
        auto w = shown(ini("s5_missing.ini"));
        QVERIFY(w);
        QVERIFY(w->tryOpen(data("mosfet_no_doping.npz")));
        QListWidgetItem* r = derivedItem(w.get(), "R");
        QVERIFY(r);
        QVERIFY(!(r->flags() & Qt::ItemIsEnabled));
        QVERIFY2(r->toolTip().contains("doping"), qPrintable(r->toolTip()));
        QVERIFY(derivedItem(w.get(), "Ec")->flags() & Qt::ItemIsEnabled);  // bands need no doping
    }

    void bandsAndRecombinationComeFromTheBackend() {
        using tcad::desktop::ColorMap;
        using tcad::desktop::FieldKind;
        auto w = shown(ini("s5_derived.ini"));
        QVERIFY(w);
        QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
        FieldView* v = w->fieldView();

        selectItem(w.get(), derivedItem(w.get(), "Ec"));
        QTRY_VERIFY_WITH_TIMEOUT(v->field() == "Ec", 120000);
        QVERIFY(v->fieldSource() != w->result() && v->fieldSource() == w->derivedModel("bands"));
        QVERIFY(v->fieldKind() == FieldKind::Band);
        QVERIFY(v->colorMap() == ColorMap::Viridis);
        v->setLogScale(true);
        QVERIFY(!v->logEffective());  // the QML bands view ignores log
        QCOMPARE(QString::fromUtf8(v->barTitle()->GetInput()), QString("Ec [eV]"));
        v->setLogScale(false);
        QString readout;
        QVERIFY(v->readoutAt(v->width() * 0.3, v->height() / 2.0, &readout));
        QVERIFY2(readout.startsWith("Ec: ") && readout.contains(" eV @ "), qPrintable(readout));
        QVERIFY2(readoutIsRawNodeValue(v, readout), qPrintable(readout));

        // a second band entry reuses the fetched maps: no new backend call
        selectItem(w.get(), derivedItem(w.get(), "Ev"));
        QCOMPARE(QString::fromStdString(v->field()), QString("Ev"));

        selectItem(w.get(), derivedItem(w.get(), "R"));
        QTRY_VERIFY_WITH_TIMEOUT(v->field() == "R", 120000);
        QVERIFY(v->fieldKind() == FieldKind::Recombination);
        QVERIFY(v->colorMap() == ColorMap::Inferno);
        QVERIFY(v->logEffective());  // always log, as the QML view draws R
        QVERIFY(QString::fromUtf8(v->barTitle()->GetInput()).startsWith("log10 |R|"));
        // drawn as log10|R|, read out as R itself
        QVERIFY(v->readoutAt(v->width() * 0.3, v->height() / 2.0, &readout));
        QVERIFY2(readout.startsWith("R: ") && readoutIsRawNodeValue(v, readout), qPrintable(readout));

        // back to a field of the result itself
        selectField(w.get(), "potential");
        QCOMPARE(QString::fromStdString(v->field()), QString("potential"));
        QVERIFY(v->fieldSource() == w->result());
    }

    void backendWarmsUpAfterA2DResultOpens() {
        auto w = shown(ini("s5_warm.ini"));
        QVERIFY(w);
        QVERIFY(!w->backendClient());  // nothing before a result: no Python for nothing
        QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
        QTRY_VERIFY_WITH_TIMEOUT(w->backendClient() != nullptr, 5000);
        QTRY_VERIFY_WITH_TIMEOUT(w->backendClient()->state() == tcad::desktop::BackendClient::State::Ready, 60000);
    }

    // A window closed while a backend call is in flight: the client's
    // shutdown fails the pending replies, and their handlers must not run
    // into the half-destroyed window (P2-S3 found this crash; it matches
    // P1's unexplained shell crash, plan 16.10 -- a warmup still pending
    // when a test's window closed under load).
    void windowClosesWhileABackendCallIsInFlight() {
        {
            auto w = shown(ini("inflight_warmup.ini"));
            QVERIFY(w);
            QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
            QTRY_VERIFY_WITH_TIMEOUT(w->backendClient() != nullptr, 5000);  // the warmup was sent
            QVERIFY(w->backendClient()->state() != tcad::desktop::BackendClient::State::Ready);
        }  // closed with system.warmup pending
        {
            auto w = shown(ini("inflight_map.ini"));
            QVERIFY(w);
            QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
            selectItem(w.get(), derivedItem(w.get(), "Ec"));  // analysis.band_map pending
            QVERIFY(w->backendClient() != nullptr);
        }
        QVERIFY(errorBoxes().isEmpty());  // nothing reported from a closed window
    }

    void backendFailureIsNamedAndTheViewStays() {
        // The client is created on the first derived request, so the bad
        // interpreter must still be configured when the entry is clicked.
        qputenv("TCAD_BACKEND_PYTHON", "C:/no/such/python.exe");
        auto w = shown(ini("s5_nobackend.ini"));
        QVERIFY(w);
        QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
        const std::string before = w->fieldView()->field();
        selectItem(w.get(), derivedItem(w.get(), "Ec"));
        QTRY_VERIFY_WITH_TIMEOUT(w->lastError().contains("does not exist"), 10000);
        qunsetenv("TCAD_BACKEND_PYTHON");
        QCOMPARE(w->fieldView()->field(), before);
    }

    void dopingGetsTheSignedMap() {
        using tcad::desktop::ColorMap;
        auto w = shown(ini("s5_doping.ini"));
        QVERIFY(w);
        QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
        FieldView* v = w->fieldView();
        selectField(w.get(), "doping");
        QVERIFY(v->colorMap() == ColorMap::RdBuR);
        QCOMPARE(v->normRange()[0], -v->normRange()[1]);  // symmetric about zero
        v->setLogScale(true);
        QCOMPARE(v->displayTransform(1e17), 17.0);
        QCOMPARE(v->displayTransform(-1e17), -17.0);
        QCOMPARE(v->displayTransform(0.5), 0.0);
        QVERIFY(QString::fromUtf8(v->barTitle()->GetInput()).startsWith("sign(N) log10"));
        QString readout;  // the readout stays raw
        QVERIFY(v->readoutAt(v->width() * 0.3, v->height() / 2.0, &readout));
        QVERIFY2(readout.contains("cm^-3") && !readout.contains("log"), qPrintable(readout));
        v->setLogScale(false);
    }

    void displayPanelDrivesTheView() {
        using tcad::desktop::ColorMap;
        auto w = shown(ini("s5_panel.ini"));
        QVERIFY(w);
        QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
        FieldView* v = w->fieldView();
        selectField(w.get(), "potential");
        w->displayDock()->toggleView(true);
        auto* cmap = w->findChild<QComboBox*>("ColorMapCombo");
        auto* logc = w->findChild<QCheckBox*>("LogCheck");
        auto* cont = w->findChild<QCheckBox*>("ContoursCheck");
        auto* mesh = w->findChild<QCheckBox*>("MeshCheck");
        auto* manual = w->findChild<QRadioButton*>("RangeManual");
        auto* autor = w->findChild<QRadioButton*>("RangeAuto");
        auto* lo = w->findChild<QLineEdit*>("RangeMin");
        auto* hi = w->findChild<QLineEdit*>("RangeMax");
        auto* lock = w->findChild<QCheckBox*>("RangeLock");
        QVERIFY(cmap && logc && cont && mesh && manual && autor && lo && hi && lock);

        cmap->setCurrentIndex(cmap->findData("plasma"));
        QVERIFY(v->colorMap() == ColorMap::Plasma);
        cmap->setCurrentIndex(0);  // Auto
        QVERIFY(v->colorMap() == ColorMap::Viridis && !v->colorMapOverride());

        cont->setChecked(true);
        QVERIFY(v->contours() && !v->contourLevels().empty());
        mesh->setChecked(true);
        QVERIFY(v->meshLines() && v->meshActor()->GetVisibility());
        cont->setChecked(false);
        mesh->setChecked(false);

        // the panel's log box and the toolbar's action agree
        QAction* log = nullptr;
        for (QAction* a : w->findChildren<QAction*>())
            if (a->text() == "Log scale") log = a;
        logc->setChecked(true);
        QVERIFY(v->logScale() && log->isChecked());
        log->trigger();
        QVERIFY(!v->logScale() && !logc->isChecked());

        // manual range, unlocked: per field
        manual->setChecked(true);
        lo->setText("-0.25");
        hi->setText("0.5");
        emit lo->editingFinished();
        QCOMPARE(v->normRange()[0], -0.25);
        QCOMPARE(v->normRange()[1], 0.5);
        QVERIFY(v->colorRange().manual && !v->colorRange().locked);
        selectField(w.get(), "electron_density");
        QVERIFY(!v->colorRange().manual);
        QVERIFY(autor->isChecked());

        // locked: kept across a switch
        manual->setChecked(true);
        lo->setText("1e5");
        hi->setText("1e18");
        lock->setChecked(true);
        QVERIFY(v->colorRange().manual && v->colorRange().locked);
        selectField(w.get(), "hole_density");
        QCOMPARE(v->normRange()[0], 1e5);
        QCOMPARE(v->normRange()[1], 1e18);
        autor->setChecked(true);
        QVERIFY(!v->colorRange().manual);
    }

    void overlaysAreDisabledIn3D() {
        auto w = shown(ini("s5_3d.ini"));
        QVERIFY(w);
        QVERIFY(w->tryOpen(data("resistor_3d.npz")));
        QVERIFY(!w->findChild<QCheckBox*>("ContoursCheck")->isEnabled());
        QVERIFY(!w->findChild<QCheckBox*>("MeshCheck")->isEnabled());
        QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
        QVERIFY(w->findChild<QCheckBox*>("ContoursCheck")->isEnabled());
    }

    // -- S6: 3D parity with viewer3d.py (section 15.19), one test per item ----
    // layers3d.npz: a synthetic 3D result with a current density, a 5-point
    // sweep with snapshots, and two structure regions (run_bench._layers_3d).
    void view3dPanelIsDisabledIn2D() {
        auto w = shown(ini("s6_2d.ini"));
        QVERIFY(w);
        QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
        QVERIFY(!w->view3dPanel()->isEnabled());
        QVERIFY(!w->playbackPanel()->isEnabled());
        QVERIFY(w->tryOpen(data("layers3d.npz")));
        QVERIFY(w->view3dPanel()->isEnabled());
        QVERIFY(w->playbackPanel()->isEnabled());
        QVERIFY(w->tryOpen(data("resistor_3d.npz")));  // 3D, no sweep: panel yes, playback no
        QVERIFY(w->view3dPanel()->isEnabled());
        QVERIFY(!w->playbackPanel()->isEnabled());
    }

    void slicesShowNodePlanes() {
        auto w = shown(ini("s6_slice.ini"));
        QVERIFY(w && w->tryOpen(data("layers3d.npz")));
        FieldView* v = w->fieldView();
        auto* on = child<QCheckBox>(w->view3dPanel(), "SliceZ");
        auto* at = child<QSlider>(w->view3dPanel(), "SliceZIndex");
        auto* label = child<QLabel>(w->view3dPanel(), "SliceZLabel");
        QVERIFY(on && at && label);
        at->setValue(3);
        on->setChecked(true);
        QVERIFY(v->slice(2).on && v->slice(2).index == 3);
        QVERIFY(v->sliceActor(2)->GetVisibility());
        QCOMPARE(label->text(), QString("%1 um").arg(v->axisUm(2)[3], 0, 'f', 3));
        QVERIFY(v->surfaceMode() == SurfaceMode::Context);  // an interior layer: the surface steps back
        // every patch of the slice is a node of plane k = 3
        vtkIdTypeArray* ids = v->sliceNodeIds(2);
        const auto n = w->result()->node_counts();
        QCOMPARE(static_cast<std::size_t>(ids->GetNumberOfValues()), n[0] * n[1]);
        for (vtkIdType c = 0; c < ids->GetNumberOfValues(); ++c)
            QCOMPARE(static_cast<std::size_t>(ids->GetValue(c)) / (n[0] * n[1]), std::size_t{3});
        at->setValue(5);
        QCOMPARE(v->slice(2).index, std::size_t{5});
        on->setChecked(false);
        QVERIFY(!v->sliceActor(2)->GetVisibility());
    }

    void centralZPlaneMatchesTheQmlView() {
        auto w = shown(ini("s6_central.ini"));
        QVERIFY(w && w->tryOpen(data("layers3d.npz")));
        FieldView* v = w->fieldView();
        auto* button = child<QPushButton>(w->view3dPanel(), "CentralZPlane");
        QVERIFY(button);
        button->click();
        const auto n = w->result()->node_counts();
        QVERIFY(v->slice(2).on);
        QCOMPARE(v->slice(2).index, n[2] / 2);  // mpl_canvas_item: values[shape[0] // 2]
        QVERIFY(v->surfaceMode() == SurfaceMode::Hidden);
        double dir[3];
        v->renderer()->GetActiveCamera()->GetDirectionOfProjection(dir);
        QVERIFY(dir[2] > 0.999);  // looking along +z, as the 2D map does
        // the pointer at the centre names a node of that plane, with its raw value
        QString readout;
        QVERIFY(v->readoutAt(v->width() * 0.4, v->height() / 2.0, &readout));
        QVERIFY2(readout.contains(QString("z=%1 um").arg(v->axisUm(2)[n[2] / 2], 0, 'f', 2)), qPrintable(readout));
    }

    void clippingCropsTheBox() {
        auto w = shown(ini("s6_crop.ini"));
        QVERIFY(w && w->tryOpen(data("layers3d.npz")));
        FieldView* v = w->fieldView();
        auto* xmin = child<QSpinBox>(w->view3dPanel(), "CropXMin");
        auto* zmax = child<QSpinBox>(w->view3dPanel(), "CropZMax");
        QVERIFY(xmin && zmax);
        xmin->setValue(5);
        zmax->setValue(6);
        QCOMPARE(v->crop().lo[0], std::size_t{5});
        QCOMPARE(v->crop().hi[2], std::size_t{6});
        double b[6];
        v->displayedGeometry()->GetBounds(b);
        QCOMPARE(b[0], v->edgesUm(0)[5]);  // the crop's patch edges
        QCOMPARE(b[5], v->edgesUm(2)[7]);
        child<QPushButton>(w->view3dPanel(), "CropReset")->click();
        QVERIFY(v->crop() == v->fullBox());
    }

    void isosurfaceFollowsTheLevel() {
        auto w = shown(ini("s6_iso.ini"));
        QVERIFY(w && w->tryOpen(data("layers3d.npz")));
        FieldView* v = w->fieldView();
        selectField(w.get(), "potential");
        auto* on = child<QCheckBox>(w->view3dPanel(), "IsoCheck");
        auto* level = child<QDoubleSpinBox>(w->view3dPanel(), "IsoLevel");
        QVERIFY(on && level);
        on->setChecked(true);
        QVERIFY(v->isosurface() && v->isoActor()->GetVisibility());
        const auto r = v->dataRange();
        QCOMPARE(v->isoLevel(), 0.5 * (r[0] + r[1]));  // viewer3d.py's default: the midpoint
        const vtkIdType before = v->isoPoly()->GetNumberOfPoints();
        QVERIFY(before > 0);
        level->setValue(r[0] + 0.2 * (r[1] - r[0]));
        QCOMPARE(v->isoLevel(), level->value());
        QVERIFY(v->isoPoly()->GetNumberOfPoints() > 0);
        // coloured as its level reads on the bar
        double want[3], got[3];
        v->lookupTable()->GetColor(lut_input(v->isoLevel(), v->normRange()[0], v->normRange()[1]), want);
        v->isoActor()->GetProperty()->GetColor(got);
        for (int c = 0; c < 3; ++c) QCOMPARE(got[c], want[c]);
        // a field change re-centres the level (viewer3d.py)
        selectField(w.get(), "electron_density");
        QCOMPARE(v->isoLevel(), 0.5 * (v->dataRange()[0] + v->dataRange()[1]));
        on->setChecked(false);
        QVERIFY(!v->isoActor()->GetVisibility());
    }

    void colourMapsApplyIn3D() {
        auto w = shown(ini("s6_cmap.ini"));
        QVERIFY(w && w->tryOpen(data("layers3d.npz")));
        FieldView* v = w->fieldView();
        auto* cmap = child<QComboBox>(w->displayPanel(), "ColorMapCombo");
        QVERIFY(cmap);
        cmap->setCurrentIndex(cmap->findData("plasma"));
        QVERIFY(v->colorMap() == ColorMap::Plasma);
        vtkNew<vtkLookupTable> ref;  // matplotlib's plasma, as the view fills it
        tcad::desktop::fill_lut(ref, ColorMap::Plasma);
        for (vtkIdType q = 0; q < ref->GetNumberOfTableValues(); ++q) {
            double got[4], want[4];
            v->lookupTable()->GetTableValue(q, got);
            ref->GetTableValue(q, want);
            for (int c = 0; c < 4; ++c) QCOMPARE(got[c], want[c]);
        }
        // a slice uses the same table
        child<QCheckBox>(w->view3dPanel(), "SliceX")->setChecked(true);
        QVERIFY(v->sliceActor(0)->GetMapper()->GetLookupTable() == v->lookupTable());
    }

    void volumeRenderingPresets() {
        auto w = shown(ini("s6_volume.ini"));
        QVERIFY(w && w->tryOpen(data("layers3d.npz")));
        FieldView* v = w->fieldView();
        auto* on = child<QCheckBox>(w->view3dPanel(), "VolumeCheck");
        auto* preset = child<QComboBox>(w->view3dPanel(), "VolumePreset");
        QVERIFY(on && preset);
        on->setChecked(true);
        QVERIFY(v->volume() && v->volumeProp()->GetVisibility());
        for (VolumePreset p : {VolumePreset::Linear, VolumePreset::LogHigh, VolumePreset::LogLow, VolumePreset::Threshold}) {
            preset->setCurrentIndex(preset->findData(static_cast<int>(p)));
            QVERIFY(v->volumePreset() == p);
            QVERIFY(v->colorMap() == volumePresetSpec(p).map);  // the bar describes the volume
            QCOMPARE(v->volumeProp()->GetProperty()->GetScalarOpacity()->GetValue(0.5), volumePresetSpec(p).opacity);
            const auto name = colorMapName(volumePresetSpec(p).map);
            QCOMPARE(child<QComboBox>(w->displayPanel(), "ColorMapCombo")->currentData().toString(),
                     QString::fromUtf8(name.data(), static_cast<qsizetype>(name.size())));
        }
        on->setChecked(false);
        QVERIFY(!v->volumeProp()->GetVisibility());
    }

    void glyphsFollowTheCurrent() {
        auto w = shown(ini("s6_glyphs.ini"));
        QVERIFY(w && w->tryOpen(data("layers3d.npz")));
        FieldView* v = w->fieldView();
        auto* on = child<QCheckBox>(w->view3dPanel(), "GlyphCheck");
        auto* spacing = child<QDoubleSpinBox>(w->view3dPanel(), "GlyphSpacing");
        QVERIFY(on && spacing && child<QComboBox>(w->view3dPanel(), "VectorField")->currentText() == "current_density");
        on->setChecked(true);
        QVERIFY(v->glyphActor()->GetVisibility() && v->vectorBar()->GetVisibility());
        const vtkIdType dense = v->glyphSources()->GetNumberOfPoints();
        spacing->setValue(0.2);
        const vtkIdType sparse = v->glyphSources()->GetNumberOfPoints();
        QVERIFY2(sparse > 0 && sparse < dense, qPrintable(QString("%1 -> %2").arg(dense).arg(sparse)));
        on->setChecked(false);
        QVERIFY(!v->glyphActor()->GetVisibility() && !v->vectorBar()->GetVisibility());
        // no vector field: the controls say why
        QVERIFY(w->tryOpen(data("mosfet_no_doping.npz")));  // 2D: the whole panel is off
        QVERIFY(!w->view3dPanel()->isEnabled());
    }

    void streamlinesTraceTheCurrent() {
        auto w = shown(ini("s6_stream.ini"));
        QVERIFY(w && w->tryOpen(data("layers3d.npz")));
        FieldView* v = w->fieldView();
        auto* on = child<QCheckBox>(w->view3dPanel(), "StreamlineCheck");
        QVERIFY(on);
        on->setChecked(true);
        QVERIFY(v->streamlineActor()->GetVisibility() && v->streamlinePoly()->GetNumberOfPoints() > 0);
        QVERIFY(v->vectorBar()->GetVisibility());
        const vtkIdType pts = v->streamlinePoly()->GetNumberOfPoints();
        on->setChecked(false);
        on->setChecked(true);  // fixed seeds: the same lines again
        QCOMPARE(v->streamlinePoly()->GetNumberOfPoints(), pts);
        on->setChecked(false);
        QVERIFY(!v->streamlineActor()->GetVisibility());
        // the note: vectors are not recomputed per snapshot
        QVERIFY(!child<QLabel>(w->view3dPanel(), "VectorNote")->text().isEmpty());
    }

    void explodedViewSeparatesRegions() {
        auto w = shown(ini("s6_exploded.ini"));
        QVERIFY(w && w->tryOpen(data("layers3d.npz")));
        FieldView* v = w->fieldView();
        auto* on = child<QCheckBox>(w->view3dPanel(), "ExplodedCheck");
        auto* sep = child<QDoubleSpinBox>(w->view3dPanel(), "ExplodedSeparation");
        QVERIFY(on && sep && on->isEnabled());
        QCOMPARE(v->explodedSeparation(), 0.15 * v->diagonalUm());  // viewer3d.py's default
        on->setChecked(true);
        QCOMPARE(v->explodedRegions().size(), std::size_t{2});
        QVERIFY(!v->fieldActor()->GetVisibility());  // the regions replace the surface
        sep->setValue(2 * v->diagonalUm());
        QCOMPARE(v->explodedRegions()[1].offset_um, sep->value());
        on->setChecked(false);
        QVERIFY(v->fieldActor()->GetVisibility());
        // a result without regions: disabled, and says why
        QVERIFY(w->tryOpen(data("resistor_3d.npz")));
        QVERIFY(!on->isEnabled());
        QVERIFY2(on->toolTip().contains("no regions"), qPrintable(on->toolTip()));
    }

    void resetLayoutAndSweepsKeepTheGlContext() {
        // Docking next to the view's own area reparents the GL widget and
        // recreates its context (S6 bench: every Reset layout did). Opening
        // a sweep shows the Playback dock; neither may touch the view.
        auto w = shown(ini("s6_gl.ini"));
        QVERIFY(w && w->tryOpen(data("mosfet_2d.npz")));
        const int before = w->fieldView()->glInitializations();
        QVERIFY(w->tryOpen(data("layers3d.npz")));  // shows Playback
        QVERIFY(!w->playbackDock()->isClosed());
        w->resetLayout();
        QApplication::processEvents();
        w->resetLayout();
        QApplication::processEvents();
        QCOMPARE(w->fieldView()->glInitializations(), before);
        QVERIFY(w->fieldsDock()->width() >= 150);
    }

    void playbackStepsThroughSnapshots() {
        auto w = shown(ini("s6_playback.ini"));
        QVERIFY(w && w->tryOpen(data("layers3d.npz")));
        FieldView* v = w->fieldView();
        QVERIFY(w->playbackDock()->isVisible() || !w->playbackDock()->isClosed());
        selectField(w.get(), "potential");
        auto* fwd = child<QPushButton>(w->playbackPanel(), "PlaybackForward");
        auto* back = child<QPushButton>(w->playbackPanel(), "PlaybackBack");
        auto* play = child<QPushButton>(w->playbackPanel(), "PlaybackPlay");
        auto* result = child<QPushButton>(w->playbackPanel(), "PlaybackResult");
        auto* label = child<QLabel>(w->playbackPanel(), "PlaybackLabel");
        QVERIFY(fwd && back && play && result && label);
        fwd->click();
        QCOMPARE(v->snapshot().value_or(99), std::size_t{0});
        fwd->click();
        QCOMPARE(v->snapshot().value_or(99), std::size_t{1});
        QVERIFY2(label->text().startsWith("0.100 V"), qPrintable(label->text()));
        // the hover reads the SNAPSHOT's raw value
        const SweepSnapshots snaps = w->result()->sweep_snapshots();
        const std::vector<double> s1 = w->result()->snapshot_field(snaps, "potential", 1);
        const auto n = w->result()->node_counts();
        QString readout;
        QVERIFY(v->readoutAt(v->width() * 0.4, v->height() / 2.0, &readout));
        bool found = false;
        for (std::size_t q = 0; q < s1.size() && !found; ++q)
            found = readout.startsWith(QString::asprintf("potential: %.3e ", s1[q]));
        QVERIFY2(found, qPrintable(readout));
        (void)n;
        back->click();
        QCOMPARE(v->snapshot().value_or(99), std::size_t{0});
        play->click();
        QVERIFY(w->playbackPanel()->playing());
        QTRY_VERIFY_WITH_TIMEOUT(v->snapshot().value_or(0) >= 2, 5000);
        play->click();
        QVERIFY(!w->playbackPanel()->playing());
        result->click();
        QVERIFY(!v->snapshot());
        QVERIFY2(label->text().startsWith("result"), qPrintable(label->text()));
    }

    // -- S8b: the result file deleted or replaced while it is open ------------
    // Everything already read keeps working from memory; anything the
    // backend would compute from the FILE is refused with a named reason.
    void deletedResultKeepsWorkingFromMemory() {
        auto w = shown(ini("s8_deleted.ini"));
        QVERIFY(w);
        const QString path = tmp_.filePath("to_delete.npz");
        QFile::remove(path);
        QVERIFY(QFile::copy(data("layers3d.npz"), path));
        QVERIFY(w->tryOpen(path));
        FieldView* v = w->fieldView();
        QVERIFY(QFile::remove(path));
        selectField(w.get(), "electron_density");  // from memory
        QCOMPARE(QString::fromStdString(v->field()), QString("electron_density"));
        QString readout;
        QVERIFY(v->readoutAt(v->width() * 0.4, v->height() / 2.0, &readout));
        v->setSnapshot(std::size_t{2});  // the snapshots were read at open too
        QVERIFY(v->showingSnapshot());
        v->setSnapshot(std::nullopt);
        // the backend would read the file: a derived map (the MOSFET has the
        // fields bands need) is refused, named, and the view stays
        const QString mos = tmp_.filePath("to_delete_2d.npz");
        QFile::remove(mos);
        QVERIFY(QFile::copy(data("mosfet_2d.npz"), mos));
        QVERIFY(w->tryOpen(mos));
        QVERIFY(QFile::remove(mos));
        const std::string before = v->field();
        QListWidgetItem* ec = derivedItem(w.get(), "Ec");
        QVERIFY(ec && (ec->flags() & Qt::ItemIsEnabled));
        selectItem(w.get(), ec);
        QVERIFY2(w->lastError().contains("deleted"), qPrintable(w->lastError()));
        QCOMPARE(v->field(), before);
        QVERIFY(!w->derivedModel("bands"));
    }

    void replacedResultIsNotMixedWithTheShownOne() {
        auto w = shown(ini("s8_replaced.ini"));
        QVERIFY(w);
        const QString path = tmp_.filePath("to_replace.npz");
        QFile::remove(path);
        QVERIFY(QFile::copy(data("mosfet_2d.npz"), path));
        QVERIFY(w->tryOpen(path));
        // the same mesh, other contents: a map computed now would be silently wrong
        QVERIFY(QFile::remove(path));
        QVERIFY(QFile::copy(data("mosfet_no_doping.npz"), path));
        selectItem(w.get(), derivedItem(w.get(), "Ec"));
        QVERIFY2(w->lastError().contains("changed on disk"), qPrintable(w->lastError()));
        QVERIFY(!w->derivedModel("bands"));  // nothing was fetched
        // reopening takes the new file, and maps work again
        QVERIFY(w->tryOpen(path));
        QVERIFY(w->derivedModel("bands") == nullptr);
    }

    // -- S8e: the section 15.5 end-to-end scenario, as ONE test with synthesized
    // input (QTest mouse, key and drop events on the real widgets). The
    // exceptions: file dialogs (bypassed through the methods they call, as
    // the S3 tests do), the native title bar of a floating dock, and menu
    // navigation (their QActions are triggered). Result export was removed
    // from the app (2026-09-26), so the scenario ends at playback.
    void endToEndScenarioWithSynthesizedInput() {
        const QString settings = ini("e2e.ini");
        QByteArray saved_layout;
        int gl_inits = 0;
        {
            auto w = shown(settings);
            QVERIFY(w);
            w->activateWindow();
            QVERIFY(QTest::qWaitForWindowActive(w.get()));
            FieldView* v = w->fieldView();
            // open: a drop
            drop(w.get(), {QUrl::fromLocalFile(data("mosfet_2d.npz"))});
            QTRY_VERIFY(w->result() != nullptr);
            gl_inits = v->glInitializations();
            // select a field: a click in the list
            selectField(w.get(), "electron_density");
            QCOMPARE(QString::fromStdString(v->field()), QString("electron_density"));
            // log on: a click on the toolbar button
            auto* bar = w->findChild<QToolBar*>("MainToolBar");
            QAction* log = nullptr;
            for (QAction* a : bar->actions())
                if (a->text() == "Log scale") log = a;
            QVERIFY(log && bar->widgetForAction(log));
            QTest::mouseClick(bar->widgetForAction(log), Qt::LeftButton);
            QVERIFY(v->logScale());
            // hover: a mouse move over the view names a node in the status bar
            auto* readout = w->findChild<QLabel*>("Readout");
            // (sent to the view: QTest::mouseMove also moves the REAL cursor on
            // Windows, so the move went to whichever window was on top there --
            // S8h found it failing 19 times in 20 with another app on screen)
            const QPoint at(v->width() * 2 / 5, v->height() / 2);
            QMouseEvent move(QEvent::MouseMove, at, v->mapToGlobal(at), Qt::NoButton, Qt::NoButton, Qt::NoModifier);
            QApplication::sendEvent(v, &move);
            QTRY_VERIFY(readout->text().startsWith("electron_density: "));
            // Fit: zoom away, then the F key
            vtkCamera* cam = v->renderer()->GetActiveCamera();
            const double fitted = cam->GetParallelScale();
            cam->Zoom(2.5);
            QTest::keyClick(w.get(), Qt::Key_F);
            QCOMPARE(cam->GetParallelScale(), fitted);
            // dock: float the Fields panel with a double-click on its tab ...
            QTest::mouseDClick(w->fieldsDock()->tabWidget(), Qt::LeftButton);
            QTRY_VERIFY(w->fieldsDock()->isFloating());
            // ... and back (a floating window's title bar is native: the menu's Reset layout)
            for (QAction* a : w->findChildren<QAction*>())
                if (a->text() == "Reset layout") a->trigger();
            QTRY_VERIFY(!w->fieldsDock()->isFloating());
            QCOMPARE(v->glInitializations(), gl_inits);  // the view survived it all
            saved_layout = w->dockManager()->saveState();
            // quit
            w->close();
        }
        // reopen: the layout and the recent file are back
        auto w = shown(settings);
        QVERIFY(w);
        QVERIFY(sameStructure(w->dockManager()->saveState(), saved_layout));
        QCOMPARE(QFileInfo(w->settings().recentFiles().value(0)).fileName(), QString("mosfet_2d.npz"));
        FieldView* v = w->fieldView();
        // a 3D sweep: drop it, open the 3D tab, turn the isosurface on with a click
        drop(w.get(), {QUrl::fromLocalFile(data("layers3d.npz"))});
        QTRY_VERIFY(w->result() && w->result()->dimensionality() == 3);
        QTest::mouseClick(w->view3dDock()->tabWidget(), Qt::LeftButton);
        QTRY_VERIFY(w->view3dPanel()->isVisible());
        auto* iso = child<QCheckBox>(w->view3dPanel(), "IsoCheck");
        QTest::mouseClick(iso, Qt::LeftButton, {}, iso->rect().center());
        QVERIFY(v->isosurface());
        // play, step, pause -- the playback buttons
        QTRY_VERIFY(w->playbackPanel()->isVisible());
        auto* fwd = child<QPushButton>(w->playbackPanel(), "PlaybackForward");
        auto* play = child<QPushButton>(w->playbackPanel(), "PlaybackPlay");
        QTest::mouseClick(fwd, Qt::LeftButton);
        QCOMPARE(v->snapshot().value_or(99), std::size_t{0});
        QTest::mouseClick(play, Qt::LeftButton);
        QTRY_VERIFY_WITH_TIMEOUT(v->snapshot().value_or(0) >= 2, 5000);
        QTest::mouseClick(play, Qt::LeftButton);
        QVERIFY(!w->playbackPanel()->playing());
    }

    // -- S8f: the 2D parity checklist, one named test per item (15.17) --------
    void parity2dFieldLinear() {
        auto w = mosfet("p_linear.ini");
        QVERIFY(w);
        FieldView* v = w->fieldView();
        selectField(w.get(), "potential");
        v->setLogScale(false);
        QVERIFY(displayedIs(v, [](double x) { return x; }));
        QVERIFY(v->colorMap() == ColorMap::Viridis);
        QCOMPARE(QString::fromUtf8(v->barTitle()->GetInput()), QString("potential [V]"));
    }

    void parity2dFieldLog() {
        auto w = mosfet("p_log.ini");
        QVERIFY(w);
        FieldView* v = w->fieldView();
        selectField(w.get(), "electron_density");
        v->setLogScale(true);
        QVERIFY(displayedIs(v, [](double x) { return std::log10(std::max(std::abs(x), 1e-30)); }));
        QCOMPARE(QString::fromUtf8(v->barTitle()->GetInput()), QString("log10 |electron_density [cm^-3]|"));
    }

    void parity2dBandsEcEvEFnEFp() {
        auto w = mosfet("p_bands.ini");
        QVERIFY(w);
        FieldView* v = w->fieldView();
        for (const char* band : {"Ec", "Ev", "EFn", "EFp"}) {
            selectItem(w.get(), derivedItem(w.get(), band));
            QTRY_VERIFY_WITH_TIMEOUT(v->field() == band, 120000);
            QVERIFY(v->fieldSource() == w->derivedModel("bands"));
            v->setLogScale(true);  // the QML bands view ignores log
            QVERIFY(!v->logEffective() && displayedIs(v, [](double x) { return x; }));
            v->setLogScale(false);
            QVERIFY(v->colorMap() == ColorMap::Viridis);
            QCOMPARE(QString::fromUtf8(v->barTitle()->GetInput()), QString("%1 [eV]").arg(band));
        }
    }

    void parity2dRecombinationAlwaysLog() {
        auto w = mosfet("p_recomb.ini");
        QVERIFY(w);
        FieldView* v = w->fieldView();
        selectItem(w.get(), derivedItem(w.get(), "R"));
        QTRY_VERIFY_WITH_TIMEOUT(v->field() == "R", 120000);
        for (bool log : {false, true}) {  // the toggle does not apply
            v->setLogScale(log);
            QVERIFY(v->logEffective());
            QVERIFY(displayedIs(v, [](double x) { return std::log10(std::max(std::abs(x), 1e-30)); }));
        }
        QVERIFY(v->colorMap() == ColorMap::Inferno);
    }

    void parity2dContoursOnOff() {
        auto w = mosfet("p_contours.ini");
        QVERIFY(w);
        FieldView* v = w->fieldView();
        selectField(w.get(), "potential");
        v->setContours(true);
        QVERIFY(v->contourActor()->GetVisibility());
        const auto r = v->dataRange();
        QVERIFY(v->contourLevels() == tcad::desktop::contour_levels(r[0], r[1], 8));  // matplotlib's levels=8
        v->setContours(false);
        QVERIFY(!v->contourActor()->GetVisibility() && v->contourLevels().empty());
    }

    void parity2dMeshLinesOnOff() {
        auto w = mosfet("p_mesh.ini");
        QVERIFY(w);
        FieldView* v = w->fieldView();
        v->setMeshLines(true);
        QVERIFY(v->meshActor()->GetVisibility());
        auto* lines = vtkPolyData::SafeDownCast(v->meshActor()->GetMapper()->GetInput());
        const auto n = w->result()->node_counts();
        QCOMPARE(static_cast<std::size_t>(lines->GetNumberOfLines()), n[0] + n[1]);  // one per node coordinate
        v->setMeshLines(false);
        QVERIFY(!v->meshActor()->GetVisibility());
    }

    void parity2dHoverReadsTheRawValue() {
        auto w = mosfet("p_hover.ini");
        QVERIFY(w);
        FieldView* v = w->fieldView();
        selectField(w.get(), "electron_density");
        v->setLogScale(true);  // drawn in log10; read out raw
        QString readout;
        QVERIFY(v->readoutAt(v->width() * 0.35, v->height() / 2.0, &readout));
        QVERIFY2(readoutIsRawNodeValue(v, readout), qPrintable(readout));
    }

    void parity2dFitAndReset() {
        auto w = mosfet("p_fit.ini");
        QVERIFY(w);
        FieldView* v = w->fieldView();
        vtkCamera* cam = v->renderer()->GetActiveCamera();
        v->resetView();
        double focal[3];
        cam->GetFocalPoint(focal);
        const double scale = cam->GetParallelScale();
        cam->Zoom(3.0);
        double f2[3] = {focal[0] + 1.0, focal[1] - 0.5, focal[2]};
        cam->SetFocalPoint(f2);  // zoomed and panned
        v->resetView();
        double back[3];
        cam->GetFocalPoint(back);
        QCOMPARE(cam->GetParallelScale(), scale);
        for (int a = 0; a < 3; ++a) QCOMPARE(back[a], focal[a]);
    }

    void parity2dRangeAutoManualLocked() {
        auto w = mosfet("p_range.ini");
        QVERIFY(w);
        FieldView* v = w->fieldView();
        selectField(w.get(), "potential");
        const auto auto_range = v->normRange();
        v->setManualRange(-0.2, 0.3, false);
        QCOMPARE(v->normRange()[0], -0.2);
        selectField(w.get(), "electron_density");
        QVERIFY(!v->colorRange().manual);  // unlocked: per field
        v->setManualRange(1e5, 1e10, true);
        selectField(w.get(), "potential");
        QVERIFY(v->colorRange().locked && v->normRange()[1] == 1e10);  // locked: kept across fields
        v->setAutoRange();
        QVERIFY(v->normRange() == auto_range);
    }

    // -- theme (S3c; one black-and-white scheme since 2026-09-26) ---------------
    // What the window PAINTS, not only its palette: the palette checks passed
    // while ADS drew a stock-grey Fields panel once (S3c screenshot). A
    // "theme/choice" left in an old settings file must change nothing.
    void theBlackAndWhiteThemeReachesQtVtkAndAds() {
        using namespace tcad::desktop::theme;
        // a fresh launch's palette, not whatever an earlier test left behind
        QApplication::setPalette(QApplication::style()->standardPalette());
        const QString path = ini("theme_bw.ini");
        {
            QSettings s(path, QSettings::IniFormat);
            s.setValue("theme/choice", "dark");  // from before 2026-09-26: ignored
        }
        auto w = shown(path);
        QVERIFY(w);
        QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
        QApplication::processEvents();
        const QPalette pal = QApplication::palette();
        QCOMPARE(pal.color(QPalette::Window), qcolor(T::Window));
        QCOMPARE(pal.color(QPalette::Base), qcolor(T::Base));
        QCOMPARE(pal.color(QPalette::Text), qcolor(T::Text));
        QCOMPARE(pal.color(QPalette::Highlight), qcolor(T::Accent));
        QCOMPARE(qcolor(T::Base), QColor(255, 255, 255));  // white surfaces, black text
        QCOMPARE(qcolor(T::Text), QColor(0, 0, 0));
        // VTK: background and scalar-bar text
        double bg[3];
        w->fieldView()->renderer()->GetBackground(bg);
        const Rgb want_bg = rgb(T::Background), want_fg = rgb(T::Text);
        QCOMPARE(bg[0], want_bg.r);
        QCOMPARE(bg[1], want_bg.g);
        QCOMPARE(bg[2], want_bg.b);
        for (vtkTextProperty* tp :
             {w->fieldView()->scalarBar()->GetTitleTextProperty(), w->fieldView()->scalarBar()->GetLabelTextProperty()}) {
            const double* c = tp->GetColor();
            QCOMPARE(c[0], want_fg.r);
            QCOMPARE(c[1], want_fg.g);
            QCOMPARE(c[2], want_fg.b);
        }
        const QImage frame = w->fieldView()->grabFramebuffer();
        QCOMPARE(QColor(frame.pixel(2, 2)), qcolor(T::Background));
        // ADS: the Fields panel's empty area, from explicit token colours
        const QImage panel = w->fieldsDock()->grab().toImage();
        QCOMPARE(QColor(panel.pixel(panel.width() / 2, panel.height() - 6)), qcolor(T::Base));
        const QString qss = w->dockManager()->styleSheet();
        QVERIFY2(!qss.contains("palette("), "ADS stylesheet still reads the palette");
        QVERIFY(qss.contains(qcolor(T::Window).name()) && qss.contains(qcolor(T::Base).name()));
        // the plot's background
        QVERIFY(w->setViewMode(ViewMode::Convergence));
        QApplication::processEvents();
        const QImage plot = w->plotView()->grab().toImage();
        QCOMPARE(QColor(plot.pixel(2, 2)), qcolor(T::Base));
        // no theme menu any more
        for (QAction* a : w->findChildren<QAction*>())
            QVERIFY2(!a->text().contains("Theme") && a->text() != "&Dark" && a->text() != "&System", qPrintable(a->text()));
    }

    void theThemeIgnoresTheOsColourScheme() {
        using namespace tcad::desktop::theme;
        auto w = shown(ini("theme_os.ini"));
        QVERIFY(w);
        QStyleHints* hints = QGuiApplication::styleHints();
        for (auto scheme : {Qt::ColorScheme::Dark, Qt::ColorScheme::Light, Qt::ColorScheme::Dark}) {
            hints->setColorScheme(scheme);
            QApplication::processEvents();
            QCOMPARE(QApplication::palette().color(QPalette::Window), qcolor(T::Window));
            QCOMPARE(QApplication::palette().color(QPalette::Text), qcolor(T::Text));
        }
        hints->unsetColorScheme();
    }

    // -- curve modes (P2-S3) --------------------------------------------------
    void curveModeFieldIsTheDefaultFor1D() {
        auto w = opened("p2_field.ini", "diode_1d.npz");
        QVERIFY(w);
        PlotView* p = w->plotView();
        const QList<ViewMode> modes = comboModes(w.get());
        QVERIFY(modes.contains(ViewMode::Field) && modes.contains(ViewMode::Bands) && modes.contains(ViewMode::Recombination));
        QVERIFY(!modes.contains(ViewMode::FieldMap));  // no map of a 1D result
        QCOMPARE(w->viewMode(), ViewMode::Field);
        QVERIFY(plotShown(w.get()));
        QCOMPARE(w->viewModeCombo()->currentText(), QString("Field"));

        // the curve is the field against x in um, raw
        const auto field = w->result()->scalar(w->plotField());
        QCOMPARE(p->model().series.size(), std::size_t{1});
        const auto& s = p->model().series[0];
        QVERIFY(s.y == field.values);
        QVERIFY(s.x == um(w->result()->axis(0)));
        QVERIFY(s.markers == tcad::desktop::plot::Markers::Never);  // ax.plot(x, field): no markers
        QCOMPARE(p->model().x.label, QString("x [um]"));
        QCOMPARE(p->model().y.label, QString::fromStdString(field.name + " [" + field.unit + "]"));

        // hover: the raw sample, in the status bar too
        const std::size_t mid = s.x.size() / 2;
        QCOMPARE(hoverSample(p, 0, mid), entry(p, 0, mid));
        QCOMPARE(statusReadout(w.get()), entry(p, 0, mid));
        snapshot(w.get(), "field_1d");

        // log through the toolbar's action: a true log axis of |v| (decision 8); the map's log is untouched
        QAction* log = logAction(w.get());
        QVERIFY(log && log->isEnabled());
        log->trigger();
        QVERIFY(w->plotLog() && p->model().y.scale == tcad::desktop::plot::Scale::Log);
        QCOMPARE(p->model().y.label, QString::fromStdString("|" + field.name + "| [" + field.unit + "]"));
        QVERIFY(!w->fieldView()->logScale());
        QVERIFY(child<QCheckBox>(w->plotPanel(), "PlotLogCheck")->isChecked());
        log->trigger();
        QVERIFY(!w->plotLog() && p->model().y.scale == tcad::desktop::plot::Scale::Linear);

        // the Fields list picks the field drawn
        const QString other = w->plotField() == "doping" ? "potential" : "doping";
        selectField(w.get(), other);
        QCOMPARE(QString::fromStdString(w->plotField()), other);
        QVERIFY(p->model().series[0].y == w->result()->scalar(other.toStdString()).values);
        QCOMPARE(w->fieldList()->currentItem()->text(), other);
    }

    void curveModeCurvesDrawsTheSweep() {
        auto w = opened("p2_series.ini", "diode_1d_iv.npz");
        QVERIFY(w);
        PlotView* p = w->plotView();
        QCOMPARE(w->viewMode(), ViewMode::Field);  // 1D: the field first
        QVERIFY(chooseMode(w.get(), ViewMode::Curves));
        QVERIFY(plotShown(w.get()));
        const auto sw = w->result()->sweep();
        QCOMPARE(w->sweepChannel(), QString("device"));  // the first channel, as QML
        const auto& m = p->model();
        QCOMPARE(m.title, QString("anode sweep"));
        QCOMPARE(m.x.label, QString("anode bias [V]"));
        QCOMPARE(m.y.label, QString("device [A/cm^2]"));
        QCOMPARE(m.series.size(), std::size_t{1});
        QVERIFY(m.series[0].x == sw.voltages && m.series[0].y == sw.channels[0].values);
        QCOMPARE(hoverSample(p, 0, 3), entry(p, 0, 3));
        QVERIFY2(p->readout().startsWith("device: ") && p->readout().contains(" A/cm^2 @ ") &&
                     p->readout().endsWith(" V"),
                 qPrintable(p->readout()));

        // the Plot panel offers the channel; an unknown one is refused
        auto* combo = child<QComboBox>(w->plotPanel(), "SweepChannelCombo");
        QVERIFY(combo->isEnabled() && combo->count() == 1 && combo->currentText() == "device");
        QVERIFY(!w->setSweepChannel("nope"));
        QCOMPARE(w->sweepChannel(), QString("device"));

        // log: |I| on a log axis, label as QML's
        logAction(w.get())->trigger();
        QCOMPARE(p->model().y.label, QString("|device| [A/cm^2]"));
        QVERIFY(p->model().y.scale == tcad::desktop::plot::Scale::Log);
        snapshot(w.get(), "curves_log");
        // ... and the channel combo is off outside Curves
        QVERIFY(chooseMode(w.get(), ViewMode::Field));
        QVERIFY(!combo->isEnabled());
    }

    void curveModeCVIsTheDefaultForACapacitanceSweep() {
        auto w = opened("p2_cv.ini", "cv.npz");
        QVERIFY(w);
        PlotView* p = w->plotView();
        QCOMPARE(w->viewMode(), ViewMode::CV);
        QVERIFY(!comboModes(w.get()).contains(ViewMode::Curves));  // a C-V sweep is not an I-V one
        const auto sw = w->result()->sweep();
        const auto& m = p->model();
        QCOMPARE(m.title, QString("C-V sweep"));
        QCOMPARE(m.x.label, QString("Vg [V]"));
        QCOMPARE(m.y.label, QString("C [F/cm^2]"));
        QVERIFY(m.series[0].x == sw.voltages && m.series[0].y == sw.channels[0].values);
        QCOMPARE(m.series[0].label, QString("C"));
        QCOMPARE(hoverSample(p, 0, 20), entry(p, 0, 20));
        QVERIFY(!logAction(w.get())->isEnabled());  // QML's C-V has no log toggle
        snapshot(w.get(), "cv");
    }

    void curveModeTransientDrawsEveryChannel() {
        auto w = opened("p2_transient.ini", "diode_1d_transient.npz");
        QVERIFY(w);
        PlotView* p = w->plotView();
        QVERIFY(chooseMode(w.get(), ViewMode::Transient));
        const auto tr = w->result()->transient();
        const auto& m = p->model();
        QCOMPARE(m.title, QString("anode transient"));
        QCOMPARE(m.x.label, QString("t [s]"));
        QCOMPARE(m.y.label, QString("current [A/cm^2]"));
        QCOMPARE(m.series.size(), std::size_t{2});
        QCOMPARE(m.series[0].label, QString("anode"));  // sorted by name, as QML
        QCOMPARE(m.series[1].label, QString("cathode"));
        QVERIFY(m.series[0].colour != m.series[1].colour);
        for (std::size_t k = 0; k < 2; ++k) {
            const auto it = std::find_if(tr.channels.begin(), tr.channels.end(),
                                         [&](const auto& c) { return QString::fromStdString(c.name) == m.series[k].label; });
            QVERIFY(it != tr.channels.end() && m.series[k].x == tr.times && m.series[k].y == it->values);
        }
        QVERIFY(!p->legendRect().isEmpty());
        QVERIFY2(hoverSample(p, 1, 5).contains(entry(p, 1, 5)), qPrintable(p->readout()));
        snapshot(w.get(), "transient");
    }

    void curveModeACHoversBothAxes() {
        auto w = opened("p2_ac.ini", "diode_1d_ac.npz");
        QVERIFY(w);
        PlotView* p = w->plotView();
        QVERIFY(chooseMode(w.get(), ViewMode::AC));
        const auto ac = w->result()->ac();
        const auto& m = p->model();
        QCOMPARE(m.title, QString("anode AC sweep"));
        QVERIFY(m.x.scale == tcad::desktop::plot::Scale::Log && m.has_y2);
        QCOMPARE(m.y.label, QString("C [F/cm^2]"));
        QCOMPARE(m.y2.label, QString("G [S/cm^2]"));
        QCOMPARE(m.series.size(), std::size_t{2});
        QVERIFY(m.series[0].y == ac.C && m.series[0].axis == tcad::desktop::plot::YAxis::Left);
        QVERIFY(m.series[1].y == ac.G && m.series[1].axis == tcad::desktop::plot::YAxis::Right);
        QVERIFY(m.y.colour == m.series[0].colour && m.y2.colour == m.series[1].colour);
        // decision 5: C and G both hover (QML hovered C only)
        QCOMPARE(hoverSample(p, 0, 0), entry(p, 0, 0));
        QCOMPARE(hoverSample(p, 1, 6), entry(p, 1, 6));
        QVERIFY2(p->readout().endsWith(" Hz") && p->readout().startsWith("G: "), qPrintable(p->readout()));
        snapshot(w.get(), "ac");
    }

    void curveModeConvergenceDrawsTheTrace() {
        using tcad::desktop::plot::MarkerShape;
        auto w = opened("p2_conv.ini", "diode_1d_rejected.npz");
        QVERIFY(w);
        PlotView* p = w->plotView();
        QVERIFY(chooseMode(w.get(), ViewMode::Convergence));
        const auto trace = *w->result()->trace();
        const auto& m = p->model();
        QVERIFY(m.y.scale == tcad::desktop::plot::Scale::Log);
        QCOMPARE(m.x.label, QString("cumulative Newton iteration"));
        QCOMPARE(m.y.label, QString("residual (all tracked metrics)"));
        // one series per (step, metric), in order, on the cumulative axis; one cross per rejected step
        std::size_t k = 0, rejected = 0;
        double offset = 0;
        for (const auto& step : trace) {
            for (const auto& metric : step.metrics) {
                QVERIFY(k < m.series.size());
                const auto& s = m.series[k++];
                QVERIFY(s.y == metric.values);
                QCOMPARE(s.x.front(), offset);
                QVERIFY(s.shape == MarkerShape::Dot);
                const QString base = QString::fromStdString(step.stage).section(':', 0, 0);
                QCOMPARE(s.label, base + ":" + QString::fromStdString(metric.name));
                const auto want = base == "equilibrium" ? tcad::desktop::theme::DataColour::StageEquilibrium
                                  : base == "bias"      ? tcad::desktop::theme::DataColour::StageBias
                                                        : tcad::desktop::theme::DataColour::StageOther;
                QCOMPARE(s.colour, tcad::desktop::theme::dataColour(want));
            }
            if (!step.converged) {
                const auto& x = m.series[k++];
                QVERIFY(x.shape == MarkerShape::Cross && x.label == "rejected" && x.in_legend == (rejected == 0));
                QCOMPARE(x.y.front(), step.metrics.front().values.back());
                QCOMPARE(x.x.front(), offset + static_cast<double>(step.metrics.front().values.size() - 1));
                QCOMPARE(x.colour, tcad::desktop::theme::dataColour(tcad::desktop::theme::DataColour::Rejected));
                ++rejected;
            }
            offset += static_cast<double>(step.metrics.front().values.size());
        }
        QCOMPARE(k, m.series.size());
        QCOMPARE(rejected, std::size_t{1});
        // the legend names each stage:metric once
        QStringList legend;
        for (const auto& s : m.series)
            if (s.in_legend) legend << s.label;
        QCOMPARE(legend.removeDuplicates(), qsizetype{0});
        QVERIFY(legend.contains("sweep:F") && legend.contains("equilibrium:dpsi") && legend.contains("rejected"));
        // hoverable -- new; QML's convergence view never was
        const std::size_t probe = 1;  // equilibrium's dpsi series is series 0; a sweep series is later
        QVERIFY(m.series[probe].y.size() > 3);
        const QString r = hoverSample(p, probe, 2);
        QVERIFY2(r.contains(entry(p, probe, 2)) && r.endsWith(" iteration"), qPrintable(r));
        QVERIFY(!logAction(w.get())->isEnabled());  // always log
        snapshot(w.get(), "convergence");
    }

    void curveModeBandsAndRecombinationThroughTheBackend() {
        auto w = opened("p2_bands.ini", "diode_1d.npz");
        QVERIFY(w);
        PlotView* p = w->plotView();
        QVERIFY(chooseMode(w.get(), ViewMode::Bands));
        QTRY_VERIFY_WITH_TIMEOUT(p->model().series.size() == 4, 120000);
        const auto* bands = w->derivedModel("bands");
        QVERIFY(bands);
        const char* names[] = {"Ec", "Ev", "EFn", "EFp"};
        for (std::size_t k = 0; k < 4; ++k) {
            const auto& s = p->model().series[k];
            QCOMPARE(s.label, QString(names[k]));
            QVERIFY(s.y == bands->scalar(names[k]).values);
            QVERIFY(s.x == um(w->result()->axis(0)));
            QVERIFY(s.line == (k < 2 ? tcad::desktop::plot::LineStyle::Solid : tcad::desktop::plot::LineStyle::Dashed));
        }
        QCOMPARE(p->model().x.label, QString("depth [um]"));
        QCOMPARE(p->model().y.label, QString("energy [eV]"));
        const std::size_t mid = p->model().series[0].x.size() / 2;
        QCOMPARE(hoverSample(p, 0, mid), entry(p, 0, mid));  // (ties: test_plot.cpp)
        snapshot(w.get(), "bands");

        QVERIFY(chooseMode(w.get(), ViewMode::Recombination));
        QTRY_VERIFY_WITH_TIMEOUT(p->model().series.size() == 1, 120000);
        const auto* rec = w->derivedModel("recombination");
        QVERIFY(rec);
        const auto& r = p->model().series[0];
        QVERIFY(r.y == rec->scalar("R").values);  // signed; the log axis shows |R| (decision 8)
        QVERIFY(p->model().y.scale == tcad::desktop::plot::Scale::Log);
        QCOMPARE(p->model().y.label, QString("|R| [cm^-3 s^-1]"));
        QVERIFY(!logAction(w.get())->isEnabled());
        snapshot(w.get(), "recombination");
        // back to Bands: cached, no second backend call
        QVERIFY(chooseMode(w.get(), ViewMode::Bands));
        QCOMPARE(p->model().series.size(), std::size_t{4});
    }

    void curveModeBackendFailureIsShownInThePlot() {
        qputenv("TCAD_BACKEND_PYTHON", "C:/no/such/python.exe");
        auto w = opened("p2_nobackend.ini", "diode_1d.npz");
        QVERIFY(w);
        QVERIFY(chooseMode(w.get(), ViewMode::Bands));
        QTRY_VERIFY_WITH_TIMEOUT(w->lastError().contains("does not exist"), 10000);
        qunsetenv("TCAD_BACKEND_PYTHON");
        QVERIFY(w->plotView()->model().series.empty());
        QVERIFY2(w->plotView()->model().empty_text.startsWith("Could not compute the bands"),
                 qPrintable(w->plotView()->model().empty_text));
    }

    void curveModesAbsentWhenUnsupported() {
        auto w = opened("p2_absent.ini", "mosfet_2d.npz");
        QVERIFY(w);
        // a 2D result without curve blocks: the map, its line cut (P2-S4), and its trace
        QCOMPARE(comboModes(w.get()), (QList<ViewMode>{ViewMode::FieldMap, ViewMode::Cut, ViewMode::Convergence}));
        QCOMPARE(w->viewMode(), ViewMode::FieldMap);
        QVERIFY(mapShown(w.get()));
        for (ViewMode m : {ViewMode::Field, ViewMode::Curves, ViewMode::CV, ViewMode::Transient, ViewMode::AC,
                           ViewMode::Bands, ViewMode::Recombination}) {
            QVERIFY(!w->setViewMode(m));
            QCOMPARE(w->viewMode(), ViewMode::FieldMap);
        }
        // the View menu offers the same modes as the combo
        QStringList menu;
        for (QAction* a : w->findChild<QMenu*>("ViewModeMenu")->actions()) menu << a->text();
        QCOMPARE(menu, (QStringList{"Field map", "Line cut", "Convergence"}));
        // a C-V file has no I-V curves, no trace, no bands (it has no potential)
        QVERIFY(w->tryOpen(data("cv.npz")));
        QCOMPARE(comboModes(w.get()), (QList<ViewMode>{ViewMode::Field, ViewMode::CV}));
        // the 1D diode: its field, trace, bands and R -- no sweep, transient or AC
        QVERIFY(w->tryOpen(data("diode_1d.npz")));
        QCOMPARE(comboModes(w.get()),
                 (QList<ViewMode>{ViewMode::Field, ViewMode::Convergence, ViewMode::Bands, ViewMode::Recombination}));
        // back to a 2D result: the map again, its GL view shown
        QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
        QCOMPARE(w->viewMode(), ViewMode::FieldMap);
        QVERIFY(mapShown(w.get()));
    }

    void viewSwitchesKeepTheGlContextAndAreFast() {
        auto w = opened("p2_switch.ini", "mosfet_2d.npz");
        QVERIFY(w);
        FieldView* v = w->fieldView();
        QTRY_VERIFY(v->glInitializations() > 0);
        const int inits = v->glInitializations();
        std::vector<double> ms;
        auto timed = [&](MainWindow* win, ViewMode m) {
            QElapsedTimer t;
            t.start();
            const bool ok = chooseMode(win, m);
            (tcad::desktop::plot::isCurveMode(m) ? static_cast<QWidget*>(win->plotView()) : win->fieldView())->repaint();
            ms.push_back(static_cast<double>(t.nsecsElapsed()) * 1e-6);
            QApplication::processEvents();
            return ok;
        };
        for (int i = 0; i < 20; ++i) QVERIFY(timed(w.get(), i % 2 ? ViewMode::FieldMap : ViewMode::Convergence));
        QCOMPARE(w->viewMode(), ViewMode::FieldMap);
        QCOMPARE(v->glInitializations(), inits);  // hidden and shown, never re-created
        QTRY_VERIFY(distinctColours(v) > 1);      // and it still renders
        // every local mode of a 1D sweep, round and round (not bands/R: those start a backend call)
        QVERIFY(w->tryOpen(data("diode_1d_iv.npz")));
        QList<ViewMode> modes = comboModes(w.get());
        modes.removeAll(ViewMode::Bands);
        modes.removeAll(ViewMode::Recombination);
        QCOMPARE(modes, (QList<ViewMode>{ViewMode::Field, ViewMode::Curves, ViewMode::Convergence}));
        for (int i = 0; i < 20; ++i) QVERIFY(timed(w.get(), modes[i % modes.size()]));
        QCOMPARE(v->glInitializations(), inits);
        std::sort(ms.begin(), ms.end());
        const double p95 = ms[static_cast<std::size_t>(0.95 * static_cast<double>(ms.size() - 1))];
        qInfo("mode switch: p50 %.2f ms, p95 %.2f ms, max %.2f ms over %zu", ms[ms.size() / 2], p95, ms.back(), ms.size());
        QVERIFY2(p95 <= 50.0, qPrintable(QString("mode switch p95 %1 ms > 50 ms").arg(p95)));
    }

    void fitAndLogActOnTheVisibleView() {
        auto w = opened("p2_route.ini", "diode_1d_iv.npz");
        QVERIFY(w);
        PlotView* p = w->plotView();
        QVERIFY(chooseMode(w.get(), ViewMode::Curves));
        const auto fitted = p->xView();
        p->zoom(0.25);
        QVERIFY(p->xView().lo != fitted.lo);
        p->setFocus();
        QTest::keyClick(w.get(), Qt::Key_F);  // Fit: the plot's, not the hidden map's
        QCOMPARE(p->xView().lo, fitted.lo);
        QCOMPARE(p->xView().hi, fitted.hi);
        // the Plot panel's log and the toolbar's are one state
        child<QCheckBox>(w->plotPanel(), "PlotLogCheck")->setChecked(true);
        QVERIFY(w->plotLog() && logAction(w.get())->isChecked());
        QVERIFY(!w->fieldView()->logScale());
        // a mode without a log toggle disables it; returning restores it
        QVERIFY(chooseMode(w.get(), ViewMode::Convergence));
        QVERIFY(!logAction(w.get())->isEnabled());
        QVERIFY(!child<QCheckBox>(w->plotPanel(), "PlotLogCheck")->isEnabled());
        QVERIFY(chooseMode(w.get(), ViewMode::Curves));
        QVERIFY(logAction(w.get())->isEnabled() && logAction(w.get())->isChecked());
        // on a 2D result the action drives the map again
        QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
        QVERIFY(!logAction(w.get())->isChecked());
        logAction(w.get())->trigger();
        QVERIFY(w->fieldView()->logScale());
    }

    // -- line cut (P2-S4, NATIVE-DESKTOP-PLAN.md 16.3) --------------------------
    // The cut itself is contract-tested against extract_line_cut
    // (test_desktop_contracts.py); these gate the mode: what it cuts, where
    // the line is drawn, what drives it.

    void cutModeIsOffered2DOnly() {
        auto w = opened("p2_cut_offer.ini", "mosfet_2d.npz");
        QVERIFY(w);
        QVERIFY(comboModes(w.get()).contains(ViewMode::Cut));
        QVERIFY(w->tryOpen(data("resistor_3d.npz")));
        QVERIFY(!comboModes(w.get()).contains(ViewMode::Cut));  // 3D cuts: out of scope (16.6)
        QVERIFY(!w->setViewMode(ViewMode::Cut));
        QVERIFY(w->tryOpen(data("diode_1d.npz")));
        QVERIFY(!comboModes(w.get()).contains(ViewMode::Cut));
    }

    void cutModeShowsTheMapAboveItsCurve() {
        auto w = opened("p2_cut_show.ini", "mosfet_2d.npz");
        QVERIFY(w);
        FieldView* v = w->fieldView();
        PlotView* p = w->plotView();
        QTRY_VERIFY(v->glInitializations() > 0);
        const int inits = v->glInitializations();
        QVERIFY(chooseMode(w.get(), ViewMode::Cut));
        QVERIFY(v->isVisible() && p->isVisible());   // both, one splitter
        QVERIFY(p->geometry().top() >= v->geometry().bottom());
        QCOMPARE(w->cutIndex(), 0);                    // QML's default: y = 0
        QVERIFY(w->cutHorizontal());
        // the curve is the nearest-node row of the field the map shows
        const auto f = v->fieldSource()->scalar(v->field());
        const auto cut = tcad::desktop::line_cut(v->fieldSource()->axis(0), v->fieldSource()->axis(1), f.values,
                                                 tcad::desktop::CutOrientation::Horizontal, v->fieldSource()->axis(1)[0]);
        const auto& s = p->model().series.at(0);
        QVERIFY(s.y == cut.values);
        QVERIFY(s.x == um(cut.coord));
        QCOMPARE(s.label, QString::fromStdString(f.name));
        QCOMPARE(p->model().x.label, QString("x [um]"));
        QCOMPARE(p->model().y.label, QString::fromStdString(f.name + " [" + f.unit + "]"));
        QCOMPARE(p->model().title, QString("cut at y=%1 um (nearest node)").arg(QString::number(cut.actual * 1e4, 'g', 4)));
        // the line on the map, where the cut is, above the map
        QVERIFY(v->cutLineActor()->GetVisibility() && v->cutHaloActor()->GetVisibility());
        double b[6];
        v->cutLineActor()->GetMapper()->GetInput()->GetBounds(b);
        QCOMPARE(b[2], v->axisUm(1)[0]);
        QCOMPARE(b[3], v->axisUm(1)[0]);
        QCOMPARE(b[0], v->edgesUm(0).front());
        QCOMPARE(b[1], v->edgesUm(0).back());
        QTRY_VERIFY(distinctColours(v) > 1);           // the map still renders
        QCOMPARE(v->glInitializations(), inits);        // shown beside the plot, never reparented
        QVERIFY(w->setCut(true, static_cast<int>(v->axisUm(1).size() / 4)));
        snapshot(w.get(), "cut");
        QVERIFY(w->setCut(true, 0));
        // leaving the mode hides the line and the plot
        QVERIFY(chooseMode(w.get(), ViewMode::FieldMap));
        QVERIFY(!v->cutLineActor()->GetVisibility() && !p->isVisible() && v->isVisible());
    }

    void cutFollowsTheSliderAndTheOrientation() {
        auto w = opened("p2_cut_drive.ini", "mosfet_2d.npz");
        QVERIFY(w);
        FieldView* v = w->fieldView();
        PlotView* p = w->plotView();
        QVERIFY(chooseMode(w.get(), ViewMode::Cut));
        const auto* src = v->fieldSource();
        const auto values = src->scalar(v->field()).values;
        const std::size_t nx = src->axis(0).size(), ny = src->axis(1).size();

        // the slider: every position is a node of y; the label names it
        auto* slider = child<QSlider>(w->plotPanel(), "CutPositionSlider");
        auto* label = child<QLabel>(w->plotPanel(), "CutPositionLabel");
        QVERIFY(slider->isEnabled());
        QCOMPARE(slider->maximum(), static_cast<int>(ny) - 1);
        const int k = static_cast<int>(ny / 2);
        slider->setValue(k);
        QCOMPARE(w->cutIndex(), k);
        std::vector<double> row(values.begin() + static_cast<std::ptrdiff_t>(k * nx),
                                values.begin() + static_cast<std::ptrdiff_t>((k + 1) * nx));
        QVERIFY(p->model().series.at(0).y == row);
        QVERIFY2(label->text().contains(QString("node %1 of %2").arg(k).arg(ny)), qPrintable(label->text()));
        double b[6];
        v->cutLineActor()->GetMapper()->GetInput()->GetBounds(b);
        QCOMPARE(b[2], v->axisUm(1)[static_cast<std::size_t>(k)]);

        // vertical: a column, along y; the index stays where the new axis allows
        auto* orient = child<QComboBox>(w->plotPanel(), "CutOrientationCombo");
        orient->setCurrentIndex(1);
        emit orient->activated(1);
        QVERIFY(!w->cutHorizontal());
        QCOMPARE(w->cutIndex(), std::min(k, static_cast<int>(nx) - 1));
        const std::size_t c = static_cast<std::size_t>(w->cutIndex());
        std::vector<double> col(ny);
        for (std::size_t j = 0; j < ny; ++j) col[j] = values[j * nx + c];
        QVERIFY(p->model().series.at(0).y == col);
        QVERIFY(p->model().series.at(0).x == um(src->axis(1)));
        QCOMPARE(p->model().x.label, QString("y [um]"));
        QVERIFY(p->model().title.startsWith("cut at x="));
        v->cutLineActor()->GetMapper()->GetInput()->GetBounds(b);
        QCOMPARE(b[0], v->axisUm(0)[c]);
        QCOMPARE(b[1], v->axisUm(0)[c]);

        // refused: outside the axis (nothing changes)
        QVERIFY(!w->setCut(false, static_cast<int>(nx)));
        QVERIFY(!w->setCut(false, -1));
        QCOMPARE(w->cutIndex(), static_cast<int>(c));
        // outside Line cut mode the controls are off
        QVERIFY(chooseMode(w.get(), ViewMode::FieldMap));
        QVERIFY(!slider->isEnabled() && !orient->isEnabled());
    }

    void cutFollowsTheFieldAndDerivedMaps() {
        auto w = opened("p2_cut_field.ini", "mosfet_2d.npz");
        QVERIFY(w);
        FieldView* v = w->fieldView();
        PlotView* p = w->plotView();
        QVERIFY(chooseMode(w.get(), ViewMode::Cut));
        QVERIFY(w->setCut(true, 2));
        // another field from the list: still Line cut, now cutting that field
        const QString other = v->field() == "potential" ? "electron_density" : "potential";
        selectField(w.get(), other);
        QCOMPARE(w->viewMode(), ViewMode::Cut);
        QCOMPARE(QString::fromStdString(v->field()), other);
        QCOMPARE(p->model().series.at(0).label, other);
        const auto vals = v->fieldSource()->scalar(other.toStdString()).values;
        const std::size_t nx = v->fieldSource()->axis(0).size();
        QVERIFY(p->model().series.at(0).y ==
                std::vector<double>(vals.begin() + static_cast<std::ptrdiff_t>(2 * nx),
                                    vals.begin() + static_cast<std::ptrdiff_t>(3 * nx)));
        // a backend-derived map (wider than QML, which cut stored fields only)
        selectItem(w.get(), derivedItem(w.get(), "Ec"));
        QTRY_VERIFY_WITH_TIMEOUT(v->field() == "Ec", 120000);
        QCOMPARE(w->viewMode(), ViewMode::Cut);
        QTRY_VERIFY(p->model().series.size() == 1 && p->model().series[0].label == "Ec");
        const auto ec = w->derivedModel("bands")->scalar("Ec").values;
        QVERIFY(p->model().series.at(0).y ==
                std::vector<double>(ec.begin() + static_cast<std::ptrdiff_t>(2 * nx),
                                    ec.begin() + static_cast<std::ptrdiff_t>(3 * nx)));
        QCOMPARE(p->model().y.label, QString("Ec [eV]"));
    }

    void cutLogAndHoverFollowDecisions8And9() {
        auto w = opened("p2_cut_log.ini", "mosfet_2d.npz");
        QVERIFY(w);
        PlotView* p = w->plotView();
        QVERIFY(chooseMode(w.get(), ViewMode::Cut));
        selectField(w.get(), "electron_density");
        QAction* log = logAction(w.get());
        QVERIFY(log->isEnabled());
        log->trigger();   // the curve's log, not the map's
        QVERIFY(w->plotLog() && p->model().y.scale == tcad::desktop::plot::Scale::Log);
        QCOMPARE(p->model().y.label, QString("|electron_density| [cm^-3]"));
        QVERIFY(!w->fieldView()->logScale());
        const std::size_t mid = p->model().series[0].x.size() / 2;
        QCOMPARE(hoverSample(p, 0, mid), entry(p, 0, mid));   // the raw value, x in um
        QVERIFY(p->readout().endsWith(" um"));
    }

    void cutSwitchesKeepTheGlContext() {
        auto w = opened("p2_cut_gl.ini", "mosfet_2d.npz");
        QVERIFY(w);
        FieldView* v = w->fieldView();
        QTRY_VERIFY(v->glInitializations() > 0);
        const int inits = v->glInitializations();
        const ViewMode cycle[] = {ViewMode::Cut, ViewMode::FieldMap, ViewMode::Convergence, ViewMode::Cut};
        for (int i = 0; i < 20; ++i) {
            QVERIFY(chooseMode(w.get(), cycle[i % 4]));
            QApplication::processEvents();
        }
        QCOMPARE(v->glInitializations(), inits);
        QVERIFY(chooseMode(w.get(), ViewMode::Cut));
        QTRY_VERIFY(distinctColours(v) > 1);
    }

    // -- overlays (P2-S5) -------------------------------------------------------
    void overlayComparisonIsDashedOnItsOwnVoltages() {
        auto w = curvesOf(tmp_, "p2_ov_cmp.ini");
        QVERIFY(w);
        PlotView* p = w->plotView();
        QCOMPARE(w->addOverlay(data("diode_1d_iv_fine.npz"), Kind::Comparison), QString());
        const auto fine = sweepOf("diode_1d_iv_fine.npz");
        const auto& m = p->model();
        QCOMPARE(m.series.size(), std::size_t{2});
        const auto& c = m.series[1];
        QCOMPARE(c.label, QString("diode_1d_iv_fine"));  // the file name, editable
        QVERIFY(c.line == tcad::desktop::plot::LineStyle::Dashed);
        QCOMPARE(c.colour, tcad::desktop::theme::dataColour(tcad::desktop::theme::DataColour::Comparison));
        QVERIFY(c.x == fine.voltages);                      // its own ramp (finding 12) ...
        QVERIFY(c.x != m.series[0].x);                      // ... not the primary's
        QVERIFY(c.y == fine.channels[0].values);
        QVERIFY(m.legend && !p->legendRect().isEmpty());
        // hover names the overlay's own sample
        const std::size_t k = c.x.size() - 1;
        QVERIFY2(hoverSample(p, 1, k).contains(entry(p, 1, k)), qPrintable(p->readout()));
        // a second comparison replaces the first (QML's setComparisonSource)
        QCOMPARE(w->addOverlay(data("diode_1d_iv_coarse.npz"), Kind::Comparison), QString());
        QCOMPARE(w->overlays().size(), std::size_t{1});
        QCOMPARE(p->model().series.size(), std::size_t{2});
        QCOMPARE(p->model().series[1].label, QString("diode_1d_iv_coarse"));
    }

    void overlayFamilyGetsOneColourEachBeforeTheComparison() {
        auto w = curvesOf(tmp_, "p2_ov_fam.ini");
        QVERIFY(w);
        PlotView* p = w->plotView();
        QCOMPARE(w->addOverlay(data("diode_1d_iv_fine.npz"), Kind::Family), QString());
        QCOMPARE(w->addOverlay(data("diode_1d_iv_coarse.npz"), Kind::Comparison), QString());
        QCOMPARE(w->addOverlay(data("diode_1d_iv_coarse.npz"), Kind::Family), QString());
        const auto& s = p->model().series;
        QCOMPARE(s.size(), std::size_t{4});   // primary, family x2, then the comparison
        QCOMPARE(s[1].label, QString("diode_1d_iv_fine"));
        QCOMPARE(s[2].label, QString("diode_1d_iv_coarse"));
        QCOMPARE(s[1].colour, tcad::desktop::theme::seriesColour(1));
        QCOMPARE(s[2].colour, tcad::desktop::theme::seriesColour(2));
        QVERIFY(s[1].line == tcad::desktop::plot::LineStyle::Solid && s[2].line == tcad::desktop::plot::LineStyle::Solid);
        QVERIFY(s[3].line == tcad::desktop::plot::LineStyle::Dashed);
        QVERIFY(s[2].x == sweepOf("diode_1d_iv_coarse.npz").voltages);
        for (const auto& ser : s) QVERIFY(ser.in_legend);
        snapshot(w.get(), "overlays");
        // the same file twice in the family is refused
        QVERIFY(!w->addOverlay(data("diode_1d_iv_fine.npz"), Kind::Family).isEmpty());
        QCOMPARE(w->overlays().size(), std::size_t{3});
    }

    void overlayRefusesAMismatchNamingIt_data() {
        QTest::addColumn<QString>("file");
        QTest::addColumn<QString>("reason");
        QTest::newRow("contact") << "diode_1d_iv_cathode.npz" << "swept contact is 'cathode', the open result's is 'anode'";
        QTest::newRow("quantity") << "diode_1d_iv_quantity.npz" << "capacitance sweep, the open result is a current sweep";
        QTest::newRow("contact first") << "cv.npz" << "swept contact is 'gate'";  // the FIRST mismatch is named
        QTest::newRow("unit") << "diode_1d_iv_unit.npz" << "unit is 'mA/cm^2', the open result's is 'A/cm^2'";
        QTest::newRow("channel") << "diode_1d_iv_channel.npz" << "no 'device' channel";
        QTest::newRow("no sweep") << "diode_1d.npz" << "has no sweep";
        QTest::newRow("itself") << "diode_1d_iv.npz" << "the open result itself";
        QTest::newRow("missing") << "no_such_file.npz" << "file not found";
        QTest::newRow("corrupt") << "corrupt.npz" << "";
    }
    void overlayRefusesAMismatchNamingIt() {
        QFETCH(QString, file);
        QFETCH(QString, reason);
        auto w = curvesOf(tmp_, "p2_ov_refuse.ini");
        QVERIFY(w);
        const QString why = w->addOverlay(data(file), Kind::Family);
        QVERIFY2(!why.isEmpty(), "accepted");
        QVERIFY2(why.contains(reason), qPrintable(why));
        QVERIFY2(w->lastError().contains(why), qPrintable(w->lastError()));   // reported, named
        QVERIFY(w->overlays().empty());
        QCOMPARE(w->plotView()->model().series.size(), std::size_t{1});
    }

    void overlayLabelsEditRemoveAndClear() {
        auto w = curvesOf(tmp_, "p2_ov_edit.ini");
        QVERIFY(w);
        PlotView* p = w->plotView();
        QVERIFY(w->addOverlay(data("diode_1d_iv_fine.npz"), Kind::Family).isEmpty());
        QVERIFY(w->addOverlay(data("diode_1d_iv_coarse.npz"), Kind::Comparison).isEmpty());
        auto* list = child<QListWidget>(w->plotPanel(), "OverlayList");
        QCOMPARE(list->count(), 2);
        QVERIFY(list->isEnabled());
        // edit a label in the list: the legend and readout follow
        list->item(0)->setText("Na = 1e17");
        QCOMPARE(w->overlays()[0].label, QString("Na = 1e17"));
        QCOMPARE(p->model().series[1].label, QString("Na = 1e17"));
        QVERIFY(!w->setOverlayLabel(0, "  "));   // an empty label is refused and undone
        QCOMPARE(list->item(0)->text(), QString("Na = 1e17"));
        // remove through the panel's button
        list->setCurrentRow(0);
        child<QPushButton>(w->plotPanel(), "RemoveOverlayButton")->click();
        QCOMPARE(w->overlays().size(), std::size_t{1});
        QCOMPARE(p->model().series.size(), std::size_t{2});
        // log: the overlays too show |I| (decision 8), their values raw
        logAction(w.get())->trigger();
        QVERIFY(p->model().y.scale == tcad::desktop::plot::Scale::Log);
        QVERIFY(p->model().series[1].y == sweepOf("diode_1d_iv_coarse.npz").channels[0].values);
        // other modes: no overlays drawn, controls off, adding refused
        QVERIFY(chooseMode(w.get(), ViewMode::Convergence));
        QVERIFY(!list->isEnabled());
        QVERIFY(w->addOverlay(data("diode_1d_iv_fine.npz"), Kind::Family).contains("Curves or C-V"));
        // another result: overlays are relative to one result, so they go
        QVERIFY(w->tryOpen(data("diode_1d_iv_fine.npz")));
        QVERIFY(w->overlays().empty());
    }

    void overlayFollowsTheSelectedChannel() {
        auto w = shown(ini("p2_ov_channel.ini"));
        QVERIFY(w);
        QVERIFY(w->tryOpen(data("diode_1d_iv_2ch.npz")));
        QVERIFY(chooseMode(w.get(), ViewMode::Curves));
        QVERIFY(w->setSweepChannel("extra"));
        QCOMPARE(w->addOverlay(data("diode_1d_iv_fine_2ch.npz"), Kind::Family), QString());
        const auto fine = sweepOf("diode_1d_iv_fine_2ch.npz");
        auto chan = [&](const char* name) {
            for (const auto& c : fine.channels)
                if (c.name == name) return c.values;
            return std::vector<double>{};
        };
        const auto& s = w->plotView()->model().series;
        QVERIFY(s.at(1).y == chan("extra"));      // the channel shown, not the first one
        QVERIFY(w->setSweepChannel("device"));
        QVERIFY(w->plotView()->model().series.at(1).y == chan("device"));
    }

    void overlaysInCVMode() {
        auto w = shown(ini("p2_ov_cv.ini"));
        QVERIFY(w);
        QVERIFY(w->tryOpen(data("cv.npz")));
        QCOMPARE(w->viewMode(), ViewMode::CV);
        QCOMPARE(w->addOverlay(data("cv_fine.npz"), Kind::Family), QString());
        const auto& s = w->plotView()->model().series;
        QCOMPARE(s.size(), std::size_t{2});
        QVERIFY(s[1].x == sweepOf("cv_fine.npz").voltages);
        const QString why = w->addOverlay(data("cv_as_current.npz"), Kind::Comparison);
        QVERIFY2(why.contains("current sweep, the open result is a capacitance sweep"), qPrintable(why));
    }

    // -- P2-S6: every curve mode, drawn (run at scales 1 / 1.5 / 2 by test_desktop_hidpi.py)
    void curveModeImagesProbe_data() {
        QTest::addColumn<QString>("file");
        QTest::addColumn<int>("mode");
        QTest::addColumn<QString>("overlay");   // "" none, else a family file
        QTest::newRow("field_1d") << "diode_1d.npz" << int(ViewMode::Field) << "";
        QTest::newRow("curves") << "diode_1d_iv.npz" << int(ViewMode::Curves) << "";
        QTest::newRow("curves_overlays") << "diode_1d_iv.npz" << int(ViewMode::Curves) << "diode_1d_iv_fine.npz";
        QTest::newRow("cv") << "cv.npz" << int(ViewMode::CV) << "";
        QTest::newRow("transient") << "diode_1d_transient.npz" << int(ViewMode::Transient) << "";
        QTest::newRow("ac") << "diode_1d_ac.npz" << int(ViewMode::AC) << "";
        QTest::newRow("convergence") << "diode_1d_rejected.npz" << int(ViewMode::Convergence) << "";
        QTest::newRow("bands") << "diode_1d.npz" << int(ViewMode::Bands) << "";
        QTest::newRow("recombination") << "diode_1d.npz" << int(ViewMode::Recombination) << "";
        QTest::newRow("cut") << "mosfet_2d.npz" << int(ViewMode::Cut) << "";
    }
    void curveModeImagesProbe() {
        QFETCH(QString, file);
        QFETCH(int, mode);
        QFETCH(QString, overlay);
        auto w = opened("p2_s6_images.ini", file.toUtf8().constData());
        QVERIFY(w);
        QVERIFY(chooseMode(w.get(), static_cast<ViewMode>(mode)));
        if (!overlay.isEmpty())
            QCOMPARE(w->addOverlay(data(overlay), tcad::desktop::plot::OverlayCurve::Kind::Family), QString());
        PlotView* p = w->plotView();
        QTRY_VERIFY_WITH_TIMEOUT(!p->model().series.empty(), 120000);   // bands/R: the backend
        QApplication::processEvents();
        QString why;
        const int probed = probeSeriesColours(p, &why);
        QVERIFY2(probed >= 0, qPrintable(why));
        // every series probed, except where another series coincides with it everywhere
        QVERIFY2(probed >= 1 && probed >= static_cast<int>(p->model().series.size()) - 2,
                 qPrintable(QString("%1 of %2 series probed").arg(probed).arg(p->model().series.size())));
        QVERIFY(!p->ticks(PlotView::Which::X).empty() && !p->ticks(PlotView::Which::Y).empty());
        if (p->model().legend) QVERIFY(!p->legendRect().isEmpty());
        if (!p->model().title.isEmpty()) QVERIFY(!p->titleRect().isEmpty());
    }

    void curveModesSurviveAdversarialFiles() {
        using tcad::desktop::plot::Scale;
        auto w = shown(ini("p2_s6_adversarial.ini"));
        QVERIFY(w);
        PlotView* p = w->plotView();

        // every point unconverged: nothing to plot, said so with the note, no invented axes
        QVERIFY(w->tryOpen(data("adv_all_unconverged.npz")));
        QVERIFY(chooseMode(w.get(), ViewMode::Curves));
        QVERIFY(p->model().series.empty());
        QVERIFY2(p->model().empty_text.contains("did not converge") &&
                     p->model().empty_text.contains("Nothing to plot"), qPrintable(p->model().empty_text));
        logAction(w.get())->trigger();
        QVERIFY(p->model().series.empty());
        logAction(w.get())->trigger();
        QVERIFY(hoverEverywhere(p).isEmpty());
        QVERIFY(chooseMode(w.get(), ViewMode::Convergence));   // the trace is still there
        QVERIFY(!p->model().series.empty());

        // one point: drawn as a marker, with a finite, non-degenerate view
        QVERIFY(w->tryOpen(data("adv_one_point.npz")));
        QVERIFY(chooseMode(w.get(), ViewMode::Curves));
        QCOMPARE(p->model().series.at(0).x.size(), std::size_t{1});
        QVERIFY(p->xView().lo < p->xView().hi && p->yView().lo < p->yView().hi);
        QString why;
        QVERIFY2(probeSeriesColours(p, &why) == 1, qPrintable(why));
        QCOMPARE(hoverSample(p, 0, 0), entry(p, 0, 0));

        // a trace whose steps carry no metrics: offered (the trace exists), and says so
        QVERIFY(w->tryOpen(data("adv_trace_no_metrics.npz")));
        QVERIFY(chooseMode(w.get(), ViewMode::Convergence));
        QVERIFY(p->model().series.empty());
        QVERIFY2(p->model().empty_text.contains("no metrics"), qPrintable(p->model().empty_text));

        // an all-NaN channel beside a good one: the good one drawn, NaN never read out
        QVERIFY(w->tryOpen(data("adv_nan_channel.npz")));
        QVERIFY(chooseMode(w.get(), ViewMode::Transient));
        QCOMPARE(p->model().series.size(), std::size_t{2});
        QVERIFY2(probeSeriesColours(p, &why) == 1, qPrintable(why));   // anode; cathode has nothing to draw
        QVERIFY(hoverEverywhere(p).isEmpty());

        // AC at one frequency: a single-decade log view, both axes drawn
        QVERIFY(w->tryOpen(data("adv_ac_one_freq.npz")));
        QVERIFY(chooseMode(w.get(), ViewMode::AC));
        QVERIFY(p->model().x.scale == Scale::Log);
        QVERIFY(p->xView().lo > 0 && p->xView().lo < p->xView().hi);
        // One value per axis is centred on each axis, so C's and G's single
        // markers land on the SAME pixel: G, drawn last, is the one seen.
        QVERIFY2(probeSeriesColours(p, &why) >= 0, qPrintable(why));
        const QPointF c0 = p->toPixel(p->model().series[0].x[0], p->model().series[0].y[0], p->model().series[0].axis);
        const QPointF g0 = p->toPixel(p->model().series[1].x[0], p->model().series[1].y[0], p->model().series[1].axis);
        QVERIFY(QLineF(c0, g0).length() < 1.0);
        const double dpr = p->devicePixelRatioF();
        QCOMPARE(p->grab().toImage().pixelColor(qRound(g0.x() * dpr), qRound(g0.y() * dpr)), p->model().series[1].colour);
    }

    // Plan 16.4's last bench row: the 1D bands through a WARM backend (reported).
    void bandsWithAWarmBackendIsReported() {
        auto w = opened("p2_s6_bands_bench.ini", "diode_1d.npz");
        QVERIFY(w);
        QTRY_VERIFY_WITH_TIMEOUT(w->backendClient() != nullptr, 5000);   // warmed after a 1D open with Bands
        QTRY_VERIFY_WITH_TIMEOUT(w->backendClient()->state() == tcad::desktop::BackendClient::State::Ready, 120000);
        QElapsedTimer t;
        t.start();
        QVERIFY(chooseMode(w.get(), ViewMode::Bands));
        QTRY_VERIFY_WITH_TIMEOUT(w->plotView()->model().series.size() == 4, 120000);
        qInfo("1D bands through a warm backend: %.1f ms (request to curves drawn)",
              static_cast<double>(t.nsecsElapsed()) * 1e-6);
    }

    // -- the view, driven through the shell ---------------------------------
    void fieldListLogFitAndHoverDriveTheView() {
        auto w = shown(ini("drive.ini"));
        QVERIFY(w);
        QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
        FieldView* v = w->fieldView();

        // select a field by clicking its list row
        QListWidget* list = w->fieldList();
        const int row = static_cast<int>(fieldRows(w.get()).back());  // the last FIELD (derived maps follow)
        QTest::mouseClick(list->viewport(), Qt::LeftButton, {}, list->visualItemRect(list->item(row)).center());
        QCOMPARE(QString::fromStdString(v->field()), list->item(row)->text());

        // log scale through the View menu's action
        QAction* log = nullptr;
        for (QAction* a : w->findChildren<QAction*>())
            if (a->text() == "Log scale") log = a;
        QVERIFY(log);
        log->trigger();
        QVERIFY(v->logScale());
        log->trigger();
        QVERIFY(!v->logScale());

        // hover: the status-bar readout is what readoutAt reports there
        const QPoint centre(v->width() / 2, v->height() / 2);
        QMouseEvent move(QEvent::MouseMove, QPointF(centre), v->mapToGlobal(QPointF(centre)), Qt::NoButton,
                         Qt::NoButton, Qt::NoModifier);
        QApplication::sendEvent(v, &move);
        QString expected;
        QVERIFY(v->readoutAt(centre.x(), centre.y(), &expected));
        auto* readout = w->findChild<QLabel*>("Readout");
        QVERIFY(readout);
        QCOMPARE(readout->text(), expected);

        // Fit (the F shortcut) undoes a zoom
        vtkCamera* cam = v->renderer()->GetActiveCamera();
        const double fitted = cam->GetParallelScale();
        cam->Zoom(2.0);
        QVERIFY(cam->GetParallelScale() != fitted);
        v->setFocus();
        QTest::keyClick(w.get(), Qt::Key_F);
        QCOMPARE(cam->GetParallelScale(), fitted);
    }
};

int main(int argc, char** argv) {
    QSurfaceFormat::setDefaultFormat(QVTKOpenGLNativeWidget::defaultFormat());
    QApplication app(argc, argv);
    TestShell t;
    return QTest::qExec(&t, argc, argv);
}

#include "test_shell.moc"
