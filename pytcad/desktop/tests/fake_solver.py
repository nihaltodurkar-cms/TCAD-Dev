"""Misbehaving stand-ins for gui.services.solver_runner, for the C++
JobRunner's tests (tests/test_run.cpp; NATIVE-DESKTOP-PLAN.md 17.10).

    python -u fake_solver.py <mode> <job> <result>

    ok           a stage marker, a progress record, the job file's bytes
                 copied to the result, RESULT_PATH, exit 0
    slow         40 plain lines 50 ms apart, printed without flushing, then as ok
    hang         one line, then sleeps
    burst        50 lines in one write, then sleeps
    tree         starts a grandchild that sleeps, prints CHILD_PID=, sleeps
    orphan       starts a grandchild that sleeps, prints CHILD_PID=, then
                 finishes as ok (the grandchild outlives the child)
    crash        an access violation (a crash exit)
    exit5        a line on stderr, exit code 5
    error        a PYTCAD_ERROR payload on stderr, exit 1
    no_marker    writes the result, exit 0, no RESULT_PATH
    no_file      RESULT_PATH without the file, exit 0
    wrong_path   the result written elsewhere and RESULT_PATH naming it
    garbage      invalid UTF-8, a NUL, 3 malformed records, 1 valid one, then ok
    long         a 3 MB line, a 2 MB line split over writes, then ok, and a
                 last line with no newline
    split        RESULT_PATH, a record and a UTF-8 character each split
                 across writes with pauses, then ok
    stderr_flood 5000 lines on stderr, exit 3
"""
import json
import os
import shutil
import subprocess
import sys
import time

mode, job, result = sys.argv[1], sys.argv[2], sys.argv[3]
out = sys.stdout.buffer
SLEEPER = [sys.executable, "-c", "import time; time.sleep(600)"]


def w(data, pause=0.0):
    out.write(data)
    out.flush()
    if pause:
        time.sleep(pause)


def record(event, **fields):
    return ("PYTCAD_PROGRESS " + json.dumps({"v": 1, "t": 0.0, "event": event, **fields}) + "\n").encode()


def finish_ok():
    w(b"PYTCAD_STAGE=equilibrium\n")
    w(record("stage", stage="equilibrium"))
    shutil.copyfile(job, result)
    w(record("done", result=result, dropped=0))
    w(("RESULT_PATH=" + result + "\n").encode("utf-8"))
    sys.exit(0)


if mode == "ok":
    finish_ok()
elif mode == "slow":
    for i in range(40):
        print(f"line {i}")   # no flush, like the core's verbose prints: live only if unbuffered
        time.sleep(0.05)
    finish_ok()
elif mode == "burst":
    w(b"".join(f"burst {i}\n".encode() for i in range(50)))   # one write: one read
    time.sleep(600)
elif mode == "hang":
    w(b"hanging\n")
    time.sleep(600)
elif mode in ("tree", "orphan"):
    child = subprocess.Popen(SLEEPER)
    w(f"CHILD_PID={child.pid}\n".encode())
    if mode == "tree":
        time.sleep(600)
    finish_ok()
elif mode == "crash":
    # A real access violation (exit 0xC0000005). Not ctypes.string_at(0):
    # ctypes catches the fault and raises OSError, a clean exit 1.
    import faulthandler
    faulthandler._read_null()
elif mode == "exit5":
    sys.stderr.write("boom: exit five\n")
    sys.stderr.flush()
    sys.exit(5)
elif mode == "error":
    payload = {"error": "ValueError", "message": "a bad thing µm",
               "traceback": "Traceback (most recent call last):\n  File x\nValueError: a bad thing"}
    sys.stderr.write("a warning first\n")
    sys.stderr.write("PYTCAD_ERROR=" + json.dumps(payload) + "\n")
    sys.stderr.flush()
    sys.exit(1)
elif mode == "no_marker":
    shutil.copyfile(job, result)
    sys.exit(0)
elif mode == "no_file":
    w(("RESULT_PATH=" + result + "\n").encode("utf-8"))
    sys.exit(0)
elif mode == "wrong_path":
    other = result + ".other.npz"
    shutil.copyfile(job, other)
    w(("RESULT_PATH=" + other + "\n").encode("utf-8"))
    sys.exit(0)
elif mode == "garbage":
    w(b"bad utf8 \xff\xfe here\n")
    w(b"nul \x00 byte\n")
    w(b"PYTCAD_PROGRESS {not json\n")
    w(b"PYTCAD_PROGRESS [1, 2]\n")
    w(b'PYTCAD_PROGRESS {"v": 2, "event": "stage"}\n')
    w(record("stage", stage="valid"))
    finish_ok()
elif mode == "long":
    w(b"x" * (3 * 1024 * 1024) + b"\n")
    for _ in range(4):
        w(b"y" * (512 * 1024), 0.02)
    w(b"\nafter the long lines\n")
    w(b"PYTCAD_STAGE=equilibrium\n")
    shutil.copyfile(job, result)
    w(("RESULT_PATH=" + result + "\n").encode("utf-8"))
    w(b"tail without newline")
    sys.exit(0)
elif mode == "split":
    rp = ("RESULT_PATH=" + result + "\n").encode("utf-8")
    rec = record("stage", stage="split µm")
    mu = "µ".encode("utf-8")
    shutil.copyfile(job, result)
    w(rp[:7], 0.05)
    w(rp[7:], 0.05)
    w(rec[:20], 0.05)
    w(rec[20:], 0.05)
    w(b"micro " + mu[:1], 0.05)
    w(mu[1:] + b"m\n")
    sys.exit(0)
elif mode == "stderr_flood":
    for i in range(5000):
        sys.stderr.write(f"stderr line {i}\n")
    sys.stderr.flush()
    sys.exit(3)
else:
    sys.stderr.write(f"unknown mode {mode}\n")
    sys.exit(2)
