"""M6 adapters: process checkpoints as DomainDevices.

A 1D checkpoint (x, net_doping, ntotal) maps losslessly onto the
IMPORTED shape of DomainDevice -- explicit axes plus array doping --
which validates and runs through the standard spec_from_domain chain
like any other device.  Per-region implants live in process_runner as a
composition mask over the existing core function; nothing numerical
changes.
"""
import numpy as np

from ..core.device import DomainDevice


def domain_from_process_state(x, net_doping, ntotal=None,
                              name="Process checkpoint"):
    dev = DomainDevice(
        id="process_ckpt", name=name,
        dimensionality=1,
        axes={"x": np.asarray(x, dtype=float).tolist()},
        explicit_doping=np.asarray(net_doping, dtype=float).tolist(),
        ntotal=(np.asarray(ntotal, dtype=float).tolist()
                if ntotal is not None else None),
    )
    dev.validate()
    return dev


def domain_from_process_store(store, step_id=None):
    """The selected (or given) checkpoint as a validated DomainDevice."""
    sid = step_id or getattr(store, "selected_step_id", None)
    state = store.state_for(sid)
    return domain_from_process_state(
        state["x"], state["net_doping"], state.get("ntotal"),
        name=f"checkpoint {sid}")
