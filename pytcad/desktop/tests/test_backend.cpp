// BackendClient tests (NATIVE-DESKTOP-PLAN.md section 15.15, S4d/S4e):
// the real backend_service, and misbehaving fakes (tests/fake_backend.py).
//
// Run by gui/tests/test_desktop_backend.py, which sets:
//   TCAD_TEST_PYTHON  the backend's interpreter (tcad-dev)
//   TCAD_TEST_ROOT    pytcad/ (backend_service's parent)
//   TCAD_TEST_DATA    mosfet_2d.npz, examples.json, and a copy of the
//                     MOSFET in a directory named with non-ASCII characters
//   TCAD_TEST_FAKE    tests/fake_backend.py
//   TCAD_TEST_STRIP   the app's runtime directory (tcad-gui DLLs), which is
//                     on THIS process's PATH and must not reach the backend's
#include "backend/backend_client.hpp"
#include "data/npz.hpp"
#include "data/result_model.hpp"

#include <QCoreApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QProcess>
#include <QTimer>
#include <QtTest/QtTest>

#include <memory>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

using tcad::desktop::BackendClient;
using tcad::desktop::BackendConfig;
using tcad::desktop::BackendReply;
using tcad::desktop::NpzFile;
using tcad::desktop::ResultModel;
using Json = nlohmann::json;

namespace {

QString env(const char* name) { return qEnvironmentVariable(name); }
QString data(const QString& name) { return QDir(env("TCAD_TEST_DATA")).absoluteFilePath(name); }

BackendConfig real(bool debug = false) {
    BackendConfig c;
    c.python = env("TCAD_TEST_PYTHON");
    c.working_dir = env("TCAD_TEST_ROOT");
    c.strip_from_path << env("TCAD_TEST_STRIP");
    c.debug = debug;
    return c;
}

BackendConfig fake(const QString& mode) {
    BackendConfig c = real();
    c.args = QStringList{env("TCAD_TEST_FAKE"), mode};
    return c;
}

bool waitFor(BackendReply* r, int ms) {
    QElapsedTimer t;
    t.start();
    while (!r->isFinished() && t.elapsed() < ms) QCoreApplication::processEvents(QEventLoop::AllEvents, 20);
    return r->isFinished();
}

bool processAlive(qint64 pid) {
    HANDLE h = OpenProcess(SYNCHRONIZE, FALSE, static_cast<DWORD>(pid));
    if (!h) return false;
    const bool alive = WaitForSingleObject(h, 0) == WAIT_TIMEOUT;
    CloseHandle(h);
    return alive;
}

std::string u8(const QString& s) { return s.toStdString(); }

}  // namespace

class TestBackend : public QObject {
    Q_OBJECT

private slots:
    void initTestCase() {
        for (const char* v : {"TCAD_TEST_PYTHON", "TCAD_TEST_ROOT", "TCAD_TEST_DATA", "TCAD_TEST_FAKE", "TCAD_TEST_STRIP"})
            QVERIFY2(!env(v).isEmpty(), v);
        QVERIFY(QFileInfo::exists(data("mosfet_2d.npz")));
    }

    // -- the real service -----------------------------------------------------
    void handshakeThenPing() {
        BackendClient c(real());
        QVERIFY(c.state() == BackendClient::State::NotStarted);  // lazy: nothing yet
        auto* r = c.call("system.ping");
        QVERIFY(waitFor(r, 30000));
        QVERIFY2(r->ok(), qPrintable(r->errorMessage()));
        QCOMPARE(r->result()["protocol"].get<int>(), 1);
        QVERIFY(c.state() == BackendClient::State::Ready);
        QVERIFY(c.backendPid() > 0 && processAlive(c.backendPid()));
        QVERIFY(QDir(c.scratchDir()).exists());
        QVERIFY(!c.backendPrefix().isEmpty());
    }

    void examplesListEqualsPython() {
        QFile f(data("examples.json"));
        QVERIFY(f.open(QIODevice::ReadOnly));
        const Json want = Json::parse(f.readAll().toStdString());
        BackendClient c(real());
        auto* r = c.call("examples.list");
        QVERIFY(waitFor(r, 30000));
        QVERIFY2(r->ok(), qPrintable(r->errorMessage()));
        QCOMPARE(r->result(), want);
    }

    void queuedCallsAnswerInOrder() {
        BackendClient c(real());
        QFile f(data("examples.json"));
        QVERIFY(f.open(QIODevice::ReadOnly));
        const Json names = Json::parse(f.readAll().toStdString());
        std::vector<BackendReply*> replies;
        std::vector<int> order;
        for (int i = 0; i < 20; ++i) {
            BackendReply* r = i % 2 ? c.call("system.ping")
                                    : c.call("examples.build", {{"name", names[static_cast<std::size_t>(i / 2) % names.size()]}});
            connect(r, &BackendReply::finished, this, [&order, i] { order.push_back(i); });
            replies.push_back(r);
        }
        QVERIFY(waitFor(replies.back(), 60000));
        QCOMPARE(static_cast<int>(order.size()), 20);
        for (int i = 0; i < 20; ++i) {
            QCOMPARE(order[static_cast<std::size_t>(i)], i);
            QVERIFY2(replies[static_cast<std::size_t>(i)]->ok(), qPrintable(replies[static_cast<std::size_t>(i)]->errorMessage()));
            if (i % 2) QVERIFY(replies[static_cast<std::size_t>(i)]->result()["pong"].get<bool>());
            else QVERIFY(replies[static_cast<std::size_t>(i)]->result().contains("mesh"));
        }
    }

    void bandMapRoundTripThroughTheReader() {
        BackendClient c(real());
        const NpzFile src_npz = NpzFile::open(data("mosfet_2d.npz").toStdWString());
        const ResultModel src = ResultModel::from_npz(src_npz);
        auto* r = c.call("analysis.band_map", {{"result", u8(data("mosfet_2d.npz"))}});
        QVERIFY(waitFor(r, 60000));
        QVERIFY2(r->ok(), qPrintable(r->errorMessage()));
        const QString path = QString::fromStdString(r->result()["path"].get<std::string>());
        QVERIFY(path.startsWith(QDir::fromNativeSeparators(c.scratchDir())) || path.startsWith(c.scratchDir()));
        const NpzFile npz = NpzFile::open(path.toStdWString());
        const ResultModel m = ResultModel::from_npz(npz, path.toStdString());
        QCOMPARE(m.scalar_names(), (std::vector<std::string>{"EFn", "EFp", "Ec", "Ev"}));
        QCOMPARE(m.dimensionality(), src.dimensionality());
        QCOMPARE(m.node_counts(), src.node_counts());
        QCOMPARE(m.scalar("Ec").unit, std::string("eV"));
        QVERIFY(QFile::remove(path));  // the caller deletes what it has read
    }

    void nonAsciiPathSurvivesThePipe() {
        BackendClient c(real());
        const QString dir = QString::fromUtf8("\xC2\xB5m \xE2\x82\xAC \xF0\x9F\x98\x80");
        const QString path = data(dir + "/mosfet_2d.npz");
        QVERIFY2(QFileInfo::exists(path), qPrintable(path));
        auto* r = c.call("analysis.recombination_map", {{"result", u8(path)}});
        QVERIFY(waitFor(r, 60000));
        QVERIFY2(r->ok(), qPrintable(r->errorMessage()));
        QCOMPARE(r->result()["fields"], Json::array({"R"}));
    }

    void backendLoadsOnlyItsOwnEnvironment() {
        // The test process has the GUI env's DLL directory on PATH, as the
        // launcher gives the app; the client strips it from the child.
        QVERIFY(QDir::fromNativeSeparators(env("PATH")).contains(QDir::fromNativeSeparators(env("TCAD_TEST_STRIP")),
                                                                 Qt::CaseInsensitive));
        BackendClient c(real(true));
        // Load what the risk is about first: numpy/pytcad (a map) -- a fresh
        // service has loaded almost nothing.
        auto* map = c.call("analysis.band_map", {{"result", u8(data("mosfet_2d.npz"))}});
        QVERIFY(waitFor(map, 120000));
        QVERIFY2(map->ok(), qPrintable(map->errorMessage()));
        auto* r = c.call("debug.loaded_modules");
        QVERIFY(waitFor(r, 60000));
        QVERIFY2(r->ok(), qPrintable(r->errorMessage()));
        // Allowed: the backend's own environment, Windows itself, and the
        // project tree (pytcad/_core*.pyd is built in place, CLAUDE.md).
        const QString prefix = QDir::fromNativeSeparators(c.backendPrefix());
        const QString windir = QDir::fromNativeSeparators(env("SystemRoot"));
        const QString root = QDir::fromNativeSeparators(env("TCAD_TEST_ROOT"));
        const QString gui_env = QDir::fromNativeSeparators(env("TCAD_TEST_STRIP"));  // .../tcad-gui/Library/bin
        int outside = 0, from_gui = 0;
        QStringList examples;
        for (const auto& m : r->result()) {
            const QString p = QDir::fromNativeSeparators(QString::fromStdString(m.get<std::string>()));
            if (p.startsWith(gui_env.section('/', 0, -3), Qt::CaseInsensitive)) ++from_gui;  // anything under tcad-gui
            if (p.startsWith(prefix, Qt::CaseInsensitive) || p.startsWith(windir, Qt::CaseInsensitive) ||
                p.startsWith(root, Qt::CaseInsensitive))
                continue;
            ++outside;
            if (examples.size() < 5) examples << p;
        }
        QCOMPARE(from_gui, 0);
        QVERIFY2(r->result().size() > 50, "the backend reported too few modules to mean anything");
        QVERIFY2(outside == 0, qPrintable(examples.join("\n")));
    }

    // -- hangs and crashes ------------------------------------------------------
    void timeoutReplacesTheBackend() {
        BackendClient c(real(true));
        auto* ping = c.call("system.ping");
        QVERIFY(waitFor(ping, 30000) && ping->ok());
        const qint64 pid = c.backendPid();
        auto* r = c.call("debug.sleep", {{"seconds", 5}}, 300);
        QVERIFY(waitFor(r, 3000));
        QCOMPARE(r->errorCode(), BackendReply::kTimedOut);
        QVERIFY2(r->elapsedMs() < 1000, qPrintable(QString::number(r->elapsedMs())));
        auto* after = c.call("system.ping");
        QVERIFY(waitFor(after, 30000));
        QVERIFY2(after->ok(), qPrintable(after->errorMessage()));
        QVERIFY(c.backendPid() != pid);
        QVERIFY(!processAlive(pid));
        QCOMPARE(c.restarts(), 1);
    }

    void killMidCallFailsThePendingCall() {
        BackendClient c(real(true));
        auto* ping = c.call("system.ping");
        QVERIFY(waitFor(ping, 30000) && ping->ok());
        const qint64 pid = c.backendPid();
        auto* r = c.call("debug.sleep", {{"seconds", 20}});
        QElapsedTimer t;
        QTimer::singleShot(200, [pid, &t] {
            t.start();
            QProcess::execute("taskkill", {"/F", "/PID", QString::number(pid)});
        });
        QVERIFY(waitFor(r, 10000));
        QCOMPARE(r->errorCode(), BackendReply::kBackendExited);
        QVERIFY2(r->errorMessage().contains("debug.sleep"), qPrintable(r->errorMessage()));
        QVERIFY2(t.elapsed() < 1500, qPrintable(QString::number(t.elapsed())));
        auto* after = c.call("system.ping");  // and a fresh backend serves the next call
        QVERIFY(waitFor(after, 30000));
        QVERIFY2(after->ok(), qPrintable(after->errorMessage()));
    }

    void exitReportsCodeAndStderr() {
        BackendClient c(real(true));
        auto* r = c.call("debug.exit", {{"code", 5}});
        QVERIFY(waitFor(r, 30000));
        QCOMPARE(r->errorCode(), BackendReply::kBackendExited);
        QVERIFY2(r->errorMessage().contains("code 5") && r->errorMessage().contains("debug.exit(5)"),
                 qPrintable(r->errorMessage()));
    }

    void threeCrashesGiveUpUntilReset() {
        BackendClient c(real(true));
        for (int i = 0; i < 3; ++i) {
            auto* r = c.call("debug.exit", {{"code", 4}});
            QVERIFY(waitFor(r, 30000));
            QVERIFY(!r->ok());
        }
        QVERIFY(c.state() == BackendClient::State::GaveUp);
        auto* refused = c.call("system.ping");
        QVERIFY(waitFor(refused, 2000));
        QCOMPARE(refused->errorCode(), BackendReply::kGaveUp);
        c.resetBackoff();
        auto* again = c.call("system.ping");
        QVERIFY(waitFor(again, 30000));
        QVERIFY2(again->ok(), qPrintable(again->errorMessage()));
    }

    void missingInterpreterIsANamedError() {
        BackendConfig cfg = real();
        cfg.python = "C:/no/such/python.exe";
        BackendClient c(cfg);
        auto* r = c.call("system.ping");
        QVERIFY(waitFor(r, 2000));
        QCOMPARE(r->errorCode(), BackendReply::kCannotStart);
        QVERIFY(r->errorMessage().contains("does not exist"));
    }

    void shutdownLeavesNothingBehind() {
        auto c = std::make_unique<BackendClient>(real(true));
        auto* ping = c->call("system.ping");
        QVERIFY(waitFor(ping, 30000) && ping->ok());
        auto* map = c->call("analysis.band_map", {{"result", u8(data("mosfet_2d.npz"))}});
        QVERIFY(waitFor(map, 60000) && map->ok());
        const qint64 pid = c->backendPid();
        const QString scratch = c->scratchDir();
        QVERIFY(QDir(scratch).exists());
        auto* pending = c->call("debug.sleep", {{"seconds", 30}});
        QTest::qWait(100);
        QElapsedTimer t;
        t.start();
        c->shutdown();
        QVERIFY(pending->isFinished());
        QCOMPARE(pending->errorCode(), BackendReply::kShutDown);
        QVERIFY2(t.elapsed() < 5000, qPrintable(QString::number(t.elapsed())));
        QVERIFY(!processAlive(pid));
        QVERIFY2(!QDir(scratch).exists(), qPrintable(scratch));
    }

    // -- fake backends ------------------------------------------------------------
    void fakeBackendsFailByName_data() {
        QTest::addColumn<QString>("mode");
        QTest::addColumn<int>("timeout");
        QTest::addColumn<int>("code");
        QTest::addColumn<QString>("needle");
        QTest::newRow("garbage") << "garbage" << 10000 << BackendReply::kProtocolError << "malformed";
        QTest::newRow("wrong-id") << "wrong_id" << 10000 << BackendReply::kProtocolError << "does not match";
        QTest::newRow("silent") << "silent" << 500 << BackendReply::kTimedOut << "timed out";
        QTest::newRow("wrong-protocol") << "wrong_protocol" << 10000 << BackendReply::kProtocolError << "protocol 99";
        QTest::newRow("exit") << "exit" << 10000 << BackendReply::kGaveUp << "code 7";
        QTest::newRow("stderr-then-exit") << "stderr_then_exit" << 10000 << BackendReply::kBackendExited
                                          << "fatal: something broke";
    }
    void fakeBackendsFailByName() {
        QFETCH(QString, mode);
        QFETCH(int, timeout);
        QFETCH(int, code);
        QFETCH(QString, needle);
        BackendClient c(fake(mode));
        auto* r = c.call("any.method", {{"x", 1}}, timeout);
        QVERIFY2(waitFor(r, 20000), "the client hung");
        QCOMPARE(r->errorCode(), code);
        QVERIFY2(r->errorMessage().contains(needle), qPrintable(r->errorMessage()));
    }

    void fakeCrlfAndSplitLinesAreRead() {
        BackendClient c(fake("crlf"));
        auto* r = c.call("echo", {{"a", "b\xC2\xB5"}});
        QVERIFY(waitFor(r, 20000));
        QVERIFY2(r->ok(), qPrintable(r->errorMessage()));
        QCOMPARE(r->result()["echo"]["a"].get<std::string>(), std::string("b\xC2\xB5"));
    }

    void fakeHugeLineIsRead() {
        BackendClient c(fake("huge"));
        auto* r = c.call("big");
        QVERIFY(waitFor(r, 30000));
        QVERIFY2(r->ok(), qPrintable(r->errorMessage()));
        QCOMPARE(r->result().get<std::string>().size(), std::size_t{10000000});
    }
};

QTEST_GUILESS_MAIN(TestBackend)
#include "test_backend.moc"
