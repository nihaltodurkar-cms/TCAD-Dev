"""QML's JobRunner in work directories with non-ASCII names
(NATIVE-DESKTOP-PLAN.md 17.10).

A piped Python stdout on Windows is cp1252 unless told otherwise, so the
solver's `RESULT_PATH=<path>` line was either garbled (a cp1252 character,
e.g. a user name like José in %TEMP%: the run was reported failed) or
crashed the child's final print (a character outside cp1252). The runner
now starts the child with PYTHONIOENCODING=utf-8.

The test process drops PYTHONIOENCODING/PYTHONUTF8 (conda run exports
them, which hid the bug): the child must not depend on its parent's.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402

from gui.services import examples  # noqa: E402
from gui.services.job_runner import JobRunner  # noqa: E402


@pytest.fixture
def clean_encoding_env(monkeypatch):
    for k in ("PYTHONIOENCODING", "PYTHONUTF8"):
        monkeypatch.delenv(k, raising=False)


@pytest.mark.parametrize("name", ["José", "µm € \U0001f600"])
def test_a_run_in_a_non_ascii_directory_finishes(tmp_path, clean_encoding_env, name):
    work = tmp_path / name
    work.mkdir()
    runner = JobRunner(work_dir=str(work))
    outcome = {}
    loop = QEventLoop()
    runner.finished.connect(lambda p: (outcome.update(result=p), loop.quit()))
    runner.failed.connect(lambda s, d: (outcome.update(failed=s, details=d), loop.quit()))
    QTimer.singleShot(120000, loop.quit)
    runner.start(examples.EXAMPLES["diode_1d"]())
    loop.exec()
    assert "result" in outcome, outcome.get("failed")
    assert outcome["result"] == runner.result_path
    assert os.path.isfile(outcome["result"])
