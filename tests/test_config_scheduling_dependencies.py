import unittest
from pathlib import Path

import ida_analyze_bin


class TestConfigSchedulingDependencies(unittest.TestCase):
    def test_all_configs_have_satisfied_dependency_graphs(self) -> None:
        for config_path in sorted(Path("configs").glob("*.yaml")):
            with self.subTest(config=config_path.name):
                modules = ida_analyze_bin.parse_config(config_path)
                gaps = []
                for platform in ("windows", "linux"):
                    gaps.extend(ida_analyze_bin.find_module_skill_dependency_gaps(modules, platform))
                self.assertEqual([], gaps)
                ida_analyze_bin.validate_module_skill_dependencies(modules)


if __name__ == "__main__":
    unittest.main()
