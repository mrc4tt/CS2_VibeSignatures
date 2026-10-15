"""The editor's IDA session never opens a database it cannot serve, and never dies with
one open: either leaves a .i64 half-packed, which IDA then refuses to open."""
import os
import socket
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cs2vibe_ida_mcp as M  # noqa: E402


class PortTests(unittest.TestCase):
    def test_a_taken_port_is_reported_not_waited_on_forever(self):
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        try:
            self.assertFalse(M.wait_for_free_port("127.0.0.1", holder.getsockname()[1], timeout=0))
        finally:
            holder.close()

    def test_a_free_port_is_free(self):
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        self.assertTrue(M.wait_for_free_port("127.0.0.1", port, timeout=0))

    def test_main_refuses_before_opening_anything(self):
        with mock.patch.object(M, "wait_for_free_port", return_value=False), \
                mock.patch.object(M, "serve") as serve, mock.patch.object(M, "install_fork_tools"):
            with self.assertRaises(SystemExit):
                M.main(["--port", "13337"])
        serve.assert_not_called()


class CloseOnErrorTests(unittest.TestCase):
    def test_an_error_after_opening_closes_every_database(self):
        manager = mock.Mock()
        manager.list_databases.return_value = {"instances": [{"instance_id": "a"}, {"instance_id": "b"}]}
        with mock.patch.object(M, "wait_for_free_port", return_value=True), \
                mock.patch.object(M, "install_fork_tools"), \
                mock.patch.object(M, "serve", side_effect=OSError(98, "Address already in use")), \
                mock.patch.object(M.hx, "DATABASE_MANAGER", manager, create=True):
            with self.assertRaises(OSError):
                M.main(["--port", "13337"])
        self.assertEqual([c.args[0] for c in manager.close_database.call_args_list], ["a", "b"])

    def test_a_signal_exit_is_left_to_the_normal_shutdown(self):
        manager = mock.Mock()
        with mock.patch.object(M, "wait_for_free_port", return_value=True), \
                mock.patch.object(M, "install_fork_tools"), \
                mock.patch.object(M, "serve", side_effect=SystemExit(143)), \
                mock.patch.object(M.hx, "DATABASE_MANAGER", manager, create=True):
            with self.assertRaises(SystemExit):
                M.main(["--port", "13337"])
        manager.close_database.assert_not_called()


if __name__ == "__main__":
    unittest.main()
