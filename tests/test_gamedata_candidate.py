import tempfile
import unittest
from pathlib import Path

from gamedata_candidate import (
    GamedataCandidateError,
    build_candidate,
    guard_candidate,
    publish_candidate,
)
from gamedata_contract import GamedataContractError, discover_generator_modules
from gamesymbol_snapshot_lib.codec import build_snapshot_document, canonical_snapshot_bytes
from gamesymbol_snapshot_lib.config import load_contract


GENERATOR_SOURCE = """
from pathlib import Path

MODULE_NAME = "Fixture"
MODULE_ENABLED = True
OUTPUT_PATHS = ("payload/final.json",)
DOWNLOAD_SOURCES = ()


def update(yaml_data, func_lib_map, platforms, output_dir, alias_to_name_map, debug=False):
    path = Path(output_dir) / OUTPUT_PATHS[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"ok": true}\\n', encoding="utf-8")
    return 1, 0, [], []
"""


class GamedataCandidateFixture:
    gamever = "14170"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.config = root / "configs" / f"{self.gamever}.yaml"
        self.snapshot = root / "candidate.yaml"
        self.modules = root / "gamedata-generators"
        self.candidate_root = root / "candidate-root"
        self.session = root / "candidate-root" / "session.json"
        self.config.parent.mkdir(parents=True)
        self.config.write_text("modules: []\n", encoding="utf-8")
        contract = load_contract(self.config, self.gamever, root / "bin")
        document = build_snapshot_document(self.gamever, contract.config_sha256, {})
        self.snapshot.write_bytes(canonical_snapshot_bytes(document))
        generator = self.modules / "fixture"
        generator.mkdir(parents=True)
        (generator / "gamedata.py").write_text(GENERATOR_SOURCE, encoding="utf-8")

    def build(self) -> dict:
        return build_candidate(
            gamever=self.gamever,
            build_id="123-1",
            snapshot=self.snapshot,
            analysis_config=self.config,
            modules_dir=self.modules,
            candidate_root=self.candidate_root,
            session_path=self.session,
        )


class TestGamedataCandidate(unittest.TestCase):
    def test_build_guard_and_publish_keep_versions_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = GamedataCandidateFixture(Path(tmp))
            session = fixture.build()
            workspace = fixture.root / "workspace"
            historical = workspace / "gamedata" / "14168" / "keep.json"
            historical.parent.mkdir(parents=True)
            historical.write_text("keep\n", encoding="utf-8")

            guard_candidate(fixture.session)
            publish_candidate(
                session_path=fixture.session,
                output_dir=workspace / "gamedata" / fixture.gamever,
            )

            self.assertEqual("gamedata/14170", session["gamedata_path"])
            self.assertEqual("keep\n", historical.read_text(encoding="utf-8"))
            self.assertEqual(
                '{"ok": true}\n',
                (workspace / "gamedata" / fixture.gamever / "fixture" / "payload" / "final.json").read_text(
                    encoding="utf-8"
                ),
            )
            published = workspace / "gamedata" / fixture.gamever / "fixture" / "payload" / "final.json"
            self.assertNotIn(b"\r", published.read_bytes())

    def test_guard_rejects_candidate_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = GamedataCandidateFixture(Path(tmp))
            fixture.build()
            output = fixture.candidate_root / "gamedata" / fixture.gamever / "fixture" / "payload" / "final.json"
            output.write_text("tampered\n", encoding="utf-8")

            with self.assertRaisesRegex(GamedataCandidateError, "bytes changed"):
                guard_candidate(fixture.session)

    def test_contract_rejects_forbidden_and_undeclared_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            modules = Path(tmp) / "gamedata-generators"
            generator = modules / "fixture"
            generator.mkdir(parents=True)
            (generator / "gamedata.py").write_text(
                'MODULE_NAME="Fixture"\nOUTPUT_PATHS=("config.yaml",)\nDOWNLOAD_SOURCES=()\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(GamedataContractError, "forbidden extension"):
                discover_generator_modules(modules)


if __name__ == "__main__":
    unittest.main()
