#!/usr/bin/env python3
"""
ExecStop for cs2vibe-ida-session.service: close every database before the server is signalled.

Hex-Rays' server answers SIGTERM by releasing its leases and exiting at once, while each
Nexus worker packs its .i64 only afterwards (a lease grace of 20 s, then the pack). The
unit's KillMode=mixed then kills whatever is left as soon as the server is gone - so a
worker still packing is cut off mid-write. That is how 14191's libserver.so.i64 became
a file IDA cannot open ("Database initialization failed with error 4") when the CSS
deploy paused the session at 06:18:45, and the deploy then failed on it.

This asks the running server to close_database each instance - the call that "waits for
the IDB to shut down" - and then waits until no worker of this unit is left, so the
SIGTERM that follows has nothing to cut off. A server that is not listening (still
opening, or already gone) is left to the normal stop: an open that is interrupted has
not rewritten the .i64.

  uv run python ida_session_stop.py [--port 13337] [--timeout 540]
"""

import argparse
import asyncio
import os
import sys
import time

UNIT = "cs2vibe-ida-session.service"


def unit_workers():
    """PIDs of Nexus/idalib workers that belong to this unit's cgroup."""
    pids = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cgroup", encoding="utf-8") as handle:
                if UNIT not in handle.read():
                    continue
            with open(f"/proc/{entry}/cmdline", "rb") as handle:
                cmdline = handle.read().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if "ida-nexus worker" in cmdline or "idalib_server" in cmdline:
            pids.append(int(entry))
    return pids


async def close_all(host, port, timeout):
    from ida_mcp_session import _open_raw_ida_mcp_session, _tool_result_payload
    closed = []
    async with _open_raw_ida_mcp_session(host, port, 5.0, float(timeout)) as session:
        listed = await session.call_tool(name="list_databases", arguments={})
        instances = (_tool_result_payload(listed) or {}).get("instances") or []
        for instance in instances:
            instance_id = instance.get("instance_id")
            if not instance_id:
                continue
            result = await session.call_tool(name="close_database", arguments={"instance_id": instance_id})
            closed.append((instance_id, not getattr(result, "isError", False)))
    return closed


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=13337)
    parser.add_argument("--timeout", type=int, default=540, help="seconds for closing and the workers to exit")
    args = parser.parse_args()

    deadline = time.monotonic() + args.timeout
    try:
        closed = asyncio.run(asyncio.wait_for(close_all(args.host, args.port, args.timeout), args.timeout))
        for instance_id, ok in closed:
            print(f"[ida-session stop] close_database {instance_id}: {'saved and closed' if ok else 'FAILED'}", flush=True)
    except Exception as error:  # not listening yet / already gone: nothing to close through it
        print(f"[ida-session stop] server not reachable ({type(error).__name__}); leaving it to SIGTERM", flush=True)
    while unit_workers() and time.monotonic() < deadline:
        time.sleep(1)
    left = unit_workers()
    if left:
        print(f"[ida-session stop] workers still running after {args.timeout} s: {left}", flush=True)
    else:
        print("[ida-session stop] every database is packed and closed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
