#include "job_runner.hpp"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QProcessEnvironment>
#include <QSaveFile>
#include <QUuid>

#include <algorithm>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

namespace tcad::desktop {
namespace {

QString normalizedPath(const QString& p) {
    return QDir::cleanPath(QDir::fromNativeSeparators(QFileInfo(p).absoluteFilePath())).toLower();
}

QString normalizedDir(const QString& d) { return QDir::cleanPath(QDir::fromNativeSeparators(d)).toLower(); }

// A job object holding the run's process (and so every process it
// starts), killed as a whole on cancel and when its handle closes. The
// process is assigned right after CreateProcess returns, before the
// interpreter has even initialized, so it cannot have started a child yet.
HANDLE makeJobFor(qint64 pid) {
    HANDLE job = CreateJobObjectW(nullptr, nullptr);
    if (!job) return nullptr;
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION info{};
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    HANDLE proc = OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, FALSE, static_cast<DWORD>(pid));
    const bool ok = proc && SetInformationJobObject(job, JobObjectExtendedLimitInformation, &info, sizeof info) &&
                    AssignProcessToJobObject(job, proc);
    if (proc) CloseHandle(proc);
    if (!ok) {
        CloseHandle(job);
        return nullptr;
    }
    return job;
}

}  // namespace

struct JobRunner::Run {
    QString id;
    QProcess* proc = nullptr;        // parented to the runner; deleteLater'd when the run ends
    HANDLE job = nullptr;
    QString job_path;
    QString result_path;
    QString result_seen;             // RESULT_PATH's value, if the child printed one
    Stream out, err;
    QStringList stderr_tail;
    bool have_payload = false;       // a PYTCAD_ERROR line was parsed
    QString error_summary, error_details;
    bool canceled = false;
    bool start_failed = false;
    QString start_error;
    int exit_code = 0;
    QProcess::ExitStatus exit_status = QProcess::NormalExit;
};

JobRunner::JobRunner(RunnerConfig config, QObject* parent) : QObject(parent), config_(std::move(config)) {
    qRegisterMetaType<JsonPayload>();
    qRegisterMetaType<ProgressRecord>();
}

JobRunner::~JobRunner() {
    // Silent: the owner may be half destroyed (a window closed mid-run).
    // Each process is disconnected first, so its exit during the wait
    // below never reaches conclude() and its signals.
    current_ = nullptr;
    for (auto& run : runs_) {
        QObject::disconnect(run->proc, nullptr, this, nullptr);
        killTree(run.get());
        run->proc->waitForFinished(5000);
        if (run->job) CloseHandle(run->job);
        run->job = nullptr;
        removeFiles(run.get(), false);
        delete run->proc;
        run->proc = nullptr;
    }
    runs_.clear();
}

QString JobRunner::currentRunId() const { return current_ ? current_->id : QString(); }
QString JobRunner::currentResultPath() const { return current_ ? current_->result_path : QString(); }
QString JobRunner::currentJobPath() const { return current_ ? current_->job_path : QString(); }
qint64 JobRunner::currentPid() const { return current_ && current_->proc ? current_->proc->processId() : 0; }

QString JobRunner::start(const JobRequest& request, QString* error) {
    auto refuse = [error](const QString& why) {
        if (error) *error = why;
        return QString();
    };
    if (current_) return refuse("a run is already going");
    if (config_.python.isEmpty()) return refuse("no solver interpreter configured");
    if (!QFileInfo::exists(config_.python)) return refuse("the solver interpreter does not exist: " + config_.python);
    if (request.entry.isEmpty()) return refuse("no solver entry point given");
    if (config_.work_dir.isEmpty() || !QDir().mkpath(config_.work_dir))
        return refuse("cannot create the run directory: " + config_.work_dir);

    auto run = std::make_unique<Run>();
    run->id = QUuid::createUuid().toString(QUuid::Id128).left(12);
    const QDir work(config_.work_dir);
    run->job_path = work.absoluteFilePath(QString("job-%1.json").arg(run->id));
    run->result_path = work.absoluteFilePath(QString("result-%1%2").arg(run->id, request.result_suffix));
    {
        QSaveFile f(run->job_path);
        if (!f.open(QIODevice::WriteOnly) || f.write(request.job_text) != request.job_text.size() || !f.commit())
            return refuse("cannot write the job file " + run->job_path + ": " + f.errorString());
    }

    run->proc = new QProcess(this);
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    QStringList path = env.value("PATH").split(QDir::listSeparator(), Qt::SkipEmptyParts);
    QStringList strip;
    for (const QString& d : config_.strip_from_path) strip << normalizedDir(d);
    path.removeIf([&](const QString& d) { return strip.contains(normalizedDir(d)); });
    env.insert("PATH", path.join(QDir::listSeparator()));
    env.insert("PYTHONUNBUFFERED", "1");
    env.insert("PYTHONIOENCODING", "utf-8");
    run->proc->setProcessEnvironment(env);
    if (!config_.working_dir.isEmpty()) run->proc->setWorkingDirectory(config_.working_dir);
    run->proc->setProgram(config_.python);
    run->proc->setArguments(QStringList{"-u"} + request.entry + QStringList{run->job_path, run->result_path});

    Run* r = run.get();
    connect(run->proc, &QProcess::readyReadStandardOutput, this, [this, r] { onOutput(r, false); });
    connect(run->proc, &QProcess::readyReadStandardError, this, [this, r] { onOutput(r, true); });
    connect(run->proc, &QProcess::finished, this,
            [this, r](int code, QProcess::ExitStatus status) { onFinished(r, code, status); });
    connect(run->proc, &QProcess::errorOccurred, this, [this, r](QProcess::ProcessError e) {
        if (e != QProcess::FailedToStart) return;  // the others end in finished()
        r->start_failed = true;
        r->start_error = r->proc->errorString();
        if (r != current_ || r->proc->state() != QProcess::NotRunning) return;
        // Reported during start() on Windows (handled there); anywhere else
        // it ends the run here.
        if (!starting_) onStartFailed(r);
    });

    runs_.push_back(std::move(run));
    current_ = r;
    starting_ = true;
    r->proc->start();
    starting_ = false;
    if (r->start_failed || r->proc->state() == QProcess::NotRunning) {
        const QString why = "could not start the solver '" + config_.python + "': " +
                            (r->start_error.isEmpty() ? r->proc->errorString() : r->start_error);
        current_ = nullptr;
        QObject::disconnect(r->proc, nullptr, this, nullptr);
        removeFiles(r, false);
        r->proc->deleteLater();
        runs_.erase(std::find_if(runs_.begin(), runs_.end(), [r](const auto& p) { return p.get() == r; }));
        return refuse(why);
    }
    r->job = makeJobFor(r->proc->processId());
    emit started(r->id);
    return r->id;
}

void JobRunner::cancel() {
    if (!current_) return;
    Run* run = current_;
    run->canceled = true;
    current_ = nullptr;  // a new run may start now; this one's end touches only itself
    killTree(run);
}

void JobRunner::killTree(Run* run) {
    if (run->job) TerminateJobObject(run->job, 1);
    if (run->proc && run->proc->state() != QProcess::NotRunning) run->proc->kill();
}

void JobRunner::onOutput(Run* run, bool is_stderr) {
    if (!run->proc) return;
    const QByteArray data = is_stderr ? run->proc->readAllStandardError() : run->proc->readAllStandardOutput();
    feed(run, is_stderr ? run->err : run->out, data, is_stderr, false);
}

void JobRunner::feed(Run* run, Stream& s, const QByteArray& data, bool is_stderr, bool at_end) {
    auto deliver = [&](const QByteArray& raw, bool truncated) {
        QByteArray bytes = raw;
        if (bytes.endsWith('\r')) bytes.chop(1);
        if (bytes.trimmed().isEmpty()) return;
        if (truncated) {
            ++truncated_lines_;
            // No marker survives truncation: it goes to the console as text.
            if (run == current_)
                emit line(QString::fromUtf8(bytes) + QString(" [line truncated at %1 bytes]").arg(kMaxLineBytes),
                          is_stderr ? LineKind::Stderr : LineKind::Output);
            if (is_stderr) run->stderr_tail << QString::fromUtf8(bytes.left(2000)) + " [truncated]";
            return;
        }
        if (is_stderr)
            handleStderr(run, bytes);
        else
            handleStdout(run, bytes);
    };
    qsizetype pos = 0;
    while (pos < data.size()) {
        const qsizetype nl = data.indexOf('\n', pos);
        const qsizetype end = nl < 0 ? data.size() : nl;
        if (!s.skipping) {
            // Append at most up to one byte past the limit: memory stays bounded.
            const qsizetype room = kMaxLineBytes + 1 - s.pending.size();
            s.pending.append(data.constData() + pos, std::min(end - pos, room));
            if (s.pending.size() > kMaxLineBytes) {
                deliver(s.pending.left(kMaxLineBytes), true);
                s.pending.clear();
                s.skipping = true;
            }
        }
        if (nl < 0) break;
        if (!s.skipping) deliver(s.pending, false);
        s.pending.clear();
        s.skipping = false;
        pos = nl + 1;
    }
    if (at_end) {
        if (!s.skipping && !s.pending.isEmpty()) deliver(s.pending, false);
        s.pending.clear();
        s.skipping = false;
    }
}

void JobRunner::handleStdout(Run* run, const QByteArray& raw) {
    static const QByteArray kResult = "RESULT_PATH=";
    static const QByteArray kStage = "PYTCAD_STAGE=";
    static const QByteArray kProgress = "PYTCAD_PROGRESS ";
    if (raw.startsWith(kResult)) {
        run->result_seen = QString::fromUtf8(raw.mid(kResult.size()));
        return;
    }
    const bool live = run == current_;  // a canceled run's output is dropped
    const QString text = QString::fromUtf8(raw);
    if (raw.startsWith(kStage)) {
        if (live) {
            emit stage(QString::fromUtf8(raw.mid(kStage.size())).trimmed());
            emit line(text, LineKind::Stage);
        }
        return;
    }
    if (raw.startsWith(kProgress)) {
        nlohmann::ordered_json rec = nlohmann::ordered_json::parse(raw.constData() + kProgress.size(), raw.constData() + raw.size(),
                                                   nullptr, false);
        const bool valid = rec.is_object() && rec.contains("v") && rec["v"] == 1 && rec.contains("event") &&
                           rec["event"].is_string();
        if (valid) {
            if (live) emit progress(ProgressRecord{rec});
            return;
        }
        ++malformed_records_;  // shown as text, never dropped silently
    }
    if (live) emit line(text, LineKind::Output);
}

void JobRunner::handleStderr(Run* run, const QByteArray& raw) {
    static const QByteArray kError = "PYTCAD_ERROR=";
    if (raw.startsWith(kError)) {
        const nlohmann::json p =
            nlohmann::json::parse(raw.constData() + kError.size(), raw.constData() + raw.size(), nullptr, false);
        if (p.is_object() && p.contains("error") && p["error"].is_string() && p.contains("message") &&
            p["message"].is_string()) {
            run->have_payload = true;
            run->error_summary = QString::fromStdString(p["error"].get<std::string>()) + ": " +
                                 QString::fromStdString(p["message"].get<std::string>());
            run->error_details = p.contains("traceback") && p["traceback"].is_string()
                                     ? QString::fromStdString(p["traceback"].get<std::string>())
                                     : QString();
            return;
        }
    }
    const QString text = QString::fromUtf8(raw);
    run->stderr_tail << text;
    while (run->stderr_tail.size() > kStderrTailLines) run->stderr_tail.removeFirst();
    if (run == current_) emit line(text, LineKind::Stderr);
}

void JobRunner::onFinished(Run* run, int exit_code, QProcess::ExitStatus status) {
    // The last words: output not yet read, and a last line without a newline.
    feed(run, run->out, run->proc->readAllStandardOutput(), false, true);
    feed(run, run->err, run->proc->readAllStandardError(), true, true);
    run->exit_code = exit_code;
    run->exit_status = status;
    conclude(run);
}

void JobRunner::onStartFailed(Run* run) { conclude(run); }

void JobRunner::removeFiles(const Run* run, bool keep_result) {
    QFile::remove(run->job_path);
    QFile::remove(run->result_path + ".tmp.npz");  // solver_runner's atomic-write name
    if (!keep_result) QFile::remove(run->result_path);
}

void JobRunner::conclude(Run* run) {
    if (run->job) {
        CloseHandle(run->job);  // kill-on-close: no grandchild outlives its run
        run->job = nullptr;
    }
    const bool was_canceled = run->canceled;
    const QString id = run->id;
    const QString result = run->result_path;
    bool ok = false;
    QString summary, details;
    if (!was_canceled) {
        const bool clean_exit = run->exit_status == QProcess::NormalExit && run->exit_code == 0 && !run->start_failed;
        const bool path_matches = !run->result_seen.isEmpty() &&
                                  normalizedPath(run->result_seen) == normalizedPath(run->result_path);
        ok = clean_exit && path_matches && QFileInfo(run->result_path).isFile();
        if (!ok) {
            details = run->stderr_tail.isEmpty() ? QString("(no output on stderr)") : run->stderr_tail.join('\n');
            if (run->start_failed) {
                summary = "Could not start the solver: " + run->start_error;
            } else if (run->have_payload) {
                summary = run->error_summary;
                if (!run->error_details.isEmpty()) details = run->error_details;
            } else if (run->exit_status == QProcess::CrashExit) {
                summary = QString("The solver crashed (exit code 0x%1)")
                              .arg(static_cast<quint32>(run->exit_code), 8, 16, QChar('0'));
            } else if (run->exit_code != 0) {
                summary = QString("The solver exited with code %1").arg(run->exit_code);
            } else if (run->result_seen.isEmpty()) {
                summary = "The solver exited without reporting a result";
            } else if (!path_matches) {
                summary = QString("The solver reported a result at an unexpected path: %1 (expected %2)")
                              .arg(run->result_seen, run->result_path);
            } else {
                summary = "The solver's result file is missing: " + run->result_seen;
            }
        }
    }
    removeFiles(run, ok);
    if (current_ == run) current_ = nullptr;
    QObject::disconnect(run->proc, nullptr, this, nullptr);
    run->proc->deleteLater();
    runs_.erase(std::find_if(runs_.begin(), runs_.end(), [run](const auto& p) { return p.get() == run; }));
    // Signals last: a handler sees the run gone and may start the next one.
    if (was_canceled)
        emit canceled(id);
    else if (ok)
        emit finished(id, result);
    else
        emit failed(id, summary, details);
}

}  // namespace tcad::desktop
