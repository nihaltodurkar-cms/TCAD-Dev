"""The structured progress channel (NATIVE-DESKTOP-PLAN.md 4.3, P3-S1).

A solver subprocess (solver_runner, moscap_runner) installs a ProgressTap
over its stdout for the whole job. Everything still reaches stdout
unchanged -- the PYTCAD_STAGE / RESULT_PATH markers and the core's
verbose Newton prints the QML GUI and the convergence trace already read
-- and the tap ADDS, as the lines go by, one record per event:

    PYTCAD_PROGRESS {"v":1,"event":...,"t":<s since start>, ...}

Events:
  stage           {"stage"}                       every PYTCAD_STAGE=<name>
  sweep_point     {"stage":"sweep","index","count","contact","value"}
                                                  PYTCAD_STAGE=sweep point i/N;
                                                  contact/value null when the
                                                  line was relayed (MPI engine)
  newton          {"stage","iter","residual":{name: value}}
                                                  a verbose Newton line, parsed
                                                  with the SAME regexes as the
                                                  post-run convergence trace
  transient_step  {"stage","time","dt","iters"}   a [transient*] step line
  done            {"result","dropped"}
  error           {"error","message"}

Non-finite numbers are written as null (NaN is not JSON). At most one
newton record per (stage, iteration), and at most 50 records per second:
excess newton/transient_step records are DROPPED, never buffered, and
counted in "done"; stage, sweep_point, done and error are never dropped.
The numbers come from the frozen core's verbose prints -- best-effort
scraping moved next to its source, not a structured hook in the core.
"""
import collections
import io
import json
import math
import re
import time

# The runners' stdout line grammars -- the ONE definition, shared by the
# post-run convergence trace (solver_runner._trace_from_output, which
# imports them from here) and the live records below.
STAGE_LINE = re.compile(r"^PYTCAD_STAGE=(\w+)(?:\s+(.*))?$")
SWEEP_POINT = re.compile(r"point (\d+)/(\d+)")   # 'sweep' is consumed by STAGE_LINE's group(1)
ITERATION = re.compile(r"\bit\s+(\d+)\b")
METRIC = re.compile(
    r"\|\s*([^|]+?)\s*\|\s*=\s*(-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?\d+)?)")

PREFIX = "PYTCAD_PROGRESS "
VERSION = 1
MAX_PER_SECOND = 50
ESSENTIAL = ("stage", "sweep_point", "done", "error")

_TRANSIENT_STEP = re.compile(
    r"\[transient(?:2d|3d)?\]\s+t=(\S+?)s\s+dt=(\S+?)s(?:\s+iters=(\d+))?")


def json_safe(obj):
    """obj with every non-finite float replaced by None (recursively)."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj


def parse_line(line):
    """The record a PYTCAD_PROGRESS line carries, or None for any other line."""
    if not line.startswith(PREFIX):
        return None
    return json.loads(line[len(PREFIX):])


class ProgressTap(io.TextIOBase):
    """A stdout wrapper: passes every write through, and emits a progress
    record for each recognised complete line, read with the module's line
    grammars -- the same ones the stored convergence trace uses, so the two
    can never read a line differently."""

    def __init__(self, out, clock=time.perf_counter):
        super().__init__()
        self._out = out
        self._stage_re, self._point_re = STAGE_LINE, SWEEP_POINT
        self._iter_re, self._metric_re = ITERATION, METRIC
        self._clock = clock
        self._t0 = clock()
        self._pending = ""
        self._stage = None
        self._last_newton = None
        self._sweep_ctx = None
        self._window = collections.deque()
        self.dropped = 0

    # -- the stream -----------------------------------------------------------
    @property
    def wrapped(self):
        return self._out

    def writable(self):
        return True

    def write(self, text):
        # Line by line: a line's record follows that line's newline, so a
        # record can never be glued onto the end of a line still being
        # written (one write may carry several lines and a partial tail).
        *complete, tail = text.split("\n")
        for piece in complete:
            self._out.write(piece + "\n")
            line, self._pending = self._pending + piece, ""
            self._line(line.rstrip("\r"))
        if tail:
            self._out.write(tail)
            self._pending += tail
        return len(text)

    def flush(self):
        self._out.flush()

    def fileno(self):
        return self._out.fileno()

    @property
    def encoding(self):
        return getattr(self._out, "encoding", "utf-8")

    # -- records ----------------------------------------------------------------
    def set_sweep_context(self, contact, value):
        """The contact and bias of the sweep point whose marker comes next."""
        self._sweep_ctx = (contact, float(value))

    def emit(self, event, **fields):
        now = self._clock()
        while self._window and now - self._window[0] >= 1.0:
            self._window.popleft()
        if event not in ESSENTIAL and len(self._window) >= MAX_PER_SECOND:
            self.dropped += 1
            return
        self._window.append(now)
        record = {"v": VERSION, "event": event, "t": round(now - self._t0, 6)}
        record.update(fields)
        if self._pending:             # emitted mid-line (e.g. an error): a record starts a line
            self._out.write("\n")
        self._out.write(PREFIX + json.dumps(json_safe(record), separators=(",", ":"),
                                            allow_nan=False) + "\n")
        self._out.flush()

    def _line(self, line):
        marker = self._stage_re.match(line.strip())
        if marker:
            name, extra = marker.group(1), marker.group(2) or ""
            point = self._point_re.search(extra) if name == "sweep" else None
            if point:
                index, count = int(point.group(1)) - 1, int(point.group(2))
                self._stage = f"sweep:{index}"   # the trace's own stage names
                contact, value = self._sweep_ctx or (None, None)
                self._sweep_ctx = None
                self.emit("sweep_point", stage="sweep", index=index, count=count,
                          contact=contact, value=value)
            else:
                self._stage = name
                self.emit("stage", stage=name)
            self._last_newton = None
            return
        step = _TRANSIENT_STEP.search(line)
        if step:
            self.emit("transient_step", stage=self._stage, time=_num(step.group(1)),
                      dt=_num(step.group(2)), iters=int(step.group(3)) if step.group(3) else None)
            return
        it = self._iter_re.search(line)
        metrics = self._metric_re.findall(line)
        if it and metrics:
            key = (self._stage, int(it.group(1)))
            if key == self._last_newton:
                return
            self._last_newton = key
            self.emit("newton", stage=self._stage, iter=key[1],
                      residual={name.strip(): _num(val) for name, val in metrics})


def _num(text):
    try:
        return float(text)
    except ValueError:
        return None
