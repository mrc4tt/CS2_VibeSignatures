import unittest
from pathlib import Path

from trusted_yaml import load_yaml_file


REQUIRED_SKILL_INPUTS = {
    "find-CEntityIdentity_AcceptInputInternal": "CEntityIdentity_AcceptInput.{platform}.yaml",
    "find-CPointTeleportAPI_TeleportEntityInternal": "CPointTeleport_Activate.{platform}.yaml",
}


class TestConfigSchedulingDependencies(unittest.TestCase):
    def test_all_configs_declare_required_scheduling_inputs(self) -> None:
        for config_path in sorted(Path("configs").glob("*.yaml")):
            config = load_yaml_file(config_path, cache=True, copy_result=False)
            configured_skills = {
                skill["name"]: skill
                for module in config["modules"]
                for skill in module.get("skills", []) or []
                if isinstance(skill, dict) and skill.get("name") in REQUIRED_SKILL_INPUTS
            }

            with self.subTest(config=config_path.name):
                self.assertEqual(set(REQUIRED_SKILL_INPUTS), set(configured_skills))
                for skill_name, required_input in REQUIRED_SKILL_INPUTS.items():
                    self.assertIn(required_input, configured_skills[skill_name].get("expected_input", []))


if __name__ == "__main__":
    unittest.main()
