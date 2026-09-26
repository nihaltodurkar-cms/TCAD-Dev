"""A fake solver child for gui/tests/test_progress_channel.py (P3-S1):
`python -m gui.tests.fixtures.chunked_writer <job.json> <out.npz>`.

It writes the lines a real solver_runner writes, but each split across
separate, flushed, delayed writes -- mid-marker, mid-number, mid-JSON and
in the middle of a UTF-8 character -- and ends with a RESULT_PATH line
that has NO newline. An unbuffered child's pipe delivers exactly such
pieces; the runner must still see whole lines.
"""
import sys
import time

import numpy as np


def _pieces(*chunks):
    for c in chunks:
        sys.stdout.buffer.write(c)
        sys.stdout.buffer.flush()
        time.sleep(0.08)


def main(argv):
    out = argv[2]
    _pieces(b"PYTCAD_STAGE=equil", b"ibrium\n")
    _pieces(b"    eq it  1  |dpsi|=1.", b"25e-02\n")
    _pieces(b'PYTCAD_PROGRESS {"v":1,"event":"stage",', b'"t":0.1,"stage":"equilibrium"}\n')
    micro = "µm ✓".encode("utf-8")          # "µm ✓": multi-byte characters
    _pieces(b"note: " + micro[:1], micro[1:] + b"\n")  # split inside the first one
    np.savez(out, marker=np.array(1))
    _pieces(b"RESULT_PATH=", out.encode("utf-8"))     # no newline: the tail
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
