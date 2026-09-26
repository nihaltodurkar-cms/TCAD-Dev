"""A fake solver child for gui/tests/test_progress_channel.py (P3-S1,
decision 7): `python -m gui.tests.fixtures.slow_printer <job> <out>`.

Prints five verbose-style Newton lines 0.25 s apart WITHOUT flushing, as
the frozen core's `verbose` prints do, then the result marker. Through a
pipe, only an unbuffered child (PYTHONUNBUFFERED / -u) delivers them as
they are printed; a buffered one delivers all five at exit.
"""
import sys
import time

import numpy as np


def main(argv):
    for it in range(5):
        print(f"    it {it:2d}  |dpsi|={10.0 ** -it:.3e}")   # no flush, like the core
        time.sleep(0.25)
    np.savez(argv[2], marker=np.array(1))
    print(f"RESULT_PATH={argv[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
