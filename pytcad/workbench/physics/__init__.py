"""Physics modules beyond the five solver-registered models (M8).

Each module here lands with a published-value benchmark in
tests/test_model_benchmarks.py BEFORE it is coupled to any solver or
registered as a selectable catalog flag (the M8 gate).
"""
from . import impact_ionization

__all__ = ["impact_ionization"]
