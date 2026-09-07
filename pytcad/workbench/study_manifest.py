"""M30 Phases 8-9: study manifest -- resume + provenance for a Study
(a split-matrix run, whether driven from the GUI's StudyController or
headless).

One JSON document per study, written INCREMENTALLY -- after every row
completes, not just at the end -- so a crash or kill partway through
leaves a usable partial manifest.  `resume_study` then re-runs only the
rows still `pending`/`failed`; a `done` row's own result path is left
untouched, never re-solved.

Deliberately named "study manifest," never "checkpoint": that word
already names a different, existing concept in this repo
(gui/services/process_runner.py's per-PROCESS-STEP device snapshots) --
reusing it here would collide with an established meaning.

Provenance (Phase 9) is deliberately minimal and honest: the split
spec, template id, base values, and bias are already enough to
reproduce the run given the same code; the manifest additionally stamps
`git_commit` (best-effort `git rev-parse HEAD`) so a later reader knows
which code version produced it. When not inside a git checkout (or the
command fails for any reason), `git_commit` is `None` -- NEVER a
fabricated hash. Each row's own result `.npz` already carries its own
RunRecord (see gui/services/solver_backend.py); the manifest
references result paths rather than duplicating that data inline, so
there is exactly one place each fact lives.
"""
import json
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field

SCHEMA_VERSION = 1


def _git_commit():
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            timeout=5, cwd=os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


@dataclass
class StudyManifest:
    schema_version: int
    template_id: str
    base_values: dict
    splits: dict
    bias: dict
    rows: list             # [{params, status, result_path, error}, ...]
    git_commit: object = None

    @classmethod
    def create(cls, template_id, base_values, splits, bias, rows):
        return cls(schema_version=SCHEMA_VERSION, template_id=template_id,
                   base_values=dict(base_values or {}),
                   splits=dict(splits or {}), bias=dict(bias or {}),
                   rows=list(rows), git_commit=_git_commit())

    def save(self, path):
        """Atomic on POSIX (os.replace): a reader never observes a
        half-written manifest."""
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(asdict(self), f, indent=2)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path):
        with open(path) as f:
            data = json.load(f)
        return cls(**data)


def _rows_from_split_matrix(split_rows):
    return [{"params": dict(row.params),
             "status": "build_error" if row.error else "pending",
             "result_path": "", "error": row.error or ""}
            for row in split_rows]


def _run_pending_rows(manifest, split_devices, manifest_path, work_dir,
                      max_workers=None):
    """Common tail for create_and_run_study/resume_study: solve every
    row still 'pending' (via workbench.batch's parallel pool), saving
    the manifest back to disk after EACH row completes -- gate
    G-INCREMENTAL.  `split_devices`: {row_index: DomainDevice} for rows
    that still need a job written (already-built rows only)."""
    from .adapters.spec import spec_from_domain
    from .batch import run_jobs_parallel_iter

    jobs, job_idx = [], []
    for i, device in split_devices.items():
        spec = spec_from_domain(device)
        spec.bias = dict(manifest.bias) if manifest.bias else None
        spec.sweep = None
        job_path = os.path.join(work_dir, f"job-{i}.json")
        out_path = os.path.join(work_dir, f"result-{i}.npz")
        spec.to_json(job_path)
        jobs.append((job_path, out_path))
        job_idx.append(i)

    for local_i, outcome in run_jobs_parallel_iter(jobs, max_workers=max_workers):
        i = job_idx[local_i]
        row = manifest.rows[i]
        if outcome.error is None:
            row["status"] = "done"
            row["result_path"] = outcome.out_path
        else:
            row["status"] = "failed"
            row["error"] = outcome.error
        manifest.save(manifest_path)
    return manifest


def create_and_run_study(template_id, base_values, splits, bias,
                         manifest_path, work_dir=None, max_workers=None):
    """Build a fresh split matrix (workbench.splits.run_split_matrix),
    write its manifest, then solve every buildable row in parallel
    (workbench.batch), saving the manifest incrementally as each row
    finishes.  Row order matches expand_splits' own documented order."""
    from .splits import run_split_matrix
    from .workflow import DeckRun

    run = DeckRun(template_id=template_id)
    run._values = dict(base_values or {})
    run.splits = dict(splits or {})
    split_rows = run_split_matrix(run)

    manifest = StudyManifest.create(template_id, base_values, splits,
                                    bias, _rows_from_split_matrix(split_rows))
    work_dir = work_dir or tempfile.mkdtemp(prefix="pytcad-study-")
    os.makedirs(work_dir, exist_ok=True)
    manifest.save(manifest_path)

    devices = {i: row.device for i, row in enumerate(split_rows)
              if row.error is None}
    return _run_pending_rows(manifest, devices, manifest_path, work_dir,
                             max_workers=max_workers)


def resume_study(manifest_path, work_dir=None, max_workers=None):
    """Load a manifest and (re-)run only its non-'done' rows.  A
    'done' row's result_path is NEVER touched; a 'failed' row IS
    retried (a failure is not treated as permanently finished)."""
    from .core.templates import get_template

    manifest = StudyManifest.load(manifest_path)
    template = get_template(manifest.template_id)
    work_dir = work_dir or tempfile.mkdtemp(prefix="pytcad-resume-")
    os.makedirs(work_dir, exist_ok=True)

    devices = {}
    for i, row in enumerate(manifest.rows):
        if row["status"] == "done":
            continue
        try:
            devices[i] = template.build(row["params"])
            row["status"] = "pending"
            row["error"] = ""
        except (ValueError, KeyError) as exc:
            row["status"] = "build_error"
            row["error"] = str(exc)
    manifest.save(manifest_path)

    if not devices:
        return manifest
    return _run_pending_rows(manifest, devices, manifest_path, work_dir,
                             max_workers=max_workers)
