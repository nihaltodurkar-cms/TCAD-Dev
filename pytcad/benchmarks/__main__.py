"""`python -m benchmarks` -- run the suite and print the dashboard.

    python -m benchmarks                     # quick size, all cases
    python -m benchmarks --size full         # the configuration to quote
    python -m benchmarks --case B4 B7        # just these
    python -m benchmarks --json out.json     # machine-readable too

Run it from the project root (pytcad/), the same directory the test
suite runs from.
"""
import argparse
import json
import sys

from .harness import run_all, environment, to_dict
from .dashboard import render_markdown


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m benchmarks")
    p.add_argument("--size", choices=("quick", "full"), default="quick",
                   help="quick is CI-sized; full is what a published "
                        "number should come from")
    p.add_argument("--case", nargs="+", metavar="NAME",
                   help="case names (B1..B7); default all")
    p.add_argument("--repeats", type=int, default=1,
                   help="runs per case; the best wall time is reported "
                        "and the spread with it")
    p.add_argument("--json", metavar="PATH", help="also write raw results here")
    p.add_argument("--out", metavar="PATH", help="write markdown here "
                                                 "instead of stdout")
    a = p.parse_args(argv)

    env = environment()
    rows = run_all(size=a.size, repeats=a.repeats, only=a.case)
    md = render_markdown(rows, env)

    if a.out:
        with open(a.out, "w") as fh:
            fh.write(md + "\n")
        print(f"wrote {a.out}")
    else:
        print(md)

    if a.json:
        with open(a.json, "w") as fh:
            json.dump(to_dict(rows, env), fh, indent=2)
        print(f"wrote {a.json}")

    # A failed case is a non-zero exit so CI notices; a SKIPPED case is
    # not -- an absent optional dependency is a fact about the machine,
    # not a regression.
    return 1 if any(r.error for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
