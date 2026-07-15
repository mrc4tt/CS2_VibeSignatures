import unittest
from pathlib import Path


class TestSymbolStoreArchitecture(unittest.TestCase):
    def test_production_consumers_do_not_read_bin_yaml(self) -> None:
        gamedata = Path("update_gamedata.py").read_text(encoding="utf-8")
        cpp_util = Path("cpp_tests_util.py").read_text(encoding="utf-8")
        cpp_runner = Path("run_cpp_tests.py").read_text(encoding="utf-8")

        self.assertNotIn("-bindir", gamedata)
        self.assertNotIn("load_yaml_data", gamedata)
        self.assertNotIn("module_dir.glob", cpp_util)
        self.assertNotIn("yaml.safe_load(f)", cpp_util)
        self.assertNotIn("-bindir", cpp_runner)
        self.assertIn("store.get", gamedata)
        self.assertIn("symbol_store.glob_module", cpp_util)
        self.assertIn("open_snapshot_store", cpp_runner)

    def test_directory_backend_is_not_used_by_production_consumers(self) -> None:
        for path in ("update_gamedata.py", "cpp_tests_util.py", "run_cpp_tests.py"):
            with self.subTest(path=path):
                source = Path(path).read_text(encoding="utf-8")
                self.assertNotIn("DirectorySymbolStore", source)

    def test_post_change_skills_preserve_candidate_lifecycle(self) -> None:
        skill_root = Path(".claude/skills")
        update = (skill_root / "post-change-update/SKILL.md").read_text(encoding="utf-8")
        validation = (skill_root / "post-change-validation/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("gamesymbol_candidate.py build", update)
        self.assertIn('update_gamedata.py -gamever "$GAMEVER" -snapshot "$CANDIDATE"', update)
        self.assertIn("gamesymbol_candidate.py publish", update)
        self.assertNotIn("gamesymbol_snapshot.py pack", update)
        self.assertIn('run_cpp_tests.py -gamever "$GAMEVER" -snapshot "$CANDIDATE"', validation)
        self.assertIn("gamesymbol_candidate.py mark", validation)


if __name__ == "__main__":
    unittest.main()
