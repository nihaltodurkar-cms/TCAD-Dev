"""M30 Phase 12 GUI test fixture: a local `ssh` stand-in that always
fails, simulating a remote worker that has dropped -- see
fake_ssh.py's docstring for the general approach.
"""
import sys

if __name__ == "__main__":
    sys.exit(1)
