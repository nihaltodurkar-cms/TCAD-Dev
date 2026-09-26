// The shell (NATIVE-DESKTOP-PLAN.md section 15.13): a QMainWindow whose
// central area is an ADS dock manager. The FieldView is the manager's
// fixed central widget -- it never floats, because floating reparents a
// native GL widget into a new window -- and panels (Fields, ...) dock
// around it. Log-scale toggle, Fit, and the hover readout in the status
// bar.
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

#include <QMainWindow>

#include <map>
#include <memory>

class QLabel;
class QListWidget;
class QAction;
class QMenu;
class QListWidgetItem;

namespace ads {
class CDockManager;
class CDockWidget;
}  // namespace ads

namespace tcad::desktop {

class DisplayPanel;
class FieldView;
class InfoPanel;
class PlaybackPanel;
class View3DPanel;

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
    // The backend client, created on the first derived-map request (nullptr before).
    BackendClient* backendClient() const { return backend_; }
    // Derived maps already fetched for the open result ("bands", "recombination").
    const ResultModel* derivedModel(const QString& kind) const;
    QListWidget* fieldList() const { return fields_; }
    AppSettings& settings() const { return *settings_; }
    theme::ThemeController* theme() const { return theme_; }
    // Applies and persists the theme choice (View > Theme).
    void setThemeChoice(theme::Choice c);
    // The last error tryOpen / layout restore reported ("" if none).
    QString lastError() const { return last_error_; }
    // Back to the default arrangement: Fields docked left, 240 px wide,
    // with Info, Display and 3D tabbed below it, and Playback below those
    // (shown when the open result has sweep snapshots).
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
    void ensureBackend();
    // The backend reads the result FILE, the view shows what was read at
    // open: before any backend call, the file must still be the one opened
    // (same size and modification time). False, with the reason, if it was
    // deleted or changed (15.23, S8b).
    bool resultFileUnchanged(QString* why) const;

    std::unique_ptr<AppSettings> settings_;
    theme::ThemeController* theme_ = nullptr;
    QList<QAction*> theme_actions_;  // View > Theme: System, Light, Dark
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
