"""M30 Phase 3 acceptance tests: DeckBuild-dialect import filter.

Contract under test (workbench/deckbuild_import.py):
  - `import_deckbuild` translates the documented, bounded DeckBuild-
    subset grammar (module docstring) into our own workflow.py dialect
    and runs it through the real, unmodified `run_deck_full` -- no
    second validator, no second simulation path.
  - Round-trip gate (self-referential, per the plan doc's stated honest
    limitation: no external DeckBuild corpus is available): a deck
    written directly in our own dialect and the "same" deck expressed
    in the supported DeckBuild subset must produce equal DeckRuns.
  - Anything outside the documented subset raises a clear,
    line-numbered error rather than silently mis-translating.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from workbench.deckbuild_import import import_deckbuild
from workbench.workflow import run_deck_full


# ----------------------------------------------------------------------
#  G-ROUNDTRIP: our own decks, through the supported subset, match
#  writing them directly in our own dialect
# ----------------------------------------------------------------------
_NATIVE_DECK = """
go
template nmos
lsd_cm = 3e-5
lg_cm = 6e-5
bias source = 0.0
bias drain = 0.05
bias body = 0.0
sweep gate start=0.0 stop=1.0 step=0.1
end
"""

_DECKBUILD_DECK = """
go atlas
#template nmos
lsd_cm=3e-5
lg_cm=6e-5
electrode name=source voltage=0.0
electrode name=drain voltage=0.05
electrode name=body voltage=0.0
solve name=gate vstep=0.1 vfinal=1.0 vstart=0.0
end
"""


def test_deckbuild_subset_roundtrips_a_native_deck():
    native = run_deck_full(_NATIVE_DECK)
    imported = import_deckbuild(_DECKBUILD_DECK)

    assert imported.template_id == native.template_id
    assert imported.bias == native.bias
    assert imported.sweep == native.sweep
    # same template + same parameter values -> the same built device
    assert imported.device.regions == native.device.regions
    assert imported.device.contacts == native.device.contacts


def test_deckbuild_solve_defaults_vstart_to_prior_electrode_voltage():
    deck = """
    go atlas
    #template mos_capacitor
    na_cm3=-1e16
    electrode name=gate voltage=0.0
    solve name=gate vstep=0.5 vfinal=2.0
    end
    """
    run = import_deckbuild(deck)
    assert run.sweep == {"contact": "gate", "start": 0.0,
                         "stop": 2.0, "step": 0.5}


def test_deckbuild_plain_comment_lines_are_skipped_not_errors():
    deck = """
    go atlas
    # just a note about this run, not a directive
    #template pn_diode
    na_cm3=-1e18
    end
    """
    run = import_deckbuild(deck)
    assert run.template_id == "pn_diode"


# ----------------------------------------------------------------------
#  G-REJECT: unsupported constructs raise a clear, line-numbered error
# ----------------------------------------------------------------------
def test_unsupported_mesh_statement_raises_line_numbered_error():
    deck = """
    go atlas
    #template pn_diode
    mesh nx=50 ny=20
    end
    """
    with pytest.raises(ValueError, match=r"line 4.*unsupported DeckBuild"):
        import_deckbuild(deck)


def test_malformed_electrode_statement_raises():
    deck = """
    go atlas
    #template pn_diode
    electrode name=anode volt=0.1
    end
    """
    with pytest.raises(ValueError, match="unsupported DeckBuild"):
        import_deckbuild(deck)


def test_malformed_solve_statement_raises():
    deck = """
    go atlas
    #template pn_diode
    solve vfinal=1.0 vstep=0.1
    end
    """
    with pytest.raises(ValueError, match="unsupported DeckBuild"):
        import_deckbuild(deck)
