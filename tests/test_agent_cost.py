import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import agent_cost


def _make_db(path):
    db = sqlite3.connect(path)
    db.execute("create table session (id text, parent_id text, time_created integer)")
    db.execute("create table message (id text, session_id text, time_created integer, data text)")
    db.execute("create table part (id text, session_id text, time_created integer, data text)")
    return db


def _session(db, sid, created_ms, prompt, provider, model, cost, tokens):
    db.execute("insert into session values (?, null, ?)", (sid, created_ms))
    db.execute(
        "insert into part values (?, ?, ?, ?)",
        (f"{sid}-p", sid, created_ms, json.dumps({"type": "text", "text": prompt})),
    )
    db.execute(
        "insert into message values (?, ?, ?, ?)",
        (
            f"{sid}-m",
            sid,
            created_ms + 1,
            json.dumps(
                {"role": "assistant", "providerID": provider, "modelID": model, "cost": cost, "tokens": tokens}
            ),
        ),
    )


class AgentCostTests(unittest.TestCase):
    def test_hunts_in_window_are_summed_and_priced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "opencode.db")
            db = _make_db(path)
            tokens = {"input": 1_000_000, "output": 0, "reasoning": 0, "cache": {"read": 10_000_000, "write": 0}}
            _session(db, "a", 2_000_000, "Run SKILL: .claude/skills/find-Foo/SKILL.md", "zai", "glm-5.3-flash", 0.45, tokens)
            _session(db, "b", 2_000_000, "fix my code", "zai", "glm-5.3-flash", 9.0, tokens)  # not a hunt
            _session(db, "c", 1_000_000, "Run SKILL: .claude/skills/find-Old/SKILL.md", "zai", "glm-5.3", 1.0, tokens)
            db.commit()
            db.close()

            report = agent_cost.collect(path, since=1500)

        self.assertEqual(1, report["total"]["hunts"])
        self.assertAlmostEqual(0.45, report["total"]["cost"])
        # 1M input at 0.15 + 10M cached at 0.03
        self.assertAlmostEqual(0.45, report["total"]["list_cost"])
        self.assertEqual(["find-Foo"], list(report["by_skill"]))
        self.assertEqual(["zai/glm-5.3-flash"], list(report["by_model"]))

    def test_missing_database_is_not_a_failure(self):
        self.assertEqual(0, agent_cost.main(["-db", "/nonexistent/opencode.db"]))


if __name__ == "__main__":
    unittest.main()
