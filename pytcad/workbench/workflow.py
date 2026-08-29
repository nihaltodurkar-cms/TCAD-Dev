"""M10 slice: a Silvaco/Sentaurus-flavoured deck front end.

A deck is plain text:  KEY = value lines plus a TEMPLATE statement,
translated into a DomainDevice via the Device Builder templates -- a
thin front door, never a second simulation path.

    go
    template nmos
    lsd_cm = 3e-5
    tox_cm = 8e-7
    end
"""
from dataclasses import dataclass, field

from .core.templates import get_template


@dataclass
class DeckRun:
    """Everything a deck can express: the template-built device plus the
    run configuration statements (bias/sweep).  `sweep` mirrors the
    SweepSpec vocabulary so it arms the GUI's existing sweep machinery
    verbatim."""
    template_id: str = ""
    device: object = None
    bias: dict = field(default_factory=dict)
    sweep: dict = None


def _parse_sweep_args(args):
    """'start=0 stop=0.5 step=0.1' -> dict; raises ValueError on junk."""
    out = {"contact": args[0]}
    for arg in args[1:]:
        key, sep, val = arg.partition("=")
        if not sep:
            raise ValueError(f"sweep argument {arg!r} needs KEY=value")
        out[key.strip()] = float(val.strip())
    missing = {"start", "stop", "step"} - set(out)
    if missing:
        raise ValueError(f"sweep statement missing {sorted(missing)}")
    return out


def run_deck_full(text):
    """Parse `text`, build the device, and validate every contact name
    against it.  Returns a DeckRun.  Raises ValueError with a
    line-numbered message on any problem (device-build errors included,
    attributed to the TEMPLATE line)."""
    from .core.device import DomainDevice

    run = DeckRun()
    bias_lines = []          # (lineno, contact, value)
    sweep_line = None        # (lineno, args)
    problems = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        low = line.lower()
        if low == "go":
            continue
        if low == "end":
            break
        parts = line.split(None, 1)
        head = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""
        if head == "template":
            if run.template_id and not problems:
                problems.append((lineno, "duplicate TEMPLATE statement"))
            run.template_id = rest.strip() or None
            continue
        if "=" in line and head not in ("bias", "sweep"):
            key, _, val = line.partition("=")
            try:
                # plain parameter lines carry no prefix keyword
                values = getattr(run, "_values", None)
                if values is None:
                    values = {}
                    setattr(run, "_values", values)
                values[key.strip()] = float(val.strip())
            except ValueError:
                problems.append(
                    (lineno, f"'{key.strip()}' is not a number"))
            continue
        if head == "bias":
            bits = rest.replace("=", " ").split()
            if len(bits) != 2:
                problems.append((lineno, "BIAS needs CONTACT = VALUE"))
            else:
                try:
                    bias_lines.append((lineno, bits[0], float(bits[1])))
                except ValueError:
                    problems.append(
                        (lineno, "BIAS voltage is not a number"))
            continue
        if head == "sweep":
            args = rest.split()
            try:
                sweep_line = (lineno, _parse_sweep_args(args))
            except ValueError as exc:
                problems.append((lineno, str(exc)))
            continue
        problems.append((lineno, f"unrecognised statement: {raw!r}"))

    values = getattr(run, "_values", {})
    if run.template_id is None:
        problems.append((0, "missing TEMPLATE statement"))
        raise ValueError("deck errors: " + "; ".join(
            f"line {n}: {msg}" for n, msg in problems))

    try:
        run.device = get_template(run.template_id).build(values)
    except KeyError as exc:
        problems.append((1, f"unknown template {run.template_id!r} "
                            f"({exc})"))
    except ValueError as exc:
        problems.append((1, str(exc)))
    if problems:
        raise ValueError("deck errors: " + "; ".join(
            f"line {n}: {msg}" for n, msg in problems))

    names = [c.name for c in run.device.contacts]
    for lineno, contact, v in bias_lines:
        if contact not in names:
            problems.append((lineno, f"unknown contact {contact!r} "
                                     f"(have: {', '.join(names)})"))
        else:
            run.bias[contact] = v
    if sweep_line is not None:
        lineno, sw = sweep_line
        if sw["contact"] not in names:
            problems.append((lineno, f"unknown contact {sw['contact']!r} "
                                     f"(have: {', '.join(names)})"))
        else:
            step = sw["step"]
            if step == 0 or (sw["stop"] - sw["start"]) * step < 0:
                problems.append((lineno, "sweep must move from start "
                                         "toward stop with nonzero step"))
            else:
                run.sweep = sw
    if problems:
        raise ValueError("deck errors: " + "; ".join(
            f"line {n}: {msg}" for n, msg in problems))
    return run


def run_deck(text):
    """Parse `text`, return (template_id, DomainDevice).  Raises
    ValueError with a line-numbered message on any problem."""
    template_id = None
    values = {}
    problems = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        low = line.lower()
        if low == "go":
            continue
        if low == "end":
            break
        if low.startswith("template"):
            if template_id is not None and problems == []:
                problems.append((lineno, "duplicate TEMPLATE statement"))
            parts = line.split(None, 1)
            template_id = parts[1].strip() if len(parts) > 1 else None
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            try:
                values[key.strip()] = float(val.strip())
            except ValueError:
                problems.append(
                    (lineno, f"'{key.strip()}' is not a number"))
        else:
            problems.append((lineno, f"unrecognised statement: {raw!r}"))
    if template_id is None:
        problems.append((0, "missing TEMPLATE statement"))
    if problems:
        raise ValueError("deck errors: " + "; ".join(
            f"line {n}: {msg}" for n, msg in problems))
    device = get_template(template_id).build(values)
    return template_id, device
