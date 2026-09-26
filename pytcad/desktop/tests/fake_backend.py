"""Misbehaving stand-ins for backend_service, for the C++ BackendClient's
tests (tests/test_backend.cpp; NATIVE-DESKTOP-PLAN.md 15.15).

    python fake_backend.py <mode>

Every mode except "exit" answers the client's handshake (system.ping,
system.info) correctly, then misbehaves on the first real call:

    garbage           a line that is not JSON
    silent            never answers
    wrong_id          answers with another request's id
    wrong_protocol    system.ping claims protocol 99
    exit              exits with code 7 before reading anything
    crlf              correct replies, CRLF-terminated, each written in two
                      halves with a pause between (a line split across reads)
    huge              the result is a 10 MB string on one line
    stderr_then_exit  writes a message to stderr, then exits with code 9
"""
import json
import os
import shutil
import sys
import tempfile
import time

mode = sys.argv[1]
if mode == "exit":
    sys.exit(7)

out = sys.stdout.buffer
scratch = tempfile.mkdtemp(prefix="tcad_backend_")


def reply(obj, crlf=False, split=False):
    data = (json.dumps(obj) + ("\r\n" if crlf else "\n")).encode("utf-8")
    if split:
        half = len(data) // 2
        out.write(data[:half])
        out.flush()
        time.sleep(0.05)
        out.write(data[half:])
    else:
        out.write(data)
    out.flush()


try:
    for raw in sys.stdin.buffer:
        if not raw.strip():
            continue
        req = json.loads(raw)
        method, rid = req["method"], req.get("id")
        crlf = mode == "crlf"
        if method == "system.ping":
            reply({"jsonrpc": "2.0", "id": rid,
                   "result": {"pong": True, "protocol": 99 if mode == "wrong_protocol" else 1}}, crlf)
        elif method == "system.info":
            reply({"jsonrpc": "2.0", "id": rid,
                   "result": {"protocol": 1, "pid": os.getpid(), "prefix": sys.prefix,
                              "python": sys.executable, "scratch_dir": scratch}}, crlf)
        elif method == "system.shutdown":
            reply({"jsonrpc": "2.0", "id": rid, "result": None}, crlf)
            break
        elif mode == "garbage":
            out.write(b"this is not json\n")
            out.flush()
        elif mode == "silent":
            continue
        elif mode == "wrong_id":
            reply({"jsonrpc": "2.0", "id": rid + 1000, "result": 1})
        elif mode == "crlf":
            reply({"jsonrpc": "2.0", "id": rid, "result": {"echo": req.get("params")}}, crlf=True, split=True)
        elif mode == "huge":
            reply({"jsonrpc": "2.0", "id": rid, "result": "x" * 10_000_000})
        elif mode == "stderr_then_exit":
            sys.stderr.write("fatal: something broke\n")
            sys.stderr.flush()
            sys.exit(9)
finally:
    shutil.rmtree(scratch, ignore_errors=True)
