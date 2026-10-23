import unittest
from unittest import mock

try:
    import cs2vibe_ida_mcp as M
    from ida_nexus import DatabaseManager
    from ida_nexus.errors import RemoteError
except Exception as exc:  # no idalib / ida-mcp on this machine
    M = None
    SKIP = str(exc)


@unittest.skipIf(M is None, "cs2vibe_ida_mcp not importable")
class TestAutoanalysisRetry(unittest.TestCase):
    def _manager(self):
        return M.EagerDatabaseManager.__new__(M.EagerDatabaseManager)

    def test_a_cancelled_wait_is_finished_with_auto_wait(self):
        # 14192: every fresh windows DLL stopped with an AU_PROC item queued
        cancelled = RemoteError("analysis_cancelled", "Autoanalysis was cancelled before completion", 409)
        manager = self._manager()
        with mock.patch.object(DatabaseManager, "ensure_autoanalysis", side_effect=[cancelled, None]) as wait, \
                mock.patch.object(M.EagerDatabaseManager, "execute_python") as run:
            manager.ensure_autoanalysis(None, operation_id="x")
        self.assertEqual(2, wait.call_count)
        self.assertIn("auto_wait()", run.call_args.args[0])

    def test_other_errors_are_not_retried(self):
        other = RemoteError("boom", "boom", 500)
        manager = self._manager()
        with mock.patch.object(DatabaseManager, "ensure_autoanalysis", side_effect=other), \
                mock.patch.object(M.EagerDatabaseManager, "execute_python") as run:
            with self.assertRaises(RemoteError):
                manager.ensure_autoanalysis(None)
        run.assert_not_called()

    def test_retries_are_bounded(self):
        cancelled = RemoteError("analysis_cancelled", "cancelled", 409)
        manager = self._manager()
        with mock.patch.object(DatabaseManager, "ensure_autoanalysis", side_effect=cancelled), \
                mock.patch.object(M.EagerDatabaseManager, "execute_python") as run:
            with self.assertRaises(RemoteError):
                manager.ensure_autoanalysis(None)
        self.assertEqual(M.AUTOANALYSIS_RETRIES, run.call_count)


if __name__ == "__main__":
    unittest.main()
