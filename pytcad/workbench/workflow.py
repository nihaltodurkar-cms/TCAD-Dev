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
from .core.templates import get_template


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
