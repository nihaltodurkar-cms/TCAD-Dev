"""Family and comparison jobs, Qt-free (NATIVE-DESKTOP-PLAN.md 17.14, P3-S6).

Moved out of FamilySweepController (the stepped values, each curve's spec,
the labels and the refusals) and AppController.runModelComparison (the
models-off spec) so the QML controllers and the native app (through the
backend's family.jobs / comparison.job) build the same jobs with the same
messages. Refusals are RunConfigError(title, detail), QML's titles.
"""
import copy

from .run_config import RunConfigError

COMPARISON_LABEL = "all models off"


def family_values(start, stop, step):
    """The stepped values, as FamilySweepController.configureFamily has
    always computed them. A single value (start == stop, or step 0) is a
    one-curve family; a step that moves AWAY from stop is refused (the old
    code silently produced a one-curve "family" for that typo)."""
    if step != 0 and (stop - start) * step < 0:
        raise RunConfigError("Invalid family configuration",
                             f"step {step:g} does not move from start {start:g} "
                             f"toward stop {stop:g}")
    if step == 0:
        return [float(start)]
    span = abs(stop - start)
    n = int(round(span / abs(step)))
    if abs(span - n * abs(step)) < 1e-9:
        n += 1
    else:
        n = int(span / abs(step)) + 1
    direction = 1.0 if stop >= start else -1.0
    return [start + i * abs(step) * direction for i in range(max(n, 1))]


def family_label(stepped, value):
    return f"{stepped}={value:g} V"


def family_specs(base, stepped, values, swept, start, stop, step):
    """[(value, spec)]: `base` re-solved as a sweep of `swept` at each
    stepped value, as FamilySweepController.runFamily builds them. Refuses,
    with runFamily's titles, a contact the device lacks and an invalid
    sweep. `base` is not modified."""
    from .device_spec import SweepSpec
    if base is None:
        raise RunConfigError("Nothing to sweep",
                             "Run the device once first; every family curve re-solves "
                             "that exact device.")
    names = [c.name for c in base.contacts]
    for contact in (stepped, swept):
        if contact not in names:
            raise RunConfigError("Family cannot run",
                                 f"Contact {contact!r} is not registered on this "
                                 f"device (have: {', '.join(names)}).")
    try:
        SweepSpec(contact=swept, start=start, stop=stop, step=step).validate(names)
    except ValueError as exc:
        raise RunConfigError("Invalid family sweep", str(exc)) from None
    out = []
    for v in values:
        spec = copy.deepcopy(base)
        spec.sweep = SweepSpec(contact=swept, start=start, stop=stop, step=step)
        spec.bias = dict(base.bias or {})
        spec.bias[stepped] = v
        out.append((v, spec))
    return out


def comparison_spec(base):
    """`base` re-solved with EVERY catalog model disabled, as
    AppController.runModelComparison builds it (the spec reused verbatim,
    only `models` changes). `base` is not modified."""
    from workbench.core.catalog import ModelCatalog
    if base is None:
        raise RunConfigError("Nothing to compare",
                             "Run the device once; the comparison re-solves that "
                             "exact device with every model off.")
    spec_off = copy.deepcopy(base)
    spec_off.sweep = copy.deepcopy(base.sweep)
    spec_off.models = {key: False for key in ModelCatalog.list()}
    spec_off.bias = dict(base.bias or {}) if base.bias else None
    return spec_off
