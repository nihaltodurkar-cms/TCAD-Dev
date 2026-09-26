#include "batch_controller.hpp"

namespace tcad::desktop {
namespace {
constexpr int kBackendTimeoutMs = 120000;
constexpr const char* kSolver = "gui.services.solver_runner";
}  // namespace

BatchController::BatchController(std::function<BackendClient*()> backend, RunnerConfig runner, QObject* parent)
    : QObject(parent), backend_(std::move(backend)) {
    runner_ = new JobRunner(std::move(runner), this);
    connect(runner_, &JobRunner::finished, this, [this](const QString&, const QString& path) {
        if (!busy_ || queue_.empty()) return;
        const QString label = queue_.front().label;
        queue_.pop_front();
        ++finished_;
        emit message(tr("%1: curve %2 of %3 finished (%4).").arg(what()).arg(finished_).arg(total_).arg(label));
        emit curveFinished(path, label, kind_);
        if (busy_) startNext();  // the handler may have stopped the batch
    });
    connect(runner_, &JobRunner::failed, this, [this](const QString&, const QString& summary, const QString& details) {
        if (!busy_) return;
        const QString label = queue_.empty() ? QString() : queue_.front().label;
        queue_.clear();
        emit failed(tr("%1 failed").arg(what()), tr("%1: %2").arg(label, summary), details);
        finish(Outcome::Failed);
    });
}

// The runner first, silently: it kills its process tree and removes its files.
BatchController::~BatchController() {
    delete runner_;
    runner_ = nullptr;
}

QString BatchController::what() const { return kind_ == Kind::Family ? tr("Family") : tr("Comparison"); }

void BatchController::refuse(const QString& title, const QString& detail) {
    outcome_ = Outcome::Failed;
    emit failed(title, detail, {});
}

bool BatchController::runFamily(const nlohmann::json& base, const QString& stepped, double start, double stop,
                                double step) {
    if (busy_) return false;
    // QML's "Nothing to sweep" (family_jobs.family_specs), and the native rule
    // that the family re-solves the last run's own sweep.
    if (base.is_null()) {
        refuse(tr("Nothing to sweep"), tr("Run the device once first; every family curve re-solves that exact device."));
        return false;
    }
    if (!base.contains("sweep") || !base["sweep"].is_object()) {
        refuse(tr("Nothing to sweep"),
               tr("Run a sweep first: a family re-solves the last run's sweep at each stepped value."));
        return false;
    }
    const auto& sw = base["sweep"];
    nlohmann::json params = {{"spec", base},
                             {"stepped", stepped.toStdString()},
                             {"values", {{"start", start}, {"stop", stop}, {"step", step}}},
                             {"swept",
                              {{"contact", sw.value("contact", std::string())},
                               {"start", sw.value("start", 0.0)},
                               {"stop", sw.value("stop", 0.0)},
                               {"step", sw.value("step", 0.0)}}}};
    return begin(Kind::Family, "family.jobs", std::move(params));
}

bool BatchController::runComparison(const nlohmann::json& base) {
    if (busy_) return false;
    if (base.is_null()) {
        refuse(tr("Nothing to compare"),
               tr("Run the device once; the comparison re-solves that exact device with every model off."));
        return false;
    }
    if (!base.contains("sweep") || !base["sweep"].is_object()) {
        refuse(tr("Nothing to compare"),
               tr("Run a sweep first: the comparison is drawn over the last run's sweep."));
        return false;
    }
    return begin(Kind::Comparison, "comparison.job", {{"spec", base}});
}

bool BatchController::begin(Kind kind, const QString& method, nlohmann::json params) {
    kind_ = kind;
    queue_.clear();
    total_ = finished_ = 0;
    outcome_ = Outcome::None;
    busy_ = true;
    const int generation = ++generation_;
    emit busyChanged(true);
    emit status(tr("%1: preparing...").arg(what()));
    BackendReply* reply = backend_()->call(method, std::move(params), kBackendTimeoutMs);
    connect(reply, &BackendReply::finished, this, [this, reply, generation] {
        reply->deleteLater();
        if (generation != generation_ || !busy_) return;  // stopped meanwhile
        if (!reply->ok()) {
            const auto& d = reply->errorData();
            const bool refused = d.is_object() && d.value("type", std::string()) == "RunConfigError";
            QString msg = reply->errorMessage();
            if (d.is_object() && d.contains("type") && d["type"].is_string()) {
                const QString prefix = QString::fromStdString(d["type"].get<std::string>()) + ": ";
                if (msg.startsWith(prefix)) msg = msg.mid(prefix.size());
            }
            outcome_ = Outcome::Failed;
            busy_ = false;
            emit busyChanged(false);
            emit status(QString());
            emit failed(refused ? QString::fromStdString(d.value("title", std::string()))
                                : tr("Could not prepare the %1").arg(what().toLower()),
                        refused ? QString::fromStdString(d.value("detail", std::string())) : msg, {});
            return;
        }
        const nlohmann::json& r = reply->result();
        auto add = [this](const nlohmann::json& j) {
            if (j.is_object() && j.contains("label") && j["label"].is_string() && j.contains("job_text") &&
                j["job_text"].is_string())
                queue_.push_back({QString::fromStdString(j["label"].get<std::string>()),
                                  QByteArray::fromStdString(j["job_text"].get<std::string>())});
        };
        if (r.is_array())
            for (const auto& j : r) add(j);
        else
            add(r);
        total_ = static_cast<int>(queue_.size());
        if (total_ == 0) {
            outcome_ = Outcome::Failed;
            busy_ = false;
            emit busyChanged(false);
            emit failed(tr("Could not prepare the %1").arg(what().toLower()), tr("the backend sent no jobs"), {});
            return;
        }
        emit message(tr("%1: %2 job(s): %3").arg(what()).arg(total_).arg([this] {
            QStringList l;
            for (const auto& j : queue_) l << j.label;
            return l.join(", ");
        }()));
        startNext();
    });
    return true;
}

void BatchController::startNext() {
    if (queue_.empty()) return finish(Outcome::Finished);
    const Job& job = queue_.front();
    QString err;
    if (runner_->start({JobRunner::moduleEntry(kSolver), job.text}, &err).isEmpty()) {
        queue_.clear();
        emit failed(tr("%1 failed").arg(what()), tr("could not start the solver: %1").arg(err), {});
        return finish(Outcome::Failed);
    }
    emit status(tr("%1: curve %2 of %3 (%4)").arg(what()).arg(finished_ + 1).arg(total_).arg(job.label));
}

void BatchController::stop() {
    if (!busy_) return;
    ++generation_;  // a pending backend reply now starts nothing
    queue_.clear();
    runner_->cancel();
    emit message(tr("%1 stopped: %2 of %3 curves finished (they stay).").arg(what()).arg(finished_).arg(total_));
    finish(Outcome::Canceled);
}

void BatchController::finish(Outcome outcome) {
    outcome_ = outcome;
    busy_ = false;
    emit busyChanged(false);
    const QString done = tr("%1 of %2 curves").arg(finished_).arg(total_);
    emit status(outcome == Outcome::Finished   ? tr("%1: %2 added.").arg(what(), done)
                : outcome == Outcome::Canceled ? tr("%1 stopped after %2.").arg(what(), done)
                                               : tr("%1 failed after %2.").arg(what(), done));
}

}  // namespace tcad::desktop
