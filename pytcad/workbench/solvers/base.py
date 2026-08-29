"""The SolverBackend door (M3c).

One protocol, addressed by string id, that any solve engine implements:
hand it a prepared DeviceSpec JSON job plus an output path, it writes a
schema-v2 result file.  gui.services.solver_runner (the homegrown FD/
Newton core) is the reference implementation; a DEVSIM adapter would
implement the same three members and register itself here -- nothing
above this layer may learn a second way to talk to solvers.

Subprocess isolation stays an implementation detail of each backend:
the protocol is deliberately file-based so the OS-kill-safe JobRunner
pattern carries over unchanged.
"""
from dataclasses import dataclass
from importlib import import_module
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SolveRequest:
    """A prepared job: DeviceSpec JSON in, .npz result out."""
    job_json_path: str
    out_npz_path: str


@runtime_checkable
class SolverBackend(Protocol):
    id: str

    def run(self, request: SolveRequest) -> None:
        """Execute the job, writing a schema-v2 result to
        request.out_npz_path (atomically).  Raises on failure."""
        ...


class PytcadBackend:
    """Reference implementation: thin wrapper over today's runner."""
    id = "pytcad"

    def run(self, request: SolveRequest) -> None:
        from gui.services import solver_runner
        solver_runner.run_job(request.job_json_path,
                              request.out_npz_path)


_BACKENDS = {"pytcad": PytcadBackend}


def _register_devsim():
    try:
        from .devsim_backend import DevsimBackend
    except ImportError:
        return
    _BACKENDS["devsim"] = DevsimBackend


_register_devsim()


def get_backend(backend_id: str) -> SolverBackend:
    try:
        return _BACKENDS[backend_id]()
    except KeyError:
        raise KeyError(
            f"unknown solver backend '{backend_id}' (available: "
            f"{', '.join(sorted(_BACKENDS))})") from None


def backend_ids():
    return sorted(_BACKENDS)
