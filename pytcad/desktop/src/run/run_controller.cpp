#include "run_controller.hpp"

#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>

#include <algorithm>
#include <functional>
#include <utility>

namespace tcad::desktop {

namespace {
constexpr int kBackendTimeoutMs = 120000;  // loading a device may import the solver stack

// The solver backends the native app runs: pytcad only. devsim is not
// supported here (user decision, 2026-09-27; NATIVE-DESKTOP-PLAN.md 17.13):
// the backend service's run.options still lists it -- that list is QML's,
// and gated equal to it -- and this app drops what it does not run.
bool nativeBackend(const std::string& id) { return id == "pytcad"; }
}  // namespace

QString runKindName(RunKind k) {
    switch (k) {
        case RunKind::Equilibrium: return "Equilibrium";
        case RunKind::Bias: return "Bias";
        case RunKind::Sweep: return "Sweep";
        case RunKind::Transient: return "Transient";
        case RunKind::AC: return "AC";
        case RunKind::CV: return "C-V";
    }
    return {};
}

RunController::RunController(std::function<BackendClient*()> backend, RunnerConfig runner, QObject* parent)
    : QObject(parent), backend_(std::move(backend)), runs_dir_(runner.work_dir) {
    runner_ = new JobRunner(std::move(runner), this);
    connect(runner_, &JobRunner::line, this, &RunController::line);
    connect(runner_, &JobRunner::stage, this, &RunController::stage);
    connect(runner_, &JobRunner::progress, this, &RunController::progress);
    connect(runner_, &JobRunner::finished, this, [this](const QString&, const QString& path) {
        outcome_ = Outcome::Finished;
        if (!pending_spec_.is_null()) {  // a DeviceSpec run (not a C-V one)
            last_run_spec_ = pending_spec_;
            last_run_result_ = path;
        }
        setPhase(Phase::Idle);
        emit message(tr("Run finished: %1").arg(path));
        emit runFinished(path);
    });
    connect(runner_, &JobRunner::failed, this, [this](const QString&, const QString& summary, const QString& details) {
        outcome_ = Outcome::Failed;
        setPhase(Phase::Idle);
        emit runFailed(tr("The run failed"), summary, details);
    });
    connect(runner_, &JobRunner::canceled, this, [this](const QString&) {
        // Stop already made the controller idle (a new run may have started
        // since): this only reports that the old process is gone.
        emit message(tr("Run canceled: the solver was stopped and its files removed."));
        emit runCanceled();
    });
}

// The runner first, silently (it kills its process tree and removes its
// files); the backend's pending replies were connected with this object as
// context, so they disconnect with it.
RunController::~RunController() {
    delete runner_;
    runner_ = nullptr;
}

void RunController::setPhase(Phase p) {
    if (p == phase_) return;
    const bool was_busy = busy();
    phase_ = p;
    if (busy() != was_busy) emit busyChanged(busy());
}

void RunController::callBackend(const QString& method, nlohmann::json params, int generation,
                                std::function<void(BackendReply*)> done) {
    BackendReply* reply = backend_()->call(method, std::move(params), kBackendTimeoutMs);
    connect(reply, &BackendReply::finished, this, [reply, generation, done = std::move(done), this] {
        reply->deleteLater();
        if (generation != run_generation_) return;  // stopped, or superseded
        done(reply);
    });
}

QString RunController::plainMessage(const BackendReply* reply) {
    QString msg = reply->errorMessage();
    const auto& data = reply->errorData();
    if (data.is_object() && data.contains("type") && data["type"].is_string()) {
        const QString prefix = QString::fromStdString(data["type"].get<std::string>()) + ": ";
        if (msg.startsWith(prefix)) msg = msg.mid(prefix.size());
    }
    return msg;
}

QString RunController::titleFor(RunKind kind, const BackendReply* reply, const QString& fallback) {
    const auto& data = reply->errorData();
    const std::string type = data.is_object() && data.contains("type") && data["type"].is_string()
                                 ? data["type"].get<std::string>()
                                 : std::string();
    if (type == "RunConfigError" && data.contains("title") && data["title"].is_string())
        return QString::fromStdString(data["title"].get<std::string>());
    // QML's arm-time titles: the configuration itself is invalid.
    if (type == "ValueError") {
        switch (kind) {
            case RunKind::Sweep: return tr("Invalid sweep configuration");
            case RunKind::Transient: return tr("Invalid transient configuration");
            case RunKind::AC: return tr("Invalid AC configuration");
            case RunKind::CV: return tr("Invalid C-V configuration");
            default: break;
        }
    }
    return fallback;
}

void RunController::fail(const QString& title, const QString& summary, const QString& details) {
    outcome_ = Outcome::Failed;
    setPhase(Phase::Idle);
    emit runFailed(title, summary, details);
}

void RunController::requestExamples() {
    BackendReply* reply = backend_()->call("examples.list", nullptr, kBackendTimeoutMs);
    connect(reply, &BackendReply::finished, this, [this, reply] {
        reply->deleteLater();
        QStringList names;
        if (reply->ok() && reply->result().is_array())
            for (const auto& n : reply->result())
                if (n.is_string()) names << QString::fromStdString(n.get<std::string>());
        if (!reply->ok()) emit deviceFailed(tr("Could not list the examples"), reply->errorMessage());
        emit examplesListed(names);
    });
}

void RunController::loadDevice(DeviceSource source, const QString& ref) {
    const int generation = ++device_generation_;
    device_.reset();
    const char* method = source == DeviceSource::Example ? "spec.from_example"
                         : source == DeviceSource::SpecFile ? "spec.load"
                                                            : "project.spec";
    const nlohmann::json params = source == DeviceSource::Example ? nlohmann::json{{"name", ref.toStdString()}}
                                                                  : nlohmann::json{{"path", ref.toStdString()}};
    BackendReply* reply = backend_()->call(method, params, kBackendTimeoutMs);
    connect(reply, &BackendReply::finished, this, [this, reply, generation, source, ref] {
        reply->deleteLater();
        if (generation != device_generation_) return;  // another device was chosen since
        if (!reply->ok()) {
            const auto& data = reply->errorData();
            const bool refused = data.is_object() && data.value("type", std::string()) == "RunConfigError";
            emit deviceFailed(refused ? QString::fromStdString(data.value("title", std::string()))
                                      : tr("Could not load the device"),
                              refused ? QString::fromStdString(data.value("detail", std::string()))
                                      : plainMessage(reply));
            return;
        }
        DeviceInfo d;
        d.source = source;
        d.ref = ref;
        const nlohmann::json& r = reply->result();
        QString name = ref;
        try {
            if (source == DeviceSource::Project) {
                d.spec = r.at("spec");
                d.project_sweep = r.value("sweep", nlohmann::json());
                d.models = r.value("models", nlohmann::json());
                name = QString::fromStdString(r.value("name", std::string()));
            } else {
                d.spec = r;
            }
            for (const auto& c : d.spec.at("contacts")) d.contacts << QString::fromStdString(c.at("name").get<std::string>());
            d.dimensionality = d.spec.at("mesh").at("dimensionality").get<int>();
        } catch (const nlohmann::json::exception& e) {
            emit deviceFailed(tr("Could not load the device"),
                              tr("The backend's device spec is malformed: %1").arg(QString::fromUtf8(e.what())));
            return;
        }
        if (source != DeviceSource::Example) name = QFileInfo(ref).fileName() + (name != ref ? " (" + name + ")" : "");
        d.label = tr("%1 - %2D, contacts: %3").arg(name).arg(d.dimensionality).arg(d.contacts.join(", "));
        device_ = std::move(d);
        emit deviceLoaded();
    });
}

void RunController::requestOptions(bool transient_armed) {
    if (!device_) return;
    const int generation = ++options_generation_;
    nlohmann::json params = {{"spec", device_->spec}, {"transient_armed", transient_armed}};
    if (!device_->models.is_null()) params["models"] = device_->models;
    BackendReply* reply = backend_()->call("run.options", params, kBackendTimeoutMs);
    connect(reply, &BackendReply::finished, this, [this, reply, generation] {
        reply->deleteLater();
        if (generation != options_generation_ || !reply->ok() || !reply->result().is_object())
            return;  // the defaults stay offered
        nlohmann::json backends = nlohmann::json::array();
        for (const auto& b : reply->result().value("backends", nlohmann::json::array()))
            if (b.is_object() && b.contains("id") && b["id"].is_string() && nativeBackend(b["id"].get<std::string>()))
                backends.push_back(b);
        emit optionsChanged(JsonPayload{backends},
                            JsonPayload{reply->result().value("engines", nlohmann::json::array())});
    });
}

bool RunController::run(const RunSettings& s) {
    if (busy()) return false;
    kind_ = s.kind;
    pending_spec_ = nullptr;
    outcome_ = Outcome::None;
    last_ = s;
    const int generation = ++run_generation_;
    if (s.kind == RunKind::CV) {
        setPhase(Phase::Preparing);
        emit message(tr("Preparing a C-V run..."));
        callBackend("cv.job_text", s.cv, generation, [this, generation](BackendReply* r) {
            if (!r->ok()) return fail(titleFor(RunKind::CV, r, tr("Could not prepare the C-V run")), plainMessage(r));
            if (!r->result().is_string()) return fail(tr("Could not prepare the C-V run"), tr("the backend sent no job text"));
            startJob("gui.services.moscap_runner", QByteArray::fromStdString(r->result().get<std::string>()), generation);
        });
        return true;
    }
    if (!device_) {
        emit runFailed(tr("Nothing to run"), tr("Load a device first."), {});
        return false;
    }
    if (!nativeBackend(s.backend.toStdString())) {
        emit runFailed(tr("Backend not supported"),
                       tr("The native app runs the pytcad backend only; '%1' is not supported here.").arg(s.backend), {});
        return false;
    }
    nlohmann::json run = {{"backend", s.backend.toStdString()}, {"engine", s.engine.toStdString()}};
    if (s.kind == RunKind::Equilibrium) run["equilibrium_only"] = true;
    if (s.kind == RunKind::Sweep) run["sweep"] = s.sweep;
    if (s.kind == RunKind::Transient) run["transient"] = s.transient;
    if (s.kind == RunKind::AC) run["ac"] = s.ac;
    if (!device_->models.is_null()) run["models"] = device_->models;  // a project's own
    setPhase(Phase::Preparing);
    emit message(tr("Preparing the %1 run of %2...").arg(runKindName(s.kind).toLower(), device_->label));
    callBackend("spec.configure_run", {{"spec", device_->spec}, {"run", run}}, generation,
                [this, generation](BackendReply* r) {
                    if (!r->ok()) {
                        const auto& d = r->errorData();
                        const bool refused = d.is_object() && d.value("type", std::string()) == "RunConfigError";
                        return fail(titleFor(kind_, r, tr("Could not prepare the run")),
                                    refused ? QString::fromStdString(d.value("detail", std::string())) : plainMessage(r));
                    }
                    pending_spec_ = r->result();
                    callBackend("spec.job_text", {{"spec", r->result()}}, generation, [this, generation](BackendReply* t) {
                        if (!t->ok()) return fail(tr("Could not prepare the run"), plainMessage(t));
                        if (!t->result().is_string())
                            return fail(tr("Could not prepare the run"), tr("the backend sent no job text"));
                        startJob("gui.services.solver_runner", QByteArray::fromStdString(t->result().get<std::string>()),
                                 generation);
                    });
                });
    return true;
}

void RunController::startJob(const QString& module, const QByteArray& text, int generation) {
    if (generation != run_generation_) return;
    QString err;
    const QString id = runner_->start({JobRunner::moduleEntry(module), text}, &err);
    if (id.isEmpty()) return fail(tr("Could not start the solver"), err);
    setPhase(Phase::Running);
    emit message(tr("Solver started (run %1).").arg(id));
}

int RunController::pruneRuns(const QString& dir, const QString& keep, int max_results, qint64 stale_ms) {
    const QDir d(dir);
    if (!d.exists()) return 0;
    const QString keep_norm = keep.isEmpty() ? QString() : QDir::cleanPath(QFileInfo(keep).absoluteFilePath()).toLower();
    int removed = 0;
    // Results, newest first; ties broken by name so the order is stable.
    QFileInfoList results = d.entryInfoList({"result-*.npz"}, QDir::Files);
    results.erase(std::remove_if(results.begin(), results.end(),
                                 [](const QFileInfo& f) { return f.fileName().endsWith(".tmp.npz"); }),
                  results.end());
    std::sort(results.begin(), results.end(), [](const QFileInfo& a, const QFileInfo& b) {
        if (a.lastModified() != b.lastModified()) return a.lastModified() > b.lastModified();
        return a.fileName() > b.fileName();
    });
    for (int i = max_results; i < results.size(); ++i) {
        if (QDir::cleanPath(results[i].absoluteFilePath()).toLower() == keep_norm) continue;
        if (QFile::remove(results[i].absoluteFilePath())) ++removed;
    }
    const QDateTime cutoff = QDateTime::currentDateTime().addMSecs(-stale_ms);
    for (const QFileInfo& f : d.entryInfoList({"job-*.json", "result-*.tmp.npz"}, QDir::Files))
        if (f.lastModified() < cutoff && QFile::remove(f.absoluteFilePath())) ++removed;
    return removed;
}

void RunController::stop() {
    if (phase_ == Phase::Preparing) {
        ++run_generation_;  // the pending backend replies now start nothing
        outcome_ = Outcome::Canceled;
        setPhase(Phase::Idle);
        emit message(tr("Run canceled before the solver started."));
        emit runCanceled();
    } else if (phase_ == Phase::Running) {
        ++run_generation_;
        runner_->cancel();  // canceled() follows when the process is gone
        outcome_ = Outcome::Canceled;
        setPhase(Phase::Idle);
        emit message(tr("Stopping the solver..."));
    }
}

}  // namespace tcad::desktop
