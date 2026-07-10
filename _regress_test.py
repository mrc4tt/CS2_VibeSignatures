import os, asyncio, subprocess, time, sys

LOG = open("_regress.log", "w", buffering=1)


def say(msg):
    LOG.write(msg + "\n")
    LOG.flush()
    os.fsync(LOG.fileno())


import ida_analyze_bin as A

HOST, PORT = "127.0.0.1", 13337
BIN = "bin/14165/server/libserver.so"
BINDIR = "bin/14165/server"
ID0 = BINDIR + "/libserver.so.id0"


def lock_held():
    r = subprocess.run(["fuser", ID0], capture_output=True, text=True)
    return bool(r.stdout.strip())


try:
    say("[1] first start (own process group)")
    proc = A.start_idalib_mcp(BIN, HOST, PORT)
    say("    first start returned: %s (pid=%s)" % (bool(proc), getattr(proc, "pid", None)))
    if not proc:
        say("RESULT: FAIL (first start failed; see /tmp/idalib-mcp-%s.log)" % PORT)
        sys.exit(1)
    child = subprocess.run(["pgrep", "-P", str(proc.pid)], capture_output=True, text=True).stdout.split()
    say("    idalib child pid(s)=%s  lock held while running=%s" % (child, lock_held()))

    say("[2] restart: _kill_process_tree(proc)")
    A._kill_process_tree(proc)
    proc.wait()
    time.sleep(2)
    child_alive = all(os.path.exists("/proc/%s" % c) for c in child) if child else False
    leaked = lock_held()
    say("    idalib child still alive=%s   lock held after kill=%s" % (child_alive, leaked))

    say("[3] second start on SAME db (old crash point)")
    proc2 = A.start_idalib_mcp(BIN, HOST, PORT)
    say("    second start returned: %s" % bool(proc2))
    healthy = asyncio.run(A.check_mcp_health(HOST, PORT)) if proc2 else False
    say("    health check: %s" % healthy)
    if proc2:
        A._kill_process_tree(proc2)
        proc2.wait()

    ok = bool(proc2) and healthy and not leaked and not child_alive
    say("RESULT: %s" % ("PASS" if ok else "FAIL"))
except Exception as e:
    import traceback

    say("EXCEPTION: %r\n%s" % (e, traceback.format_exc()))
    subprocess.run(["pkill", "-9", "-f", "idalib-mcp"])
    say("RESULT: FAIL (exception)")
finally:
    LOG.close()
