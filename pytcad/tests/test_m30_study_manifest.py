"""M30 Phases 8-9 acceptance tests: study manifest resume + provenance.

Contract under test (workbench/study_manifest.py):
  - create_and_run_study builds a split matrix (Phase 1), writes a
    StudyManifest, and solves every buildable row in parallel (Phase
    4), saving the manifest back to disk after EACH row completes --
    not only at the end (G-INCREMENTAL).
  - resume_study loads a manifest and re-runs only rows that are not
    'done': a 'done' row's result_path is left untouched (never
    re-solved), a 'failed' row IS retried.
  - The manifest carries an explicit schema_version and a best-effort
    git commit stamp -- 'unknown'/None when not determinable, NEVER a
    fabricated hash.
"""
import json
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from workbench.study_manifest import (
    StudyManifest, create_and_run_study, resume_study,
)

_BASE = {"length_cm": 1e-4, "height_cm": 2e-5, "nx": 16, "ny": 6,
         "nd_cm3": 1e18}


# ----------------------------------------------------------------------
#  G-SCHEMA: explicit schema version from day one
# ----------------------------------------------------------------------
def test_manifest_has_explicit_schema_version(tmp_path):
    manifest = create_and_run_study(
        "pn_diode", _BASE, {"na_cm3": [-1e18]}, None,
        str(tmp_path / "study.json"), work_dir=str(tmp_path / "work"))
    assert manifest.schema_version == 1
    on_disk = json.loads((tmp_path / "study.json").read_text())
    assert on_disk["schema_version"] == 1


# ----------------------------------------------------------------------
#  G-GIT-STAMP: real commit hash inside a git checkout, honest None
#  otherwise -- never fabricated
# ----------------------------------------------------------------------
def test_manifest_git_stamp_matches_real_head(tmp_path):
    manifest = create_and_run_study(
        "pn_diode", _BASE, {"na_cm3": [-1e18]}, None,
        str(tmp_path / "study.json"), work_dir=str(tmp_path / "work"))
    real_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)))
    if real_head.returncode == 0:
        assert manifest.git_commit == real_head.stdout.strip()
    else:
        assert manifest.git_commit is None


def test_git_commit_is_none_outside_a_git_checkout(tmp_path, monkeypatch):
    import workbench.study_manifest as sm

    def _fake_run(*a, **k):
        raise FileNotFoundError("git not found")
    monkeypatch.setattr(sm.subprocess, "run", _fake_run)
    assert sm._git_commit() is None


# ----------------------------------------------------------------------
#  G-MANIFEST-COMPLETE: round-trips into the same split matrix
# ----------------------------------------------------------------------
def test_manifest_roundtrips_the_exact_split_matrix(tmp_path):
    manifest_path = str(tmp_path / "study.json")
    original = create_and_run_study(
        "pn_diode", _BASE, {"na_cm3": [-1e18, -2e18, -3e18]}, None,
        manifest_path, work_dir=str(tmp_path / "work"))

    reloaded = StudyManifest.load(manifest_path)
    assert reloaded.template_id == original.template_id
    assert reloaded.splits == original.splits
    assert reloaded.base_values == original.base_values
    assert [r["params"] for r in reloaded.rows] == \
        [r["params"] for r in original.rows]
    assert all(r["status"] == "done" for r in reloaded.rows)


# ----------------------------------------------------------------------
#  G-NO-DUPLICATION: the manifest references result paths, does not
#  copy each row's RunRecord inline
# ----------------------------------------------------------------------
def test_manifest_rows_reference_results_not_duplicate_run_records(tmp_path):
    manifest = create_and_run_study(
        "pn_diode", _BASE, {"na_cm3": [-1e18]}, None,
        str(tmp_path / "study.json"), work_dir=str(tmp_path / "work"))
    row = manifest.rows[0]
    assert set(row) == {"params", "status", "result_path", "error"}
    assert "trace" not in row and "numerics" not in row


# ----------------------------------------------------------------------
#  G-INCREMENTAL: the manifest on disk shows partial completion DURING
#  the run, not only after it finishes
# ----------------------------------------------------------------------
def test_manifest_is_written_incrementally_not_only_at_the_end(tmp_path):
    manifest_path = str(tmp_path / "study.json")
    work_dir = str(tmp_path / "work")

    # max_workers=1 forces every row through ONE worker sequentially,
    # and a generous row count (16) stretches the whole run to well
    # past the polling interval regardless of how fast a single tiny
    # equilibrium solve happens to be on this machine -- without both,
    # a fast enough machine could finish all rows between two polls and
    # wrongly fail this gate for being too fast, not for skipping
    # incremental writes.
    na_values = [-1e18 * (1 + 0.1 * i) for i in range(16)]
    thread = threading.Thread(
        target=create_and_run_study,
        args=("pn_diode", _BASE, {"na_cm3": na_values}, None, manifest_path),
        kwargs={"work_dir": work_dir, "max_workers": 1})
    thread.start()
    try:
        saw_partial_completion = False
        for _ in range(4000):
            time.sleep(0.01)
            if os.path.exists(manifest_path):
                try:
                    data = json.loads(open(manifest_path).read())
                except (json.JSONDecodeError, OSError):
                    continue
                statuses = [r["status"] for r in data["rows"]]
                if "done" in statuses and "pending" in statuses:
                    saw_partial_completion = True
                    break
            if not thread.is_alive():
                break
    finally:
        thread.join(timeout=60)
    assert saw_partial_completion, \
        "manifest never showed a partial (some done, some pending) " \
        "state -- it is only being written once, at the end"


# ----------------------------------------------------------------------
#  G-RESUME-SKIPS-DONE / G-RESUME-RETRIES-FAILED
# ----------------------------------------------------------------------
def test_resume_skips_done_rows_and_retries_failed_rows(tmp_path):
    manifest_path = str(tmp_path / "study.json")
    manifest = create_and_run_study(
        "pn_diode", _BASE, {"na_cm3": [-1e18, -2e18, -3e18]}, None,
        manifest_path, work_dir=str(tmp_path / "work"))
    assert all(r["status"] == "done" for r in manifest.rows)

    # simulate a partial prior run: row 0 stays done, row 1 is
    # (falsely) marked failed, row 2 is reset to pending
    manifest.rows[1]["status"] = "failed"
    manifest.rows[1]["error"] = "simulated prior failure"
    original_done_path = manifest.rows[0]["result_path"]
    original_done_mtime = os.path.getmtime(original_done_path)
    manifest.rows[2]["status"] = "pending"
    manifest.rows[2]["result_path"] = ""
    manifest.save(manifest_path)

    resumed = resume_study(manifest_path, work_dir=str(tmp_path / "resume"))

    # row 0 ('done') is untouched: same path, same mtime, never re-solved
    assert resumed.rows[0]["status"] == "done"
    assert resumed.rows[0]["result_path"] == original_done_path
    assert os.path.getmtime(original_done_path) == original_done_mtime

    # rows 1 (failed) and 2 (pending) were both retried and now done
    assert resumed.rows[1]["status"] == "done"
    assert resumed.rows[1]["result_path"]
    assert resumed.rows[2]["status"] == "done"
    assert resumed.rows[2]["result_path"]


def test_resume_with_nothing_pending_is_a_noop(tmp_path):
    manifest_path = str(tmp_path / "study.json")
    create_and_run_study(
        "pn_diode", _BASE, {"na_cm3": [-1e18]}, None,
        manifest_path, work_dir=str(tmp_path / "work"))
    before = StudyManifest.load(manifest_path)
    resumed = resume_study(manifest_path, work_dir=str(tmp_path / "resume2"))
    assert resumed.rows == before.rows


def test_resume_reports_build_error_for_a_row_no_longer_buildable(tmp_path):
    """A row that built fine originally but is corrupted (e.g. a
    parameter now outside the template's own bounds) into an invalid
    state must surface as 'build_error' on resume, not crash."""
    manifest_path = str(tmp_path / "study.json")
    manifest = create_and_run_study(
        "pn_diode", _BASE, {"na_cm3": [-1e18]}, None,
        manifest_path, work_dir=str(tmp_path / "work"))
    manifest.rows[0]["status"] = "pending"
    manifest.rows[0]["params"]["na_cm3"] = -1e30   # now out of range
    manifest.save(manifest_path)

    resumed = resume_study(manifest_path, work_dir=str(tmp_path / "resume3"))
    assert resumed.rows[0]["status"] == "build_error"
    assert resumed.rows[0]["error"]
