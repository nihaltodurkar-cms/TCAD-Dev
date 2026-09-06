"""M30 Phase 1: SWB-style parameter splits (parameter table x deck =
run matrix).

`expand_splits` is the pure cartesian-product core; `run_split_matrix`
drives a `workbench.workflow.DeckRun` (or any object exposing
`template_id`, `splits`, and the same `_values` base-parameter dict
`run_deck_full` already populates) through the existing template
`.build()` path, one device per row, isolating a bad row rather than
aborting the whole matrix -- solving/sweeping each row is deliberately
OUT of scope this phase (see pytcad/M30-WORKBENCH-PLAN.md section 3).
"""
import itertools
from dataclasses import dataclass
from typing import Optional


@dataclass
class SplitRow:
    params: dict
    device: object
    error: Optional[str]


def expand_splits(base_values, split_spec):
    """Cartesian product of `split_spec` (name -> value sequence)
    overlaid on `base_values`.  With no split_spec, returns the single
    base row unchanged.  Order: itertools.product(*values) over
    split_spec's keys in insertion order -- the LAST key varies
    fastest."""
    if not split_spec:
        return [dict(base_values)]
    keys = list(split_spec)
    rows = []
    for combo in itertools.product(*(split_spec[k] for k in keys)):
        row = dict(base_values)
        row.update(zip(keys, combo))
        rows.append(row)
    return rows


def run_split_matrix(run):
    """Build one device per expanded split row via `run`'s template.
    A row whose parameters the template rejects is recorded with its
    error, not raised -- the rest of the matrix still builds."""
    from .core.templates import get_template

    template = get_template(run.template_id)
    base_values = getattr(run, "_values", {})
    rows = expand_splits(base_values, run.splits or {})

    results = []
    for row in rows:
        try:
            device = template.build(row)
            results.append(SplitRow(row, device, None))
        except (ValueError, KeyError) as exc:
            results.append(SplitRow(row, None, str(exc)))
    return results
