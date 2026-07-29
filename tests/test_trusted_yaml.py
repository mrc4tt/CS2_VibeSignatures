import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml

import generate_reference_yaml
import trusted_yaml


class TestTrustedYaml(unittest.TestCase):
    def tearDown(self) -> None:
        trusted_yaml.clear_yaml_file_cache()

    def test_selected_loader_matches_safe_loader_for_yaml_features(self) -> None:
        documents = (
            b"",
            "message: 你好\nitems: &items [one, two]\nalias: *items\n",
            b"\xef\xbb\xbfmessage: bom\n",
        )
        for document in documents:
            with self.subTest(document=document):
                expected = yaml.load(document, Loader=yaml.SafeLoader)
                self.assertEqual(expected, trusted_yaml.load_yaml(document))

        with self.assertRaises(yaml.YAMLError):
            trusted_yaml.load_yaml("invalid: [")

    def test_file_cache_returns_defensive_copies_and_invalidates_on_rewrite(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.yaml"
            path.write_text("value: one\n", encoding="utf-8")
            original_loader = trusted_yaml.load_yaml
            with patch.object(trusted_yaml, "load_yaml", wraps=original_loader) as loader:
                first = trusted_yaml.load_yaml_file(path, cache=True)
                first["value"] = "mutated"
                second = trusted_yaml.load_yaml_file(path, cache=True)
                first_stat = path.stat()
                path.write_text("value: two\n", encoding="utf-8")
                os.utime(path, ns=(first_stat.st_atime_ns, first_stat.st_mtime_ns + 1_000_000))
                third = trusted_yaml.load_yaml_file(path, cache=True)

        self.assertEqual("one", second["value"])
        self.assertEqual("two", third["value"])
        self.assertEqual(2, loader.call_count)


class TestRepositoryYamlCompatibility(unittest.TestCase):
    def test_selected_loader_matches_safe_loader_for_repository_fixtures(self) -> None:
        fixture_paths = (
            Path("configs/14172.yaml"),
            Path("gamesymbols/14172.yaml"),
            Path("ida_preprocessor_scripts/references/client/CAM_Command_CommandHandler.windows.yaml"),
        )
        for fixture_path in fixture_paths:
            with self.subTest(fixture=fixture_path):
                raw = fixture_path.read_bytes()
                self.assertEqual(yaml.load(raw, Loader=yaml.SafeLoader), trusted_yaml.load_yaml(raw))

    def test_reference_yamls_match_generation_contract(self) -> None:
        reference_root = Path("ida_preprocessor_scripts/references")
        reference_paths = sorted(reference_root.rglob("*.yaml"))
        self.assertTrue(reference_paths, f"no reference YAML files found under {reference_root}")

        for reference_path in reference_paths:
            with self.subTest(reference=reference_path):
                payload = trusted_yaml.load_yaml_file(reference_path)
                self.assertIsInstance(payload, dict)
                try:
                    generate_reference_yaml._validate_reference_yaml_payload(payload)
                except generate_reference_yaml.ReferenceGenerationError as exc:
                    self.fail(f"{reference_path}: {exc}")


if __name__ == "__main__":
    unittest.main()
