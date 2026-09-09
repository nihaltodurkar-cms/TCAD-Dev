"""M30 Phase 12 GUI test fixture: a local stand-in for the `scp`
binary -- see fake_ssh.py's docstring for why. Strips the "user@host:"
prefix RemoteJobRunner adds to a remote path (there is no real host
here) and does a plain local file copy.

Usage: python fake_scp.py [-P PORT] [-o K=V]... [-i FILE] SRC DST
"""
import shutil
import sys


def _strip_target(path):
    if ":" in path:
        head, tail = path.split(":", 1)
        if "@" in head or head and "/" not in head:
            return tail
    return path


def main(argv):
    i = 0
    while i < len(argv):
        if argv[i] in ("-P", "-i"):
            i += 2
        elif argv[i] == "-o":
            i += 2
        else:
            break
    src, dst = argv[i], argv[i + 1]
    shutil.copy(_strip_target(src), _strip_target(dst))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
