"""check_deploy_drift.py only works if it knows where each file is actually deployed.

The mappings live in the deploy scripts; DEPLOY_TARGETS is a second copy of them, and a
second copy drifts the first time a plugin is added to one and not the other - which would
make the drift check silently stop covering that plugin, the exact failure it exists to
catch. So the table is asserted against the scripts rather than trusted.

Those scripts are git-ignored on purpose (.gitignore excludes *.sh; sync_upstream.sh is the
one exception), so the comparison can only run on a machine that actually deploys. There it
is the check that matters; on a fresh clone it skips, and the comparison semantics below -
which are repository code - are asserted either way.
"""

import os
import re
import unittest

import check_deploy_drift


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    path = os.path.join(REPO, name)
    if not os.path.isfile(path):
        raise unittest.SkipTest(f"{name} is a git-ignored local script and is not present here")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _target(plugin):
    for entry in check_deploy_drift.DEPLOY_TARGETS:
        if entry["plugin"] == plugin:
            return entry
    raise AssertionError(f"{plugin} is deployed but has no entry in DEPLOY_TARGETS")


class DeployTargetsMatchTheScripts(unittest.TestCase):
    def test_css_paths_come_from_update_css_gamedata(self):
        script = _read("update_css_gamedata.sh")

        dist = re.search(r'^DIST_SUBPATH="([^"]+)"', script, re.M)
        install = re.search(r'^INSTALL_REL="([^"]+)"', script, re.M)
        root = re.search(r'^CSS_INSTALL="\$\{CSS_INSTALL:-([^}]+)\}"', script, re.M)
        self.assertTrue(dist and install and root, "update_css_gamedata.sh no longer declares its paths")

        entry = _target("CounterStrikeSharp")
        self.assertEqual(dist.group(1), f"{entry['plugin']}/{entry['dist']}")
        self.assertEqual(install.group(1), entry["install"])
        self.assertEqual(root.group(1).replace("$HOME", "~"), entry["root_default"])
        self.assertEqual(entry["mode"], "merge", "update_css_gamedata.sh merges by key, it does not copy")

    def test_every_deploy_call_has_a_target(self):
        script = _read("deploy_local_plugins.sh")

        calls = re.findall(
            r'deploy\s+"\$OUT_ROOT/([^"]+)"\s*\\?\s*\n?\s*"\$HOME/([^"]+)"',
            script,
        )
        self.assertTrue(calls, "deploy_local_plugins.sh no longer has recognisable deploy calls")

        for dist, install in calls:
            plugin, _, rest = dist.partition("/")
            entry = _target(plugin)
            self.assertEqual(rest, entry["dist"])
            self.assertEqual(entry["mode"], "copy", "deploy_local_plugins.sh copies the file")
            root = entry["root_default"].replace("~/", "")
            self.assertEqual(install, f"{root}/{entry['install']}")

    def test_no_target_is_left_over(self):
        declared = {entry["plugin"] for entry in check_deploy_drift.DEPLOY_TARGETS}
        scripts = _read("deploy_local_plugins.sh") + _read("update_css_gamedata.sh")
        for plugin in declared:
            self.assertIn(plugin, scripts, f"{plugin} is in DEPLOY_TARGETS but no script deploys it")


class CompareSemantics(unittest.TestCase):
    def test_merge_ignores_keys_only_the_install_has(self):
        # update_css_gamedata.sh preserves install-only symbols on purpose.
        details = check_deploy_drift._diff_keys(
            {"A": {"offsets": {"linux": 1}}},
            {"A": {"offsets": {"linux": 1}}, "B": {"offsets": {"linux": 2}}},
            generated_only=True,
        )
        self.assertEqual(details, [])

    def test_merge_reports_a_generated_key_the_install_lacks(self):
        details = check_deploy_drift._diff_keys(
            {"A": {"offsets": {"linux": 1}}}, {}, generated_only=True
        )
        self.assertEqual(len(details), 1)
        self.assertIn("A.offsets.linux", details[0])

    def test_zero_is_not_confused_with_absent(self):
        # CEntityResourceManifest_AddResource is linux vtable slot 0.
        details = check_deploy_drift._diff_keys(
            {"A": {"offsets": {"linux": 0}}},
            {"A": {"offsets": {"linux": 0}}},
            generated_only=True,
        )
        self.assertEqual(details, [])

    def test_copy_mode_reports_a_changed_value(self):
        details = check_deploy_drift._diff_keys(
            {"A": {"signatures": {"linux": "48 8B"}}},
            {"A": {"signatures": {"linux": "DE AD"}}},
            generated_only=False,
        )
        self.assertEqual(len(details), 1)
        self.assertIn("A.signatures.linux", details[0])


class BuildSelection(unittest.TestCase):
    def test_builds_sort_numerically_with_a_suffix_last(self):
        # 14178b is older than 14180; a plain string sort puts it after.
        order = sorted(["14180", "14178b", "14181", "14178"],
                       key=lambda tag: (int(re.match(r"[0-9]+", tag).group()), tag))
        self.assertEqual(order, ["14178", "14178b", "14180", "14181"])
        self.assertEqual(order[-1], "14181", "the newest build is the one the plugins hold")


if __name__ == "__main__":
    unittest.main()
