// The Telemetry dock (NATIVE-DESKTOP-PLAN.md 17.2/17.7, P3-S5): a run's live
// state from its PYTCAD_PROGRESS records -- the stage, the Newton iteration,
// the sweep point k of N, the transient step, the elapsed time -- and the
// residual history on a log axis.
//
// The history is drawn by the Convergence mode's own function, from the
// same trace steps (TelemetryModel), so the live plot of a finished run is
// its result's Convergence plot. Labels update per record; the plot is
// redrawn at most every kPlotMs.
//
// Stage-level progress only (17.7 point 2): the MPI engine and a C-V run
// print no Newton lines (devsim, which prints none either, is not a native
// backend: 17.13). The dock says so up front
// when the run's settings tell, and at the end when a run reported stages
// but no Newton iteration (the auto engine may pick MPI) -- instead of an
// empty plot that looks broken.
#pragma once

#include "run/telemetry.hpp"

#include <QElapsedTimer>
#include <QString>
#include <QTimer>
#include <QWidget>

class QLabel;

namespace tcad::desktop {

namespace plot {
class PlotView;
}

class TelemetryPanel : public QWidget {
    Q_OBJECT

public:
    static constexpr int kPlotMs = 100;

    explicit TelemetryPanel(QWidget* parent = nullptr);

    // A run starts: `what` names it; `stage_level_reason` non-empty when the
    // run is known to report stages only (e.g. "a C-V run").
    void begin(const QString& what, const QString& stage_level_reason);
    void apply(const nlohmann::ordered_json& record);
    // The run ended: "Finished", "Failed" or "Canceled".
    void end(const QString& outcome);
    void refreshPlot();  // redraw now (tests; the timer does it otherwise)

    const TelemetryModel& model() const { return model_; }
    plot::PlotView* plotView() const { return plot_; }
    bool running() const { return running_; }
    // The labels' texts, for tests.
    QString statusText() const;
    QString stageText() const;
    QString iterationText() const;
    QString sweepText() const;
    QString transientText() const;
    QString noteText() const;
    QString elapsedText() const;

private:
    void updateLabels();
    void updateElapsed();
    QString emptyText() const;

    TelemetryModel model_;
    plot::PlotView* plot_ = nullptr;
    QLabel* status_ = nullptr;
    QLabel* stage_ = nullptr;
    QLabel* iteration_ = nullptr;
    QLabel* sweep_ = nullptr;
    QLabel* transient_ = nullptr;
    QLabel* note_ = nullptr;
    QLabel* elapsed_ = nullptr;
    QTimer plot_timer_;
    QTimer elapsed_timer_;
    QElapsedTimer clock_;
    QString what_;
    QString stage_level_reason_;
    bool running_ = false;
    bool ever_ran_ = false;
};

}  // namespace tcad::desktop
