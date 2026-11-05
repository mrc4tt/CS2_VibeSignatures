"""Split one module's tasks across several IDA instances (CS2VIBE_SHARDS).

IDA analyses one database on one core, and server's ~700 tasks are almost all
deterministic preprocessors at ~1.5 s each, so one binary is the long pole of a run
however many cores the box has. The tasks form a wide DAG (on 14196 server: 201
components, critical path 7 tasks), so K copies of the same warm IDB can each take
a share and finish in about 1/K of the time.

The parent plans, the children run:

- ``plan_shards`` orders the pending tasks topologically (the same dependency
  graph the serial run uses) and assigns them by list scheduling: each task goes to
  the shard where it can start earliest.
- every shard runs its own tasks in that one global order. Before a task it waits
  for each producer in another shard to be marked done (or for that shard to have
  exited); a producer always comes earlier in the global order, so no wait can
  close a cycle.
- a shard does only the free work. A task whose inputs are missing or whose
  preprocessor fails is left alone, and the parent's sweep on the primary IDB -
  the ordinary serial run, with hunter, agents and deferral - picks up whatever
  has no artifact once the shards are done.

The shard IDBs are throwaway copies: the artifacts are what count, and the sweep
replays the IDA names from them onto the primary database.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

SHARD_PLAN_ENV = "CS2VIBE_SHARD_PLAN"
SHARDS_ENV = "CS2VIBE_SHARDS"
SHARD_MIN_TASKS_ENV = "CS2VIBE_SHARD_MIN_TASKS"
DEFAULT_SHARDS = 4
DEFAULT_SHARD_MIN_TASKS = 150
WAIT_POLL_SECONDS = 0.2


def configured_shard_count(environ=None):
    """K from CS2VIBE_SHARDS: 0 or 1 turns sharding off."""
    environ = os.environ if environ is None else environ
    raw = str(environ.get(SHARDS_ENV, DEFAULT_SHARDS)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def configured_min_tasks(environ=None):
    environ = os.environ if environ is None else environ
    raw = str(environ.get(SHARD_MIN_TASKS_ENV, DEFAULT_SHARD_MIN_TASKS)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_SHARD_MIN_TASKS


def plan_shards(order, dependencies, shard_count):
    """Assign *order* (dependency-first task names) to shards.

    *dependencies* maps a task to the tasks it waits for; names outside *order*
    are ignored (their outputs already exist). Unit cost per task: the measured
    spread is narrow (preprocessors), and the occasional slow one only delays
    the tasks that wait on it.

    Returns ``{task: shard index}``.
    """
    wanted = set(order)
    finish = {}
    free = [0] * max(1, shard_count)
    owner = {}
    for name in order:
        ready = max((finish[dep] for dep in dependencies.get(name, ()) if dep in wanted and dep in finish), default=0)
        shard = min(range(len(free)), key=lambda k: (max(free[k], ready), k))
        start = max(free[shard], ready)
        finish[name] = start + 1
        free[shard] = start + 1
        owner[name] = shard
    return owner


def simulated_speedup(order, dependencies, owner):
    """Serial task count over the simulated makespan of *owner* (for the log)."""
    finish = {}
    free = {}
    for name in order:
        shard = owner[name]
        ready = max((finish[dep] for dep in dependencies.get(name, ()) if dep in finish), default=0)
        start = max(free.get(shard, 0), ready)
        finish[name] = start + 1
        free[shard] = start + 1
    makespan = max(finish.values(), default=0)
    return (len(order) / makespan) if makespan else 1.0


def _marker_name(task_name):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", task_name)


def write_plan(path, *, shard, order, dependencies, owner, state_dir, stage=0):
    """The JSON a child reads from CS2VIBE_SHARD_PLAN."""
    mine = [name for name in order if owner[name] == shard]
    payload = {
        "shard": shard,
        "stage": stage,
        "order": mine,
        "deps": {name: sorted(dep for dep in dependencies.get(name, ()) if dep in owner) for name in mine},
        "owner": owner,
        "state_dir": os.fspath(state_dir),
        "parent_pid": os.getpid(),
    }
    Path(path).write_text(json.dumps(payload), encoding="utf-8")


def exit_marker(state_dir, shard):
    return Path(state_dir) / f"exit-{shard}"


class ShardPlan:
    """A child's view: which tasks are its own, and how to wait for the others."""

    def __init__(self, payload):
        self.shard = int(payload["shard"])
        self.stage = int(payload.get("stage", 0))
        self.order = list(payload["order"])
        self.deps = {name: list(deps) for name, deps in payload.get("deps", {}).items()}
        self.owner = dict(payload.get("owner", {}))
        self.state_dir = Path(payload["state_dir"])
        self.parent_pid = payload.get("parent_pid")
        (self.state_dir / "done").mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls, environ=None):
        environ = os.environ if environ is None else environ
        path = environ.get(SHARD_PLAN_ENV)
        if not path:
            return None
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def _done_path(self, name):
        return self.state_dir / "done" / _marker_name(name)

    def mark_done(self, name):
        self._done_path(name).touch()

    def is_settled(self, name):
        if self._done_path(name).exists():
            return True
        owner = self.owner.get(name)
        if owner is None:
            return True
        return exit_marker(self.state_dir, owner).exists()

    def _parent_gone(self):
        return bool(self.parent_pid) and os.getppid() != self.parent_pid

    def wait_for(self, name, sleep=time.sleep):
        """Block until every producer of *name* in another shard is settled."""
        pending = [dep for dep in self.deps.get(name, ()) if self.owner.get(dep) != self.shard]
        reported = False
        while pending:
            pending = [dep for dep in pending if not self.is_settled(dep)]
            if not pending or self._parent_gone():
                return
            if not reported:
                print(f"  Waiting: {name} (for {', '.join(pending)})", flush=True)
                reported = True
            sleep(WAIT_POLL_SECONDS)

    def iterate(self, items, name_of):
        """Yield *items* in order, waiting before each and marking it done after.

        Own tasks that never reach the loop (outputs already exist) are marked done
        up front, so no other shard waits on them.
        """
        items = list(items)
        reached = {name_of(item) for item in items}
        for name in self.order:
            if name not in reached:
                self.mark_done(name)
        previous = None
        try:
            for item in items:
                if previous is not None:
                    self.mark_done(previous)
                    previous = None
                name = name_of(item)
                self.wait_for(name)
                previous = name
                yield item
        finally:
            if previous is not None:
                self.mark_done(previous)
            for name in self.order:
                self.mark_done(name)
