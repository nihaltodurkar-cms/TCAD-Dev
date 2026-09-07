"""M30 Phase 10: parameter constraints for splits and calibration.

A small, deliberately narrow constraint vocabulary -- one comparison
between a parameter and either another parameter or a numeric literal
(e.g. "lg_cm < width_cm", "tox_cm >= 1e-7") -- not a general expression
language. Matches this repo's consistent "simple, stated, bounded
scope" pattern (the same spirit as Phase 2's "simple Nelder-Mead"
scoping note): a row/trial that needs a richer constraint than this
covers is out of scope for this phase, not silently mishandled.
"""
import operator
import re

_OPS = {
    "<=": operator.le, ">=": operator.ge, "==": operator.eq,
    "!=": operator.ne, "<": operator.lt, ">": operator.gt,
}
# Longer operators (<=, >=, ==, !=) must be tried before their
# single-character prefixes (<, >) -- the dict above is iterated in
# that order for matching, not alphabetically.
_EXPR_RE = re.compile(
    r"^\s*(\w+)\s*(<=|>=|==|!=|<|>)\s*"
    r"(\w+|[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*$")


class Constraint:
    """One parsed 'LHS OP RHS' expression.  RHS is either another
    parameter name or a numeric literal, resolved at check() time."""

    def __init__(self, expr):
        self.expr = expr
        m = _EXPR_RE.match(expr)
        if not m:
            raise ValueError(
                f"unsupported constraint expression: {expr!r} (expected "
                f"'PARAM OP PARAM' or 'PARAM OP NUMBER', OP one of "
                f"{sorted(_OPS)})")
        self.lhs, self.op_symbol, self.rhs = m.groups()
        self._op = _OPS[self.op_symbol]
        try:
            self._rhs_value = float(self.rhs)
            self._rhs_is_param = False
        except ValueError:
            self._rhs_value = None
            self._rhs_is_param = True

    def check(self, params):
        """True if `params` (a dict of parameter name -> value)
        satisfies this constraint.  Raises KeyError naming the missing
        parameter if either side references one `params` doesn't have
        -- a constraint on an unknown parameter is a configuration
        error, not a silently-passing no-op."""
        if self.lhs not in params:
            raise KeyError(
                f"constraint {self.expr!r} references unknown parameter "
                f"{self.lhs!r}")
        rhs_value = self._rhs_value
        if self._rhs_is_param:
            if self.rhs not in params:
                raise KeyError(
                    f"constraint {self.expr!r} references unknown "
                    f"parameter {self.rhs!r}")
            rhs_value = params[self.rhs]
        return self._op(params[self.lhs], rhs_value)

    def __repr__(self):
        return f"Constraint({self.expr!r})"


def parse_constraints(exprs):
    """`exprs`: an iterable of constraint-expression strings.  Returns
    a list of Constraint objects, raising ValueError with the offending
    expression on the first unparseable one."""
    return [Constraint(e) if isinstance(e, str) else e for e in exprs]


def first_violation(params, constraints):
    """The expression string of the first constraint `params` fails,
    or None if all pass.  `constraints` may be raw strings or already-
    parsed Constraint objects."""
    for c in parse_constraints(constraints):
        if not c.check(params):
            return c.expr
    return None
