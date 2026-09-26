// The shell (NATIVE-DESKTOP-PLAN.md section 15.13): a QMainWindow whose
// central area is an ADS dock manager. The manager's fixed central widget
// is a splitter holding the FieldView and the PlotView (P2-S3, 16.2
// decision 7) -- it never floats, because floating reparents a native GL
// widget into a new window -- and panels (Fields, ...) dock around it.
// A view-mode selector (toolbar combo and View menu) shows the field map
// or one of the curve modes the open result supports; the FieldView is
// only ever hidden or shown, never reparented. Log-scale toggle and Fit
// act on the visible view; the hover readout is in the status bar.
//
// Every way of opening a result (command line, File > Open, Open
// Recent, drag-and-drop) goes through tryOpen(): a failure reports a
// named error and leaves the current result on screen. Layout, window
// geometry and recent files persist through AppSettings.
#pragma once

#include "app_settings.hpp"
#include "backend/backend_client.hpp"
#include "theme/theme.hpp"
#include "data/npz.hpp"
#include "data/result_model.hpp"
#include "views/plot/curve_modes.hpp"

#include <QMainWindow>

#include <map>
#include <set>
#include <memory>
#include <string>
#include <vector>

class QLabel;
class QListWidget;
class QAction;
class QComboBox;
class QSplitter;
class QMenu;
class QListWidgetItem;
class QTimer;

namespace ads {
class CDockManager;
class CDockWidget;
}  // namespace ads

namespace tcad::desktop {

class DisplayPanel;
class FieldView;
class InfoPanel;
class PlaybackPanel;
class PlotPanel;
namespace plot {
class PlotView;
}
class View3DPanel;
class ConsolePanel;
class RunController;
class BatchController;
class RunPanel;
class TelemetryPanel;

class MainWindow : public QMainWindow {
    Q_OBJECT

public:
    // Restores the saved layout from `settings` when it has one.
    explicit MainWindow(std::unique_ptr<AppSettings> settings, QWidget* parent = nullptr);
    ~MainWindow() override;

    // Opens and shows a result; throws NpzError / ResultSchemaError on a
    // bad file. Callers that face the user use tryOpen().
    void openResult(const QString& path);
    // Validates `path`, opens it and records it in the recent files. On
    // failure: reports a named error (status bar + a non-modal message
    // box), keeps the current result, returns false.
    bool tryOpen(const QString& path);

    FieldView* fieldView() const { return view_; }
    const ResultModel* result() const { return model_.get(); }
    QString resultPath() const { return result_path_; }
    ads::CDockManager* dockManager() const { return docks_; }
    ads::CDockWidget* fieldsDock() const { return fields_dock_; }
    ads::CDockWidget* infoDock() const { return info_dock_; }
    InfoPanel* infoPanel() const { return info_; }
    ads::CDockWidget* displayDock() const { return display_dock_; }
    DisplayPanel* displayPanel() const { return display_; }
    ads::CDockWidget* view3dDock() const { return view3d_dock_; }
    View3DPanel* view3dPanel() const { return view3d_; }
    ads::CDockWidget* playbackDock() const { return playback_dock_; }
    PlaybackPanel* playbackPanel() const { return playback_; }
    // -- curve modes (P2-S3) -------------------------------------------------------
    plot::PlotView* plotView() const { return plot_; }
    QSplitter* centralSplitter() const { return central_; }
    ads::CDockWidget* plotDock() const { return plot_dock_; }
    PlotPanel* plotPanel() const { return plot_panel_; }
    QComboBox* viewModeCombo() const { return mode_combo_; }
    // The modes the open result can show, in menu order (empty: none open).
    const std::vector<plot::ViewMode>& availableModes() const { return modes_; }
    plot::ViewMode viewMode() const { return mode_; }
    // Shows `m`; false, and nothing changes, when the open result cannot.
    bool setViewMode(plot::ViewMode m);
    // Curves mode's channel; false when the sweep has no such channel.
    bool setSweepChannel(const QString& channel);
    QString sweepChannel() const { return sweep_channel_; }
    // Log y of the modes with a log toggle (the 1D field, Curves).
    void setPlotLog(bool on);
    bool plotLog() const { return plot_log_; }
    // The 1D field the Field mode draws.
    const std::string& plotField() const { return plot_field_; }
    // Line cut mode (P2-S4): orientation and node index on the cut axis (y
    // for horizontal, x for vertical). False, nothing changed, when the
    // index is outside the open 2D result's axis.
    bool setCut(bool horizontal, int index);
    bool cutHorizontal() const { return cut_horizontal_; }
    int cutIndex() const { return cut_index_; }
    // Overlays (P2-S5): sweeps from other result files over the open one's,
    // in Curves or C-V mode. Returns "" when added; otherwise the reason,
    // which is also reported. A second comparison replaces the first; the
    // same file twice is refused. Cleared when another result opens.
    QString addOverlay(const QString& path, plot::OverlayCurve::Kind kind);
    bool removeOverlay(int index);
    bool setOverlayLabel(int index, const QString& label);
    const std::vector<plot::OverlayCurve>& overlays() const { return overlays_; }
    // The backend client, created on the first backend call -- a derived map,
    // the warm-up, or the Run dock (nullptr before).
    BackendClient* backendClient() const { return backend_; }
    // -- running (P3-S4) ------------------------------------------------------------
    RunController* runController() const { return run_ctl_; }
    BatchController* batchController() const { return batch_; }
    RunPanel* runPanel() const { return run_panel_; }
    ConsolePanel* consolePanel() const { return console_; }
    ads::CDockWidget* runDock() const { return run_dock_; }
    ads::CDockWidget* consoleDock() const { return console_dock_; }
    TelemetryPanel* telemetryPanel() const { return telemetry_; }
    ads::CDockWidget* telemetryDock() const { return telemetry_dock_; }
    QAction* runAction() const { return run_act_; }
    QAction* stopAction() const { return stop_act_; }
    // The directory runs write to: the settings key run/dir, else
    // <LocalAppData>/PyTCAD/runs (decision 4).
    QString runsDir() const;
    // Copies the open result to `target` (File > Save result as...); false,
    // with the reason, on failure.
    bool saveResultAs(const QString& target, QString* error);
    // Derived maps already fetched for the open result ("bands", "recombination").
    const ResultModel* derivedModel(const QString& kind) const;
    QListWidget* fieldList() const { return fields_; }
    AppSettings& settings() const { return *settings_; }
    // The last error tryOpen / layout restore reported ("" if none).
    QString lastError() const { return last_error_; }
    // Back to the default arrangement: Fields docked left, 240 px wide,
    // with Info, Display and 3D tabbed below it, and Playback below those
    // (shown when the open result has sweep snapshots). Plot is tabbed
    // with Display.
    void resetLayout();
    // The dock state as built, before any restore: the default layout's
    // STRUCTURE (its splitter sizes are pre-show zeros -- compare
    // structure only).
    QByteArray defaultLayout() const { return default_layout_; }

protected:
    void closeEvent(QCloseEvent* event) override;
    void dragEnterEvent(QDragEnterEvent* event) override;
    void dropEvent(QDropEvent* event) override;

private:
    void chooseResult();
    void rebuildRecentMenu();
    void reportError(const QString& title, const QString& text);
    void restoreSavedLayout();
    void populateFields();
    void onFieldItem(QListWidgetItem* item);
    void requestDerived(const QString& kind);
    void showDerived(const QString& kind, const QString& field);
    void warmBackend();
    void rebuildModes();    // after an open: the selector's entries and the default mode
    void rebuildPlot();     // the current curve mode's model
    void syncControls();    // the Log action and the Plot panel follow the visible view
    void onLogToggled(bool on);
    void updateCutLine();   // the map's cut line follows the mode and the cut
    int cutAxisNodes() const;
    void chooseOverlay(plot::OverlayCurve::Kind kind);
    std::string overlayChannel() const;  // the channel the open sweep mode draws
    void ensureBackend();
    // The backend reads the result FILE, the view shows what was read at
    // open: before any backend call, the file must still be the one opened
    // (same size and modification time). False, with the reason, if it was
    // deleted or changed (15.23, S8b).
    bool resultFileUnchanged(QString* why) const;

    void buildRunning();   // the Run and Console docks, their actions and wiring
    void onRunFinished(const QString& path);
    void updateRunStatus();
    void beginTelemetry();
    // P3-S6: a family / the comparison of the open result, which must be
    // the last run's (the batch re-solves that run); false, reported, if not.
    bool startFamily(const QString& stepped, double start, double stop, double step);
    bool startComparison();
    bool batchBaseIsOpen(const QString& what);
    void onBatchCurve(const QString& path, const QString& label, bool comparison);

    std::unique_ptr<AppSettings> settings_;
    RunController* run_ctl_ = nullptr;
    BatchController* batch_ = nullptr;
    RunPanel* run_panel_ = nullptr;
    ConsolePanel* console_ = nullptr;
    ads::CDockWidget* run_dock_ = nullptr;
    ads::CDockWidget* console_dock_ = nullptr;
    TelemetryPanel* telemetry_ = nullptr;
    ads::CDockWidget* telemetry_dock_ = nullptr;
    QAction* run_act_ = nullptr;
    QAction* stop_act_ = nullptr;
    QAction* save_as_ = nullptr;
    QTimer* run_tick_ = nullptr;   // the status bar's elapsed time, once a second
    qint64 run_started_ms_ = 0;
    QString run_stage_;
    ads::CDockManager* docks_ = nullptr;
    ads::CDockWidget* fields_dock_ = nullptr;
    ads::CDockWidget* info_dock_ = nullptr;
    InfoPanel* info_ = nullptr;
    ads::CDockWidget* display_dock_ = nullptr;
    DisplayPanel* display_ = nullptr;
    ads::CDockWidget* view3d_dock_ = nullptr;
    View3DPanel* view3d_ = nullptr;
    ads::CDockWidget* playback_dock_ = nullptr;
    PlaybackPanel* playback_ = nullptr;
    // Derived maps (S5g): computed by the backend service, read with the
    // conformance-gated reader, kept until the result changes.
    struct Derived {
        std::unique_ptr<NpzFile> npz;
        std::unique_ptr<ResultModel> model;
    };
    std::map<QString, Derived> derived_;
    BackendClient* backend_ = nullptr;
    int result_generation_ = 0;  // a reply for an older result is ignored
    bool warmed_ = false;        // system.warmup sent (once per window)
    QByteArray default_layout_;  // saveState() right after construction
    QString ads_default_qss_;    // ADS's own stylesheet, re-coloured per scheme
    FieldView* view_ = nullptr;
    QSplitter* central_ = nullptr;
    plot::PlotView* plot_ = nullptr;
    ads::CDockWidget* plot_dock_ = nullptr;
    PlotPanel* plot_panel_ = nullptr;
    QComboBox* mode_combo_ = nullptr;
    QMenu* mode_menu_ = nullptr;
    std::vector<plot::ViewMode> modes_;
    plot::ViewMode mode_ = plot::ViewMode::FieldMap;
    std::string plot_field_;
    QString sweep_channel_;
    bool plot_log_ = false;
    bool cut_horizontal_ = true;   // QML's default: a horizontal cut at y = 0 (node 0)
    int cut_index_ = 0;
    const ResultModel* cut_source_ = nullptr;  // what the cut curve was built from
    std::string cut_field_;
    std::vector<plot::OverlayCurve> overlays_;
    std::map<QString, QString> derived_error_;  // a failed derived request, shown by its curve mode
    std::set<QString> derived_pending_;         // requested, reply not yet in
    QStringList channels_;                      // the open sweep's channels, archive order
    QListWidget* fields_ = nullptr;
    QLabel* readout_ = nullptr;
    QAction* log_ = nullptr;
    qint64 result_size_ = -1;    // the result file's size and modification time at open
    qint64 result_mtime_ms_ = -1;
    QMenu* recent_ = nullptr;
    QString result_path_;
    QString last_error_;
    std::unique_ptr<NpzFile> npz_;
    std::unique_ptr<ResultModel> model_;
};

}  // namespace tcad::desktop
