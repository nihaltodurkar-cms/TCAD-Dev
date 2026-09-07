"""M30 Phase 7: RunRecord provenance diff.

A small, Qt-free helper so the GUI's Run Comparison view and any future
headless caller (a script, a CLI report) share ONE diff implementation
-- never two competing "what changed between these runs" algorithms.
Pure function over gui.services.solver_backend.RunRecord objects; the
comparison view itself (StudyController.compareRows) is the only
current caller.
"""

# created_utc/trace/continuation_records are deliberately excluded:
# the first always differs trivially between any two runs (a
# timestamp), the latter two are per-run Newton history, not
# configuration provenance -- comparing them would flag every pair of
# runs as "differing" on fields that carry no configuration meaning.
_COMPARE_FIELDS = ("backend", "dimensionality", "material", "T", "models",
                   "numerics", "sweep", "transient", "schema_version")


def provenance_diff(records, labels=None):
    """`records`: a list of RunRecord (or None for a run with no
    recorded provenance -- pre-v2 result files). Returns a list of
    {field, values, labels, differs} rows, one per compared field.
    `models`/`numerics`/`sweep`/`transient` compare as whole dicts (any
    single differing key marks the whole field 'differs'), matching how
    the Physics Lab panel already treats model_config as one unit
    rather than diffing individual model flags separately."""
    labels = list(labels) if labels is not None else \
        [f"run {i}" for i in range(len(records))]
    rows = []
    for field in _COMPARE_FIELDS:
        values = [getattr(r, field, None) if r is not None else None
                 for r in records]
        differs = any(v != values[0] for v in values[1:])
        rows.append({"field": field, "values": values, "labels": labels,
                     "differs": differs})
    return rows
