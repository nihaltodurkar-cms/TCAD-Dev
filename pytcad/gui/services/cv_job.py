"""The C-V job (gui.services.moscap_runner's input), Qt-free.

Moved out of CVController (NATIVE-DESKTOP-PLAN.md 17.11, P3-S4) so the
QML controller and the native app (through the backend's `cv.job_text`)
build the same job file, byte for byte.
"""
import json
import math


def cv_params(nsub_cm3, tox_nm, vstart, vstop, vstep):
    """The job's parameters, as CVController.runCV has always built them
    (a zero step falls back to 0.05 V)."""
    return {
        "nsub_cm3": float(nsub_cm3),
        "tox_nm": float(tox_nm),
        "vstart": float(vstart),
        "vstop": float(vstop),
        "vstep": abs(float(vstep)) or 0.05,
    }


def validate(params):
    """Refuse, naming the field, what moscap_runner cannot run: a
    non-finite value, a non-positive oxide, zero doping, or a gate ramp
    that does not go up (an empty sweep)."""
    for key in ("nsub_cm3", "tox_nm", "vstart", "vstop", "vstep"):
        if not math.isfinite(params[key]):
            raise ValueError(f"C-V {key} must be finite, got {params[key]!r}")
    if params["tox_nm"] <= 0.0:
        raise ValueError(f"C-V tox_nm must be > 0, got {params['tox_nm']}")
    if params["nsub_cm3"] == 0.0:
        raise ValueError("C-V nsub_cm3 must be nonzero (negative for p-type)")
    if params["vstop"] <= params["vstart"]:
        raise ValueError(f"C-V vstop ({params['vstop']}) must be greater than vstart ({params['vstart']})")


def job_text(params):
    """The job file's text: what json.dump writes, as CVController's job
    always wrote it."""
    return json.dumps(params)


class CVJob:
    """Adapts the parameters to JobRunner.start()'s `to_json(path)` contract."""

    def __init__(self, params):
        self.params = dict(params)

    def to_json(self, path):
        with open(path, "w") as fh:
            json.dump(self.params, fh)
