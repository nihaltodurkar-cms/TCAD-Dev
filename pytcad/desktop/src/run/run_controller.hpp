// From a Run click to a result -- NATIVE-DESKTOP-PLAN.md section 17.11,
// P3-S4. Qt Core only.
//
// The job is built by the backend (decision 1) and run by the JobRunner:
//   device:  spec.from_example | spec.load | project.spec   (loadDevice)
//   options: run.options                                   (requestOptions)
//   run:     spec.configure_run -> spec.job_text -> JobRunner.start
//            (a C-V job: cv.job_text -> moscap_runner)
// Stop works in both phases: while the backend prepares the job, the
// pending replies are disowned (a late one starts nothing); while the
// child runs, the runner kills it.
//
// A refusal keeps the title the QML app shows: configure_run's own
// RunConfigError title and detail, or, for a configuration that fails its
// own validation, QML's arm-time title ("Invalid sweep configuration").
#pragma once

#include "backend/backend_client.hpp"
#include "run/job_runner.hpp"

#include <nlohmann/json.hpp>

#include <QObject>
#include <QString>
#include <QStringList>

#include <functional>
#include <optional>

namespace tcad::desktop {

enum class DeviceSource { Example, SpecFile, Project };
enum class RunKind { Equilibrium, Bias, Sweep, Transient, AC, CV };

QString runKindName(RunKind k);  // "Equilibrium", ..., "C-V"

struct DeviceInfo {
    DeviceSource source = DeviceSource::Example;
    QString ref;                     // example name, or the file's path
    QString label;                   // what the Run dock shows
    nlohmann::json spec;             // the DeviceSpec dict
    nlohmann::json project_sweep;    // a project's armed sweep, or null
    nlohmann::json models;           // a project's models config, or null (the spec's own)
    QStringList contacts;
    int dimensionality = 0;
};

struct RunSettings {
    RunKind kind = RunKind::Bias;
    nlohmann::json sweep;            // SweepSpec dict, for RunKind::Sweep
    nlohmann::json transient;        // TransientSpec dict
    nlohmann::json ac;               // ACSpec dict
    nlohmann::json cv;               // {nsub_cm3, tox_nm, vstart, vstop, vstep}
    QString backend = "pytcad";
    QString engine = "auto";
};

class RunController : public QObject {
    Q_OBJECT

public:
    enum class Phase { Idle, Preparing, Running };
    // How the last run ended, set BEFORE busyChanged(false): a Stop's
    // runCanceled() arrives only when the process is gone, maybe after
    // the next run began, so a view that ends with the run reads this.
    enum class Outcome { None, Finished, Failed, Canceled };

    // `backend` gives the (lazily created) client, which must outlive this
    // controller; it is called only when a backend call is made.
    RunController(std::function<BackendClient*()> backend, RunnerConfig runner, QObject* parent = nullptr);
    ~RunController() override;

    void loadDevice(DeviceSource source, const QString& ref);
    const std::optional<DeviceInfo>& device() const { return device_; }
    void requestOptions(bool transient_armed);
    void requestExamples();

    // False (and nothing happens) while a run is going.
    bool run(const RunSettings& settings);
    void stop();

    // The runs directory's retention (decision 4): the `max_results` newest
    // result-*.npz stay, and `keep` (the open result) is never removed; a
    // job-*.json or *.tmp.npz older than `stale_ms` is removed (the age is
    // what protects a live run of another app instance sharing the
    // directory). Only files the runner's own naming matches are touched.
    // Returns how many files were removed.
    static int pruneRuns(const QString& dir, const QString& keep, int max_results = 20,
                         qint64 stale_ms = 24LL * 3600 * 1000);

    Phase phase() const { return phase_; }
    Outcome lastOutcome() const { return outcome_; }
    RunKind lastKind() const { return kind_; }  // the kind of the run last started
    const RunSettings& lastSettings() const { return last_; }  // the run last started
    // The last FINISHED DeviceSpec run (not C-V): the spec it ran, as
    // configure_run returned it (null before any), and its result file.
    // A family or a comparison re-solves this (P3-S6).
    const nlohmann::json& lastRunSpec() const { return last_run_spec_; }
    const QString& lastRunResult() const { return last_run_result_; }
    bool busy() const { return phase_ != Phase::Idle; }
    JobRunner* runner() const { return runner_; }
    QString runsDir() const { return runs_dir_; }

signals:
    void examplesListed(const QStringList& names);
    void deviceLoaded();
    void deviceFailed(const QString& title, const QString& detail);
    void optionsChanged(const tcad::desktop::JsonPayload& backends, const tcad::desktop::JsonPayload& engines);
    void busyChanged(bool busy);
    void message(const QString& text);  // the controller's own notes, for the console
    void line(const QString& text, tcad::desktop::JobRunner::LineKind kind);
    void stage(const QString& name);
    void progress(const tcad::desktop::ProgressRecord& record);
    void runFinished(const QString& result_path);
    void runFailed(const QString& title, const QString& summary, const QString& details);
    void runCanceled();

private:
    // A backend call owned by the current generation: a reply for an older
    // generation (a Stop, a newer load) is dropped.
    void callBackend(const QString& method, nlohmann::json params, int generation,
                     std::function<void(BackendReply*)> done);
    void startJob(const QString& module, const QByteArray& text, int generation);
    void fail(const QString& title, const QString& summary, const QString& details = {});
    void setPhase(Phase p);
    static QString titleFor(RunKind kind, const BackendReply* reply, const QString& fallback);
    static QString plainMessage(const BackendReply* reply);  // without the "Type: " prefix

    std::function<BackendClient*()> backend_;
    JobRunner* runner_;
    QString runs_dir_;
    std::optional<DeviceInfo> device_;
    Phase phase_ = Phase::Idle;
    RunKind kind_ = RunKind::Bias;
    Outcome outcome_ = Outcome::None;
    RunSettings last_;
    nlohmann::json pending_spec_;    // the configured spec of the run going
    nlohmann::json last_run_spec_;
    QString last_run_result_;
    int run_generation_ = 0;
    int device_generation_ = 0;
    int options_generation_ = 0;
};

}  // namespace tcad::desktop
