import unittest
from types import SimpleNamespace
from unittest.mock import patch

from process_reporter import NullProcessReporter, ProcessReporterConfigurationError
from process_reporter_factory import create_process_reporter


class TestProcessReporterFactory(unittest.TestCase):
    def test_defaults_to_null_reporter(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            reporter = create_process_reporter(SimpleNamespace())

        self.assertIsInstance(reporter, NullProcessReporter)

    def test_rejects_unknown_backend(self) -> None:
        with self.assertRaisesRegex(ProcessReporterConfigurationError, "Unsupported"):
            create_process_reporter(SimpleNamespace(process_reporter="unknown"))

    def test_redis_backend_is_lazy_and_reports_missing_phase_three_module(self) -> None:
        with self.assertRaisesRegex(ProcessReporterConfigurationError, "Phase 3"):
            create_process_reporter(SimpleNamespace(process_reporter="redis"))


if __name__ == "__main__":
    unittest.main()
