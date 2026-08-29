"""GUI runtime validation layer (GUI-IMPROVEMENT-PLAN Phase 4).

Monitors the GUI state machine for inconsistencies that are difficult to
catch with unit tests alone.  Reports problems via signals so the UI can
show visual indicators and tests can assert correctness.

Design principles:
- Only OBSERVES state (never mutates it) -- the controllers own state.
- Event-driven (see onStateChange/checkValue below), not polled -- no
  timer, so there's no per-tick cost and no delay between a state
  change and it being reported.
- Reports problems via signals so QML can react in real time.
- Every check is idempotent and reversible (safe to run multiple times).
"""
import math
from PySide6.QtCore import QObject, Property, Signal, Slot


class GuiStateValidator(QObject):
    """Validates GUI state consistency at runtime.

    Both checks below are event-driven, not polled: there is no
    periodic timer here. An earlier version ran a 500ms QTimer that
    called three "checks" on every tick, but two of the three
    (state-transition and result-consistency scanning) were empty
    placeholder bodies that never actually checked anything --
    exactly the kind of fake/no-op implementation this codebase's own
    conventions rule out. The one check that already did real work
    (stale-result detection) is event-driven via onStateChange(), and
    input-value checking is event-driven via checkValue() (called
    directly from ValidatedTextField.qml on every edit) -- so the
    timer was pure overhead wired to nothing.

    Monitors for:
    - Stale results (structure edited after solve) -- via onStateChange()
    - Invalid input values (NaN, inf, empty required fields) -- via checkValue()
    """

    # Emitted when a validation problem is detected
    stateProblem = Signal(str, str)  # category, message

    # Emitted when validation state changes (for QML binding)
    validationStateChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._problems = []  # List of (category, message) tuples
        # Track last known state for change detection
        self._last_has_result = False
        self._last_has_store = False
        self._last_is_dirty = False

    def _add_problem(self, category, message):
        """Add a validation problem if not already present."""
        # Avoid duplicate problems
        for cat, msg in self._problems:
            if cat == category and msg == message:
                return
        self._problems.append((category, message))
        self.stateProblem.emit(category, message)
        self.validationStateChanged.emit()

    def _clear_problem(self, category):
        """Remove all problems in a category."""
        self._problems = [(cat, msg) for cat, msg in self._problems
                          if cat != category]
        self.validationStateChanged.emit()

    def _clear_all_problems(self):
        """Clear all validation problems."""
        if self._problems:
            self._problems.clear()
            self.validationStateChanged.emit()

    @Property(int, notify=validationStateChanged)
    def problemCount(self):
        """Number of active validation problems."""
        return len(self._problems)

    @Property("QVariant", notify=validationStateChanged)
    def problems(self):
        """List of active validation problems as [{category, message}]."""
        return [{"category": cat, "message": msg}
                for cat, msg in self._problems]

    @Slot(str, "QVariant")
    def checkValue(self, field_name, value):
        """Check a single input value and report problems."""
        self._check_single_value(field_name, value)

    def _check_single_value(self, field_name, value):
        """Check a single input value for validity."""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not math.isfinite(value):
                self._add_problem(
                    "invalid_input",
                    f"Field '{field_name}' has non-finite value: {value}"
                )
                return
        elif isinstance(value, str):
            if value.strip() == "":
                self._add_problem(
                    "empty_input",
                    f"Required field '{field_name}' is empty"
                )

    @Slot()
    def clearProblems(self):
        """Clear all validation problems."""
        self._clear_all_problems()

    @Slot(str)
    def clearProblem(self, category):
        """Clear problems in a specific category."""
        self._clear_problem(category)

    # -- State change observers (called by AppController) ----------------

    @Slot(bool, bool, bool)
    def onStateChange(self, has_result, has_store, is_dirty):
        """Called by AppController when major state changes occur.

        Args:
            has_result: Whether a result is currently loaded
            has_store: Whether a result store exists
            is_dirty: Whether the project has unsaved changes

        has_store is accepted for interface symmetry with
        AppController's own (hasResult, has_store, isDirty) state, but
        it carries no independent information here: AppController.hasResult
        is defined as `self._store is not None and ...`, so has_result=True
        implies has_store=True by construction -- no reachable state ever
        has has_result=True and has_store=False. An earlier version of
        this method tried to detect that combination as both a
        "stale result" precondition and a separate "inconsistent state"
        problem; both checks were dead code. Only the achievable check
        (a result exists and the project has since been dirtied) remains.
        """
        if has_result and is_dirty:
            self._add_problem(
                "stale_result",
                "Result may be stale: structure edited after solve"
            )
        else:
            self._clear_problem("stale_result")

        # Update last known state
        self._last_has_result = has_result
        self._last_has_store = has_store
        self._last_is_dirty = is_dirty

