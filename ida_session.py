#!/usr/bin/env python3
"""Start the editor's ida-pro-mcp server (idalib-mcp on 13337) on the newest analysed build.

Run by systemd/cs2vibe-ida-session.service so the IDA tools in the editor are always
there. The binary is the newest bin/<VER>/server/libserver.so that already has a
.i64 next to it: a build with no database would first be auto-analysed from
scratch, which takes as long as a run and is the run's job, not the editor's.
Other binaries (server.dll, engine, client) are opened on demand through the
supervisor's idalib_open tool, one worker each.

The run scripts stop this service while they analyse and start it again on exit,
so it never holds a database a run needs; starting it then also moves it on to the
build that run just produced.

    uv run python ida_session.py            # newest analysed build
    uv run python ida_session.py -print     # only say which binary it would open
    uv run python ida_session.py bin/14185/server/libserver.so
"""

import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
PORT = os.environ.get("CS2VIBE_SESSION_MCP_PORT", "13337")


def version_key(name):
    m = re.match(r"^(\d+)([a-z]*)$", name)
    return (int(m.group(1)), m.group(2)) if m else (-1, name)


def newest_analysed_binary(bin_root=REPO / "bin"):
    """bin/<VER>/server/libserver.so for the newest VER whose .i64 exists, or None."""
    if not bin_root.is_dir():
        return None
    for ver in sorted((p.name for p in bin_root.iterdir() if p.is_dir()), key=version_key, reverse=True):
        binary = bin_root / ver / "server" / "libserver.so"
        if binary.is_file() and binary.with_name(binary.name + ".i64").is_file():
            return binary
    return None


def main(argv):
    only_print = "-print" in argv
    args = [a for a in argv if a != "-print"]
    binary = Path(args[0]) if args else newest_analysed_binary()
    if binary is None:
        print("no bin/<VER>/server/libserver.so with a .i64 yet; nothing to open", file=sys.stderr)
        return 1
    binary = binary if binary.is_absolute() else REPO / binary
    if only_print:
        print(binary.relative_to(REPO))
        return 0
    cmd = ["idalib-mcp", "--unsafe", "--host", "127.0.0.1", "--port", PORT, str(binary.relative_to(REPO))]
    print(" ".join(cmd), flush=True)
    os.chdir(REPO)
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
