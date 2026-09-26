"""NATIVE-DESKTOP-PLAN.md P1 S8 hardening gates for the native app's reader.

S8a -- bounded memory (the reader, tcad_npz_dump --open-only):
- a 2 GB file that is not a zip is refused from its last 64 KB: the
  reader's peak working set rises by under 64 MB;
- a real result opens holding about ONE copy of its arrays: the peak
  rises by at most (the arrays' bytes) + max(16 MB, 10%) -- measured
  overhead is ~0.3 MB (15.24). The pre-S8 reader read the whole file into
  a buffer and copied every array out of it (~2x); the plan's first
  margin, +64 MB, let that mutant through on this ~61 MB file, so it was
  tightened;
- a result whose arrays exceed the limit is refused BEFORE any array is
  read, naming both sizes;
- a mesh over the viewer's node limit (64M, decision 1) is refused by the
  result model, naming the count and the limit.

S8c -- fuzzing: 2000 seeded mutations of a real 3D sweep result (bit
flips, truncations, zip-directory edits, and -- rewritten with correct
CRCs, so they reach the parsers -- .npy header and JSON metadata edits),
each run through tcad_npz_dump in its own process. Every run must exit 0
(it parses) or 2 (a named rejection) within 10 s: no crash, no uncaught
exception, no hang.

S8d -- soak: tcad_desktop --soak opens a 2D MOSFET, a layered 3D sweep and
a 1M-node grid into ONE window 60 times, exercising every layer; no GL
re-init, and private memory not rising over the last 40 cycles (a
Theil-Sen slope, robust to the allocator's steps -- plan 16.10).

Skipped when the desktop app has not been built.
"""
import io
import json
import os
import random
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "desktop", "bench"))

BUILD = os.path.join(ROOT, "build", "desktop")
MANIFEST = os.path.join(BUILD, "desktop_runtime.json")

pytestmark = pytest.mark.skipif(
    not os.path.isfile(MANIFEST),
    reason="native desktop app not built (powershell -File desktop\\build.ps1)")

MB = 1024 * 1024


def _dump(*args, timeout=60):
    with open(MANIFEST) as fh:
        manifest = json.load(fh)
    env = dict(os.environ)
    env["PATH"] = manifest["runtime_bin"] + os.pathsep + env.get("PATH", "")
    exe = os.path.join(BUILD, manifest["tools"]["npz_dump"])
    return subprocess.run([exe, *args], capture_output=True, text=True, env=env, timeout=timeout)


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    import run_bench
    d = str(tmp_path_factory.mktemp("hardening"))
    return {"layers_small": run_bench._synthetic(d, "layers_small", (24, 18, 14)),
            "layers_big": run_bench._synthetic(d, "layers_big", (80, 80, 80)),
            "dir": d}


# -- S8a ------------------------------------------------------------------------

def test_a_2gb_non_zip_is_refused_from_its_tail(tmp_path):
    junk = tmp_path / "junk_2gb.npz"
    with open(junk, "wb") as fh:          # 2 GB + a little, not a zip
        fh.seek(2 * 1024 ** 3 + 12345)
        fh.write(b"\x01")
    try:
        out = _dump("--open-only", str(junk))
        rep = json.loads(out.stdout)
        assert out.returncode == 2 and not rep["ok"]
        assert "not a zip archive" in rep["error"]
        assert rep["peak_mb_after"] - rep["peak_mb_before"] < 64, rep
    finally:
        junk.unlink()


def test_a_result_opens_holding_one_copy_of_its_arrays(results):
    out = _dump("--open-only", results["layers_big"])
    rep = json.loads(out.stdout)
    assert out.returncode == 0 and rep["ok"], out.stdout
    arrays_mb = rep["array_bytes"] / MB
    assert arrays_mb > 50, "the probe needs arrays large enough to see a second copy"
    rise = rep["peak_mb_after"] - rep["peak_mb_before"]
    assert rise <= arrays_mb + max(16.0, 0.1 * arrays_mb), f"peak rose {rise:.0f} MB for {arrays_mb:.0f} MB of arrays"


def test_an_over_limit_result_is_refused_before_reading(results):
    out = _dump("--open-only", "--max-bytes", str(10 * MB), results["layers_big"])
    rep = json.loads(out.stdout)
    assert out.returncode == 2 and not rep["ok"]
    assert "need" in rep["error"] and "over the limit of 0.01 GB" in rep["error"], rep["error"]
    assert rep["peak_mb_after"] - rep["peak_mb_before"] < 16, rep


def test_a_mesh_over_the_node_limit_is_refused(tmp_path):
    # 4096 x 4096 x 5 = 83.9M nodes > 64M: the axes alone (small) trip it,
    # before any field shape is looked at.
    p = tmp_path / "too_many_nodes.npz"
    np.savez(p, result__schema=np.int64(3), solved_bias=np.array(True), dimensionality=np.int64(3),
             axis_x=np.linspace(0, 1e-4, 4096), axis_y=np.linspace(0, 1e-4, 4096),
             axis_z=np.linspace(0, 1e-5, 5))
    out = _dump(str(p))
    rep = json.loads(out.stdout)
    assert out.returncode == 0 and rep["ok"]           # the archive itself reads
    assert "83886080 nodes" in rep["result_error"], rep.get("result_error")
    assert "at most 67108864" in rep["result_error"]


# -- S8c ------------------------------------------------------------------------

def _entries(path):
    with zipfile.ZipFile(path) as z:
        return [(i.filename, z.read(i.filename)) for i in z.infolist()]


def _rezip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for name, data in entries:
            z.writestr(name, data)
    return buf.getvalue()


def _npy_bytes(arr):
    b = io.BytesIO()
    np.save(b, arr, allow_pickle=False)
    return b.getvalue()


def _mutants(base_path, n, seed=20260926):
    rng = random.Random(seed)
    raw = open(base_path, "rb").read()
    entries = _entries(base_path)
    json_keys = [i for i, (name, _) in enumerate(entries)
                 if name[:-4] in ("sweep__meta", "sweep__snapshot__voltages", "structure_regions__meta",
                                  "mesh__shape", "record__meta")]
    eocd = raw.rfind(b"PK\x05\x06")
    cd_off = int.from_bytes(raw[eocd + 16:eocd + 20], "little")
    kinds = ["flip"] * 500 + ["truncate"] * 300 + ["directory"] * 400 + ["npy_header"] * 400 + ["json"] * 400
    rng.shuffle(kinds)
    for k in kinds[:n]:
        if k == "flip":
            b = bytearray(raw)
            for _ in range(rng.randint(1, 8)):
                b[rng.randrange(len(b))] ^= 1 << rng.randrange(8)
            yield k, bytes(b)
        elif k == "truncate":
            yield k, raw[:rng.randrange(len(raw))]
        elif k == "directory":   # 16/32-bit fields of the central directory and its end record
            b = bytearray(raw)
            for _ in range(rng.randint(1, 3)):
                pos = rng.randrange(cd_off, len(b) - 4)
                width = rng.choice([2, 4])
                val = rng.choice([0, 1, 0xFFFF, 0xFFFFFFFF, rng.getrandbits(8 * width)]) & ((1 << (8 * width)) - 1)
                b[pos:pos + width] = val.to_bytes(width, "little")
            yield k, bytes(b)
        elif k == "npy_header":  # correct CRCs: the edit reaches parse_npy
            e = list(entries)
            i = rng.randrange(len(e))
            name, data = e[i]
            b = bytearray(data)
            hl = 10 + int.from_bytes(b[8:10], "little") if len(b) > 10 else len(b)
            for _ in range(rng.randint(1, 4)):
                pos = rng.randrange(0, min(hl, len(b)))
                b[pos] = rng.choice(b"0123456789()[]{},:'\" <>|fiubUTFrues-") if rng.random() < 0.7 else rng.randrange(256)
            e[i] = (name, bytes(b))
            yield k, _rezip(e)
        else:                    # JSON metadata, re-saved as a valid npy string
            e = list(entries)
            i = rng.choice(json_keys)
            name, data = e[i]
            text = str(np.load(io.BytesIO(data), allow_pickle=False))
            chars = list(text)
            for _ in range(rng.randint(1, 4)):
                op = rng.random()
                pos = rng.randrange(len(chars) + 1)
                if op < 0.4 and chars:
                    del chars[min(pos, len(chars) - 1)]
                elif op < 0.8:
                    chars.insert(pos, rng.choice('[]{},:"-0123456789.eE nulltruefalse\\u'))
                else:
                    chars = chars[:pos]
            e[i] = (name, _npy_bytes(np.array("".join(chars))))
            yield k, _rezip(e)


def test_the_reader_survives_2000_mutations(results, tmp_path):
    cases = list(_mutants(results["layers_small"], 2000))
    assert len(cases) == 2000
    paths = []
    for n, (kind, data) in enumerate(cases):
        p = tmp_path / f"m{n:04d}_{kind}.npz"
        p.write_bytes(data)
        paths.append(p)

    def run(p):
        try:
            out = _dump(str(p), timeout=10)
        except subprocess.TimeoutExpired:
            return p.name, "timeout", ""
        return p.name, out.returncode, (out.stdout + out.stderr)[-300:]

    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(run, paths))
    bad = [r for r in runs if r[1] not in (0, 2)]
    codes = {}
    for _, code, _ in runs:
        codes[code] = codes.get(code, 0) + 1
    assert not bad, f"{len(bad)} of 2000 crashed/hung (exit codes {codes}); first: {bad[:3]}"
    assert codes.get(2, 0) > 500, f"the mutations must mostly be rejected, got {codes}"


# -- S8d ------------------------------------------------------------------------

# The soak's memory gate (NATIVE-DESKTOP-PLAN.md 16.10). Settled private
# memory is flat plateaus with 10-25 MB steps either way (allocator and
# driver caches), so a least-squares slope over 20 cycles read one step as
# a trend: 4 false failures in 51 recorded runs of a leak-free build. The
# Theil-Sen slope (the median of every pairwise slope) over the last 40
# cycles is robust to a step: 0 false failures on the same 51 runs (the
# largest was 0.18 MB/cycle), and with a synthetic 0.5 MB/cycle leak added
# to each it fails 34/51 against the old gate's 21/51 (1.0 MB/cycle: 41 vs
# 42). Neither catches a leak that small every time in 60 cycles: memory is
# often still falling there, and hides it.
SOAK_RISE_LIMIT = 0.3   # MB/cycle
SOAK_WINDOW = 40        # cycles


def _rise_per_cycle(mem):
    tail = np.asarray(mem[-SOAK_WINDOW:], dtype=float)
    i, j = np.triu_indices(len(tail), 1)
    return float(np.median((tail[j] - tail[i]) / (j - i)))


# A real run of the current build that the old gate failed (the full suite,
# 2026-09-26): flat, then one +12 MB step at cycle 48.
_STEP_SERIES = [
    512.45, 538.2, 540.04, 540.37, 547.23, 571.68, 568.24, 566.14, 565.24, 564.11,
    564.57, 562.94, 562.53, 563.45, 558.39, 559.01, 556.86, 558.81, 557.98, 550.35,
    547.05, 547.42, 547.46, 546.72, 546.89, 546.8, 547.21, 547.69, 546.41, 546.74,
    522.95, 524.41, 523.89, 523.29, 524.8, 524.17, 523.5, 523.54, 525.07, 524.16,
    524.52, 524.21, 524.03, 525.0, 523.99, 525.68, 524.05, 524.35, 536.07, 536.7,
    536.86, 536.25, 537.04, 536.41, 535.73, 536.21, 536.47, 536.21, 536.04, 536.65]


def test_the_soak_memory_gate_ignores_a_step_and_catches_a_steady_rise():
    """The gate itself, on the recorded run: one step passes; the same run
    with a steady 0.5 MB/cycle leak added fails, as does a clean ramp."""
    assert _rise_per_cycle(_STEP_SERIES) < SOAK_RISE_LIMIT
    old = np.polyfit(np.arange(20), np.array(_STEP_SERIES[-20:]), 1)[0]
    assert old >= 0.5, "the old least-squares gate failed this run"
    leaking = [m + 0.5 * k for k, m in enumerate(_STEP_SERIES)]
    assert _rise_per_cycle(leaking) >= SOAK_RISE_LIMIT
    assert _rise_per_cycle([500 + 0.35 * k for k in range(60)]) >= SOAK_RISE_LIMIT


@pytest.mark.timing  # memory-growth budget under load: run serially (pytest.ini "timing")
def test_a_soak_keeps_memory_and_the_gl_context(results):
    """60 cycles of opening a 2D MOSFET, a layered 3D sweep and a 1M-node
    grid into ONE window, switching fields and every layer each has. The
    GL context is never recreated, and private memory does not rise over
    the last 40 cycles (the Theil-Sen gate above; a 100-cycle probe, 15.24:
    private memory peaks while caches warm, then falls back and holds)."""
    import run_bench
    d = results["dir"]
    files = [run_bench._solve(d, "mosfet_2d"), results["layers_small"],
             run_bench._synthetic(d, "grid1m", (1000, 1000))]
    with open(MANIFEST) as fh:
        manifest = json.load(fh)
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}   # a real GL surface
    env["PATH"] = manifest["runtime_bin"] + os.pathsep + env.get("PATH", "")
    out = subprocess.run([os.path.join(BUILD, manifest["tools"]["desktop"]), "--soak", *files,
                          "--cycles", "60", "--size", "900x600"],
                         capture_output=True, text=True, env=env, timeout=900)
    rep = json.loads(out.stdout)
    assert out.returncode == 0 and rep["ok"] and rep["gl_reinits"] == 0, out.stdout[-500:]
    mem = rep["private_mb"]
    rise = _rise_per_cycle(mem)
    assert rise < SOAK_RISE_LIMIT, f"private memory rising {rise:.3f} MB/cycle over the last 40 cycles: {mem}"
