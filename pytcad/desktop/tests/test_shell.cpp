// Shell end-to-end tests (NATIVE-DESKTOP-PLAN.md section 15.13, S3b and
// S3f): the REAL MainWindow, shown in a real window, driven with QTest
// and synthesized input events.
//
// Test data comes from gui/tests/test_desktop_shell.py through
// TCAD_TEST_DATA: mosfet_2d.npz and resistor_3d.npz (solved), corrupt.npz,
// schema99.npz, notes.txt, layers3d.npz (S6: a synthetic 3D result with a
// current density, sweep snapshots and regions), and a copy of mosfet_2d.npz inside a
// directory named with non-ASCII characters. Every window uses its own
// settings file in a temporary directory -- never the user's.
#include "shell/app_settings.hpp"
#include "shell/display_panel.hpp"
#include "shell/info_panel.hpp"
#include "shell/main_window.hpp"
#include "shell/playback_panel.hpp"
#include "shell/view3d_panel.hpp"
#include "views/colormaps.hpp"
#include "data/contour_levels.hpp"
#include "views/field/field_view.hpp"

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
#include <QFile>
#include <QLabel>
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

    // -- theme (S3c) ---------------------------------------------------------
    void themeSwitchReachesQtAndVtk() {
        using namespace tcad::desktop::theme;
        const QString path = ini("theme.ini");
        {
            auto w = shown(path);
            QVERIFY(w);
            QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
            for (auto [choice, scheme] : {std::pair{Choice::Light, Scheme::Light}, std::pair{Choice::Dark, Scheme::Dark},
                                          std::pair{Choice::Light, Scheme::Light}}) {
                w->setThemeChoice(choice);
                QVERIFY(w->theme()->scheme() == scheme);
                const QPalette pal = QApplication::palette();
                QCOMPARE(pal.color(QPalette::Window), qcolor(T::Window, scheme));
                QCOMPARE(pal.color(QPalette::Base), qcolor(T::Base, scheme));
                QCOMPARE(pal.color(QPalette::Text), qcolor(T::Text, scheme));
                QCOMPARE(pal.color(QPalette::Highlight), qcolor(T::Accent, scheme));
                double bg[3];
                w->fieldView()->renderer()->GetBackground(bg);
                const Rgb want_bg = rgb(T::Background, scheme), want_fg = rgb(T::Text, scheme);
                QCOMPARE(bg[0], want_bg.r);
                QCOMPARE(bg[1], want_bg.g);
                QCOMPARE(bg[2], want_bg.b);
                for (vtkTextProperty* tp : {w->fieldView()->scalarBar()->GetTitleTextProperty(),
                                            w->fieldView()->scalarBar()->GetLabelTextProperty()}) {
                    const double* c = tp->GetColor();
                    QCOMPARE(c[0], want_fg.r);
                    QCOMPARE(c[1], want_fg.g);
                    QCOMPARE(c[2], want_fg.b);
                }
                // the rendered frame's corner is the background colour
                const QImage frame = w->fieldView()->grabFramebuffer();
                QCOMPARE(QColor(frame.pixel(2, 2)), qcolor(T::Background, scheme));
                // what ADS actually PAINTS follows too: the Fields panel's
                // empty area below its rows (a stylesheet palette(light)
                // fill, or the list's base) -- the palette checks above
                // passed while this was a stock grey (S3c screenshot).
                QApplication::processEvents();
                const QImage panel = w->fieldsDock()->grab().toImage();
                QCOMPARE(QColor(panel.pixel(panel.width() / 2, panel.height() - 6)), qcolor(T::Base, scheme));
            }
            w->close();
        }
        auto w2 = shown(path);  // the choice (Light, last) persists
        QVERIFY(w2);
        QVERIFY(w2->theme()->choice() == Choice::Light);
        QVERIFY(w2->theme()->scheme() == Scheme::Light);
    }

    // A theme applied at STARTUP (the saved choice) must be painted too --
    // the live-switch test above passed while a light startup still drew
    // a stock-grey Fields panel (S3c screenshot).
    void savedThemeIsPaintedAtStartup_data() {
        QTest::addColumn<QString>("choice");
        QTest::newRow("light") << "light";
        QTest::newRow("dark") << "dark";
    }
    void savedThemeIsPaintedAtStartup() {
        using namespace tcad::desktop::theme;
        QFETCH(QString, choice);
        // a fresh launch's palette, not whatever an earlier test left behind
        QApplication::setPalette(QApplication::style()->standardPalette());
        const QString path = ini("startup_" + choice + ".ini");
        {
            QSettings s(path, QSettings::IniFormat);
            s.setValue("theme/choice", choice);
        }
        auto w = shown(path);
        QVERIFY(w);
        QVERIFY(w->tryOpen(data("mosfet_2d.npz")));
        QApplication::processEvents();
        const Scheme scheme = choice == "light" ? Scheme::Light : Scheme::Dark;
        QVERIFY(w->theme()->scheme() == scheme);
        const QImage panel = w->fieldsDock()->grab().toImage();
        QCOMPARE(QColor(panel.pixel(panel.width() / 2, panel.height() - 6)), qcolor(T::Base, scheme));
        const QImage frame = w->fieldView()->grabFramebuffer();
        QCOMPARE(QColor(frame.pixel(2, 2)), qcolor(T::Background, scheme));
        QCOMPARE(w->fieldList()->palette().color(QPalette::Text), qcolor(T::Text, scheme));
        // ADS paints from explicit token colours, not palette(...) references
        const QString qss = w->dockManager()->styleSheet();
        QVERIFY2(!qss.contains("palette("), "ADS stylesheet still reads the palette");
        QVERIFY(qss.contains(qcolor(T::Window, scheme).name()));
        QVERIFY(qss.contains(qcolor(T::Base, scheme).name()));
    }

    void systemThemeFollowsTheColourScheme() {
        using namespace tcad::desktop::theme;
        auto w = shown(ini("theme_system.ini"));
        QVERIFY(w);
        w->setThemeChoice(Choice::System);
        QStyleHints* hints = QGuiApplication::styleHints();
        hints->setColorScheme(Qt::ColorScheme::Light);
        QTRY_VERIFY(w->theme()->scheme() == Scheme::Light);
        QCOMPARE(QApplication::palette().color(QPalette::Window), qcolor(T::Window, Scheme::Light));
        hints->setColorScheme(Qt::ColorScheme::Dark);
        QTRY_VERIFY(w->theme()->scheme() == Scheme::Dark);
        QCOMPARE(QApplication::palette().color(QPalette::Window), qcolor(T::Window, Scheme::Dark));
        w->setThemeChoice(Choice::Light);  // an explicit choice stops following the OS
        hints->setColorScheme(Qt::ColorScheme::Dark);
        QApplication::processEvents();
        QVERIFY(w->theme()->scheme() == Scheme::Light);
        hints->unsetColorScheme();
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
