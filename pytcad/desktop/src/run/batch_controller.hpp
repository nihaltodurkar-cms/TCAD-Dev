// Families and comparisons by running (NATIVE-DESKTOP-PLAN.md 17.14,
// P3-S6). Qt Core only.
//
// A family re-solves the last run's sweep at each value of a stepped
// contact; a comparison re-solves it with every model off. The jobs come
// from the backend (family.jobs / comparison.job: QML's rules, labels and
// refusals) and run one after another on this controller's OWN JobRunner
// (decision 2: families have their own pool), beside the main run.
// Each finished job is handed on as curveFinished(path, label, kind); the
// window draws it as a P2-S5 overlay.
//
// A curve that fails ends the batch (the curves already finished stay, as
// in QML); stop() cancels the running job and drops the rest.
#pragma once

#include "backend/backend_client.hpp"
#include "run/job_runner.hpp"

#include <nlohmann/json.hpp>

#include <QObject>
#include <QString>
#include <QStringList>

#include <deque>
#include <functional>

namespace tcad::desktop {

class BatchController : public QObject {
    Q_OBJECT

public:
    enum class Kind { Family, Comparison };
    enum class Outcome { None, Finished, Failed, Canceled };

    BatchController(std::function<BackendClient*()> backend, RunnerConfig runner, QObject* parent = nullptr);
    ~BatchController() override;

    // `base` is the last run's configured spec (RunController::lastRunSpec);
    // a family steps `stepped` over start..stop by step, re-solving base's
    // own sweep. False (and failed()) when refused before anything starts.
    bool runFamily(const nlohmann::json& base, const QString& stepped, double start, double stop, double step);
    bool runComparison(const nlohmann::json& base);
    void stop();

    bool busy() const { return busy_; }
    Kind kind() const { return kind_; }
    int total() const { return total_; }
    int finishedCurves() const { return finished_; }
    Outcome lastOutcome() const { return outcome_; }
    JobRunner* runner() const { return runner_; }

signals:
    void busyChanged(bool busy);
    void message(const QString& text);                  // for the console
    void status(const QString& text);                   // for the Run dock
    void curveFinished(const QString& path, const QString& label, tcad::desktop::BatchController::Kind kind);
    void failed(const QString& title, const QString& summary, const QString& details);

private:
    struct Job {
        QString label;
        QByteArray text;
    };
    bool begin(Kind kind, const QString& method, nlohmann::json params);
    void startNext();
    void finish(Outcome outcome);
    void refuse(const QString& title, const QString& detail);
    QString what() const;

    std::function<BackendClient*()> backend_;
    JobRunner* runner_;
    std::deque<Job> queue_;
    Kind kind_ = Kind::Family;
    bool busy_ = false;
    int generation_ = 0;
    int total_ = 0;
    int finished_ = 0;
    QString current_label_;
    Outcome outcome_ = Outcome::None;
};

}  // namespace tcad::desktop
