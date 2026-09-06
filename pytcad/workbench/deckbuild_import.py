"""M30 Phase 3: DeckBuild-dialect import filter.

Translates a documented, DELIBERATELY BOUNDED subset of Silvaco
DeckBuild/ATLAS statement syntax into our own workbench/workflow.py
deck dialect (TEMPLATE/BIAS/SWEEP/plain KEY=value parameters), then
hands the translated text to the EXISTING run_deck_full -- a pure
text-to-text translator, never a second simulation path, and never a
second validator (all validation stays in run_deck_full).

No external DeckBuild corpus is available to validate this filter
against (see pytcad/M30-WORKBENCH-PLAN.md section 5's honest
limitation); the round-trip gate is therefore SELF-referential -- our
own decks, expressed in this documented subset, must import to the
same DeckRun as writing them directly in our own dialect.

SUPPORTED SUBSET (exhaustive -- anything else raises a clear,
line-numbered error rather than silently mis-translating):

  go atlas                                -> ignored (our dialect's own
                                              'go' plays the same role)
  #template <id>                          -> TEMPLATE <id>.  Real
                                              DeckBuild has no template
                                              concept (device geometry
                                              comes from mesh/region/
                                              electrode statements this
                                              filter does not attempt to
                                              translate); this pragma is
                                              OUR OWN documented
                                              extension standing in for
                                              geometry selection, since
                                              every device in this repo
                                              is template-authored.
  key=value                               -> plain parameter line,
                                              unchanged (identical to
                                              our own dialect).
  electrode name=<contact> voltage=<v>    -> BIAS <contact> = <v>
  solve name=<contact> vstep=<step> vfinal=<stop> [vstart=<start>]
                                           -> SWEEP <contact>
                                              start=<start, or the
                                              contact's own prior
                                              'electrode ... voltage='
                                              if vstart is omitted>
                                              stop=<stop> step=<step>

Explicitly NOT translated: mesh/region statements, material/doping
statements, multi-line continuations, or any DeckBuild syntax beyond
the five forms above -- decades of real DeckBuild grammar exist and
this filter does not attempt to cover it (see the plan doc).
"""
import re

_TEMPLATE_PRAGMA_RE = re.compile(r"#\s*template\s+(\S+)", re.IGNORECASE)
_ELECTRODE_RE = re.compile(
    r"electrode\s+name\s*=\s*(\S+)\s+voltage\s*=\s*([-\d.eE+]+)\s*$")
_SOLVE_RE = re.compile(
    r"solve\s+name\s*=\s*(\S+)\s+vstep\s*=\s*([-\d.eE+]+)\s+"
    r"vfinal\s*=\s*([-\d.eE+]+)(?:\s+vstart\s*=\s*([-\d.eE+]+))?\s*$")

_PARAM_RE = re.compile(r"^[A-Za-z_]\w*\s*=\s*\S.*$")

_SUPPORTED_SUBSET_MSG = (
    "supported subset: 'go atlas', '#template ID', "
    "'electrode name=... voltage=...', "
    "'solve name=... vstep=... vfinal=... [vstart=...]', "
    "and plain KEY=value parameter lines")


def import_deckbuild(text):
    """Translate a DeckBuild-subset deck (see module docstring) into
    our own dialect and run it through the real, unmodified
    run_deck_full.  Raises ValueError with a line-numbered message on
    any construct outside the documented subset."""
    from .workflow import run_deck_full

    translated = []
    bias_values = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if stripped.startswith("#"):
            m = _TEMPLATE_PRAGMA_RE.match(stripped)
            if m:
                translated.append(f"template {m.group(1)}")
            # any other '#...' line is a plain comment -- skipped, not
            # an error, same as our own dialect's inline '#' comments.
            continue

        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        low = line.lower()
        if low in ("go", "go atlas"):
            translated.append("go")
            continue
        if low == "end":
            continue          # our own consolidated 'end' is appended below

        m = _ELECTRODE_RE.match(low)
        if m:
            name, v = m.group(1), float(m.group(2))
            bias_values[name] = v
            translated.append(f"bias {name} = {v}")
            continue

        m = _SOLVE_RE.match(low)
        if m:
            name, step, final, start = m.groups()
            start_v = float(start) if start is not None \
                else bias_values.get(name, 0.0)
            translated.append(
                f"sweep {name} start={start_v} stop={float(final)} "
                f"step={float(step)}")
            continue

        if _PARAM_RE.match(line) and not low.startswith(("electrode", "solve")):
            translated.append(line)
            continue

        raise ValueError(
            f"line {lineno}: unsupported DeckBuild construct: {raw!r} "
            f"({_SUPPORTED_SUBSET_MSG})")

    translated.append("end")
    return run_deck_full("\n".join(translated))
