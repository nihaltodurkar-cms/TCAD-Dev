// The native app's local solver runner -- NATIVE-DESKTOP-PLAN.md section
// 17.2, P3-S3. Qt Core only. The C++ counterpart of gui/services/
// job_runner.py: one subprocess per run (`python -u -m <module> <job>
// <result>`), the job file written from bytes the backend produced, the
// result read back only from the file the child names.
//
// Contract, and why each part exists:
//   - Jobs are built by the backend (decision 1): start() writes the given
//     bytes verbatim, so the job file is byte-identical to the QML one.
//   - A per-run id names the job and result files, so a canceled run's
//     missing file can never be mistaken for another run's result, and a
//     run is only a success if its child reported THAT result path (exit
//     0, RESULT_PATH equal to the requested path, the file present).
//   - The child is unbuffered (-u, PYTHONUNBUFFERED) so progress is live
//     (decision 7), and its stdio is UTF-8 (PYTHONIOENCODING): a piped
//     Python stdout on Windows is cp1252, which crashes the final print of
//     a result path holding a character outside it and garbles one inside
//     it (measured, section 17.10).
//   - Lines are assembled from BYTES across reads, "\r" stripped, and
//     bounded: a line longer than kMaxLineBytes is delivered truncated and
//     the rest dropped up to the next newline, so a runaway child cannot
//     grow the app's memory.
//   - stdout: RESULT_PATH is recorded, PYTCAD_STAGE becomes stage(),
//     PYTCAD_PROGRESS records (section 4.3) become progress(); every other
//     line, and a malformed record, goes to line(). stderr: PYTCAD_ERROR's
//     payload is the failure summary and details; other lines go to
//     line(..., Stderr) and a bounded tail kept for the details.
//   - Cancel kills at once (decision 3) and the WHOLE process tree: each
//     run's process is put in its own Windows job object, so an MPI or pool
//     grandchild dies with it. A run canceled and a new one started at
//     once are separate objects: the old run's end can only ever touch its
//     own process and files (QML's final-review I-5 bug).
//   - Every outcome removes the job file; a failed or canceled run also its
//     partial result. The destructor kills every live run silently (no
//     signals into a half-destroyed owner) and cleans up the same way.
#pragma once

#include <nlohmann/json.hpp>

#include <QByteArray>
#include <QObject>
#include <QProcess>
#include <QString>
#include <QStringList>

#include <memory>
#include <vector>

namespace tcad::desktop {

// A JSON value as a Qt signal argument. Not nlohmann::json itself: its
// catch-all converting constructors make Qt's metatype traits probe
// arbitrary types, which fails to compile once QtWidgets is included
// (the incomplete Windows MSG type; found building P3-S4).
struct JsonPayload {
    nlohmann::json value;
};

// A PYTCAD_PROGRESS record, its keys in the order written: a newton
// record's residual metrics keep the printed order (F, dpsi, dn/n), as
// the stored convergence trace does (ResultModel reads it as ordered JSON),
// so the live and post-run plots style each metric the same (P3-S5).
struct ProgressRecord {
    nlohmann::ordered_json value;
};

struct RunnerConfig {
    QString python;                  // the solver's interpreter (the backend's)
    QString working_dir;             // pytcad/ (the modules' root)
    QString work_dir;                // where job and result files are written
    QStringList strip_from_path;     // directories removed from the child's PATH
};

struct JobRequest {
    QStringList entry;               // e.g. moduleEntry(...); the job and result paths are appended
    QByteArray job_text;             // written verbatim to the job file
    QString result_suffix = ".npz";
};

class JobRunner : public QObject {
    Q_OBJECT

public:
    enum class LineKind { Output, Stage, Stderr };
    Q_ENUM(LineKind)

    // A line longer than this is delivered truncated (and counted).
    static constexpr qsizetype kMaxLineBytes = 1024 * 1024;
    static constexpr int kStderrTailLines = 400;

    explicit JobRunner(RunnerConfig config, QObject* parent = nullptr);
    ~JobRunner() override;

    static QStringList moduleEntry(const QString& module) { return {"-m", module}; }

    // Start a run: its id, or an empty string with the reason in *error
    // (a run already going, no interpreter, an unwritable work directory).
    QString start(const JobRequest& request, QString* error = nullptr);
    // Cancel the current run: its process tree is killed now; canceled()
    // follows when it has exited. A new run may be started straight away.
    void cancel();

    bool isRunning() const { return current_ != nullptr; }
    QString currentRunId() const;
    QString currentResultPath() const;
    QString currentJobPath() const;
    qint64 currentPid() const;
    // Runs whose process has not exited yet: the current one, plus canceled
    // ones still dying.
    int liveRuns() const { return static_cast<int>(runs_.size()); }
    int malformedRecords() const { return malformed_records_; }
    int truncatedLines() const { return truncated_lines_; }

signals:
    void started(const QString& run_id);
    void line(const QString& text, tcad::desktop::JobRunner::LineKind kind);
    void stage(const QString& name);
    void progress(const tcad::desktop::ProgressRecord& record);
    void finished(const QString& run_id, const QString& result_path);
    void failed(const QString& run_id, const QString& summary, const QString& details);
    void canceled(const QString& run_id);

private:
    struct Run;
    struct Stream {
        QByteArray pending;
        bool skipping = false;       // inside an over-long line: drop to the next newline
    };

    void onOutput(Run* run, bool is_stderr);
    void feed(Run* run, Stream& s, const QByteArray& data, bool is_stderr, bool at_end);
    void handleStdout(Run* run, const QByteArray& raw);
    void handleStderr(Run* run, const QByteArray& raw);
    void onFinished(Run* run, int exit_code, QProcess::ExitStatus status);
    void onStartFailed(Run* run);
    void conclude(Run* run);         // files and signals of an ended run; destroys it
    static void killTree(Run* run);
    static void removeFiles(const Run* run, bool keep_result);

    RunnerConfig config_;
    std::vector<std::unique_ptr<Run>> runs_;
    Run* current_ = nullptr;
    int malformed_records_ = 0;
    int truncated_lines_ = 0;
    bool starting_ = false;          // inside start(): a start failure is returned, not signalled
};

}  // namespace tcad::desktop

Q_DECLARE_METATYPE(tcad::desktop::JsonPayload)
Q_DECLARE_METATYPE(tcad::desktop::ProgressRecord)
