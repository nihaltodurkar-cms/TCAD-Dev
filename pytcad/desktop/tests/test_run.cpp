// JobRunner tests (NATIVE-DESKTOP-PLAN.md section 17.10, P3-S3): the real
// solver_runner, and misbehaving fakes (tests/fake_solver.py).
//
// Run by gui/tests/test_desktop_run.py, which sets:
//   TCAD_TEST_PYTHON  the solver's interpreter (tcad-dev)
//   TCAD_TEST_ROOT    pytcad/ (the modules' root)
//   TCAD_TEST_DATA    diode_bias.json, diode_sweep.json (+ its point count
//                     in diode_sweep.count) -- job files written by the QML
//                     path's DeviceSpec.to_json -- and a scratch area
//   TCAD_TEST_FAKE    tests/fake_solver.py
//   TCAD_TEST_STRIP   the app's runtime directory (kept off the child's PATH)
#include "data/npz.hpp"
#include "data/result_model.hpp"
#include "run/job_runner.hpp"

#include <QCoreApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QtTest/QtTest>

#include <functional>
#include <memory>
#include <optional>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

using tcad::desktop::JobRequest;
using tcad::desktop::JobRunner;
using tcad::desktop::NpzFile;
using tcad::desktop::ResultModel;
using tcad::desktop::RunnerConfig;
using Json = nlohmann::json;
using Kind = JobRunner::LineKind;

namespace {

QString env(const char* name) { return qEnvironmentVariable(name); }
QString data(const QString& name) { return QDir(env("TCAD_TEST_DATA")).absoluteFilePath(name); }

QByteArray readFile(const QString& path) {
    QFile f(path);
    return f.open(QIODevice::ReadOnly) ? f.readAll() : QByteArray();
}

bool processAlive(qint64 pid) {
    HANDLE h = OpenProcess(SYNCHRONIZE, FALSE, static_cast<DWORD>(pid));
    if (!h) return false;
    const bool alive = WaitForSingleObject(h, 0) == WAIT_TIMEOUT;
    CloseHandle(h);
    return alive;
}

bool waitUntil(const std::function<bool()>& cond, int ms) {
    QElapsedTimer t;
    t.start();
    while (!cond() && t.elapsed() < ms) QCoreApplication::processEvents(QEventLoop::AllEvents, 20);
    return cond();
}

// Everything a runner reports, per run.
struct Log {
    QStringList lines;
    QList<Kind> kinds;
    QStringList stages;
    std::vector<nlohmann::ordered_json> records;
    QStringList started, finished, canceled, failed;
    QString result, summary, details;
    std::vector<qint64> line_ms;  // arrival time of each line
    QElapsedTimer clock;

    explicit Log(JobRunner& r) {
        clock.start();
        QObject::connect(&r, &JobRunner::started, [this](const QString& id) { started << id; });
        QObject::connect(&r, &JobRunner::line, [this](const QString& text, Kind kind) {
            lines << text;
            kinds << kind;
            line_ms.push_back(clock.elapsed());
        });
        QObject::connect(&r, &JobRunner::stage, [this](const QString& s) { stages << s; });
        QObject::connect(&r, &JobRunner::progress, [this](const tcad::desktop::ProgressRecord& rec) { records.push_back(rec.value); });
        QObject::connect(&r, &JobRunner::finished, [this](const QString& id, const QString& path) {
            finished << id;
            result = path;
        });
        QObject::connect(&r, &JobRunner::canceled, [this](const QString& id) { canceled << id; });
        QObject::connect(&r, &JobRunner::failed, [this](const QString& id, const QString& s, const QString& d) {
            failed << id;
            summary = s;
            details = d;
        });
    }
    int ended() const { return static_cast<int>(finished.size() + canceled.size() + failed.size()); }
    int count(const std::string& event) const {
        return static_cast<int>(std::count_if(records.begin(), records.end(),
                                              [&](const nlohmann::ordered_json& r) { return r["event"] == event; }));
    }
};

}  // namespace

class TestRun : public QObject {
    Q_OBJECT

    QString work_;

    RunnerConfig config(const QString& sub = "runs") const {
        RunnerConfig c;
        c.python = env("TCAD_TEST_PYTHON");
        c.working_dir = env("TCAD_TEST_ROOT");
        c.work_dir = QDir(work_).absoluteFilePath(sub);
        c.strip_from_path << env("TCAD_TEST_STRIP");
        return c;
    }
    static JobRequest solver(const QString& job_file) {
        return {JobRunner::moduleEntry("gui.services.solver_runner"), readFile(data(job_file))};
    }
    static JobRequest fake(const QString& mode, QByteArray job = "{\"fake\": true}") {
        return {QStringList{env("TCAD_TEST_FAKE"), mode}, std::move(job)};
    }
    // Start, wait for the end, return the log.
    static std::unique_ptr<Log> runToEnd(JobRunner& r, const JobRequest& req, int ms = 120000) {
        auto log = std::make_unique<Log>(r);
        QString err;
        const QString id = r.start(req, &err);
        if (id.isEmpty()) {
            log->summary = "start refused: " + err;
            return log;
        }
        waitUntil([&] { return log->ended() > 0; }, ms);
        return log;
    }
    static QStringList filesIn(const QString& dir) { return QDir(dir).entryList(QDir::Files); }

private slots:
    void initTestCase() {
        for (const char* v : {"TCAD_TEST_PYTHON", "TCAD_TEST_ROOT", "TCAD_TEST_DATA", "TCAD_TEST_FAKE", "TCAD_TEST_STRIP"})
            QVERIFY2(!env(v).isEmpty(), v);
        work_ = data("work");
        QVERIFY(QDir().mkpath(work_));
    }

    // -- the real solver --------------------------------------------------------
    void realDiodeBias() {
        JobRunner r(config("real"));
        auto log = runToEnd(r, solver("diode_bias.json"));
        QVERIFY2(log->finished.size() == 1, qPrintable(log->summary + "\n" + log->details.right(3000)));
        QVERIFY(QFileInfo(log->result).isFile());
        // It opens as a result, and it solved the bias.
        const NpzFile npz = NpzFile::open(log->result.toStdWString());
        const ResultModel m = ResultModel::from_npz(npz);
        QCOMPARE(m.dimensionality(), 1);
        QVERIFY(m.solved_bias());
        // Progress: stage first, done last naming this result; Newton records;
        // no record text reaches line(); the stage markers did.
        QVERIFY(!log->records.empty());
        QCOMPARE(log->records.front()["event"].get<std::string>(), std::string("stage"));
        QCOMPARE(log->records.back()["event"].get<std::string>(), std::string("done"));
        QCOMPARE(QString::fromStdString(log->records.back()["result"].get<std::string>()), log->result);
        QVERIFY(log->count("newton") > 0);
        for (const QString& l : log->lines) QVERIFY2(!l.startsWith("PYTCAD_PROGRESS") && !l.startsWith("RESULT_PATH"), qPrintable(l));
        QVERIFY(log->stages.contains("equilibrium"));
        QVERIFY(log->kinds.contains(Kind::Stage));
        QCOMPARE(r.malformedRecords(), 0);
        // Only the result is left: the job file is gone.
        QCOMPARE(filesIn(config("real").work_dir), QStringList{QFileInfo(log->result).fileName()});
        QFile::remove(log->result);
    }

    void realDiodeSweep() {
        const int n = readFile(data("diode_sweep.count")).trimmed().toInt();
        QVERIFY(n > 1);
        JobRunner r(config("real"));
        auto log = runToEnd(r, solver("diode_sweep.json"));
        QVERIFY2(log->finished.size() == 1, qPrintable(log->summary + "\n" + log->details.right(3000)));
        QCOMPARE(log->count("sweep_point"), n);
        for (const auto& rec : log->records)
            if (rec["event"] == "sweep_point") QCOMPARE(rec["contact"].get<std::string>(), std::string("anode"));
        const NpzFile npz = NpzFile::open(log->result.toStdWString());
        QCOMPARE(static_cast<int>(ResultModel::from_npz(npz).sweep_points()), n);
        QFile::remove(log->result);
    }

    void realFailureIsNamed() {
        // Not JSON: the real runner's own PYTCAD_ERROR payload names it.
        JobRunner r(config("real"));
        auto log = runToEnd(r, {JobRunner::moduleEntry("gui.services.solver_runner"), "{ not json"});
        QCOMPARE(log->failed.size(), 1);
        QVERIFY2(log->summary.startsWith("JSONDecodeError: "), qPrintable(log->summary));
        QVERIFY2(log->details.contains("Traceback"), qPrintable(log->details));
        QVERIFY(filesIn(config("real").work_dir).isEmpty());
    }

    void realRunInANonAsciiDirectory() {
        const QString sub = QString::fromUtf8("\xC2\xB5m \xE2\x82\xAC \xF0\x9F\x98\x80/runs");  // µm € 😀
        JobRunner r(config(sub));
        auto log = runToEnd(r, solver("diode_bias.json"));
        QVERIFY2(log->finished.size() == 1, qPrintable(log->summary + "\n" + log->details.right(3000)));
        QVERIFY(log->result.contains(QString::fromUtf8("\xF0\x9F\x98\x80")));
        QVERIFY(QFileInfo(log->result).isFile());
        QFile::remove(log->result);
    }

    void progressArrivesWhileTheStageRuns() {
        // Decision 7 in the native runner: lines 50 ms apart arrive spread
        // out, not all at the end.
        JobRunner r(config());
        auto log = runToEnd(r, fake("slow"));
        QCOMPARE(log->finished.size(), 1);
        QVERIFY(log->line_ms.size() >= 40);
        const qint64 spread = log->line_ms[39] - log->line_ms[0];
        QVERIFY2(spread > 1000, qPrintable(QString("40 lines 50 ms apart arrived within %1 ms").arg(spread)));
        QFile::remove(log->result);
    }

    // -- the job file ------------------------------------------------------------
    void theJobFileIsTheGivenBytes() {
        // Verbatim, whatever the bytes: CRLF, a float repr, non-ASCII.
        const QByteArray job = "{\"x\": 0.1, \"y\": 1e-05, \"s\": \"\xC2\xB5m\"}\r\n";
        JobRunner r(config());
        auto log = runToEnd(r, fake("ok", job));
        QCOMPARE(log->finished.size(), 1);
        QCOMPARE(readFile(log->result), job);  // the fake copies its job to the result
        QFile::remove(log->result);
    }

    // -- misbehaving children ------------------------------------------------------
    void failuresAreNamed_data() {
        QTest::addColumn<QString>("mode");
        QTest::addColumn<QString>("summary");
        QTest::addColumn<QString>("detail");
        auto row = [](const char* mode, const QString& summary, const QString& detail) {
            QTest::newRow(mode) << QString(mode) << summary << detail;
        };
        row("crash", "The solver crashed (exit code 0x", "");
        row("exit5", "The solver exited with code 5", "boom: exit five");
        row("error", QString::fromUtf8("ValueError: a bad thing \xC2\xB5m"), "ValueError: a bad thing");
        row("no_marker", "The solver exited without reporting a result", "");
        row("no_file", "The solver's result file is missing: ", "");
        row("wrong_path", "The solver reported a result at an unexpected path: ", "");
        row("stderr_flood", "The solver exited with code 3", "stderr line 4999");
    }
    void failuresAreNamed() {
        QFETCH(QString, mode);
        QFETCH(QString, summary);
        QFETCH(QString, detail);
        JobRunner r(config(mode));
        auto log = runToEnd(r, fake(mode), 30000);
        QVERIFY2(log->failed.size() == 1, qPrintable(mode + ": " + log->summary));
        QVERIFY2(log->summary.startsWith(summary), qPrintable(log->summary));
        QVERIFY2(detail.isEmpty() || log->details.contains(detail), qPrintable(log->details.right(2000)));
        QVERIFY(!r.isRunning() && r.liveRuns() == 0);
        // No job file and no partial result stay behind (wrong_path's own
        // stray file is the child's, not the runner's).
        for (const QString& f : filesIn(config(mode).work_dir))
            QVERIFY2(f.endsWith(".other.npz"), qPrintable(f));
        if (mode == "stderr_flood") QVERIFY(log->details.count('\n') < JobRunner::kStderrTailLines);
    }

    void garbageIsShownNotFatal() {
        JobRunner r(config());
        auto log = runToEnd(r, fake("garbage"));
        QCOMPARE(log->finished.size(), 1);
        QCOMPARE(r.malformedRecords(), 3);
        QCOMPARE(log->count("stage"), 2);  // the valid record, and finish_ok's
        QVERIFY(log->lines.filter("PYTCAD_PROGRESS").size() == 3);  // the malformed ones, as text
        QVERIFY(log->lines.filter("bad utf8").size() == 1);
        QVERIFY(log->lines.filter("nul").size() == 1);
        QFile::remove(log->result);
    }

    void longLinesAreBounded() {
        JobRunner r(config());
        auto log = runToEnd(r, fake("long"));
        QVERIFY2(log->finished.size() == 1, qPrintable(log->summary));
        QCOMPARE(r.truncatedLines(), 2);
        for (const QString& l : log->lines) QVERIFY(l.size() <= JobRunner::kMaxLineBytes + 64);
        QVERIFY(log->lines.contains("after the long lines"));  // the line after each is intact
        QVERIFY(log->lines.contains("tail without newline"));  // read at exit
        QVERIFY(log->stages.contains("equilibrium"));
        QFile::remove(log->result);
    }

    void linesSplitAcrossReads() {
        JobRunner r(config());
        auto log = runToEnd(r, fake("split"));
        QVERIFY2(log->finished.size() == 1, qPrintable(log->summary));  // RESULT_PATH reassembled
        QCOMPARE(log->count("stage"), 1);
        QCOMPARE(QString::fromStdString(log->records[0]["stage"].get<std::string>()), QString::fromUtf8("split \xC2\xB5m"));
        QVERIFY(log->lines.contains(QString::fromUtf8("micro \xC2\xB5m")));
        QFile::remove(log->result);
    }

    // -- cancel ----------------------------------------------------------------------
    void cancelKillsAtOnceAndLeavesNothing() {
        JobRunner r(config("cancel"));
        Log log(r);
        const QString id = r.start(fake("hang"));
        QVERIFY(!id.isEmpty());
        QVERIFY(waitUntil([&] { return log.lines.contains("hanging"); }, 20000));
        const qint64 pid = r.currentPid();
        QVERIFY(processAlive(pid));
        QElapsedTimer t;
        t.start();
        r.cancel();
        QVERIFY(!r.isRunning());
        QVERIFY(waitUntil([&] { return log.canceled.size() == 1; }, 5000));
        QVERIFY2(t.elapsed() < 2000, qPrintable(QString("cancel took %1 ms").arg(t.elapsed())));
        QCOMPARE(log.canceled.front(), id);
        QVERIFY(log.failed.isEmpty() && log.finished.isEmpty());
        QVERIFY(!processAlive(pid));
        QVERIFY(filesIn(config("cancel").work_dir).isEmpty());
    }

    void cancelKillsTheWholeTree() {
        JobRunner r(config());
        Log log(r);
        QVERIFY(!r.start(fake("tree")).isEmpty());
        QVERIFY(waitUntil([&] { return !log.lines.filter("CHILD_PID=").isEmpty(); }, 20000));
        const qint64 child = log.lines.filter("CHILD_PID=").front().mid(10).toLongLong();
        const qint64 pid = r.currentPid();
        QVERIFY(processAlive(child) && processAlive(pid));
        r.cancel();
        QVERIFY(waitUntil([&] { return log.canceled.size() == 1; }, 5000));
        QVERIFY2(waitUntil([&] { return !processAlive(child); }, 3000), "the grandchild survived the cancel");
        QVERIFY(!processAlive(pid));
    }

    void aFinishedRunLeavesNoGrandchild() {
        JobRunner r(config());
        auto log = runToEnd(r, fake("orphan"));
        QCOMPARE(log->finished.size(), 1);
        const qint64 child = log->lines.filter("CHILD_PID=").front().mid(10).toLongLong();
        QVERIFY2(waitUntil([&] { return !processAlive(child); }, 3000), "a grandchild outlived its finished run");
        QFile::remove(log->result);
    }

    void cancelThenImmediateRestart() {
        // QML's final-review I-5: the old run's end must never touch the new run.
        JobRunner r(config("restart"));
        Log log(r);
        const QString first = r.start(fake("slow"));
        QVERIFY(waitUntil([&] { return log.lines.contains("line 2"); }, 20000));
        r.cancel();
        const int lines_at_cancel = static_cast<int>(log.lines.size());
        const QString second = r.start(fake("slow"));  // straight away: the first is still dying
        QVERIFY(!second.isEmpty() && second != first);
        QVERIFY(r.liveRuns() >= 1);
        const QString second_job = r.currentJobPath();
        QVERIFY(waitUntil([&] { return log.canceled.size() == 1; }, 5000));
        QCOMPARE(log.canceled.front(), first);
        QVERIFY2(QFileInfo::exists(second_job), "the first run's end removed the second run's job file");
        QVERIFY(r.isRunning() && r.currentRunId() == second);
        QVERIFY(waitUntil([&] { return log.ended() == 2; }, 60000));
        QCOMPARE(log.finished, QStringList{second});
        // After the cancel only the second run's lines arrived: 40 + stage marker.
        QCOMPARE(static_cast<int>(log.lines.size()) - lines_at_cancel, 41);
        QFile::remove(log.result);
        QCOMPARE(filesIn(config("restart").work_dir), QStringList{});
    }

    void nothingIsShownAfterCancel() {
        // Stop clicked while output flows: lines already read in the same
        // batch as the one on show must not reach the console.
        JobRunner r(config());
        Log log(r);
        QObject::connect(&r, &JobRunner::line, &r, [&r](const QString& text) {
            if (text == "burst 0") r.cancel();
        });
        QVERIFY(!r.start(fake("burst")).isEmpty());
        QVERIFY(waitUntil([&] { return log.canceled.size() == 1; }, 20000));
        QCOMPARE(log.lines, QStringList{"burst 0"});
    }

    void oneRunAtATime() {
        JobRunner r(config());
        QVERIFY(!r.start(fake("hang")).isEmpty());
        QString err;
        QVERIFY(r.start(fake("ok"), &err).isEmpty());
        QCOMPARE(err, QString("a run is already going"));
        r.cancel();
        QVERIFY(waitUntil([&] { return r.liveRuns() == 0; }, 5000));
    }

    void destructionKillsSilently() {
        // A window closed mid-run: no signal into the half-destroyed owner,
        // no process left, no file left.
        int signals_after = 0;
        qint64 pid = 0, child = 0;
        {
            auto r = std::make_unique<JobRunner>(config("teardown"));
            Log log(*r);
            QVERIFY(!r->start(fake("tree")).isEmpty());
            QVERIFY(waitUntil([&] { return !log.lines.filter("CHILD_PID=").isEmpty(); }, 20000));
            child = log.lines.filter("CHILD_PID=").front().mid(10).toLongLong();
            pid = r->currentPid();
            QObject::connect(r.get(), &JobRunner::canceled, [&] { ++signals_after; });
            QObject::connect(r.get(), &JobRunner::failed, [&] { ++signals_after; });
            QObject::connect(r.get(), &JobRunner::finished, [&] { ++signals_after; });
            r.reset();
        }
        QCoreApplication::processEvents();
        QCOMPARE(signals_after, 0);
        QVERIFY(!processAlive(pid));
        QVERIFY2(waitUntil([&] { return !processAlive(child); }, 3000), "the grandchild survived the teardown");
        QVERIFY(filesIn(config("teardown").work_dir).isEmpty());
    }

    void refusalsAreNamed() {
        RunnerConfig c = config();
        c.python = work_ + "/no-such-python.exe";
        JobRunner r(c);
        QString err;
        QVERIFY(r.start(fake("ok"), &err).isEmpty());
        QVERIFY2(err.startsWith("the solver interpreter does not exist: "), qPrintable(err));
        RunnerConfig empty = config();
        empty.python.clear();
        JobRunner r2(empty);
        QVERIFY(r2.start(fake("ok"), &err).isEmpty());
        QCOMPARE(err, QString("no solver interpreter configured"));
    }
};

QTEST_GUILESS_MAIN(TestRun)
#include "test_run.moc"
