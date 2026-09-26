// The native app's client for the Python backend service
// (backend_service/, JSON-RPC 2.0 over stdio) -- NATIVE-DESKTOP-PLAN.md
// section 15.15, S4d. Qt Core only.
//
// Contract, and why each part exists:
//   - Lazy start: the process starts on the first call, never before the
//     app's first frame. A handshake (system.ping, then system.info)
//     checks the protocol version and learns the service's pid and
//     scratch directory before any caller's request is written.
//   - ONE request in flight: the service answers strictly in order, so
//     a timer started for a request queued behind a slow one would kill
//     a healthy service (review revision 4). Requests wait in this
//     client's FIFO; each call's timer starts when it is written.
//   - Requests are ASCII-escaped JSON (a piped stdin on Windows is not
//     UTF-8 unless the service reconfigures it -- revision 1), and a
//     trailing "\r" is stripped from every reply line (revision 2).
//   - A timeout fails that call, kills the service, and the queue goes
//     on in a fresh process. An unexpected exit fails the in-flight call
//     with the exit code and the stderr tail. Three unexpected exits
//     within 30 s: the client gives up ("keeps crashing") until
//     resetBackoff().
//   - The child's PATH has the app's own runtime directory (the Qt/VTK
//     DLLs of the GUI env) removed: the backend must load only its own
//     environment's DLLs (revision 3).
//   - shutdown(): system.shutdown, a bounded wait, then kill; the
//     scratch directory is removed if the service left it behind.
#pragma once

#include <nlohmann/json.hpp>

#include <QByteArray>
#include <QElapsedTimer>
#include <QObject>
#include <QPointer>
#include <QProcess>
#include <QString>
#include <QStringList>
#include <QTimer>

#include <deque>
#include <optional>
#include <vector>

namespace tcad::desktop {

struct BackendConfig {
    QString python;                      // the backend's interpreter
    QStringList args{"-m", "backend_service"};
    QString working_dir;                 // pytcad/ (backend_service's parent)
    QStringList strip_from_path;         // directories removed from the child's PATH
    bool debug = false;                  // TCAD_BACKEND_DEBUG=1 (debug.* methods)
    int default_timeout_ms = 30000;
    int shutdown_wait_ms = 2000;
};

// Where the backend lives, in order: the TCAD_BACKEND_PYTHON environment
// variable, then `settings_python` (the settings key backend/python),
// then "backend_python" / "backend_root" in desktop_runtime.json next to
// the executable. Empty python -> the first call fails with a named error.
BackendConfig resolveBackendConfig(const QString& settings_python = QString());

class BackendReply : public QObject {
    Q_OBJECT

public:
    const QString& method() const { return method_; }
    bool isFinished() const { return finished_; }
    bool ok() const { return finished_ && !error_code_; }
    const nlohmann::json& result() const { return result_; }
    int errorCode() const { return error_code_; }  // JSON-RPC code, or one of the client codes below
    const QString& errorMessage() const { return error_message_; }
    double elapsedMs() const { return elapsed_ms_; }  // enqueue -> answer

    // Failures the client itself reports (outside JSON-RPC's range).
    static constexpr int kTimedOut = -33001;
    static constexpr int kBackendExited = -33002;
    static constexpr int kProtocolError = -33003;
    static constexpr int kCannotStart = -33004;
    static constexpr int kGaveUp = -33005;
    static constexpr int kShutDown = -33006;

signals:
    void finished();  // exactly once; then check ok()

private:
    friend class BackendClient;
    explicit BackendReply(QString method, QObject* parent) : QObject(parent), method_(std::move(method)) {
        clock_.start();
    }
    void succeed(nlohmann::json result);
    void fail(int code, QString message);

    QString method_;
    bool finished_ = false;
    nlohmann::json result_;
    int error_code_ = 0;
    QString error_message_;
    double elapsed_ms_ = 0;
    QElapsedTimer clock_;
};

class BackendClient : public QObject {
    Q_OBJECT

public:
    enum class State { NotStarted, Starting, Ready, GaveUp };

    explicit BackendClient(BackendConfig config, QObject* parent = nullptr);
    ~BackendClient() override;

    // Queue a call. The reply is owned by this client; delete it (or let
    // the client) after finished(). timeout_ms <= 0 uses the default.
    BackendReply* call(const QString& method, nlohmann::json params = nullptr, int timeout_ms = 0);

    State state() const { return state_; }
    qint64 backendPid() const { return backend_pid_; }
    QString scratchDir() const { return scratch_dir_; }
    QString backendPrefix() const { return backend_prefix_; }
    QStringList stderrTail() const { return stderr_tail_; }
    int restarts() const { return restarts_; }
    // After "keeps crashing": allow starting again.
    void resetBackoff();
    // system.shutdown, wait, kill; remove a scratch directory left behind.
    void shutdown();

signals:
    void stateChanged(tcad::desktop::BackendClient::State state);

private:
    struct Pending {
        int id = 0;
        QString method;
        nlohmann::json params;
        int timeout_ms = 0;
        QPointer<BackendReply> reply;  // null for the internal handshake
        bool handshake = false;
    };

    void ensureStarted();
    void startProcess();
    void pump();  // write the next request if none is in flight
    void onReadyRead();
    void onStderr();
    void onFinished(int exit_code, QProcess::ExitStatus status);
    void onErrorOccurred(QProcess::ProcessError error);
    void onTimeout();
    void handleLine(const QByteArray& line);
    void completeInflight(const nlohmann::json& response);
    void failInflight(int code, const QString& message);
    void failAll(int code, const QString& message);
    void killProcess();  // an intentional kill: not counted as a crash
    void setState(State s);
    void removeScratch();
    QString exitDescription(int exit_code, QProcess::ExitStatus status) const;

    BackendConfig config_;
    QProcess* process_ = nullptr;
    State state_ = State::NotStarted;
    std::deque<Pending> queue_;
    std::optional<Pending> inflight_;
    QTimer timer_;
    QByteArray buffer_;
    QStringList stderr_tail_;
    int next_id_ = 1;
    qint64 backend_pid_ = 0;
    QString scratch_dir_;
    QString backend_prefix_;
    bool handshake_done_ = false;
    bool killing_ = false;       // our own kill in progress: its exit is expected
    bool shutting_down_ = false;
    // Every scratch directory a service reported. A dead service's is
    // kept until shutdown: a caller may still hold a path from it.
    QStringList scratch_dirs_;
    QString last_failure_;  // why everything was last failed: repeated after giving up
    int restarts_ = 0;
    std::vector<qint64> crash_times_ms_;
    QElapsedTimer uptime_;
};

}  // namespace tcad::desktop
