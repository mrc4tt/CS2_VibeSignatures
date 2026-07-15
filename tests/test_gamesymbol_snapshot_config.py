import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from gamesymbol_snapshot_lib.config import load_contract
from gamesymbol_snapshot_lib.errors import SnapshotConfigError
from tests.gamesymbol_snapshot_test_support import module, skill, write_config


class TestSnapshotContract(unittest.TestCase):
    def test_collects_platform_outputs_optional_cross_module_and_owners(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "config.yaml"
            modules = [
                module(
                    "engine",
                    [
                        skill(
                            "find-common",
                            ["Common.{platform}.yaml", "notes.txt", "../server/Cross.{platform}.yaml"],
                            expected_output_windows=["WinOnly.{platform}.yaml"],
                            optional_output=["Maybe.{platform}.yaml"],
                        ),
                        skill("find-linux", ["LinuxOnly.{platform}.yaml"], platform="linux"),
                    ],
                ),
                module("engine", [skill("find-common-again", ["Common.{platform}.yaml"])]),
            ]
            write_config(config, modules)

            contract = load_contract(config, "14168", root / "bin")

        self.assertEqual(
            {
                "engine/Common.windows.yaml",
                "engine/Common.linux.yaml",
                "engine/WinOnly.windows.yaml",
                "engine/LinuxOnly.linux.yaml",
                "server/Cross.windows.yaml",
                "server/Cross.linux.yaml",
            },
            contract.required_paths,
        )
        self.assertEqual(
            {"engine/Maybe.windows.yaml", "engine/Maybe.linux.yaml"},
            contract.optional_paths,
        )
        self.assertEqual(2, len(contract.owners_by_path["engine/Common.windows.yaml"]))

    def test_module_without_platform_binary_does_not_emit_that_platform(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "config.yaml"
            write_config(config, [module("server", [skill("find-a", ["A.{platform}.yaml"])], linux=False)])

            contract = load_contract(config, "1", root / "bin")

        self.assertEqual({"server/A.windows.yaml"}, contract.required_paths)

    def test_digest_ignores_descriptions_but_tracks_analysis_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.yaml"
            second = root / "second.yaml"
            third = root / "third.yaml"
            base = module("server", [skill("find-a", ["A.{platform}.yaml"], description="old")])
            changed_description = module("server", [skill("find-a", ["A.{platform}.yaml"], description="new")])
            changed_output = module("server", [skill("find-a", ["B.{platform}.yaml"])])
            write_config(first, [base])
            write_config(second, [changed_description])
            write_config(third, [changed_output])

            first_digest = load_contract(first, "1", root / "bin").config_sha256
            second_digest = load_contract(second, "1", root / "bin").config_sha256
            third_digest = load_contract(third, "1", root / "bin").config_sha256

        self.assertEqual(first_digest, second_digest)
        self.assertNotEqual(first_digest, third_digest)

    def test_rejects_escape_and_case_insensitive_collision(self) -> None:
        cases = [
            [module("server", [skill("find-a", ["../../outside.yaml"])])],
            [
                module(
                    "server",
                    [
                        skill("find-a", ["Same.windows.yaml"], platform="windows"),
                        skill("find-b", ["same.windows.yaml"], platform="windows"),
                    ],
                    linux=False,
                )
            ],
        ]
        for modules in cases:
            with self.subTest(modules=modules), TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                config = root / "config.yaml"
                write_config(config, modules)
                with self.assertRaises(SnapshotConfigError):
                    load_contract(config, "1", root / "bin")


if __name__ == "__main__":
    unittest.main()
