#include "main_window.hpp"

#include "display_panel.hpp"
#include "info_panel.hpp"
#include "playback_panel.hpp"
#include "view3d_panel.hpp"
#include "views/field/field_view.hpp"

#include <DockAreaWidget.h>
#include <DockManager.h>
#include <DockWidget.h>

#include <QAction>
#include <QActionGroup>
#include <QCloseEvent>
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
    // polished, so a palette applied after them left the startup theme's
    // dock panels a stock grey (S3c screenshot; gated by the shell test).
    theme_ = new theme::ThemeController(this);
    theme_->setChoice(theme::choiceFromString(settings_->value("theme/choice")).value_or(theme::Choice::System));
    setWindowTitle("PyTCAD Desktop");
    setAcceptDrops(true);
    // Uncompressed XML state: readable in the settings file, and
    // comparable structurally by the layout gate (section 15.13 rev. 8).
    ads::CDockManager::setConfigFlags(ads::CDockManager::DefaultOpaqueConfig);
    ads::CDockManager::setConfigFlag(ads::CDockManager::XmlCompressionEnabled, false);
    docks_ = new ads::CDockManager(this);  // becomes this window's central widget
    ads_default_qss_ = docks_->styleSheet();

    view_ = new FieldView(this);
    auto* central = new ads::CDockWidget(docks_, tr("Field view"));
    central->setObjectName("FieldViewDock");
    central->setWidget(view_, ads::CDockWidget::ForceNoScrollArea);
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
    connect(log_, &QAction::toggled, view_, &FieldView::setLogScale);

    auto* fit = new QAction(tr("Fit"), this);
    fit->setShortcut(Qt::Key_F);
    connect(fit, &QAction::triggered, view_, &FieldView::resetView);

    auto* file = menuBar()->addMenu(tr("&File"));
    file->addAction(open);
    file->addMenu(recent_);
    file->addSeparator();
    file->addAction(quit);
    auto* view = menuBar()->addMenu(tr("&View"));
    view->addAction(fit);
    view->addAction(log_);
    view->addAction(fields_dock_->toggleViewAction());
    view->addAction(info_dock_->toggleViewAction());
    view->addAction(display_dock_->toggleViewAction());
    view->addAction(view3d_dock_->toggleViewAction());
    view->addAction(playback_dock_->toggleViewAction());
    view->addSeparator();
    auto* reset = new QAction(tr("Reset layout"), this);
    connect(reset, &QAction::triggered, this, &MainWindow::resetLayout);
    view->addAction(reset);
    auto* theme_menu = view->addMenu(tr("&Theme"));
    auto* theme_group = new QActionGroup(this);
    for (auto [choice, label] : {std::pair{theme::Choice::System, tr("&System")},
                                 std::pair{theme::Choice::Light, tr("&Light")},
                                 std::pair{theme::Choice::Dark, tr("&Dark")}}) {
        auto* act = theme_menu->addAction(label);
        act->setCheckable(true);
        act->setData(theme::toString(choice));
        theme_group->addAction(act);
        theme_actions_ << act;
        connect(act, &QAction::triggered, this, [this, choice] { setThemeChoice(choice); });
    }
    auto* tools = addToolBar(tr("Main"));
    tools->setObjectName("MainToolBar");
    tools->addAction(open);
    tools->addAction(fit);
    tools->addAction(log_);

    readout_ = new QLabel(this);
    readout_->setObjectName("Readout");
    statusBar()->addPermanentWidget(readout_, 1);
    connect(view_, &FieldView::readoutChanged, readout_, &QLabel::setText);
    connect(fields_, &QListWidget::currentItemChanged, this,
            [this](QListWidgetItem* item, QListWidgetItem*) { onFieldItem(item); });
    // The toolbar's Log action follows the view (the Display panel edits it too).
    connect(view_, &FieldView::displayChanged, this, [this] {
        const QSignalBlocker block(log_);
        log_->setChecked(view_->logScale());
    });
    // The theme's menu state and the view's VTK colours: the palette
    // itself was applied first thing (above).
    connect(theme_, &theme::ThemeController::schemeChanged, view_, &FieldView::applyTheme);
    // ADS paints from its own stylesheet's palette(...) references, which
    // it fixes when its widgets are polished -- a startup theme left dock
    // panels a stock grey. Instead, its default stylesheet is rewritten
    // with the token colours on every scheme change (section 15.13 S3c).
    connect(theme_, &theme::ThemeController::schemeChanged, this, [this](theme::Scheme s) {
        docks_->setStyleSheet(theme::themedStyleSheet(ads_default_qss_, s));
    });
    setThemeChoice(theme_->choice());

    default_layout_ = docks_->saveState();
    resize(1500, 950);  // the default; a saved geometry replaces it
    restoreSavedLayout();
    if (!settings_->writable())
        statusBar()->showMessage(tr("Settings file is read-only (%1): the layout and recent files will not be saved.")
                                     .arg(settings_->fileName()));
}

MainWindow::~MainWindow() = default;

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

void MainWindow::setThemeChoice(theme::Choice c) {
    theme_->setChoice(c);
    settings_->setValue("theme/choice", theme::toString(c));
    for (QAction* a : theme_actions_) a->setChecked(a->data().toString() == theme::toString(c));
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
    display_dock_->setAsCurrentTab();
    docks_->addDockWidget(ads::BottomDockWidgetArea, playback_dock_, info_dock_->dockAreaWidget());
    playback_dock_->toggleView(view_->snapshots() != nullptr);
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

void MainWindow::closeEvent(QCloseEvent* event) {
    settings_->saveLayout({saveGeometry(), docks_->saveState()});
    settings_->sync();  // a read-only file was already reported at startup
    QMainWindow::closeEvent(event);
}

void MainWindow::openResult(const QString& path) {
    auto npz = std::make_unique<NpzFile>(NpzFile::open(path.toStdWString()));
    auto model = std::make_unique<ResultModel>(ResultModel::from_npz(*npz, path.toStdString()));
    view_->setResult(nullptr);  // drop references into the old models first
    derived_.clear();
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
    populateFields();
    info_->showResult(model_.get(), path);
    setWindowTitle(QString("%1 - PyTCAD Desktop").arg(QFileInfo(path).fileName()));
    if (model_->dimensionality() == 1)
        statusBar()->showMessage(tr("1D result: curve views arrive with PlotView (P2)."));
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
    if (model_ && model_->dimensionality() >= 2) QTimer::singleShot(300, this, &MainWindow::warmBackend);
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
    const auto hits = fields_->findItems(QString::fromStdString(view_->field()), Qt::MatchExactly);
    for (auto* h : hits)
        if (h->data(kRoleKind).toString() == "field") fields_->setCurrentItem(h);
}

void MainWindow::onFieldItem(QListWidgetItem* item) {
    if (!item || !model_) return;
    const QString role = item->data(kRoleKind).toString();
    if (role == "field") {
        view_->setField(item->text().toStdString());
    } else if (role == "derived") {
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
    if (QString why; !resultFileUnchanged(&why)) {
        reportError(tr("Could not compute the %1 map").arg(kind), why);
        return;
    }
    ensureBackend();
    const int generation = result_generation_;
    const QString method = kind == "bands" ? "analysis.band_map" : "analysis.recombination_map";
    statusBar()->showMessage(tr("Computing the %1 map with the backend...").arg(kind));
    BackendReply* reply = backend_->call(method, {{"result", result_path_.toStdString()}}, 300000);
    connect(reply, &BackendReply::finished, this, [this, reply, kind, generation] {
        reply->deleteLater();
        if (generation != result_generation_) return;  // another result is open now
        if (!reply->ok()) {
            reportError(tr("Could not compute the %1 map").arg(kind), reply->errorMessage());
            return;
        }
        const QString path = QString::fromStdString(reply->result()["path"].get<std::string>());
        try {
            Derived d;
            d.npz = std::make_unique<NpzFile>(NpzFile::open(path.toStdWString()));
            d.model = std::make_unique<ResultModel>(ResultModel::from_npz(*d.npz, path.toStdString()));
            derived_[kind] = std::move(d);
        } catch (const std::exception& e) {
            reportError(tr("Could not read the %1 map").arg(kind), QString::fromUtf8(e.what()));
            return;
        }
        QFile::remove(path);  // read eagerly: the service's scratch copy has served its purpose
        statusBar()->showMessage(tr("The %1 map is ready.").arg(kind), 3000);
        // Show it only if one of its entries is still the selected one.
        QListWidgetItem* current = fields_->currentItem();
        if (current && current->data(kRoleKind).toString() == "derived" &&
            current->data(kRoleDerived).toString() == kind)
            showDerived(kind, current->text());
    });
}

}  // namespace tcad::desktop
