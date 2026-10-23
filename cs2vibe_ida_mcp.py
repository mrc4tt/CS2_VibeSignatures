#!/usr/bin/env python3
"""Hex-Rays' official IDA MCP server, carrying this repo's IDA tools as well.

The server is ``ida-mcp`` (HexRaysSA/ida-mcp on IDA Nexus, IDA 9.4+): its six tools
(open_database, execute_python, reference, list_databases, save_database,
close_database) are served unchanged. On top of them it lists every tool of the
mrc4tt/ida-pro-mcp fork the pipeline and the agent skills were written against
(py_eval, find_bytes, decompile, xrefs_to, make_signature, ...), and runs each one
inside the Nexus worker that holds the database, through the fork's own dispatcher.
So a call returns exactly what idalib-mcp returned, byte for byte, while the
database itself is opened, leased, saved and closed by Nexus.

Command line is idalib-mcp's, so a launcher only swaps the executable:

    uv run python cs2vibe_ida_mcp.py --unsafe --host 127.0.0.1 --port 13337 bin/<VER>/server/libserver.so

Unlike plain ``ida-mcp http``, the port opens only once the database is open and
its auto-analysis has finished, which is the readiness signal the run scripts and
``ida_analyze_bin.start_idalib_mcp`` wait for. ``--unsafe`` is accepted and ignored:
execute_python is always available here, so py_eval is too.

Differences from idalib-mcp, on purpose:
- the fork's idalib_* / list_instances / select_instance / open_file tools are not
  listed; open_database / list_databases / close_database replace them;
- no output truncation: the fork cut any result over 50 000 characters to a preview
  plus a download URL nothing in this repo ever fetched.
"""

import argparse
import json
import os
import signal
import socket
import time
import sys
import threading
import uuid
from pathlib import Path

from ida_nexus import DatabaseManager
from ida_nexus.errors import RemoteError

import ida_mcp.mcp as hx

# Cold auto-analysis of server.dll / libserver.so takes 20+ minutes; Nexus' default
# open budget is 300 s. Same knob and default as ida_analyze_bin's cold start.
OPEN_TIMEOUT = float(os.environ.get("CS2VIBE_IDA_COLD_TIMEOUT", "3600"))
# One tool call. pipeline_hunt runs whole hunts through a single py_eval.
EXECUTE_TIMEOUT = float(os.environ.get("CS2VIBE_IDA_EXECUTE_TIMEOUT", "7200"))

# Fork tools that manage databases or GUI instances. Nexus owns that now.
HIDDEN_FORK_TOOLS = frozenset(
    {
        "idalib_open",
        "idalib_close",
        "idalib_switch",
        "idalib_unbind",
        "idalib_list",
        "idalib_current",
        "idalib_save",
        "idalib_health",
        "idalib_warmup",
        "list_instances",
        "select_instance",
        "open_file",
    }
)

# Runs inside the Nexus worker. Importing the package registers every fork tool on
# its MCP_SERVER; _mcp_tools_call is the fork's own argument parsing and result
# shaping, minus the HTTP layer's truncation patch.
_WORKER_LIST = """
import json
from ida_pro_mcp.ida_mcp import MCP_SERVER as _cs2vibe_fork
json.dumps(_cs2vibe_fork._mcp_tools_list()["tools"])
"""

_WORKER_CALL = """
import json
from ida_pro_mcp.ida_mcp import MCP_SERVER as _cs2vibe_fork
json.dumps(_cs2vibe_fork._mcp_tools_call({name!r}, json.loads({arguments!r})))
"""


# Nexus waits by stepping auto_make_step() until it returns False and then asks
# auto_is_ok(). On a fresh PE that loop stops with one AU_PROC item still queued,
# so every first open of a windows DLL failed as "Autoanalysis was cancelled" right
# as analysis finished (14192: all ten, from worldrenderer.dll in 8 s to client.dll
# in 2.5 min), and the half-written database then failed the reopen as well.
# The native auto_wait() drains that item; Nexus's own wait then completes.
_FINISH_AUTOANALYSIS = """
import ida_auto
ida_auto.auto_wait()
ida_auto.auto_is_ok()
"""
AUTOANALYSIS_RETRIES = 3


class EagerDatabaseManager(DatabaseManager):
    """Opens the startup database and waits for analysis before the port binds."""

    def ensure_autoanalysis(self, instance_id, *, operation_id=None):
        for attempt in range(AUTOANALYSIS_RETRIES + 1):
            try:
                return super().ensure_autoanalysis(instance_id, operation_id=operation_id)
            except RemoteError as exc:
                if exc.code != "analysis_cancelled" or attempt == AUTOANALYSIS_RETRIES:
                    raise
            print("autoanalysis stopped with work queued; finishing it with auto_wait()", file=sys.stderr, flush=True)
            self.execute_python(_FINISH_AUTOANALYSIS, instance_id, timeout=OPEN_TIMEOUT)
            operation_id = uuid.uuid4().hex

    def __init__(self, *, startup_path=None, **kwargs):
        super().__init__(**kwargs)
        if startup_path:
            print(f"opening {startup_path} (limit {OPEN_TIMEOUT:.0f} s)", file=sys.stderr, flush=True)
            self.open_database(startup_path, set_current=True)
            self.ensure_autoanalysis(None, operation_id=uuid.uuid4().hex)
            print(f"database ready: {startup_path}", file=sys.stderr, flush=True)


class ForkTools:
    """The fork's tool list, read from the worker once, and dispatch into it."""

    def __init__(self):
        self._lock = threading.Lock()
        self._tools = None

    def _execute(self, code):
        manager = hx.DATABASE_MANAGER
        operation_id = uuid.uuid4().hex
        target = manager.resolve_instance_id(None)
        manager.ensure_autoanalysis(target, operation_id=operation_id)
        out = manager.execute_python(code, target, timeout=EXECUTE_TIMEOUT, operation_id=operation_id)
        return json.loads(out["result"])

    def tools(self):
        with self._lock:
            if self._tools is None:
                listed = self._execute(_WORKER_LIST)
                self._tools = {t["name"]: t for t in listed if t["name"] not in HIDDEN_FORK_TOOLS}
            return self._tools

    def call(self, name, arguments):
        code = _WORKER_CALL.format(name=name, arguments=json.dumps(arguments or {}))
        try:
            return self._execute(code)
        except Exception as exc:  # the fork reported errors as isError results too
            return {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}], "isError": True}


def install_fork_tools(fork=None):
    """Add the fork's tools to Hex-Rays' tools/list and route their calls."""
    fork = fork or ForkTools()
    registry = hx.mcp.registry.methods
    original_list = registry["tools/list"]
    original_call = registry["tools/call"]
    own = None

    def own_names():
        nonlocal own
        if own is None:
            own = {t["name"] for t in original_list()["tools"]}
        return own

    def tools_list(cursor=None, _meta=None):
        listed = original_list(cursor, _meta)
        try:
            extra = [t for name, t in fork.tools().items() if name not in own_names()]
        except Exception as exc:
            print(f"fork tool list unavailable: {exc}", file=sys.stderr, flush=True)
            extra = []
        return {**listed, "tools": listed["tools"] + extra}

    def tools_call(name, arguments=None, _meta=None):
        if name not in own_names():
            try:
                known = name in fork.tools()
            except Exception:
                known = False
            if known:
                return fork.call(name, arguments)
        return original_call(name, arguments, _meta)

    registry["tools/list"] = tools_list
    registry["tools/call"] = tools_call
    return fork


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=13337)
    parser.add_argument("--unsafe", action="store_true", help="accepted for idalib-mcp compatibility")
    parser.add_argument("--agent", default=None, help="label shown in `ida-mcp dashboard`")
    parser.add_argument("input_path", nargs="?", type=Path)
    return parser.parse_args(argv)


PORT_WAIT = 120


def wait_for_free_port(host, port, timeout=PORT_WAIT):
    """True once host:port can be bound. The database must not be opened before that:
    serve_http opens it eagerly and binds afterwards, so a taken port (a previous
    instance not yet gone) made the server die WITH the database open - its worker was
    killed mid-pack and 14191's libserver.so.i64 could not be opened again."""
    deadline = time.monotonic() + timeout
    while True:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
            return True
        except OSError:
            if time.monotonic() > deadline:
                return False
            time.sleep(2)
        finally:
            probe.close()


def close_open_databases():
    """Close every database the server holds - close_database waits for the pack."""
    manager = getattr(hx.mcp, "DATABASE_MANAGER", None) if hasattr(hx, "mcp") else None
    manager = manager or getattr(hx, "DATABASE_MANAGER", None)
    if manager is None:
        return
    try:
        instances = (manager.list_databases() or {}).get("instances") or []
    except Exception as exc:
        print(f"could not list databases to close: {exc}", file=sys.stderr, flush=True)
        return
    for instance in instances:
        instance_id = instance.get("instance_id")
        if instance_id:
            try:
                manager.close_database(instance_id)
                print(f"closed database {instance_id} before exiting", file=sys.stderr, flush=True)
            except Exception as exc:
                print(f"could not close database {instance_id}: {exc}", file=sys.stderr, flush=True)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    startup = None
    if args.input_path is not None:
        if not args.input_path.exists():
            raise SystemExit(f"Input file not found: {args.input_path}")
        startup = str(args.input_path.resolve())
    if not wait_for_free_port(args.host, args.port):
        raise SystemExit(f"{args.host}:{args.port} stayed in use for {PORT_WAIT} s; not opening the database")
    install_fork_tools()
    try:
        serve(args, startup)
    except SystemExit:
        raise  # SIGTERM/SIGINT: Hex-Rays' own shutdown path (ExecStop has closed the databases)
    except BaseException:
        # dying of an error with a database open must not leave it half-packed
        close_open_databases()
        raise
    return 0


def serve(args, startup):
    hx.serve_http(
        args.host,
        args.port,
        database_manager_class=EagerDatabaseManager,
        database_manager_kwargs={
            "startup_path": startup,
            "open_timeout": OPEN_TIMEOUT,
            "execute_timeout": EXECUTE_TIMEOUT,
            "idle_timeout": None,
            "worker_cwd": str(Path(__file__).resolve().parent),
        },
        agent=args.agent,
        background=False,
    )


if __name__ == "__main__":
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    sys.exit(main())
