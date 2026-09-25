"""M30 Phase 12 GUI test fixture: a local stand-in for the `ssh`
binary.

Strips the same flags RemoteJobRunner/SSHTransport pass
(-p/-i/-o KEY=VAL), then just runs the remote command STRING locally
via the shell -- "a second local process pretending to be remote over
loopback," the plan doc's own suggested test strategy, re-used here at
the GUI/QProcess layer instead of the library-level Transport layer.
No real network or sshd involved.

Usage: python fake_ssh.py [-p PORT] [-o K=V]... [-i FILE] TARGET COMMAND
"""
import os
import subprocess
import sys


def main(argv):
    i = 0
    while i < len(argv):
        if argv[i] in ("-p", "-i"):
            i += 2
        elif argv[i] == "-o":
            i += 2
        else:
            break
    # argv[i] is TARGET (ignored -- there is no real remote host),
    # argv[i + 1] is the command string to execute "remotely."
    command = argv[i + 1]
    # The pretend remote is a POSIX host, but the local shell may be
    # cmd.exe, whose `mkdir` takes "-p" as a directory NAME (it left a
    # stray "-p" folder in the project and failed on every later run).
    # Do what POSIX `mkdir -p` does, portably. The path is taken
    # verbatim: RemoteJobRunner sends exactly one, and a Windows path's
    # backslashes must not be read as shell escapes.
    if command.startswith("mkdir -p "):
        os.makedirs(command[len("mkdir -p "):].strip().strip("'\""),
                    exist_ok=True)
        return 0
    return subprocess.run(command, shell=True).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
