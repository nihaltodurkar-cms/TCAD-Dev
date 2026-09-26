#include "main_window.hpp"

#include "console_panel.hpp"
#include "display_panel.hpp"
#include "run/batch_controller.hpp"
#include "run/run_controller.hpp"
#include "run_panel.hpp"
#include "telemetry_panel.hpp"
#include "info_panel.hpp"
#include "playback_panel.hpp"
#include "plot_panel.hpp"
#include "view3d_panel.hpp"
#include "views/field/field_view.hpp"
#include "views/plot/plot_view.hpp"

#include <DockAreaWidget.h>
#include <DockManager.h>
#include <DockWidget.h>

#include <QAction>
#include <QCloseEvent>
#include <QComboBox>
#include <QDragEnterEvent>
#include <QDropEvent>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFont>
#include <QFileDialog>
#include <QFileInfo>
#include <QLabel>
#include <QListWidget>
#include <QMenu>
#include <QMenuBar>
#include <QMessageBox>
#include <QMimeData>
#include <QSignalBlocker>
#include <QSplitter>
#include <QStandardPaths>
#include <QStatusBar>
#include <QTimer>
#include <QToolBar>
#include <QUrl>

#include <algorithm>
#include <utility>

namespace tcad::desktop {
namespace {

constexpr int kFieldsPanelWidth = 240;  // the default layout's Fields panel, logical px

// The Fields list's entries: a field of the result, a derived map, or a
// header line.
constexpr int kRoleKind = Qt::UserRole;       // "field" | "derived" | "header"
constexpr int kRoleDerived = Qt::UserRole + 1;  // "bands" | "recombination"

struct DerivedEntry {
    const char* field;
    const char* kind;
};
constexpr DerivedEntry kDerived[] = {
    {"Ec", "bands"}, {"Ev", "bands"}, {"EFn", "bands"}, {"EFp", "bands"}, {"R", "recombination"}};

}  // namespace

MainWindow::MainWindow(std::unique_ptr<AppSettings> settings, QWidget* parent)
    : QMainWindow(parent), settings_(std::move(settings)) {
    // The theme FIRST, before any widget exists: ADS resolves its
    // stylesheet's palette(...) references when its widgets are
    // polished, so a palette applied after them left dock panels a stock
    // grey (S3c screenshot; gated by the shell test). One scheme, black
    // and white (2026-09-26): no choice, no following the OS.
    theme::apply();
    setWindowTitle("PyTCAD Desktop");
    setAcceptDrops(true);
    // Uncompressed XML state: readable in the settings file, and
    // comparable structurally by the layout gate (section 15.13 rev. 8).
    ads::CDockManager::setConfigFlags(ads::CDockManager::DefaultOpaqueConfig);
    ads::CDockManager::setConfigFlag(ads::CDockManager::XmlCompressionEnabled, false);
    docks_ = new ads::CDockManager(this);  // becomes this window's central widget
    ads_default_qss_ = docks_->styleSheet();

    // The central area (P2-S3, 16.2 decision 7): the FieldView and the
    // PlotView in one splitter for the window's lifetime. The FieldView
    // is placed here before its GL context exists and is only ever hidden
    // or shown -- reparenting a GL widget recreates its context (S6).
    central_ = new QSplitter(Qt::Vertical, this);
    central_->setObjectName("CentralSplitter");
    central_->setChildrenCollapsible(false);
    view_ = new FieldView(central_);
    plot_ = new plot::PlotView(central_);
    plot_->setObjectName("PlotView");
    central_->addWidget(view_);
    central_->addWidget(plot_);
    plot_->hide();
    auto* central = new ads::CDockWidget(docks_, tr("Field view"));
    central->setObjectName("FieldViewDock");
    central->setWidget(central_, ads::CDockWidget::ForceNoScrollArea);
    central->setFeatures(ads::CDockWidget::NoDockWidgetFeatures);  // fixed: never floats or closes
    docks_->setCentralWidget(central);

    fields_ = new QListWidget(this);
    fields_dock_ = new ads::CDockWidget(docks_, tr("Fields"));
    fields_dock_->setObjectName("FieldsDock");
    fields_dock_->setWidget(fields_);
    docks_->addDockWidget(ads::LeftDockWidgetArea, fields_dock_);

    info_ = new InfoPanel(this);
    info_dock_ = new ads::CDockWidget(docks_, tr("Info"));
    info_dock_->setObjectName("InfoDock");
    info_dock_->setWidget(info_);
    docks_->addDockWidget(ads::BottomDockWidgetArea, info_dock_, fields_dock_->dockAreaWidget());

    display_ = new DisplayPanel(view_, this);
    display_dock_ = new ads::CDockWidget(docks_, tr("Display"));
    display_dock_->setObjectName("DisplayDock");
    display_dock_->setWidget(display_);
    docks_->addDockWidget(ads::CenterDockWidgetArea, display_dock_, info_dock_->dockAreaWidget());

    view3d_ = new View3DPanel(view_, this);  // S6
    view3d_dock_ = new ads::CDockWidget(docks_, tr("3D"));
    view3d_dock_->setObjectName("View3DDock");
    view3d_dock_->setWidget(view3d_, ads::CDockWidget::ForceNoScrollArea);  // it scrolls itself
    docks_->addDockWidget(ads::CenterDockWidgetArea, view3d_dock_, info_dock_->dockAreaWidget());
    plot_panel_ = new PlotPanel(this);  // P2-S3: the curve modes' controls
    plot_dock_ = new ads::CDockWidget(docks_, tr("Plot"));
    plot_dock_->setObjectName("PlotDock");
    plot_dock_->setWidget(plot_panel_);
    docks_->addDockWidget(ads::CenterDockWidgetArea, plot_dock_, info_dock_->dockAreaWidget());
    display_dock_->setAsCurrentTab();

    playback_ = new PlaybackPanel(view_, this);
    playback_dock_ = new ads::CDockWidget(docks_, tr("Playback"));
    playback_dock_->setObjectName("PlaybackDock");
    playback_dock_->setWidget(playback_);
    // Below the left column's tabs, NOT beside the view: docking relative
    // to the view's own area reparents the GL widget, which recreates its
    // context on every Reset layout (measured in S6: 10 re-inits in 10).
    docks_->addDockWidget(ads::BottomDockWidgetArea, playback_dock_, info_dock_->dockAreaWidget());
    playback_dock_->toggleView(false);  // shown when a result with sweep snapshots opens

    auto* open = new QAction(tr("&Open result..."), this);
    open->setShortcut(QKeySequence::Open);
    connect(open, &QAction::triggered, this, &MainWindow::chooseResult);
    recent_ = new QMenu(tr("Open &recent"), this);
    connect(recent_, &QMenu::aboutToShow, this, &MainWindow::rebuildRecentMenu);
    auto* quit = new QAction(tr("&Quit"), this);
    quit->setShortcut(QKeySequence::Quit);
    connect(quit, &QAction::triggered, this, &QWidget::close);
    log_ = new QAction(tr("Log scale"), this);
    log_->setCheckable(true);
    connect(log_, &QAction::toggled, this, &MainWindow::onLogToggled);

    auto* fit = new QAction(tr("Fit"), this);
    fit->setShortcut(Qt::Key_F);
    connect(fit, &QAction::triggered, this, [this] {
        if (plot::isCurveMode(mode_)) plot_->fit();
        if (plot::showsMap(mode_)) view_->resetView();  // Line cut: both
    });
    mode_combo_ = new QComboBox(this);
    mode_combo_->setObjectName("ViewModeCombo");
    mode_combo_->setToolTip(tr("View mode"));
    mode_combo_->setAccessibleName(tr("View mode"));  // screen readers and UI Automation
    mode_combo_->setSizeAdjustPolicy(QComboBox::AdjustToContents);
    mode_combo_->setEnabled(false);
    connect(mode_combo_, &QComboBox::activated, this,
            [this](int i) { setViewMode(static_cast<plot::ViewMode>(mode_combo_->itemData(i).toInt())); });

    auto* file = menuBar()->addMenu(tr("&File"));
    file->addAction(open);
    file->addMenu(recent_);
    file->addSeparator();
    file->addAction(quit);
    auto* view = menuBar()->addMenu(tr("&View"));
    mode_menu_ = view->addMenu(tr("View &mode"));
    mode_menu_->setObjectName("ViewModeMenu");
    mode_menu_->setEnabled(false);
    view->addSeparator();
    view->addAction(fit);
    view->addAction(log_);
    view->addAction(fields_dock_->toggleViewAction());
    view->addAction(info_dock_->toggleViewAction());
    view->addAction(display_dock_->toggleViewAction());
    view->addAction(view3d_dock_->toggleViewAction());
    view->addAction(playback_dock_->toggleViewAction());
    view->addAction(plot_dock_->toggleViewAction());
    view->addSeparator();
    auto* reset = new QAction(tr("Reset layout"), this);
    connect(reset, &QAction::triggered, this, &MainWindow::resetLayout);
    view->addAction(reset);
    auto* tools = addToolBar(tr("Main"));
    tools->setObjectName("MainToolBar");
    tools->addAction(open);
    tools->addAction(fit);
    tools->addAction(log_);
    tools->addSeparator();
    tools->addWidget(mode_combo_);

    readout_ = new QLabel(this);
    readout_->setObjectName("Readout");
    // No stretch: a permanent widget with stretch took the whole bar, and
    // Qt draws a temporary message only beside the permanent widgets -- every
    // showMessage() was invisible (found in P3-S4's window grabs).
    statusBar()->addPermanentWidget(readout_, 0);
    connect(view_, &FieldView::readoutChanged, readout_, &QLabel::setText);
    connect(plot_, &plot::PlotView::readoutChanged, readout_, &QLabel::setText);
    connect(plot_panel_, &PlotPanel::channelChosen, this, [this](const QString& c) { setSweepChannel(c); });
    connect(plot_panel_, &PlotPanel::logToggled, this, &MainWindow::setPlotLog);
    connect(plot_panel_, &PlotPanel::cutOrientationChosen, this,
            [this](bool horizontal) { setCut(horizontal, cut_index_); });
    connect(plot_panel_, &PlotPanel::cutIndexChosen, this, [this](int i) { setCut(cut_horizontal_, i); });
    connect(plot_panel_, &PlotPanel::addComparisonRequested, this,
            [this] { chooseOverlay(plot::OverlayCurve::Kind::Comparison); });
    connect(plot_panel_, &PlotPanel::addFamilyRequested, this,
            [this] { chooseOverlay(plot::OverlayCurve::Kind::Family); });
    connect(plot_panel_, &PlotPanel::removeOverlayRequested, this, [this](int i) { removeOverlay(i); });
    connect(plot_panel_, &PlotPanel::overlayLabelEdited, this,
            [this](int i, const QString& label) { setOverlayLabel(i, label); });
    connect(fields_, &QListWidget::currentItemChanged, this,
            [this](QListWidgetItem* item, QListWidgetItem*) { onFieldItem(item); });
    // The toolbar's Log action follows the view (the Display panel edits it too).
    connect(view_, &FieldView::displayChanged, this, [this] {
        if (!plot::isCurveMode(mode_)) syncControls();
        // Line cut: the curve follows the map's field (a stored field or a
        // derived map) -- rebuilt only when that changed, not on a colour-map
        // or range edit, which would refit the curve for nothing.
        if (mode_ == plot::ViewMode::Cut &&
            (view_->fieldSource() != cut_source_ || view_->field() != cut_field_))
            rebuildPlot();
    });
    buildRunning();  // P3-S4: the Run and Console docks
    file->insertAction(recent_->menuAction(), save_as_);
    tools->addSeparator();
    tools->addAction(run_act_);
    tools->addAction(stop_act_);
    view->insertAction(reset, run_dock_->toggleViewAction());
    view->insertAction(reset, console_dock_->toggleViewAction());
    view->insertAction(reset, telemetry_dock_->toggleViewAction());
    // ADS paints from its own stylesheet's palette(...) references, which
    // it fixes when its widgets are polished -- that left dock panels a
    // stock grey once. Instead, its default stylesheet is rewritten with
    // the token colours (section 15.13 S3c).
    docks_->setStyleSheet(theme::themedStyleSheet(ads_default_qss_));

    default_layout_ = docks_->saveState();
    resize(1500, 950);  // the default; a saved geometry replaces it
    restoreSavedLayout();
    if (!settings_->writable())
        statusBar()->showMessage(tr("Settings file is read-only (%1): the layout and recent files will not be saved.")
                                     .arg(settings_->fileName()));
}

// The backend goes first, while the window is whole: its shutdown fails the
// pending replies, whose handlers (connected with this window as context)
// would otherwise run from ~QWidget's deleteChildren, after ~QMainWindow --
// statusBar() on a half-destroyed window, an access violation (found in
// P2-S3; the likely cause of P1's unexplained shell crash, plan 16.10).
MainWindow::~MainWindow() {
    // The runner before anything else (17.7 point 12): it kills the solver's
    // process tree and removes its files, silently -- no finished/failed
    // handler may run into this half-destroyed window.
    delete run_ctl_;
    run_ctl_ = nullptr;
    delete batch_;
    batch_ = nullptr;
    if (!backend_) return;
    for (BackendReply* r : backend_->findChildren<BackendReply*>()) r->disconnect(this);
    delete backend_;
    backend_ = nullptr;
}

void MainWindow::restoreSavedLayout() {
    AppSettings::Layout saved;
    if (!settings_->loadLayout(&saved)) return;  // none, or another layout version
    if (!saved.geometry.isEmpty()) restoreGeometry(saved.geometry);
    if (!docks_->restoreState(saved.docks)) {
        resetLayout();  // a corrupt blob must not leave a half layout
        last_error_ = tr("The saved window layout could not be read; using the default layout.");
        statusBar()->showMessage(last_error_);
    }
}

// The default arrangement is REBUILT, not replayed from a saved blob: a
// state taken before the window is first shown records 0-pixel splitters,
// and restoring it left a 60 px Fields panel (found by the S3 shell tests).
void MainWindow::resetLayout() {
    fields_dock_->toggleView(true);
    info_dock_->toggleView(true);
    display_dock_->toggleView(true);
    docks_->addDockWidget(ads::LeftDockWidgetArea, fields_dock_);
    docks_->addDockWidget(ads::BottomDockWidgetArea, info_dock_, fields_dock_->dockAreaWidget());
    docks_->addDockWidget(ads::CenterDockWidgetArea, display_dock_, info_dock_->dockAreaWidget());
    view3d_dock_->toggleView(true);
    docks_->addDockWidget(ads::CenterDockWidgetArea, view3d_dock_, info_dock_->dockAreaWidget());
    plot_dock_->toggleView(true);
    docks_->addDockWidget(ads::CenterDockWidgetArea, plot_dock_, info_dock_->dockAreaWidget());
    display_dock_->setAsCurrentTab();
    docks_->addDockWidget(ads::BottomDockWidgetArea, playback_dock_, info_dock_->dockAreaWidget());
    playback_dock_->toggleView(view_->snapshots() != nullptr);
    run_dock_->toggleView(true);
    docks_->addDockWidget(ads::CenterDockWidgetArea, run_dock_, fields_dock_->dockAreaWidget());
    fields_dock_->setAsCurrentTab();
    console_dock_->toggleView(true);
    docks_->addDockWidget(ads::CenterDockWidgetArea, console_dock_, info_dock_->dockAreaWidget());
    telemetry_dock_->toggleView(true);
    docks_->addDockWidget(ads::CenterDockWidgetArea, telemetry_dock_, info_dock_->dockAreaWidget());
    display_dock_->setAsCurrentTab();
    // The left column's width lives on the first HORIZONTAL splitter above
    // the Fields area (its own is the vertical Fields/Info one). Not "the
    // central area's splitter": with Playback docked below the view, that
    // one is vertical too (found by the S6 shell tests).
    const int total = docks_->width() > 0 ? docks_->width() : width();
    for (QWidget* w = fields_dock_->dockAreaWidget(); w; w = w->parentWidget()) {
        auto* split = qobject_cast<QSplitter*>(w->parentWidget());
        if (split && split->orientation() == Qt::Horizontal && split->count() == 2) {
            split->setSizes({kFieldsPanelWidth, std::max(1, total - kFieldsPanelWidth)});
            break;
        }
    }
}

// -- running (P3-S4) ---------------------------------------------------------------

QString MainWindow::runsDir() const {
    const QString configured = settings_->value("run/dir");
    if (!configured.isEmpty()) return QDir::cleanPath(configured);
    return QDir(QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation)).filePath("PyTCAD/runs");
}

void MainWindow::buildRunning() {
    const BackendConfig backend = resolveBackendConfig(settings_->value("backend/python"));
    RunnerConfig rc;
    rc.python = backend.python;
    rc.working_dir = backend.working_dir;
    rc.strip_from_path = backend.strip_from_path;
    rc.work_dir = runsDir();
    // The backend client is created on the first call, as for derived maps.
    run_ctl_ = new RunController(
        [this] {
            ensureBackend();
            return backend_;
        },
        rc, this);

    // Both tabbed into the left column: the view keeps every pixel it had
    // (docking beside it cut it from nearly the whole window to 1014 x 616 at
    // 1500 x 950, measured). Either can be dragged out; the layout persists.
    batch_ = new BatchController(
        [this] {
            ensureBackend();
            return backend_;
        },
        rc, this);
    run_panel_ = new RunPanel(run_ctl_, this);
    run_dock_ = new ads::CDockWidget(docks_, tr("Run"));
    run_dock_->setObjectName("RunDock");
    run_dock_->setWidget(run_panel_);
    docks_->addDockWidget(ads::CenterDockWidgetArea, run_dock_, fields_dock_->dockAreaWidget());
    fields_dock_->setAsCurrentTab();
    console_ = new ConsolePanel(this);
    console_dock_ = new ads::CDockWidget(docks_, tr("Console"));
    console_dock_->setObjectName("ConsoleDock");
    console_dock_->setWidget(console_, ads::CDockWidget::ForceNoScrollArea);  // it scrolls itself
    docks_->addDockWidget(ads::CenterDockWidgetArea, console_dock_, info_dock_->dockAreaWidget());
    telemetry_ = new TelemetryPanel(this);  // P3-S5
    telemetry_dock_ = new ads::CDockWidget(docks_, tr("Telemetry"));
    telemetry_dock_->setObjectName("TelemetryDock");
    telemetry_dock_->setWidget(telemetry_, ads::CDockWidget::ForceNoScrollArea);
    docks_->addDockWidget(ads::CenterDockWidgetArea, telemetry_dock_, info_dock_->dockAreaWidget());
    display_dock_->setAsCurrentTab();

    run_act_ = new QAction(tr("&Run"), this);
    run_act_->setObjectName("RunAction");
    run_act_->setShortcut(Qt::Key_F5);
    connect(run_act_, &QAction::triggered, run_panel_, &RunPanel::requestRun);
    stop_act_ = new QAction(tr("&Stop"), this);
    stop_act_->setObjectName("StopAction");
    stop_act_->setShortcut(QKeySequence(Qt::SHIFT | Qt::Key_F5));
    stop_act_->setEnabled(false);
    connect(stop_act_, &QAction::triggered, run_ctl_, &RunController::stop);
    auto* menu = menuBar()->addMenu(tr("&Run"));
    menu->addAction(run_act_);
    menu->addAction(stop_act_);
    save_as_ = new QAction(tr("&Save result as..."), this);
    save_as_->setObjectName("SaveResultAs");
    save_as_->setEnabled(false);
    connect(save_as_, &QAction::triggered, this, [this] {
        const QString target = QFileDialog::getSaveFileName(this, tr("Save result as"), QFileInfo(result_path_).fileName(),
                                                            tr("PyTCAD results (*.npz)"));
        if (target.isEmpty()) return;
        if (QString why; !saveResultAs(target, &why)) reportError(tr("Could not save the result"), why);
    });

    run_tick_ = new QTimer(this);
    run_tick_->setInterval(1000);
    connect(run_tick_, &QTimer::timeout, this, &MainWindow::updateRunStatus);
    connect(run_panel_, &RunPanel::inputRejected, this, &MainWindow::reportError);
    connect(run_panel_, &RunPanel::familyRequested, this, &MainWindow::startFamily);
    connect(run_panel_, &RunPanel::comparisonRequested, this, &MainWindow::startComparison);
    connect(run_panel_, &RunPanel::batchStopRequested, batch_, &BatchController::stop);
    connect(batch_, &BatchController::busyChanged, run_panel_, &RunPanel::setBatchBusy);
    connect(batch_, &BatchController::status, run_panel_, &RunPanel::setBatchStatus);
    connect(batch_, &BatchController::message, this,
            [this](const QString& text) { console_->append(text, ConsolePanel::Style::Note); });
    connect(batch_, &BatchController::failed, this,
            [this](const QString& title, const QString& summary, const QString& details) {
                console_->append(title + ": " + summary, ConsolePanel::Style::Error);
                if (!details.isEmpty()) console_->append(details, ConsolePanel::Style::Stderr);
                reportError(title, summary);
            });
    connect(batch_, &BatchController::curveFinished, this,
            [this](const QString& path, const QString& label, BatchController::Kind kind) {
                onBatchCurve(path, label, kind == BatchController::Kind::Comparison);
            });
    connect(run_ctl_, &RunController::message, this, [this](const QString& text) {
        console_->append(text, ConsolePanel::Style::Note);
    });
    connect(run_ctl_, &RunController::line, this, [this](const QString& text, JobRunner::LineKind kind) {
        console_->append(text, kind == JobRunner::LineKind::Stage    ? ConsolePanel::Style::Stage
                               : kind == JobRunner::LineKind::Stderr ? ConsolePanel::Style::Stderr
                                                                     : ConsolePanel::Style::Plain);
    });
    connect(run_ctl_, &RunController::progress, this,
            [this](const ProgressRecord& r) { telemetry_->apply(r.value); });
    connect(run_ctl_, &RunController::stage, this, [this](const QString& s) {
        run_stage_ = s;
        updateRunStatus();
    });
    connect(run_ctl_, &RunController::busyChanged, this, [this](bool busy) {
        run_act_->setEnabled(!busy);
        stop_act_->setEnabled(busy);
        if (busy) {
            beginTelemetry();
            run_started_ms_ = QDateTime::currentMSecsSinceEpoch();
            run_stage_.clear();
            run_tick_->start();
            updateRunStatus();
        } else {
            run_tick_->stop();
            const auto o = run_ctl_->lastOutcome();
            telemetry_->end(o == RunController::Outcome::Finished ? tr("Finished")
                            : o == RunController::Outcome::Canceled ? tr("Canceled")
                                                                    : tr("Failed"));
        }
    });
    connect(run_ctl_, &RunController::runFinished, this, &MainWindow::onRunFinished);
    connect(run_ctl_, &RunController::runFailed, this,
            [this](const QString& title, const QString& summary, const QString& details) {
                console_->append(title + ": " + summary, ConsolePanel::Style::Error);
                if (!details.isEmpty()) console_->append(details, ConsolePanel::Style::Stderr);
                reportError(title, summary);
            });
    connect(run_ctl_, &RunController::runCanceled, this, [this] { statusBar()->showMessage(tr("Run canceled.")); });
}

// The Telemetry dock follows the run just started: what it is, and whether
// its settings already say it reports stages only (17.7 point 2).
void MainWindow::beginTelemetry() {
    const RunSettings& s = run_ctl_->lastSettings();
    QString what = runKindName(s.kind);
    if (s.kind != RunKind::CV && run_ctl_->device()) what += tr(" of %1").arg(run_ctl_->device()->label);
    QString reason;
    if (s.kind == RunKind::CV)
        reason = tr("a C-V run");
    else if (s.engine == "mpi_schwarz")
        reason = tr("the MPI Schwarz engine");
    telemetry_->begin(what, reason);
}

bool MainWindow::batchBaseIsOpen(const QString& what) {
    const QString title = tr("Cannot run the %1").arg(what);
    const QString last = run_ctl_->lastRunResult();
    if (run_ctl_->lastRunSpec().is_null() || last.isEmpty()) {
        reportError(title, tr("Run a sweep first: the %1 re-solves the last run.").arg(what));
        return false;
    }
    if (!model_ || !samePath(result_path_, last)) {
        reportError(title, tr("The open result is not the last run's (%1): the %2 re-solves that run and is "
                              "drawn over it. Open it, or run again.")
                               .arg(QFileInfo(last).fileName(), what));
        return false;
    }
    return true;
}

bool MainWindow::startFamily(const QString& stepped, double start, double stop, double step) {
    if (!batchBaseIsOpen(tr("family"))) return false;
    return batch_->runFamily(run_ctl_->lastRunSpec(), stepped, start, stop, step);
}

bool MainWindow::startComparison() {
    if (!batchBaseIsOpen(tr("comparison"))) return false;
    return batch_->runComparison(run_ctl_->lastRunSpec());
}

// A family curve or the comparison: drawn as a P2-S5 overlay (its checks and
// refusals unchanged), labelled as QML labels it, in the Curves (or C-V) view.
void MainWindow::onBatchCurve(const QString& path, const QString& label, bool comparison) {
    if (mode_ != plot::ViewMode::Curves && mode_ != plot::ViewMode::CV) setViewMode(plot::ViewMode::Curves);
    const QString why = addOverlay(path, comparison ? plot::OverlayCurve::Kind::Comparison
                                                    : plot::OverlayCurve::Kind::Family);
    if (why.isEmpty())
        setOverlayLabel(static_cast<int>(overlays_.size()) - 1, label);
    else
        batch_->stop();  // refused (reported by addOverlay): the rest would be too
}

void MainWindow::updateRunStatus() {
    if (!run_ctl_ || !run_ctl_->busy()) return;
    const qint64 s = (QDateTime::currentMSecsSinceEpoch() - run_started_ms_) / 1000;
    const QString phase = run_ctl_->phase() == RunController::Phase::Preparing ? tr("preparing")
                          : run_stage_.isEmpty()                                  ? tr("starting")
                                                                                  : run_stage_;
    statusBar()->showMessage(tr("Running: %1 (%2 s)").arg(phase).arg(s));
}

void MainWindow::onRunFinished(const QString& path) {
    const double s = static_cast<double>(QDateTime::currentMSecsSinceEpoch() - run_started_ms_) / 1000.0;
    if (!tryOpen(path)) return;  // named by tryOpen; the run's file stays for inspection
    // A run opens in its natural view (17.2): a sweep in Curves, a transient
    // in Transient, an AC run in AC, a C-V in C-V; the others keep the
    // default an opened file gets.
    switch (run_ctl_->lastKind()) {
        case RunKind::Sweep: setViewMode(plot::ViewMode::Curves); break;
        case RunKind::Transient: setViewMode(plot::ViewMode::Transient); break;
        case RunKind::AC: setViewMode(plot::ViewMode::AC); break;
        case RunKind::CV: setViewMode(plot::ViewMode::CV); break;
        default: break;
    }
    statusBar()->showMessage(tr("Run finished in %1 s: %2").arg(s, 0, 'f', 1).arg(QFileInfo(path).fileName()));
    RunController::pruneRuns(run_ctl_->runsDir(), result_path_);
}

bool MainWindow::saveResultAs(const QString& target, QString* error) {
    if (result_path_.isEmpty()) {
        *error = tr("No result is open.");
        return false;
    }
    if (samePath(target, result_path_)) {
        *error = tr("That is the open result's own file.");
        return false;
    }
    if (QString why; !resultFileUnchanged(&why)) {
        *error = why;  // a copy now would not be what the view shows
        return false;
    }
    if (QFileInfo::exists(target) && !QFile::remove(target)) {
        *error = tr("Cannot replace %1.").arg(QDir::toNativeSeparators(target));
        return false;
    }
    if (!QFile::copy(result_path_, target)) {
        *error = tr("Cannot write %1.").arg(QDir::toNativeSeparators(target));
        return false;
    }
    statusBar()->showMessage(tr("Saved the result as %1").arg(QDir::toNativeSeparators(target)));
    return true;
}

void MainWindow::closeEvent(QCloseEvent* event) {
    settings_->saveLayout({saveGeometry(), docks_->saveState()});
    settings_->sync();  // a read-only file was already reported at startup
    QMainWindow::closeEvent(event);
}

void MainWindow::openResult(const QString& path) {
    auto npz = std::make_unique<NpzFile>(NpzFile::open(path.toStdWString()));
    auto model = std::make_unique<ResultModel>(ResultModel::from_npz(*npz, path.toStdString()));
    if (batch_ && batch_->busy()) {
        batch_->stop();
        console_->append(tr("The family / comparison was stopped: another result was opened, and its "
                            "curves belong to the one before."),
                         ConsolePanel::Style::Note);
    }
    view_->setResult(nullptr);  // drop references into the old models first
    derived_.clear();
    derived_error_.clear();
    derived_pending_.clear();
    ++result_generation_;
    npz_ = std::move(npz);
    model_ = std::move(model);
    result_path_ = path;
    const QFileInfo stamp(path);
    result_size_ = stamp.size();
    result_mtime_ms_ = stamp.lastModified().toMSecsSinceEpoch();
    view_->setResult(model_.get());
    playback_->setPlaying(false);
    if (view_->snapshots()) playback_dock_->toggleView(true);  // a 3D sweep: offer playback
    // The Field mode's 1D field and Curves mode's channel carry over when
    // the new result has them (as the FieldView keeps its field).
    const auto& names = model_->scalar_names();
    if (std::find(names.begin(), names.end(), plot_field_) == names.end())
        plot_field_ = names.empty() ? std::string() : names.front();
    channels_.clear();
    for (const auto& c : plot::sweepChannels(*model_)) channels_ << QString::fromStdString(c);
    cut_index_ = std::min(cut_index_, std::max(0, cutAxisNodes() - 1));  // the new mesh may be smaller
    cut_source_ = nullptr;
    cut_field_.clear();
    overlays_.clear();  // overlays are compared with ONE open result
    if (!channels_.contains(sweep_channel_)) sweep_channel_ = channels_.isEmpty() ? QString() : channels_.front();
    rebuildModes();
    populateFields();
    info_->showResult(model_.get(), path);
    save_as_->setEnabled(true);
    setWindowTitle(QString("%1 - PyTCAD Desktop").arg(QFileInfo(path).fileName()));
}

bool MainWindow::tryOpen(const QString& path) {
    const QFileInfo info(path);
    if (!info.exists()) {
        settings_->removeRecent(path);  // a stale recent entry goes
        reportError(tr("Result not found"), tr("File not found: %1").arg(path));
        return false;
    }
    if (info.suffix().compare("npz", Qt::CaseInsensitive) != 0) {
        reportError(tr("Not a result file"), tr("Not a PyTCAD result (.npz): %1").arg(path));
        return false;
    }
    try {
        openResult(info.absoluteFilePath());
    } catch (const std::exception& e) {
        reportError(tr("Could not open result"),
                    tr("Could not open %1:\n%2").arg(info.fileName(), QString::fromUtf8(e.what())));
        return false;
    }
    last_error_.clear();
    settings_->addRecent(info.absoluteFilePath());
    // Derived maps are possible: warm the backend while the user looks
    // (after this first frame), so the first map does not wait ~0.7 s
    // for Python imports (decision 4, measured in section 15.18).
    if (model_ && (model_->dimensionality() >= 2 ||
                   std::find(modes_.begin(), modes_.end(), plot::ViewMode::Bands) != modes_.end()))
        QTimer::singleShot(300, this, &MainWindow::warmBackend);
    return true;
}

void MainWindow::reportError(const QString& title, const QString& text) {
    last_error_ = text;
    statusBar()->showMessage(text);
    // Non-modal: the window stays usable (and scriptable by the e2e tests).
    auto* box = new QMessageBox(QMessageBox::Warning, title, text, QMessageBox::Ok, this);
    box->setObjectName("ErrorBox");
    box->setAttribute(Qt::WA_DeleteOnClose);
    box->setWindowModality(Qt::NonModal);
    box->show();
}

void MainWindow::chooseResult() {
    const QString path = QFileDialog::getOpenFileName(this, tr("Open result"), QString(),
                                                      tr("PyTCAD results (*.npz)"));
    if (!path.isEmpty()) tryOpen(path);
}

void MainWindow::rebuildRecentMenu() {
    recent_->clear();
    const QStringList files = settings_->recentFiles();
    for (int i = 0; i < files.size(); ++i) {
        const QString& path = files[i];
        auto* act = recent_->addAction(QString("&%1  %2").arg(i + 1).arg(QFileInfo(path).fileName()));
        act->setToolTip(path);
        act->setStatusTip(path);
        connect(act, &QAction::triggered, this, [this, path] { tryOpen(path); });
    }
    if (files.isEmpty()) recent_->addAction(tr("(none)"))->setEnabled(false);
    recent_->addSeparator();
    auto* clear = recent_->addAction(tr("Clear recent"));
    clear->setEnabled(!files.isEmpty());
    connect(clear, &QAction::triggered, this, [this] { settings_->clearRecent(); });
}

// Any drag of local files is accepted, so a wrong drop can be reported
// by name on release, rather than silently refused by a no-drop cursor.
void MainWindow::dragEnterEvent(QDragEnterEvent* event) {
    const QMimeData* mime = event->mimeData();
    if (mime->hasUrls() && !mime->urls().isEmpty() && mime->urls().front().isLocalFile())
        event->acceptProposedAction();
}

void MainWindow::dropEvent(QDropEvent* event) {
    const QList<QUrl> urls = event->mimeData()->urls();
    event->acceptProposedAction();
    if (urls.size() != 1) {
        reportError(tr("Drop one file"), tr("Drop one result file at a time (got %1).").arg(urls.size()));
        return;
    }
    tryOpen(urls.front().toLocalFile());
}


// -- Fields list and derived maps (S5g) ------------------------------------------

void MainWindow::populateFields() {
    const QSignalBlocker block(fields_);
    fields_->clear();
    for (const auto& n : model_->scalar_names()) {
        auto* item = new QListWidgetItem(QString::fromStdString(n), fields_);
        item->setData(kRoleKind, "field");
    }
    if (model_->dimensionality() >= 2) {
        auto* header = new QListWidgetItem(tr("Derived (via the backend)"), fields_);
        header->setData(kRoleKind, "header");
        header->setFlags(Qt::NoItemFlags);
        QFont f = header->font();
        f.setItalic(true);
        header->setFont(f);
        const auto& names = model_->scalar_names();
        auto has = [&names](const char* n) { return std::find(names.begin(), names.end(), n) != names.end(); };
        for (const auto& e : kDerived) {
            auto* item = new QListWidgetItem(QString::fromLatin1(e.field), fields_);
            item->setData(kRoleKind, "derived");
            item->setData(kRoleDerived, QString::fromLatin1(e.kind));
            QStringList missing;
            for (const char* need : {"potential", "electron_density", "hole_density"})
                if (!has(need)) missing << QString::fromLatin1(need);
            if (QString::fromLatin1(e.kind) == "recombination" && !has("doping")) missing << "doping";
            if (!missing.isEmpty()) {
                item->setFlags(item->flags() & ~Qt::ItemIsEnabled);
                item->setToolTip(tr("Needs %1, which this result lacks").arg(missing.join(", ")));
            } else {
                item->setToolTip(QString::fromLatin1(e.kind) == "bands"
                                     ? tr("Band edge / quasi-Fermi level [eV], computed by the backend")
                                     : tr("Net SRH + Auger recombination, computed by the backend"));
            }
        }
    }
    const std::string& shown = model_->dimensionality() == 1 ? plot_field_ : view_->field();
    const auto hits = fields_->findItems(QString::fromStdString(shown), Qt::MatchExactly);
    for (auto* h : hits)
        if (h->data(kRoleKind).toString() == "field") fields_->setCurrentItem(h);
}

void MainWindow::onFieldItem(QListWidgetItem* item) {
    if (!item || !model_) return;
    const QString role = item->data(kRoleKind).toString();
    if (role == "field" && model_->dimensionality() == 1) {
        plot_field_ = item->text().toStdString();
        setViewMode(plot::ViewMode::Field);  // rebuilds the curve
    } else if (role == "field") {
        // choosing a map shows the map (Line cut shows it already, and cuts it)
        if (mode_ != plot::ViewMode::Cut) setViewMode(plot::ViewMode::FieldMap);
        view_->setField(item->text().toStdString());
    } else if (role == "derived") {
        if (mode_ != plot::ViewMode::Cut) setViewMode(plot::ViewMode::FieldMap);
        const QString kind = item->data(kRoleDerived).toString();
        if (derived_.count(kind))
            showDerived(kind, item->text());
        else
            requestDerived(kind);
    }
}

const ResultModel* MainWindow::derivedModel(const QString& kind) const {
    const auto it = derived_.find(kind);
    return it == derived_.end() ? nullptr : it->second.model.get();
}

void MainWindow::showDerived(const QString& kind, const QString& field) {
    try {
        view_->setDerivedField(derived_.at(kind).model.get(), field.toStdString());
    } catch (const std::exception& e) {
        reportError(tr("Could not show %1").arg(field), QString::fromUtf8(e.what()));
    }
}

void MainWindow::warmBackend() {
    // Never in the measurement modes (ephemeral settings), and never twice.
    if (warmed_ || !settings_->persistent() || settings_->value("backend/warmup", "on") == "off") return;
    warmed_ = true;
    if (!backend_) backend_ = new BackendClient(resolveBackendConfig(settings_->value("backend/python")), this);
    BackendReply* reply = backend_->call("system.warmup", nullptr, 120000);
    connect(reply, &BackendReply::finished, this, [this, reply] {
        reply->deleteLater();
        if (!reply->ok())  // quiet: a map request will report it properly
            statusBar()->showMessage(tr("Backend unavailable: %1").arg(reply->errorMessage()), 8000);
    });
}

void MainWindow::ensureBackend() {
    if (!backend_) backend_ = new BackendClient(resolveBackendConfig(settings_->value("backend/python")), this);
}

bool MainWindow::resultFileUnchanged(QString* why) const {
    const QFileInfo now(result_path_);
    if (!now.exists()) {
        *why = tr("%1 was deleted after it was opened: the view still shows what was read, but the backend "
                  "cannot compute from it. Reopen or re-run the result.")
                   .arg(QDir::toNativeSeparators(result_path_));
        return false;
    }
    if (now.size() != result_size_ || now.lastModified().toMSecsSinceEpoch() != result_mtime_ms_) {
        *why = tr("%1 changed on disk after it was opened: a map computed from it now would not "
                  "match the view. Reopen it.")
                   .arg(QDir::toNativeSeparators(result_path_));
        return false;
    }
    return true;
}

void MainWindow::requestDerived(const QString& kind) {
    if (derived_pending_.count(kind)) return;  // its reply is on the way
    if (QString why; !resultFileUnchanged(&why)) {
        derived_error_[kind] = why;
        reportError(tr("Could not compute the %1 map").arg(kind), why);
        if (plot::derivedKind(mode_) == kind) rebuildPlot();
        return;
    }
    derived_error_.erase(kind);
    derived_pending_.insert(kind);
    ensureBackend();
    const int generation = result_generation_;
    const QString method = kind == "bands" ? "analysis.band_map" : "analysis.recombination_map";
    statusBar()->showMessage(tr("Computing the %1 map with the backend...").arg(kind));
    BackendReply* reply = backend_->call(method, {{"result", result_path_.toStdString()}}, 300000);
    connect(reply, &BackendReply::finished, this, [this, reply, kind, generation] {
        reply->deleteLater();
        if (generation != result_generation_) return;  // another result is open now
        derived_pending_.erase(kind);
        if (!reply->ok()) {
            derived_error_[kind] = reply->errorMessage();
            reportError(tr("Could not compute the %1 map").arg(kind), reply->errorMessage());
            if (plot::derivedKind(mode_) == kind) rebuildPlot();
            return;
        }
        const QString path = QString::fromStdString(reply->result()["path"].get<std::string>());
        try {
            Derived d;
            d.npz = std::make_unique<NpzFile>(NpzFile::open(path.toStdWString()));
            d.model = std::make_unique<ResultModel>(ResultModel::from_npz(*d.npz, path.toStdString()));
            derived_[kind] = std::move(d);
        } catch (const std::exception& e) {
            derived_error_[kind] = QString::fromUtf8(e.what());
            reportError(tr("Could not read the %1 map").arg(kind), QString::fromUtf8(e.what()));
            if (plot::derivedKind(mode_) == kind) rebuildPlot();
            return;
        }
        QFile::remove(path);  // read eagerly: the service's scratch copy has served its purpose
        statusBar()->showMessage(tr("The %1 map is ready.").arg(kind), 3000);
        if (plot::derivedKind(mode_) == kind) rebuildPlot();  // a 1D curve mode waiting for it
        // Show it only if one of its entries is still the selected one.
        QListWidgetItem* current = fields_->currentItem();
        if (current && current->data(kRoleKind).toString() == "derived" &&
            current->data(kRoleDerived).toString() == kind)
            showDerived(kind, current->text());
    });
}

// -- view modes (P2-S3) -------------------------------------------------------------

void MainWindow::rebuildModes() {
    modes_ = model_ ? plot::availableModes(*model_) : std::vector<plot::ViewMode>{};
    {
        const QSignalBlocker block(mode_combo_);
        mode_combo_->clear();
        for (plot::ViewMode m : modes_) mode_combo_->addItem(plot::modeName(m), static_cast<int>(m));
        mode_combo_->setEnabled(!modes_.empty());
    }
    mode_menu_->clear();
    for (plot::ViewMode m : modes_) {
        QAction* act = mode_menu_->addAction(plot::modeName(m));
        act->setObjectName(QStringLiteral("ViewMode_") + plot::modeKey(m));
        act->setCheckable(true);
        act->setData(static_cast<int>(m));
        connect(act, &QAction::triggered, this, [this, m] { setViewMode(m); });
    }
    mode_menu_->setEnabled(!modes_.empty());
    if (!model_ || !setViewMode(plot::defaultMode(*model_))) {
        mode_ = plot::ViewMode::FieldMap;
        plot_->hide();
        view_->show();
        syncControls();
    }
}

bool MainWindow::setViewMode(plot::ViewMode m) {
    if (std::find(modes_.begin(), modes_.end(), m) == modes_.end()) return false;
    mode_ = m;
    const bool curve = plot::isCurveMode(m);
    // Hidden, never reparented: the FieldView keeps its GL context. Line cut
    // shows both, the map above its curve (decision 7).
    if (!curve) plot_->hide();
    if (!plot::showsMap(m)) view_->hide();
    view_->setVisible(plot::showsMap(m));
    plot_->setVisible(curve);
    if (m == plot::ViewMode::Cut) {
        const int h = std::max(2, central_->height());
        central_->setSizes({h * 3 / 5, h - h * 3 / 5});
    }
    updateCutLine();
    readout_->clear();
    if (curve) {
        const QString kind = plot::derivedKind(m);
        if (!kind.isEmpty() && !derived_.count(kind) && !derived_error_.count(kind)) requestDerived(kind);
        rebuildPlot();
    }
    syncControls();
    return true;
}

void MainWindow::rebuildPlot() {
    using plot::ViewMode;
    if (!model_ || !plot::isCurveMode(mode_)) return;
    plot::PlotModel pm;
    switch (mode_) {
        case ViewMode::FieldMap: return;
        case ViewMode::Cut:
            cut_source_ = view_->fieldSource();
            cut_field_ = view_->field();
            pm = cut_source_ ? plot::cutModel(*cut_source_, cut_field_,
                                              cut_horizontal_ ? CutOrientation::Horizontal : CutOrientation::Vertical,
                                              static_cast<std::size_t>(cut_index_), plot_log_)
                             : plot::messageModel(tr("No field to cut"));
            break;
        case ViewMode::Field: pm = plot::fieldModel(*model_, plot_field_, plot_log_); break;
        case ViewMode::Curves:
            pm = plot::seriesModel(*model_, sweep_channel_.toStdString(), plot_log_, overlays_);
            break;
        case ViewMode::CV: pm = plot::cvModel(*model_, false, overlays_); break;
        case ViewMode::Transient: pm = plot::transientModel(*model_, false); break;
        case ViewMode::AC: pm = plot::acModel(*model_); break;
        case ViewMode::Convergence: pm = plot::convergenceModel(*model_); break;
        case ViewMode::Bands:
        case ViewMode::Recombination: {
            const QString kind = plot::derivedKind(mode_);
            if (const auto err = derived_error_.find(kind); err != derived_error_.end())
                pm = plot::messageModel(tr("Could not compute the %1:\n%2").arg(kind, err->second));
            else if (mode_ == ViewMode::Bands)
                pm = plot::bandsModel(derivedModel(kind));
            else
                pm = plot::recombinationModel(derivedModel(kind));
            break;
        }
    }
    plot_->setModel(plot::nothingToPlot(std::move(pm)));
}

void MainWindow::syncControls() {
    const bool curve = model_ && plot::isCurveMode(mode_);
    const bool can_log = curve && plot::hasLogToggle(mode_);
    {
        const QSignalBlocker block(log_);
        log_->setEnabled(!curve || can_log);
        log_->setChecked(curve ? can_log && plot_log_ : view_->logScale());
    }
    {
        const QSignalBlocker block(mode_combo_);
        mode_combo_->setCurrentIndex(mode_combo_->findData(static_cast<int>(mode_)));
    }
    for (QAction* a : mode_menu_->actions()) a->setChecked(a->data().toInt() == static_cast<int>(mode_));
    PlotPanel::State st;
    st.mode = model_ ? plot::modeName(mode_) : QString();
    st.channels = channels_;
    st.channel = sweep_channel_;
    st.channel_enabled = mode_ == plot::ViewMode::Curves;
    st.log = plot_log_;
    st.log_enabled = can_log;
    st.cut_enabled = mode_ == plot::ViewMode::Cut;
    st.cut_horizontal = cut_horizontal_;
    st.cut_index = cut_index_;
    st.cut_nodes = cutAxisNodes();
    st.overlays_enabled = mode_ == plot::ViewMode::Curves || mode_ == plot::ViewMode::CV;
    {
        const std::string ch = overlayChannel();
        for (const auto& o : overlays_) {
            const bool has = std::any_of(o.sweep.channels.begin(), o.sweep.channels.end(),
                                         [&](const Channel& c) { return c.name == ch; });
            st.overlays.push_back({o.label, o.kind == plot::OverlayCurve::Kind::Comparison,
                                   has ? QString() : tr("it has no '%1' channel").arg(QString::fromStdString(ch)),
                                   QDir::toNativeSeparators(o.path)});
        }
    }
    if (st.cut_nodes > 0) {
        const auto& axis = model_->axis(cut_horizontal_ ? 1 : 0);
        st.cut_position = tr("%1 = %2 um (node %3 of %4)")
                              .arg(cut_horizontal_ ? "y" : "x")
                              .arg(QString::number(axis[static_cast<std::size_t>(cut_index_)] * 1e4, 'g', 4))
                              .arg(cut_index_)
                              .arg(st.cut_nodes);
    }
    plot_panel_->setState(st);
}

std::string MainWindow::overlayChannel() const {
    if (mode_ == plot::ViewMode::CV) {
        const auto ch = model_ ? plot::sweepChannels(*model_) : std::vector<std::string>{};
        return ch.empty() ? std::string() : ch.front();  // C-V draws the first channel
    }
    return sweep_channel_.toStdString();
}

QString MainWindow::addOverlay(const QString& path, plot::OverlayCurve::Kind kind) {
    const QString title = tr("Could not add the overlay");
    auto refuse = [&](const QString& why) {
        reportError(title, tr("%1:\n%2").arg(QFileInfo(path).fileName(), why));
        return why;
    };
    if (!model_ || (mode_ != plot::ViewMode::Curves && mode_ != plot::ViewMode::CV))
        return refuse(tr("overlays compare sweeps: show the Curves or C-V view first"));
    const QFileInfo info(path);
    if (!info.exists()) return refuse(tr("file not found"));
    const QString abs = info.absoluteFilePath();
    if (QFileInfo(result_path_) == info) return refuse(tr("it is the open result itself"));
    for (const auto& o : overlays_)
        if (QFileInfo(o.path) == info && o.kind == kind) return refuse(tr("it is already overlaid"));
    SweepSeries primary, sweep;
    try {
        primary = model_->sweep();
        const NpzFile npz = NpzFile::open(abs.toStdWString());
        const ResultModel r = ResultModel::from_npz(npz, abs.toStdString());
        if (!r.has_sweep()) return refuse(tr("it has no sweep"));
        sweep = r.sweep();  // decoded now: the file is not kept open
    } catch (const std::exception& e) {
        return refuse(QString::fromUtf8(e.what()));
    }
    if (const QString why = plot::overlayMismatch(primary, sweep, overlayChannel()); !why.isEmpty())
        return refuse(why);
    if (kind == plot::OverlayCurve::Kind::Comparison)
        overlays_.erase(std::remove_if(overlays_.begin(), overlays_.end(),
                                       [](const auto& o) { return o.kind == plot::OverlayCurve::Kind::Comparison; }),
                        overlays_.end());
    overlays_.push_back({kind, info.completeBaseName(), abs, std::move(sweep)});
    rebuildPlot();
    syncControls();
    return {};
}

bool MainWindow::removeOverlay(int index) {
    if (index < 0 || index >= static_cast<int>(overlays_.size())) return false;
    overlays_.erase(overlays_.begin() + index);
    rebuildPlot();
    syncControls();
    return true;
}

bool MainWindow::setOverlayLabel(int index, const QString& label) {
    if (index < 0 || index >= static_cast<int>(overlays_.size()) || label.trimmed().isEmpty()) {
        syncControls();  // an empty edit is undone in the list
        return false;
    }
    overlays_[static_cast<std::size_t>(index)].label = label.trimmed();
    rebuildPlot();
    syncControls();
    return true;
}

void MainWindow::chooseOverlay(plot::OverlayCurve::Kind kind) {
    const QString path = QFileDialog::getOpenFileName(
        this, kind == plot::OverlayCurve::Kind::Comparison ? tr("Add a comparison sweep") : tr("Add a sweep to the family"),
        QFileInfo(result_path_).absolutePath(), tr("PyTCAD results (*.npz)"));
    if (!path.isEmpty()) addOverlay(path, kind);
}

int MainWindow::cutAxisNodes() const {
    if (!model_ || model_->dimensionality() != 2) return 0;
    return static_cast<int>(model_->axis(cut_horizontal_ ? 1 : 0).size());
}

bool MainWindow::setCut(bool horizontal, int index) {
    const bool was = cut_horizontal_;
    cut_horizontal_ = horizontal;
    const int n = cutAxisNodes();
    if (n == 0 || index < 0) {
        cut_horizontal_ = was;
        return false;
    }
    // An orientation switch keeps the index where the new axis allows it.
    if (horizontal != was) index = std::min(index, n - 1);
    if (index >= n) {
        cut_horizontal_ = was;
        return false;
    }
    cut_index_ = index;
    if (mode_ == plot::ViewMode::Cut) {
        rebuildPlot();
        updateCutLine();
    }
    syncControls();
    return true;
}

void MainWindow::updateCutLine() {
    if (mode_ != plot::ViewMode::Cut || cutAxisNodes() == 0) {
        if (view_->cutLine()) view_->setCutLine(std::nullopt);
        return;
    }
    const auto& axis = view_->axisUm(cut_horizontal_ ? 1 : 0);
    if (axis.empty()) return;
    const std::size_t i = std::min(static_cast<std::size_t>(cut_index_), axis.size() - 1);
    view_->setCutLine(FieldView::CutLine{
        cut_horizontal_ ? CutOrientation::Horizontal : CutOrientation::Vertical, axis[i]});
}

void MainWindow::onLogToggled(bool on) {
    if (model_ && plot::isCurveMode(mode_))
        setPlotLog(on);
    else
        view_->setLogScale(on);  // displayChanged syncs the controls
}

void MainWindow::setPlotLog(bool on) {
    plot_log_ = on;
    if (plot::hasLogToggle(mode_)) rebuildPlot();
    syncControls();
}

bool MainWindow::setSweepChannel(const QString& channel) {
    if (!channels_.contains(channel)) return false;
    sweep_channel_ = channel;
    if (mode_ == plot::ViewMode::Curves) rebuildPlot();
    syncControls();
    return true;
}

}  // namespace tcad::desktop
