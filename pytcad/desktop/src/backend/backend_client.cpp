#include "backend_client.hpp"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QProcessEnvironment>

#include <algorithm>

namespace tcad::desktop {
namespace {

constexpr int kProtocolVersion = 1;                    // backend_service.server.PROTOCOL_VERSION
constexpr qsizetype kMaxLineBytes = 256LL * 1024 * 1024;  // a reply line longer than this is a protocol error
constexpr int kStderrLines = 200;
constexpr int kCrashLimit = 3;
constexpr qint64 kCrashWindowMs = 30000;

QString normalizedDir(const QString& d) {
    return QDir::cleanPath(QDir::fromNativeSeparators(d)).toLower();
}

}  // namespace

// -- BackendReply ---------------------------------------------------------------

void BackendReply::succeed(nlohmann::json result) {
    if (finished_) return;
    finished_ = true;
    result_ = std::move(result);
    elapsed_ms_ = static_cast<double>(clock_.nsecsElapsed()) / 1e6;
    emit finished();
}

void BackendReply::fail(int code, QString message) {
    if (finished_) return;
    finished_ = true;
    error_code_ = code ? code : kProtocolError;
    error_message_ = std::move(message);
    elapsed_ms_ = static_cast<double>(clock_.nsecsElapsed()) / 1e6;
    emit finished();
}

// -- configuration ---------------------------------------------------------------

BackendConfig resolveBackendConfig(const QString& settings_python) {
    BackendConfig c;
    QString runtime_bin;
    QFile manifest(QDir(QCoreApplication::applicationDirPath()).filePath("desktop_runtime.json"));
    if (manifest.open(QIODevice::ReadOnly)) {
        try {
            const auto j = nlohmann::json::parse(manifest.readAll().toStdString());
            if (j.contains("backend_python")) c.python = QString::fromStdString(j["backend_python"].get<std::string>());
            if (j.contains("backend_root")) c.working_dir = QString::fromStdString(j["backend_root"].get<std::string>());
            if (j.contains("runtime_bin")) runtime_bin = QString::fromStdString(j["runtime_bin"].get<std::string>());
        } catch (const nlohmann::json::exception&) {
            // an unreadable manifest: fall through to the other sources
        }
    }
    if (!settings_python.isEmpty()) c.python = settings_python;
    if (const QString env = qEnvironmentVariable("TCAD_BACKEND_PYTHON"); !env.isEmpty()) c.python = env;
    if (const QString env = qEnvironmentVariable("TCAD_BACKEND_ROOT"); !env.isEmpty()) c.working_dir = env;
    if (!runtime_bin.isEmpty()) c.strip_from_path << runtime_bin;
    return c;
}

// -- BackendClient ----------------------------------------------------------------

BackendClient::BackendClient(BackendConfig config, QObject* parent) : QObject(parent), config_(std::move(config)) {
    timer_.setSingleShot(true);
    connect(&timer_, &QTimer::timeout, this, &BackendClient::onTimeout);
    uptime_.start();
}

BackendClient::~BackendClient() { shutdown(); }

void BackendClient::setState(State s) {
    if (s == state_) return;
    state_ = s;
    emit stateChanged(s);
}

BackendReply* BackendClient::call(const QString& method, nlohmann::json params, int timeout_ms) {
    auto* reply = new BackendReply(method, this);
    if (state_ == State::GaveUp) {
        // Asynchronous, like every other outcome: the caller connects to
        // finished() after call() returns.
        const QString why = last_failure_.isEmpty() ? QString("it kept crashing or could not start") : last_failure_;
        QTimer::singleShot(0, reply, [reply, why] {
            reply->fail(BackendReply::kGaveUp, "the backend is not running: " + why);
        });
        return reply;
    }
    Pending p;
    p.id = next_id_++;
    p.method = method;
    p.params = std::move(params);
    p.timeout_ms = timeout_ms > 0 ? timeout_ms : config_.default_timeout_ms;
    p.reply = reply;
    queue_.push_back(std::move(p));
    ensureStarted();
    pump();
    return reply;
}

void BackendClient::ensureStarted() {
    if (state_ == State::NotStarted && !process_) startProcess();
}

void BackendClient::startProcess() {
    auto cannot_start = [this](const QString& why) {
        last_failure_ = why;  // now: a call() before the deferred failAll must see it
        setState(State::GaveUp);
        QTimer::singleShot(0, this, [this, why] { failAll(BackendReply::kCannotStart, why); });
    };
    if (config_.python.isEmpty()) {
        cannot_start("no backend interpreter configured (TCAD_BACKEND_PYTHON, the settings key "
                     "backend/python, or backend_python in desktop_runtime.json)");
        return;
    }
    if (!QFileInfo::exists(config_.python)) {
        cannot_start(QString("the backend interpreter does not exist: %1").arg(config_.python));
        return;
    }
    process_ = new QProcess(this);
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    QStringList path = env.value("PATH").split(QDir::listSeparator(), Qt::SkipEmptyParts);
    QStringList strip;
    for (const QString& d : config_.strip_from_path) strip << normalizedDir(d);
    path.removeIf([&](const QString& d) { return strip.contains(normalizedDir(d)); });
    env.insert("PATH", path.join(QDir::listSeparator()));
    if (config_.debug)
        env.insert("TCAD_BACKEND_DEBUG", "1");
    else
        env.remove("TCAD_BACKEND_DEBUG");
    process_->setProcessEnvironment(env);
    if (!config_.working_dir.isEmpty()) process_->setWorkingDirectory(config_.working_dir);
    connect(process_, &QProcess::readyReadStandardOutput, this, &BackendClient::onReadyRead);
    connect(process_, &QProcess::readyReadStandardError, this, &BackendClient::onStderr);
    connect(process_, &QProcess::finished, this, &BackendClient::onFinished);
    connect(process_, &QProcess::errorOccurred, this, &BackendClient::onErrorOccurred);
    connect(process_, &QProcess::started, this, &BackendClient::pump);

    // The handshake goes first: nothing of the caller's is written before it.
    Pending info{next_id_++, "system.info", nullptr, config_.default_timeout_ms, nullptr, true};
    Pending ping{next_id_++, "system.ping", nullptr, config_.default_timeout_ms, nullptr, true};
    queue_.push_front(std::move(info));
    queue_.push_front(std::move(ping));
    handshake_done_ = false;
    buffer_.clear();
    setState(State::Starting);
    process_->start(config_.python, config_.args);
}

void BackendClient::pump() {
    // killing_: kill() is asynchronous and the dying process still reads
    // as Running -- a request written now would die with it (found by
    // the timeout test). The queue resumes in the replacement process.
    if (inflight_ || queue_.empty() || !process_ || killing_ || process_->state() != QProcess::Running) return;
    if (!handshake_done_ && !queue_.front().handshake) return;
    inflight_ = std::move(queue_.front());
    queue_.pop_front();
    nlohmann::json req = {{"jsonrpc", "2.0"}, {"id", inflight_->id}, {"method", inflight_->method.toStdString()}};
    if (!inflight_->params.is_null()) req["params"] = inflight_->params;
    // ensure_ascii: every non-ASCII character travels as a \u escape
    const std::string line = req.dump(-1, ' ', true) + "\n";
    process_->write(line.data(), static_cast<qint64>(line.size()));
    timer_.start(inflight_->timeout_ms);
}

void BackendClient::onReadyRead() {
    if (!process_) return;
    buffer_ += process_->readAllStandardOutput();
    qsizetype nl;
    while ((nl = buffer_.indexOf('\n')) >= 0) {
        QByteArray line = buffer_.left(nl);
        buffer_.remove(0, nl + 1);
        if (line.endsWith('\r')) line.chop(1);  // Python's text-mode stdout on Windows
        if (!line.trimmed().isEmpty()) handleLine(line);
        if (!process_) return;  // handleLine killed it
    }
    if (buffer_.size() > kMaxLineBytes) {
        failInflight(BackendReply::kProtocolError, "a reply line from the backend exceeded 256 MB");
        killProcess();
    }
}

void BackendClient::handleLine(const QByteArray& line) {
    nlohmann::json j;
    try {
        j = nlohmann::json::parse(line.constData(), line.constData() + line.size());
    } catch (const nlohmann::json::exception&) {
        failInflight(BackendReply::kProtocolError,
                     QString("malformed reply from the backend: %1").arg(QString::fromUtf8(line.left(200))));
        killProcess();  // the stream is out of step: start clean
        return;
    }
    if (!inflight_) {
        stderr_tail_ << QString("[client] unsolicited reply ignored: %1").arg(QString::fromUtf8(line.left(200)));
        return;
    }
    if (!j.is_object() || !j.contains("id") || j["id"] != inflight_->id) {
        failInflight(BackendReply::kProtocolError,
                     QString("reply id does not match request %1: %2").arg(inflight_->id).arg(QString::fromUtf8(line.left(200))));
        killProcess();
        return;
    }
    completeInflight(j);
}

void BackendClient::completeInflight(const nlohmann::json& response) {
    timer_.stop();
    Pending p = std::move(*inflight_);
    inflight_.reset();
    const bool is_error = response.contains("error");
    if (p.handshake) {
        if (is_error) {
            failAll(BackendReply::kProtocolError,
                    QString("backend handshake (%1) failed: %2").arg(p.method, QString::fromStdString(response["error"].dump())));
            setState(State::GaveUp);
            killProcess();
            return;
        }
        const auto& r = response["result"];
        if (p.method == "system.ping") {
            const int proto = r.contains("protocol") && r["protocol"].is_number_integer() ? r["protocol"].get<int>() : -1;
            if (proto != kProtocolVersion) {
                failAll(BackendReply::kProtocolError, QString("the backend speaks protocol %1; this app speaks %2")
                                                          .arg(proto)
                                                          .arg(kProtocolVersion));
                setState(State::GaveUp);
                killProcess();
                return;
            }
        } else {  // system.info
            backend_pid_ = r.value("pid", 0LL);
            scratch_dir_ = QString::fromStdString(r.value("scratch_dir", std::string()));
            backend_prefix_ = QString::fromStdString(r.value("prefix", std::string()));
            if (!scratch_dir_.isEmpty() && !scratch_dirs_.contains(scratch_dir_)) scratch_dirs_ << scratch_dir_;
            handshake_done_ = true;
            setState(State::Ready);
        }
    } else if (p.reply) {
        if (is_error) {
            const auto& e = response["error"];
            QString msg = QString::fromStdString(e.value("message", std::string("backend error")));
            if (e.contains("data") && e["data"].is_object()) {
                p.reply->error_data_ = e["data"];
                if (e["data"].contains("type") && e["data"]["type"].is_string())
                    msg = QString::fromStdString(e["data"]["type"].get<std::string>()) + ": " + msg;
            }
            p.reply->fail(e.value("code", BackendReply::kProtocolError), msg);
        } else {
            p.reply->succeed(response.value("result", nlohmann::json()));
        }
    }
    pump();
}

void BackendClient::onTimeout() {
    if (!inflight_) return;
    const QString what = QString("%1 timed out after %2 ms").arg(inflight_->method).arg(inflight_->timeout_ms);
    if (inflight_->handshake) {
        failAll(BackendReply::kTimedOut, "backend handshake: " + what);
        setState(State::GaveUp);
    } else {
        failInflight(BackendReply::kTimedOut, what);
    }
    killProcess();  // the service is sequential and stuck: replace it
}

void BackendClient::onStderr() {
    if (!process_) return;
    const QStringList lines = QString::fromUtf8(process_->readAllStandardError()).split('\n', Qt::SkipEmptyParts);
    for (QString l : lines) stderr_tail_ << l.remove('\r');
    while (stderr_tail_.size() > kStderrLines) stderr_tail_.removeFirst();
}

QString BackendClient::exitDescription(int exit_code, QProcess::ExitStatus status) const {
    QString why = status == QProcess::CrashExit ? QString("crashed") : QString("exited with code %1").arg(exit_code);
    const QStringList tail = stderr_tail_.mid(std::max<qsizetype>(0, stderr_tail_.size() - 5));
    if (!tail.isEmpty()) why += "; stderr: " + tail.join(" | ");
    return why;
}

void BackendClient::onFinished(int exit_code, QProcess::ExitStatus status) {
    if (!process_) return;
    onStderr();  // the last words
    const bool expected = killing_ || shutting_down_;
    killing_ = false;
    const QString why = exitDescription(exit_code, status);
    if (inflight_) {
        if (shutting_down_)  // shutdown() killed a busy service: that is why the call ends
            failInflight(BackendReply::kShutDown, "the backend was shut down");
        else
            failInflight(BackendReply::kBackendExited, QString("the backend %1 during %2").arg(why, inflight_->method));
    }
    // handshake entries belong to the dead process
    queue_.erase(std::remove_if(queue_.begin(), queue_.end(), [](const Pending& p) { return p.handshake; }), queue_.end());
    process_->deleteLater();
    process_ = nullptr;
    handshake_done_ = false;
    buffer_.clear();
    if (shutting_down_ || state_ == State::GaveUp) return;
    if (!expected) {
        const qint64 now = uptime_.elapsed();
        crash_times_ms_.push_back(now);
        crash_times_ms_.erase(std::remove_if(crash_times_ms_.begin(), crash_times_ms_.end(),
                                             [now](qint64 t) { return now - t > kCrashWindowMs; }),
                              crash_times_ms_.end());
        if (static_cast<int>(crash_times_ms_.size()) >= kCrashLimit) {
            setState(State::GaveUp);
            failAll(BackendReply::kGaveUp,
                    QString("the backend keeps crashing (%1 exits in %2 s); last: %3").arg(kCrashLimit).arg(kCrashWindowMs / 1000).arg(why));
            return;
        }
    }
    setState(State::NotStarted);
    if (!queue_.empty()) {
        ++restarts_;
        startProcess();
    }
}

void BackendClient::onErrorOccurred(QProcess::ProcessError error) {
    if (error != QProcess::FailedToStart || !process_) return;  // other errors end in finished()
    const QString why = QString("could not start the backend '%1': %2").arg(config_.python, process_->errorString());
    process_->deleteLater();
    process_ = nullptr;
    setState(State::GaveUp);
    failAll(BackendReply::kCannotStart, why);
}

void BackendClient::failInflight(int code, const QString& message) {
    timer_.stop();
    if (!inflight_) return;
    Pending p = std::move(*inflight_);
    inflight_.reset();
    if (p.reply) p.reply->fail(code, message);
}

void BackendClient::failAll(int code, const QString& message) {
    last_failure_ = message;  // what a later call() in the gave-up state reports
    failInflight(code, message);
    std::deque<Pending> queued;
    queued.swap(queue_);
    for (Pending& p : queued)
        if (p.reply) p.reply->fail(code, message);
}

void BackendClient::killProcess() {
    if (process_ && process_->state() != QProcess::NotRunning) {
        killing_ = true;
        process_->kill();
    }
}

void BackendClient::resetBackoff() {
    crash_times_ms_.clear();
    if (state_ == State::GaveUp && !process_) setState(State::NotStarted);
}

void BackendClient::removeScratch() {
    // Only directories the service itself reported, and only if they look
    // like its own (tcad_backend_* under the temp directory).
    const QString temp = normalizedDir(QDir::tempPath());
    for (const QString& d : scratch_dirs_) {
        const QFileInfo fi(d);
        if (fi.fileName().startsWith("tcad_backend_") && normalizedDir(fi.absolutePath()) == temp && fi.isDir())
            QDir(d).removeRecursively();
    }
    scratch_dirs_.clear();
}

void BackendClient::shutdown() {
    shutting_down_ = true;
    timer_.stop();
    if (process_) {
        if (process_->state() == QProcess::Running) {
            const std::string req = nlohmann::json({{"jsonrpc", "2.0"}, {"id", next_id_++}, {"method", "system.shutdown"}}).dump() + "\n";
            process_->write(req.data(), static_cast<qint64>(req.size()));
            process_->closeWriteChannel();
            if (!process_->waitForFinished(config_.shutdown_wait_ms)) {
                process_->kill();
                process_->waitForFinished(1000);
            }
        } else if (process_->state() == QProcess::Starting) {
            process_->kill();
            process_->waitForFinished(1000);
        }
        if (process_) {  // onFinished may already have released it
            process_->disconnect(this);
            delete process_;
            process_ = nullptr;
        }
    }
    failAll(BackendReply::kShutDown, "the backend was shut down");
    removeScratch();
    handshake_done_ = false;
    shutting_down_ = false;
    if (state_ != State::GaveUp) setState(State::NotStarted);
}

}  // namespace tcad::desktop
