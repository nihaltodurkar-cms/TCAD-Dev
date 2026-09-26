// Run dock, Console, Run/Stop and open on success, in the real window
// (NATIVE-DESKTOP-PLAN.md 17.11, P3-S4). Every run goes through the real
// backend service and the real solver: the Run dock's form -> the backend's
// configure_run/job_text -> the JobRunner -> the result opened in the view.
//
// Run by gui/tests/test_desktop_run_shell.py, which sets TCAD_TEST_DATA:
//   diode_spec.json       a DeviceSpec file (the diode)
//   project_models.json   a project: a 2D p-n structure, an armed sweep
//                         (anode 0..0.2 V by 0.1) and models with auger off
//   flow_only.json        a project with a process flow and no structure
//   prev.npz              a result to have open before a run
#include "data/npz.hpp"
#include "data/result_model.hpp"
#include "run/batch_controller.hpp"
#include "run/job_runner.hpp"
#include "run/run_controller.hpp"
#include "shell/app_settings.hpp"
#include "shell/console_panel.hpp"
#include "shell/main_window.hpp"
#include "shell/run_panel.hpp"
#include "shell/telemetry_panel.hpp"
#include "run/telemetry.hpp"
#include "views/plot/plot_view.hpp"
#include "views/plot/curve_modes.hpp"

#include <DockManager.h>
#include <DockWidget.h>

#include <QAction>
#include <QApplication>
#include <QComboBox>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPushButton>
#include <QLocale>
#include <QSplitter>
#include <QStandardItemModel>
#include <QStatusBar>
#include <QTemporaryDir>
#include <QtTest/QtTest>

#include <algorithm>
#include <cmath>
#include <memory>
#include <vector>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

using tcad::desktop::AppSettings;
using tcad::desktop::ConsolePanel;
using tcad::desktop::DeviceSource;
using tcad::desktop::MainWindow;
using tcad::desktop::RunController;
using tcad::desktop::RunKind;
using tcad::desktop::RunPanel;
using tcad::desktop::TelemetryPanel;
using tcad::desktop::plot::ViewMode;

namespace {

bool processAlive(qint64 pid) {
    HANDLE h = OpenProcess(SYNCHRONIZE, FALSE, static_cast<DWORD>(pid));
    if (!h) return false;
    const bool alive = WaitForSingleObject(h, 0) == WAIT_TIMEOUT;
    CloseHandle(h);
    return alive;
}

QStringList errorBoxTitles() {
    QStringList out;
    for (QWidget* w : QApplication::topLevelWidgets())
        if (w->objectName() == "ErrorBox" && w->isVisible()) out << w->windowTitle();
    return out;
}

void closeErrorBoxes() {
    for (QWidget* w : QApplication::topLevelWidgets())
        if (w->objectName() == "ErrorBox") w->close();
}

// What a window's run controller reported.
struct RunLog {
    int finished = 0, failed = 0, canceled = 0;
    QString result, title, summary;
    explicit RunLog(RunController* c) {
        QObject::connect(c, &RunController::runFinished, [this](const QString& p) {
            ++finished;
            result = p;
        });
        QObject::connect(c, &RunController::runFailed, [this](const QString& t, const QString& s, const QString&) {
            ++failed;
            title = t;
            summary = s;
        });
        QObject::connect(c, &RunController::runCanceled, [this] { ++canceled; });
    }
    int ended() const { return finished + failed + canceled; }
};

}  // namespace

class TestRunShell : public QObject {
    Q_OBJECT

    QTemporaryDir tmp_;

    static QString data(const QString& name) {
        return QDir(qEnvironmentVariable("TCAD_TEST_DATA")).absoluteFilePath(name);
    }
    QString runsDir(const QString& name) const { return tmp_.filePath("runs_" + name); }

    // A shown window whose runs go to their own directory.
    std::unique_ptr<MainWindow> window(const QString& name) {
        auto settings = AppSettings::atFile(tmp_.filePath(name + ".ini"));
        settings->setValue("run/dir", runsDir(name));
        auto w = std::make_unique<MainWindow>(std::move(settings));
        w->show();
        if (!QTest::qWaitForWindowExposed(w.get())) return nullptr;
        return w;
    }

    static bool loaded(MainWindow* w, const QString& ref, int ms = 120000) {
        return QTest::qWaitFor(
            [&] {
                const auto& d = w->runController()->device();
                return d && d->ref == ref;
            },
            ms);
    }

    static void loadExample(MainWindow* w, const QString& name) {
        w->runPanel()->loadExample(name);
        QVERIFY2(loaded(w, name), qPrintable("the example did not load: " + w->runPanel()->deviceLabel()->text()));
    }

    // Click Run and wait for the run's end.
    static void clickRunAndWait(MainWindow* w, RunLog& log, int ms = 180000) {
        const int before = log.ended();
        QTest::mouseClick(w->runPanel()->runButton(), Qt::LeftButton);
        QVERIFY(QTest::qWaitFor([&] { return log.ended() > before; }, ms));
    }

    // TCAD_SHELL_SNAPSHOT=<dir>: saves the whole window as <name>.png, to look at.
    static void snapshot(MainWindow* w, const QString& name) {
        const QString dir = qEnvironmentVariable("TCAD_SHELL_SNAPSHOT");
        if (dir.isEmpty()) return;
        w->consolePanel()->flush();  // the batched lines, drawn
        QApplication::processEvents();
        w->grab().save(QDir(dir).filePath(name + ".png"));
    }

    static QStringList runFiles(const QString& dir, const QStringList& patterns = {"*"}) {
        return QDir(dir).entryList(patterns, QDir::Files);
    }

    // A finished run's result: opened, from the runs directory, in the view's
    // natural mode, with the console holding its stage lines and no record text.
    void checkOpened(MainWindow* w, const RunLog& log, const QString& runs) {
        QCOMPARE(log.failed, 0);
        QCOMPARE(log.finished, 1);
        QVERIFY(samePathInDir(w->resultPath(), runs));
        QCOMPARE(QFileInfo(w->resultPath()).absoluteFilePath(), QFileInfo(log.result).absoluteFilePath());
        QVERIFY(w->result() != nullptr);
        // The natural view (17.2): a sweep in Curves, and so on; else an opened file's default.
        ViewMode want = tcad::desktop::plot::defaultMode(*w->result());
        switch (w->runController()->lastKind()) {
            case RunKind::Sweep: want = ViewMode::Curves; break;
            case RunKind::Transient: want = ViewMode::Transient; break;
            case RunKind::AC: want = ViewMode::AC; break;
            case RunKind::CV: want = ViewMode::CV; break;
            default: break;
        }
        QVERIFY2(w->viewMode() == want, qPrintable(QString("mode %1, want %2")
                                                        .arg(static_cast<int>(w->viewMode()))
                                                        .arg(static_cast<int>(want))));
        QVERIFY(w->settings().recentFiles().contains(QFileInfo(log.result).absoluteFilePath()));
        w->consolePanel()->flush();
        const QStringList lines = w->consolePanel()->lines();
        QVERIFY2(!lines.filter(QRegularExpression("^PYTCAD_STAGE=")).isEmpty(), qPrintable(lines.join('\n').right(2000)));
        for (const QString& l : lines)
            QVERIFY2(!l.startsWith("PYTCAD_PROGRESS") && !l.startsWith("RESULT_PATH"), qPrintable(l));
        QVERIFY(runFiles(runs, {"job-*.json", "*.tmp.npz"}).isEmpty());
        QVERIFY(w->runAction()->isEnabled() && !w->stopAction()->isEnabled());
        QVERIFY(w->runPanel()->runButton()->isEnabled() && !w->runPanel()->stopButton()->isEnabled());
    }
    static bool samePathInDir(const QString& file, const QString& dir) {
        return QDir::cleanPath(QFileInfo(file).absolutePath()).compare(QDir::cleanPath(QFileInfo(dir).absoluteFilePath()),
                                                                      Qt::CaseInsensitive) == 0;
    }

private slots:
    void initTestCase() {
        QVERIFY(tmp_.isValid());
        for (const char* f : {"diode_spec.json", "project_models.json", "flow_only.json", "prev.npz"})
            QVERIFY2(QFileInfo::exists(data(f)), f);
    }
    void cleanup() { closeErrorBoxes(); }

    // -- the layout: the Run and Console docks cost the view nothing -----------------
    // Docked beside the view they cut it to 1014 x 616 of a 1500 x 950 window
    // (measured), which also broke the curve-image probes of the P2 shell
    // tests. Tabbed into the left column, the view is the size it is with
    // both docks closed -- in a fresh window and after Reset layout.
    void theRunDocksCostTheViewNothing() {
        for (bool reset : {false, true}) {
            auto w = window(reset ? "layout_reset" : "layout_fresh");
            QVERIFY(w);
            if (reset) w->resetLayout();
            QApplication::processEvents();
            const QSize with = w->centralSplitter()->size();
            QVERIFY(w->runDock()->dockAreaWidget() == w->fieldsDock()->dockAreaWidget());
            QVERIFY(w->consoleDock()->dockAreaWidget() == w->infoDock()->dockAreaWidget());
            QVERIFY(w->telemetryDock()->dockAreaWidget() == w->infoDock()->dockAreaWidget());  // P3-S5
            QVERIFY(!w->runDock()->isClosed() && !w->consoleDock()->isClosed() && !w->telemetryDock()->isClosed());
            // The tabs a result needs stay in front.
            QVERIFY(w->fieldsDock()->isCurrentTab() && w->displayDock()->isCurrentTab());
            w->runDock()->toggleView(false);
            w->consoleDock()->toggleView(false);
            w->telemetryDock()->toggleView(false);
            QApplication::processEvents();
            const QSize without = w->centralSplitter()->size();
            qInfo("%s: view %dx%d with the docks, %dx%d without", reset ? "reset" : "fresh", with.width(),
                  with.height(), without.width(), without.height());
            QCOMPARE(with, without);
        }
    }

    // -- the status bar shows the run's status ----------------------------------------
    // Found looking at S4's window grabs: the status bar was blank while its
    // currentMessage() held "Run finished in ..." -- the hover readout, a
    // permanent widget with stretch 1, left the temporary message no width.
    void theStatusMessageIsDrawn() {
        auto w = window("status");
        QVERIFY(w);
        auto darkPixels = [&] {
            QApplication::processEvents();
            const QImage img = w->statusBar()->grab().toImage();
            int n = 0;
            for (int y = 0; y < img.height(); ++y)
                for (int x = 0; x < img.width() / 2; ++x) n += qGray(img.pixel(x, y)) < 100;
            return n;
        };
        const int blank = darkPixels();
        w->statusBar()->showMessage("Running: sweep point 3/10 (12 s)");
        const int shown = darkPixels();
        QVERIFY2(shown > blank + 50, qPrintable(QString("dark pixels %1 blank, %2 with the message").arg(blank).arg(shown)));
    }

    // -- the lazy backend rule, kept -------------------------------------------------
    void noPythonUntilTheRunDockIsUsed() {
        auto w = window("lazy");
        QVERIFY(w);
        QTest::qWait(1500);
        QVERIFY(!w->backendClient());  // the Run and Console docks start nothing
        QVERIFY(!w->runDock()->isClosed() && !w->consoleDock()->isClosed());
        QVERIFY(!w->runPanel()->isVisible());  // a background tab
        // Bringing the Run tab to the front lists the examples, and loads the diode.
        w->runDock()->setAsCurrentTab();
        QVERIFY(QTest::qWaitFor([&] { return w->runPanel()->exampleCombo()->count() > 0; }, 120000));
        QVERIFY(loaded(w.get(), "diode_1d"));
        QVERIFY(w->runPanel()->exampleCombo()->findText("mosfet_2d") >= 0);
    }

    // -- run -> view, each run kind ---------------------------------------------------
    void biasRunOpens() {
        auto w = window("bias");
        QVERIFY(w);
        RunLog log(w->runController());
        loadExample(w.get(), "diode_1d");
        w->runPanel()->setKind(RunKind::Bias);
        clickRunAndWait(w.get(), log);
        checkOpened(w.get(), log, runsDir("bias"));
        QCOMPARE(w->result()->dimensionality(), 1);
        QVERIFY(w->result()->solved_bias());
        QVERIFY(w->statusBar()->currentMessage().startsWith("Run finished in"));
        // Only the result is left in the runs directory.
        QCOMPARE(runFiles(runsDir("bias")), QStringList{QFileInfo(log.result).fileName()});
    }

    void equilibriumRunOpens() {
        auto w = window("eq");
        QVERIFY(w);
        RunLog log(w->runController());
        loadExample(w.get(), "diode_1d");
        w->runPanel()->setKind(RunKind::Equilibrium);
        clickRunAndWait(w.get(), log);
        checkOpened(w.get(), log, runsDir("eq"));
        QVERIFY(!w->result()->solved_bias());
    }

    void sweepRunOpensInCurves() {
        auto w = window("sweep");
        QVERIFY(w);
        RunLog log(w->runController());
        loadExample(w.get(), "diode_1d");
        RunPanel* p = w->runPanel();
        p->setKind(RunKind::Sweep);
        p->combo("SweepContact")->setCurrentText("anode");
        p->field("SweepStart")->setText("0");
        p->field("SweepStop")->setText("0.3");
        p->field("SweepStep")->setText("0.1");
        clickRunAndWait(w.get(), log);
        checkOpened(w.get(), log, runsDir("sweep"));
        QCOMPARE(static_cast<int>(w->result()->sweep_points()), 4);
        QVERIFY(w->viewMode() == ViewMode::Curves);
        w->runDock()->setAsCurrentTab();
        w->consoleDock()->setAsCurrentTab();
        snapshot(w.get(), "s4_sweep_run");
    }

    void transientRunOpens() {
        auto w = window("transient");
        QVERIFY(w);
        RunLog log(w->runController());
        loadExample(w.get(), "diode_1d");
        RunPanel* p = w->runPanel();
        p->setKind(RunKind::Transient);
        p->combo("TransientContact")->setCurrentText("anode");
        p->combo("TransientWaveform")->setCurrentText("step");
        p->field("TransientV0")->setText("0.3");
        p->field("TransientV1")->setText("0");
        p->field("TransientTEnd")->setText("1e-9");
        p->field("TransientDt0")->setText("1e-10");
        clickRunAndWait(w.get(), log);
        checkOpened(w.get(), log, runsDir("transient"));
        QVERIFY(w->result()->has_transient());
        QVERIFY(w->viewMode() == ViewMode::Transient);
    }

    void acRunOpens() {
        auto w = window("ac");
        QVERIFY(w);
        RunLog log(w->runController());
        loadExample(w.get(), "diode_1d");
        RunPanel* p = w->runPanel();
        p->setKind(RunKind::AC);
        p->combo("AcContact")->setCurrentText("anode");
        p->field("AcFStart")->setText("1");
        p->field("AcFStop")->setText("1e9");
        p->field("AcPoints")->setText("7");
        clickRunAndWait(w.get(), log);
        checkOpened(w.get(), log, runsDir("ac"));
        QCOMPARE(static_cast<int>(w->result()->ac_points()), 7);
        QVERIFY(w->viewMode() == ViewMode::AC);
    }

    void cvRunOpens() {
        auto w = window("cv");
        QVERIFY(w);
        RunLog log(w->runController());
        RunPanel* p = w->runPanel();
        p->setKind(RunKind::CV);  // no device needed
        QVERIFY(!p->sourceCombo()->isEnabled() && !p->backendCombo()->isEnabled());
        p->field("CvVStep")->setText("0.25");
        clickRunAndWait(w.get(), log);
        checkOpened(w.get(), log, runsDir("cv"));
        QCOMPARE(static_cast<int>(w->result()->sweep_points()), 17);  // -2..2 by 0.25
        QVERIFY(w->viewMode() == ViewMode::CV);
    }

    void twoDAndThreeDRunsOpen() {
        auto w = window("dims");
        QVERIFY(w);
        RunLog log(w->runController());
        loadExample(w.get(), "mosfet_2d");
        clickRunAndWait(w.get(), log);
        checkOpened(w.get(), log, runsDir("dims"));
        QCOMPARE(w->result()->dimensionality(), 2);
        QVERIFY(w->viewMode() == ViewMode::FieldMap);
        loadExample(w.get(), "resistor_3d");
        clickRunAndWait(w.get(), log);
        QCOMPARE(log.failed, 0);
        QCOMPARE(log.finished, 2);
        QCOMPARE(w->result()->dimensionality(), 3);
        QVERIFY(w->viewMode() == ViewMode::FieldMap);
    }

    // -- device sources ----------------------------------------------------------------
    void aDeviceFileRuns() {
        auto w = window("specfile");
        QVERIFY(w);
        RunLog log(w->runController());
        w->runPanel()->loadFile(DeviceSource::SpecFile, data("diode_spec.json"));
        QVERIFY(loaded(w.get(), data("diode_spec.json")));
        QVERIFY(w->runPanel()->deviceLabel()->text().contains("anode"));
        clickRunAndWait(w.get(), log);
        checkOpened(w.get(), log, runsDir("specfile"));
    }

    void aProjectRunsWithItsSweepAndModels() {
        auto w = window("project");
        QVERIFY(w);
        RunLog log(w->runController());
        RunPanel* p = w->runPanel();
        p->loadFile(DeviceSource::Project, data("project_models.json"));
        QVERIFY(loaded(w.get(), data("project_models.json")));
        QVERIFY(p->kind() == RunKind::Sweep);  // the project's armed sweep, selected
        QCOMPARE(p->field("SweepStop")->text(), QString("0.2"));
        clickRunAndWait(w.get(), log);
        checkOpened(w.get(), log, runsDir("project"));
        QCOMPARE(static_cast<int>(w->result()->sweep_points()), 3);
        const auto record = w->result()->record();
        QVERIFY(record.has_value());
        QVERIFY2((*record)["models"]["auger"] == false, (*record)["models"].dump().c_str());
    }

    void aFlowOnlyProjectIsRefusedNamed() {
        auto w = window("flow");
        QVERIFY(w);
        w->runPanel()->loadFile(DeviceSource::Project, data("flow_only.json"));
        QVERIFY(QTest::qWaitFor([] { return !errorBoxTitles().isEmpty(); }, 120000));
        QCOMPARE(errorBoxTitles(), QStringList{"Nothing to run"});
        QVERIFY(w->lastError().contains("process flow only"));
        QVERIFY(!w->runController()->device().has_value());
    }

    // -- refusals ------------------------------------------------------------------------
    void anInvalidConfigurationIsRefusedNamed() {
        auto w = window("refuse");
        QVERIFY(w);
        RunLog log(w->runController());
        loadExample(w.get(), "diode_1d");
        RunPanel* p = w->runPanel();
        p->setKind(RunKind::Sweep);
        p->field("SweepStep")->setText("0");
        clickRunAndWait(w.get(), log, 60000);
        QCOMPARE(log.failed, 1);
        QCOMPARE(log.title, QString("Invalid sweep configuration"));  // QML's arm-time title
        QCOMPARE(log.summary, QString("sweep step must be nonzero"));
        QCOMPARE(errorBoxTitles(), QStringList{"Invalid sweep configuration"});
        QVERIFY(runFiles(runsDir("refuse")).isEmpty());  // nothing ran
        QVERIFY(!w->result());
        // A value that is not a number never leaves the form.
        closeErrorBoxes();
        p->field("SweepStep")->setText("abc");
        QVERIFY(!p->requestRun());
        QCOMPARE(errorBoxTitles(), QStringList{"Invalid sweep configuration"});
        QVERIFY(w->lastError().contains("Step [V] must be a finite number"));
        QVERIFY(!w->runController()->busy());
    }

    // -- Stop ------------------------------------------------------------------------------
    void stopDuringTheSolve() {
        auto w = window("stop");
        QVERIFY(w);
        QVERIFY(w->tryOpen(data("prev.npz")));
        RunLog log(w->runController());
        loadExample(w.get(), "mosfet_2d");
        RunPanel* p = w->runPanel();
        p->setKind(RunKind::Sweep);
        p->combo("SweepContact")->setCurrentText("gate");
        p->field("SweepStart")->setText("0");
        p->field("SweepStop")->setText("2");
        p->field("SweepStep")->setText("0.02");  // 101 points: long enough to stop
        QTest::mouseClick(p->runButton(), Qt::LeftButton);
        tcad::desktop::JobRunner* runner = w->runController()->runner();
        QVERIFY(QTest::qWaitFor([&] { return runner->currentPid() > 0; }, 120000));
        const qint64 pid = runner->currentPid();
        const QString job = runner->currentJobPath();
        QVERIFY(QTest::qWaitFor([&] { return w->statusBar()->currentMessage().contains("sweep"); }, 120000));
        QTest::mouseClick(p->stopButton(), Qt::LeftButton);
        QVERIFY(QTest::qWaitFor([&] { return log.canceled == 1; }, 10000));
        QCOMPARE(log.finished + log.failed, 0);
        QVERIFY(!processAlive(pid));
        QVERIFY(!QFileInfo::exists(job));
        QVERIFY(runFiles(runsDir("stop")).isEmpty());
        QCOMPARE(QFileInfo(w->resultPath()).fileName(), QString("prev.npz"));  // the previous result stays
        QVERIFY(w->runAction()->isEnabled() && !w->stopAction()->isEnabled());
        QVERIFY(errorBoxTitles().isEmpty());
        w->runDock()->setAsCurrentTab();
        w->consoleDock()->setAsCurrentTab();
        snapshot(w.get(), "s4_stopped");
    }

    void stopBeforeTheSolverStarts() {
        auto w = window("stop_early");
        QVERIFY(w);
        RunLog log(w->runController());
        loadExample(w.get(), "diode_1d");
        QTest::mouseClick(w->runPanel()->runButton(), Qt::LeftButton);
        QVERIFY(w->runController()->phase() == RunController::Phase::Preparing);
        QTest::mouseClick(w->runPanel()->stopButton(), Qt::LeftButton);
        QCOMPARE(log.canceled, 1);
        // The backend's replies still arrive: they must start nothing.
        QTest::qWait(4000);
        QCOMPARE(log.finished + log.failed, 0);
        QCOMPARE(w->runController()->runner()->liveRuns(), 0);
        QVERIFY(runFiles(runsDir("stop_early")).isEmpty());
        QVERIFY(!w->result());
    }

    void closingTheWindowMidRun() {
        qint64 pid = 0;
        QString job;
        {
            auto w = window("close");
            QVERIFY(w);
            loadExample(w.get(), "mosfet_2d");
            RunPanel* p = w->runPanel();
            p->setKind(RunKind::Sweep);
            p->combo("SweepContact")->setCurrentText("gate");
            p->field("SweepStart")->setText("0");
            p->field("SweepStop")->setText("2");
            p->field("SweepStep")->setText("0.02");
            QTest::mouseClick(p->runButton(), Qt::LeftButton);
            QVERIFY(QTest::qWaitFor([&] { return w->runController()->runner()->currentPid() > 0; }, 120000));
            pid = w->runController()->runner()->currentPid();
            job = w->runController()->runner()->currentJobPath();
            QTest::qWait(500);
            w->close();
        }  // destroyed mid-run
        QVERIFY(pid > 0);
        QVERIFY(!processAlive(pid));
        QVERIFY(!QFileInfo::exists(job));
        QVERIFY(runFiles(runsDir("close")).isEmpty());
        QVERIFY(errorBoxTitles().isEmpty());
    }

    void closingTheWindowWhileTheBackendPrepares() {
        // The backend's shutdown fails the pending configure_run call: its
        // failure must not be reported into the window being destroyed (the
        // P2-S3 crash class, 16.12). ~MainWindow tears the run controller
        // down before the backend for this.
        int failed = 0;
        {
            auto w = window("close_preparing");
            QVERIFY(w);
            loadExample(w.get(), "diode_1d");
            QObject::connect(w->runController(), &RunController::runFailed, [&failed] { ++failed; });
            QTest::mouseClick(w->runPanel()->runButton(), Qt::LeftButton);
            QVERIFY(w->runController()->phase() == RunController::Phase::Preparing);
        }  // destroyed with configure_run in flight
        QCoreApplication::processEvents();
        QCOMPARE(failed, 0);
        QVERIFY(errorBoxTitles().isEmpty());
        QVERIFY(runFiles(runsDir("close_preparing")).isEmpty());
    }

    // -- P3-S5: the Telemetry dock ---------------------------------------------------------
    // Its state and plot come from the PYTCAD_PROGRESS records of the real run;
    // a finished run's live plot IS its result's Convergence plot.
    void telemetryOfASweepIsItsConvergencePlot() {
        auto w = window("tele_sweep");
        QVERIFY(w);
        RunLog log(w->runController());
        std::vector<nlohmann::ordered_json> records;
        connect(w->runController(), &RunController::progress, this,
                [&records](const tcad::desktop::ProgressRecord& r) { records.push_back(r.value); });
        loadExample(w.get(), "diode_1d");
        RunPanel* p = w->runPanel();
        p->setKind(RunKind::Sweep);
        p->combo("SweepContact")->setCurrentText("anode");
        p->field("SweepStart")->setText("0");
        p->field("SweepStop")->setText("0.3");
        p->field("SweepStep")->setText("0.1");
        clickRunAndWait(w.get(), log);
        QCOMPARE(log.finished, 1);
        TelemetryPanel* t = w->telemetryPanel();
        const tcad::desktop::TelemetryModel& m = t->model();
        QVERIFY(!t->running());
        QVERIFY2(t->statusText().startsWith("Finished: Sweep of diode_1d"), qPrintable(t->statusText()));
        QVERIFY(t->elapsedText().startsWith("Elapsed: "));
        // Every record was folded in: the counts are the records'.
        auto count = [&](const char* e) {
            return static_cast<int>(std::count_if(records.begin(), records.end(), [e](const auto& r) { return r["event"] == e; }));
        };
        QVERIFY(count("newton") > 0);
        QCOMPARE(m.newtonRecords(), count("newton"));
        QCOMPARE(m.ignored(), 0);
        QVERIFY(m.done());
        QCOMPARE(m.dropped(), 0);  // a small run: nothing rate-limited, so the plots must be equal
        std::size_t traced = 0;
        for (const auto& s : m.trace()) traced += s.iterations.size();
        QCOMPARE(static_cast<int>(traced), count("newton"));
        // The labels are the last records'.
        nlohmann::ordered_json last_newton, last_sweep;
        std::string last_stage;
        for (const auto& r : records) {
            if (r["event"] == "newton") last_newton = r;
            if (r["event"] == "sweep_point") last_sweep = r;
            if (r["event"] == "stage") last_stage = r["stage"].get<std::string>();
            if (r["event"] == "sweep_point") last_stage = "sweep";
        }
        QCOMPARE(t->stageText(), QString("Stage: %1").arg(QString::fromStdString(last_stage)));
        QCOMPARE(t->iterationText(), QString("Newton: iteration %1 of stage %2 (%3 in all)")
                                         .arg(last_newton["iter"].get<int>())
                                         .arg(QString::fromStdString(last_newton["stage"].get<std::string>()))
                                         .arg(count("newton")));
        QCOMPARE(last_sweep["index"].get<int>(), 3);  // 0-based in the record
        QCOMPARE(t->sweepText(), QString("Sweep: point 4 of 4, anode = 0.3 V"));  // 1-based for people
        // The live plot is the result's Convergence plot, series for series.
        t->refreshPlot();
        const auto& live = t->plotView()->model();
        const auto post = tcad::desktop::plot::convergenceModel(*w->result());
        QCOMPARE(live.series.size(), post.series.size());
        QVERIFY(!live.series.empty());
        QVERIFY(live.y.scale == tcad::desktop::plot::Scale::Log);
        for (std::size_t i = 0; i < live.series.size(); ++i) {
            const auto& a = live.series[i];
            const auto& b = post.series[i];
            QCOMPARE(a.label, b.label);
            QCOMPARE(a.colour, b.colour);
            QVERIFY(a.line == b.line && a.in_legend == b.in_legend);
            QVERIFY2(a.x == b.x, qPrintable(a.label));
            QCOMPARE(a.y.size(), b.y.size());
            for (std::size_t j = 0; j < a.y.size(); ++j)
                QVERIFY2(a.y[j] == b.y[j] || (std::isnan(a.y[j]) && std::isnan(b.y[j])),
                         qPrintable(QString("%1[%2]: live %3, stored %4").arg(a.label).arg(j).arg(a.y[j]).arg(b.y[j])));
        }
        w->telemetryDock()->setAsCurrentTab();
        snapshot(w.get(), "s5_telemetry_sweep");
    }

    void telemetryIsLiveAndEndsWithTheRun() {
        auto w = window("tele_live");
        QVERIFY(w);
        RunLog log(w->runController());
        loadExample(w.get(), "mosfet_2d");
        RunPanel* p = w->runPanel();
        p->setKind(RunKind::Sweep);
        p->combo("SweepContact")->setCurrentText("gate");
        p->field("SweepStart")->setText("0");
        p->field("SweepStop")->setText("2");
        p->field("SweepStep")->setText("0.02");
        QTest::mouseClick(p->runButton(), Qt::LeftButton);
        TelemetryPanel* t = w->telemetryPanel();
        // While the solver runs: the sweep has moved, and Newton iterations are drawn.
        QVERIFY(QTest::qWaitFor([&] { return t->model().sweep() && t->model().sweep()->index >= 2; }, 180000));
        QVERIFY(w->runController()->busy() && t->running());
        QVERIFY2(t->statusText().startsWith("Running: Sweep of mosfet_2d"), qPrintable(t->statusText()));
        QVERIFY2(t->sweepText().startsWith("Sweep: point") && t->sweepText().contains(" of 101, gate = "),
                 qPrintable(t->sweepText()));
        t->refreshPlot();
        QVERIFY(!t->plotView()->model().series.empty());
        const int newton_at_stop = t->model().newtonRecords();
        QTest::mouseClick(p->stopButton(), Qt::LeftButton);
        QVERIFY(!t->running());
        QVERIFY2(t->statusText().startsWith("Canceled: "), qPrintable(t->statusText()));
        QVERIFY(QTest::qWaitFor([&] { return log.canceled == 1; }, 10000));
        QTest::qWait(300);
        QCOMPARE(t->model().newtonRecords(), newton_at_stop);  // nothing after the Stop
        // A new run starts the dock afresh.
        loadExample(w.get(), "diode_1d");
        p->setKind(RunKind::Bias);
        clickRunAndWait(w.get(), log);
        QVERIFY2(t->statusText().startsWith("Finished: Bias of diode_1d"), qPrintable(t->statusText()));
        QVERIFY(!t->model().sweep().has_value());
    }

    void telemetryOfATransientShowsItsSteps() {
        auto w = window("tele_transient");
        QVERIFY(w);
        RunLog log(w->runController());
        std::vector<nlohmann::ordered_json> steps;
        connect(w->runController(), &RunController::progress, this, [&steps](const tcad::desktop::ProgressRecord& r) {
            if (r.value["event"] == "transient_step") steps.push_back(r.value);
        });
        loadExample(w.get(), "diode_1d");
        RunPanel* p = w->runPanel();
        p->setKind(RunKind::Transient);
        p->combo("TransientContact")->setCurrentText("anode");
        p->field("TransientV0")->setText("0.3");
        p->field("TransientV1")->setText("0");
        p->field("TransientTEnd")->setText("1e-9");
        p->field("TransientDt0")->setText("1e-10");
        clickRunAndWait(w.get(), log);
        QCOMPARE(log.finished, 1);
        TelemetryPanel* t = w->telemetryPanel();
        QVERIFY(!steps.empty());
        QCOMPARE(t->model().transientSteps(), static_cast<int>(steps.size()));
        const double time = steps.back()["time"].get<double>();
        QCOMPARE(t->model().transient()->time, time);
        QVERIFY2(t->transientText().startsWith(QString("Transient: step %1, t = %2 s")
                                                   .arg(steps.size())
                                                   .arg(QLocale::c().toString(time, 'e', 3))),
                 qPrintable(t->transientText()));
    }

    void stageLevelProgressIsSaidNotHidden() {
        auto w = window("tele_cv");
        QVERIFY(w);
        RunLog log(w->runController());
        w->runPanel()->setKind(RunKind::CV);
        w->runPanel()->field("CvVStep")->setText("0.5");
        clickRunAndWait(w.get(), log);
        QCOMPARE(log.finished, 1);
        TelemetryPanel* t = w->telemetryPanel();
        QCOMPARE(t->stageText(), QString("Stage: cv"));
        QVERIFY2(t->noteText().contains("Stage-level progress only: a C-V run reports no Newton iterations"),
                 qPrintable(t->noteText()));
        t->refreshPlot();
        QVERIFY(t->plotView()->model().series.empty());
        QVERIFY2(t->plotView()->model().empty_text.startsWith("Stage-level progress only"),
                 qPrintable(t->plotView()->model().empty_text));
    }

    // -- the native app's backends: pytcad only (user decision, 2026-09-27, 17.13) ------
    void theNativeAppOffersPytcadOnly() {
        auto w = window("backends");
        QVERIFY(w);
        loadExample(w.get(), "diode_1d");  // a 1D device: the backend service lists devsim for it
        RunPanel* p = w->runPanel();
        // run.options has answered once the engine list is filled
        QVERIFY(QTest::qWaitFor([&] { return p->engineCombo()->findData("direct") >= 0; }, 60000));
        QCOMPARE(p->backendCombo()->count(), 1);
        QCOMPARE(p->backendCombo()->itemData(0).toString(), QString("pytcad"));
        // ... although the backend service itself still lists devsim (its
        // run.options is QML's list; the native app filters it).
        auto* reply = w->backendClient()->call("run.options", {{"spec", w->runController()->device()->spec}});
        QVERIFY(QTest::qWaitFor([&] { return reply->isFinished(); }, 60000));
        QVERIFY(reply->ok());
        bool listed = false;
        for (const auto& b : reply->result()["backends"]) listed |= b["id"] == "devsim";
        QVERIFY2(listed, "the service no longer lists devsim: this gate would pass vacuously");
    }

    void aRunOnAnotherBackendIsRefusedNamed() {
        auto w = window("backend_refused");
        QVERIFY(w);
        RunLog log(w->runController());
        loadExample(w.get(), "diode_1d");
        tcad::desktop::RunSettings s;
        s.kind = RunKind::Bias;
        s.backend = "devsim";  // not from the form (it cannot offer it): a programmatic caller
        QVERIFY(!w->runController()->run(s));
        QCOMPARE(log.failed, 1);
        QCOMPARE(log.title, QString("Backend not supported"));
        QVERIFY2(log.summary.contains("runs the pytcad backend only"), qPrintable(log.summary));
        QVERIFY(!w->runController()->busy());
        QCOMPARE(w->runController()->runner()->liveRuns(), 0);
        QVERIFY(runFiles(runsDir("backend_refused")).isEmpty());
    }

    void theSupportedBackendRunsWithAChosenEngine() {
        auto w = window("engine_direct");
        QVERIFY(w);
        RunLog log(w->runController());
        loadExample(w.get(), "diode_1d");
        RunPanel* p = w->runPanel();
        QVERIFY(QTest::qWaitFor([&] { return p->engineCombo()->findData("direct") >= 0; }, 60000));
        p->engineCombo()->setCurrentIndex(p->engineCombo()->findData("direct"));
        clickRunAndWait(w.get(), log);
        checkOpened(w.get(), log, runsDir("engine_direct"));
        const auto record = w->result()->record();
        QVERIFY(record.has_value());
        QCOMPARE(QString::fromStdString((*record)["backend"].get<std::string>()), QString("pytcad"));
    }

    void theTelemetryModelFoldsTheGrammar() {
        using J = nlohmann::ordered_json;
        tcad::desktop::TelemetryModel m;
        QVERIFY(m.apply(J{{"v", 1}, {"t", 0.1}, {"event", "stage"}, {"stage", "equilibrium"}}));
        QVERIFY(m.apply(J{{"v", 1}, {"event", "newton"}, {"stage", "equilibrium"}, {"iter", 0}, {"residual", {{"dpsi", 1.0}}}}));
        // a metric that appears midway: a gap before it; one that goes missing: a gap
        QVERIFY(m.apply(J{{"v", 1}, {"event", "newton"}, {"stage", "equilibrium"}, {"iter", 1},
                          {"residual", {{"dpsi", 0.5}, {"F", nullptr}}}}));
        QVERIFY(m.apply(J{{"v", 1}, {"event", "newton"}, {"stage", "bias"}, {"iter", 0},
                          {"residual", {{"F", 2.0}, {"dpsi", 0.1}, {"dn/n", 0.01}}}}));
        QCOMPARE(m.trace().size(), std::size_t{2});  // a new step per stage
        const auto& eq = m.trace()[0];
        QCOMPARE(eq.metrics.size(), std::size_t{2});
        QCOMPARE(eq.metrics[0].name, std::string("dpsi"));
        QCOMPARE(eq.metrics[1].values.size(), std::size_t{2});
        QVERIFY(std::isnan(eq.metrics[1].values[0]) && std::isnan(eq.metrics[1].values[1]));  // absent, then null
        const auto& bias = m.trace()[1];
        QCOMPARE(bias.metrics[0].name, std::string("F"));   // the order written, not sorted
        QCOMPARE(bias.metrics[2].name, std::string("dn/n"));
        // not the grammar: ignored and counted, nothing changed
        const int before = m.newtonRecords();
        QVERIFY(!m.apply(J{{"v", 2}, {"event", "stage"}, {"stage", "x"}}));
        QVERIFY(!m.apply(J{{"v", 1}, {"event", "newton"}, {"stage", "bias"}, {"iter", "one"}, {"residual", J::object()}}));
        QVERIFY(!m.apply(J{{"v", 1}, {"event", "newton"}, {"stage", "bias"}, {"iter", 2}, {"residual", {{"F", "big"}}}}));
        QVERIFY(!m.apply(J{{"v", 1}, {"event", "teleport"}}));
        QVERIFY(!m.apply(J::array({1, 2})));
        QCOMPARE(m.ignored(), 5);
        QCOMPARE(m.newtonRecords(), before);
        QCOMPARE(m.stage(), std::string("equilibrium"));
        QVERIFY(m.apply(J{{"v", 1}, {"event", "sweep_point"}, {"stage", "sweep"}, {"index", 2}, {"count", 5},
                          {"contact", nullptr}, {"value", nullptr}}));  // relayed by the MPI engine
        QVERIFY(m.sweep()->contact.empty() && std::isnan(m.sweep()->value));
        QVERIFY(m.apply(J{{"v", 1}, {"event", "done"}, {"result", "r.npz"}, {"dropped", 7}}));
        QVERIFY(m.done() && m.dropped() == 7);
        QVERIFY(m.apply(J{{"v", 1}, {"event", "error"}, {"error", "ValueError"}, {"message", "bad"}}));
        QCOMPARE(m.error()->message, std::string("bad"));
    }

    // -- P3-S6: families and comparisons by running ------------------------------------------
    // The diode's anode sweep, run and opened: the base of a family or comparison.
    void runDiodeSweep(MainWindow* w, RunLog& log) {
        loadExample(w, "diode_1d");
        RunPanel* p = w->runPanel();
        p->setKind(RunKind::Sweep);
        p->combo("SweepContact")->setCurrentText("anode");
        p->field("SweepStart")->setText("0");
        p->field("SweepStop")->setText("0.3");
        p->field("SweepStep")->setText("0.1");
        clickRunAndWait(w, log);
        QCOMPARE(log.finished, 1);
        QVERIFY(w->viewMode() == ViewMode::Curves);
    }
    static void setFamily(RunPanel* p, const char* stepped, const char* start, const char* stop, const char* step) {
        p->combo("FamilyContact")->setCurrentText(stepped);
        p->field("FamilyStart")->setText(start);
        p->field("FamilyStop")->setText(stop);
        p->field("FamilyStep")->setText(step);
    }
    static bool batchEnds(MainWindow* w, int ms = 240000) {
        return QTest::qWaitFor([&] { return !w->batchController()->busy(); }, ms);
    }

    void aFamilyRunsIntoLabelledOverlays() {
        auto w = window("family");
        QVERIFY(w);
        RunLog log(w->runController());
        runDiodeSweep(w.get(), log);
        const std::vector<double> primary_v = w->result()->sweep().voltages;
        RunPanel* p = w->runPanel();
        setFamily(p, "cathode", "0", "0.2", "0.1");
        QTest::mouseClick(p->runFamilyButton(), Qt::LeftButton);
        QVERIFY(w->batchController()->busy() && !p->runFamilyButton()->isEnabled() && p->stopBatchButton()->isEnabled());
        QVERIFY(batchEnds(w.get()));
        QVERIFY(w->batchController()->lastOutcome() == tcad::desktop::BatchController::Outcome::Finished);
        QCOMPARE(w->overlays().size(), std::size_t{3});
        const QStringList labels{"cathode=0 V", "cathode=0.1 V", "cathode=0.2 V"};  // QML's labels
        for (std::size_t i = 0; i < 3; ++i) {
            const auto& o = w->overlays()[i];
            QVERIFY(o.kind == tcad::desktop::plot::OverlayCurve::Kind::Family);
            QCOMPARE(o.label, labels[static_cast<int>(i)]);
            QVERIFY(o.sweep.voltages == primary_v);  // the last run's own sweep, re-solved
            QVERIFY(samePathInDir(o.path, runsDir("family")));
        }
        QVERIFY(w->viewMode() == ViewMode::Curves);
        QCOMPARE(w->plotView()->model().series.size(), std::size_t{4});  // the primary + 3
        QCOMPARE(p->batchStatus()->text(), QString("Family: 3 of 3 curves added."));
        QVERIFY(p->runFamilyButton()->isEnabled() && !p->stopBatchButton()->isEnabled());
        QVERIFY(runFiles(runsDir("family"), {"job-*.json", "*.tmp.npz"}).isEmpty());
        QVERIFY(errorBoxTitles().isEmpty());
        snapshot(w.get(), "s6_family");
    }

    void theComparisonRunsWithEveryModelOff() {
        auto w = window("comparison");
        QVERIFY(w);
        RunLog log(w->runController());
        runDiodeSweep(w.get(), log);
        QTest::mouseClick(w->runPanel()->runComparisonButton(), Qt::LeftButton);
        QVERIFY(batchEnds(w.get()));
        QCOMPARE(w->overlays().size(), std::size_t{1});
        const auto& o = w->overlays()[0];
        QVERIFY(o.kind == tcad::desktop::plot::OverlayCurve::Kind::Comparison);
        QCOMPARE(o.label, QString("all models off"));
        const tcad::desktop::NpzFile npz = tcad::desktop::NpzFile::open(o.path.toStdWString());
        const auto record = tcad::desktop::ResultModel::from_npz(npz).record();
        QVERIFY(record.has_value());
        for (const auto& [k, v] : (*record)["models"].items())
            QVERIFY2(v == false, qPrintable(QString::fromStdString(k + " is on")));
        QVERIFY(!(*record)["models"].empty());
    }

    void batchRefusalsAreNamed() {
        auto w = window("family_refused");
        QVERIFY(w);
        RunLog log(w->runController());
        RunPanel* p = w->runPanel();
        // nothing run yet
        QTest::mouseClick(p->runFamilyButton(), Qt::LeftButton);
        QCOMPARE(errorBoxTitles(), QStringList{"Cannot run the family"});
        QVERIFY(w->lastError().contains("Run a sweep first"));
        closeErrorBoxes();
        // the last run was not a sweep
        loadExample(w.get(), "diode_1d");
        p->setKind(RunKind::Bias);
        clickRunAndWait(w.get(), log);
        QTest::mouseClick(p->runComparisonButton(), Qt::LeftButton);
        QCOMPARE(errorBoxTitles(), QStringList{"Nothing to compare"});
        QVERIFY(w->lastError().contains("Run a sweep first"));
        closeErrorBoxes();
        // a step that moves away from the stop: QML's refusal, from the backend
        RunLog sweep_log(w->runController());
        runDiodeSweep(w.get(), sweep_log);
        setFamily(p, "cathode", "0", "0.2", "-0.1");
        QTest::mouseClick(p->runFamilyButton(), Qt::LeftButton);
        QVERIFY(batchEnds(w.get(), 60000));
        QCOMPARE(errorBoxTitles(), QStringList{"Invalid family configuration"});
        QVERIFY2(w->lastError().contains("step -0.1 does not move from start 0 toward stop 0.2"), qPrintable(w->lastError()));
        closeErrorBoxes();
        // another result open: the family would be drawn over the wrong curves
        QVERIFY(w->tryOpen(data("prev.npz")));
        setFamily(p, "cathode", "0", "0.2", "0.1");
        QTest::mouseClick(p->runFamilyButton(), Qt::LeftButton);
        QCOMPARE(errorBoxTitles(), QStringList{"Cannot run the family"});
        QVERIFY(w->lastError().contains("is not the last run's"));
        QVERIFY(!w->batchController()->busy());
        QVERIFY(w->overlays().empty());
    }

    void aFamilyStoppedMidwayKeepsItsCurves() {
        auto w = window("family_stop");
        QVERIFY(w);
        RunLog log(w->runController());
        runDiodeSweep(w.get(), log);
        RunPanel* p = w->runPanel();
        setFamily(p, "cathode", "0", "0.5", "0.05");  // 11 curves
        QTest::mouseClick(p->runFamilyButton(), Qt::LeftButton);
        QVERIFY(QTest::qWaitFor([&] { return w->batchController()->finishedCurves() >= 1; }, 240000));
        QTest::mouseClick(p->stopBatchButton(), Qt::LeftButton);
        QVERIFY(!w->batchController()->busy());
        const std::size_t kept = w->overlays().size();
        QVERIFY(kept >= 1 && kept < 11);
        QVERIFY(QTest::qWaitFor([&] { return w->batchController()->runner()->liveRuns() == 0; }, 10000));
        QTest::qWait(1500);  // nothing more arrives
        QCOMPARE(w->overlays().size(), kept);
        QVERIFY(w->batchController()->lastOutcome() == tcad::desktop::BatchController::Outcome::Canceled);
        QVERIFY2(p->batchStatus()->text().startsWith("Family stopped after"), qPrintable(p->batchStatus()->text()));
        QVERIFY(runFiles(runsDir("family_stop"), {"job-*.json", "*.tmp.npz"}).isEmpty());
        QVERIFY(errorBoxTitles().isEmpty());
    }

    void openingAnotherResultStopsTheBatch() {
        auto w = window("family_reopen");
        QVERIFY(w);
        RunLog log(w->runController());
        runDiodeSweep(w.get(), log);
        RunPanel* p = w->runPanel();
        setFamily(p, "cathode", "0", "0.5", "0.05");
        QTest::mouseClick(p->runFamilyButton(), Qt::LeftButton);
        QVERIFY(QTest::qWaitFor([&] { return w->batchController()->finishedCurves() >= 1; }, 240000));
        QVERIFY(w->tryOpen(data("prev.npz")));
        QVERIFY(!w->batchController()->busy());
        QTest::qWait(1500);
        QVERIFY(w->overlays().empty());       // nothing drawn over the other result
        QVERIFY(errorBoxTitles().isEmpty());  // and nothing refused on it
        w->consolePanel()->flush();
        QVERIFY(!w->consolePanel()->lines().filter("another result was opened").isEmpty());
    }

    void closingTheWindowMidFamily() {
        qint64 pid = 0;
        {
            auto w = window("family_close");
            QVERIFY(w);
            RunLog log(w->runController());
            runDiodeSweep(w.get(), log);
            setFamily(w->runPanel(), "cathode", "0", "0.5", "0.05");
            QTest::mouseClick(w->runPanel()->runFamilyButton(), Qt::LeftButton);
            QVERIFY(QTest::qWaitFor([&] { return w->batchController()->runner()->currentPid() > 0; }, 240000));
            pid = w->batchController()->runner()->currentPid();
        }
        QVERIFY(!processAlive(pid));
        QVERIFY(runFiles(runsDir("family_close"), {"job-*.json", "*.tmp.npz"}).isEmpty());
        QVERIFY(errorBoxTitles().isEmpty());
    }

    void closingTheWindowWhileAFamilyPrepares() {
        // The backend's shutdown in ~MainWindow ends the in-flight family.jobs
        // call -- failing it, or (the service being quick) answering it. Either
        // way the batch must be gone by then: no failure reported into the dying
        // window, and no job started in it. Any batch signal during the teardown
        // counts (the first version watched only failed(), and missed a teardown
        // that started a solver job from the answered reply).
        bool closing = false;
        int late = 0;
        {
            auto w = window("family_close_early");
            QVERIFY(w);
            RunLog log(w->runController());
            runDiodeSweep(w.get(), log);
            tcad::desktop::BatchController* b = w->batchController();
            auto count = [&] {
                if (closing) ++late;
            };
            connect(b, &tcad::desktop::BatchController::failed, this, count);
            connect(b, &tcad::desktop::BatchController::message, this, count);
            connect(b, &tcad::desktop::BatchController::status, this, count);
            connect(b, &tcad::desktop::BatchController::curveFinished, this, count);
            setFamily(w->runPanel(), "cathode", "0", "0.2", "0.1");
            QTest::mouseClick(w->runPanel()->runFamilyButton(), Qt::LeftButton);
            QVERIFY(b->busy() && b->total() == 0);  // family.jobs in flight
            closing = true;
        }
        QCoreApplication::processEvents();
        QCOMPARE(late, 0);
        QVERIFY(errorBoxTitles().isEmpty());
    }

    // -- Save result as ---------------------------------------------------------------------
    void saveResultAsCopiesTheOpenResult() {
        auto w = window("saveas");
        QVERIFY(w);
        QVERIFY(w->tryOpen(data("prev.npz")));
        QString why;
        const QString target = tmp_.filePath("copy.npz");
        QVERIFY2(w->saveResultAs(target, &why), qPrintable(why));
        QFile a(data("prev.npz")), b(target);
        QVERIFY(a.open(QIODevice::ReadOnly) && b.open(QIODevice::ReadOnly));
        QCOMPARE(a.readAll(), b.readAll());
        QVERIFY(!w->saveResultAs(data("prev.npz"), &why));  // onto itself: refused
        QVERIFY(why.contains("own file"));
    }

    // -- the console and the runs directory -----------------------------------------------------
    void theConsoleIsBounded() {
        ConsolePanel c;
        for (int i = 0; i < 60000; ++i) c.append(QString("line %1").arg(i));
        c.flush();
        QCOMPARE(c.lineCount(), ConsolePanel::kMaxLines);
        QCOMPARE(c.droppedLines(), qint64{10000});
        QCOMPARE(c.lines().front(), QString("line 10000"));
        QCOMPARE(c.lines().back(), QString("line 59999"));
        QVERIFY(c.findChild<QLabel*>("ConsoleDropped")->text().startsWith("10000 earlier lines dropped"));
        // A multi-line text is one line per line; a traceback's last newline adds none.
        c.clear();
        c.append("Traceback:\n  File x\nValueError: bad\n", ConsolePanel::Style::Error);
        c.flush();
        QCOMPARE(c.lines(), (QStringList{"Traceback:", "  File x", "ValueError: bad"}));
        QCOMPARE(c.droppedLines(), qint64{0});
    }

    void theRunsDirectoryKeepsTheNewest20AndTheOpenResult() {
        const QString dir = tmp_.filePath("retention");
        QVERIFY(QDir().mkpath(dir));
        const QDateTime base = QDateTime::currentDateTime().addSecs(-3600);
        auto make = [&](const QString& name, const QDateTime& t) {
            QFile f(QDir(dir).filePath(name));
            QVERIFY(f.open(QIODevice::WriteOnly));
            f.write("x");
            QVERIFY(f.setFileTime(t, QFileDevice::FileModificationTime));
        };
        for (int i = 0; i < 25; ++i) make(QString("result-%1.npz").arg(i, 2, 10, QChar('0')), base.addSecs(i));
        make("job-old.json", base.addDays(-2));
        make("result-old.npz.tmp.npz", base.addDays(-2));
        make("job-live.json", QDateTime::currentDateTime());   // another instance's run
        make("notes.txt", base.addDays(-30));                     // not the runner's: untouched
        const QString open = QDir(dir).filePath("result-00.npz");  // the oldest, open in the view
        QCOMPARE(RunController::pruneRuns(dir, open), 4 + 2);
        QStringList expect{"job-live.json", "notes.txt", "result-00.npz"};
        for (int i = 5; i < 25; ++i) expect << QString("result-%1.npz").arg(i, 2, 10, QChar('0'));
        QStringList have = QDir(dir).entryList(QDir::Files);
        have.sort();
        expect.sort();
        QCOMPARE(have, expect);
    }
};

QTEST_MAIN(TestRunShell)
#include "test_run_shell.moc"
