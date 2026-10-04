"""Unit tests for audit_vtable_slots (a virtual's slot against the previous gamever)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import audit_vtable_slots as slots  # noqa: E402


class TestSlotShiftVerdict(unittest.TestCase):
    def test_a_vtable_that_kept_its_size_allows_no_move(self):
        # vtidx_FinishMove.windows 14183 -> 14184: 38 -> 39, vtable 59 -> 59
        verdict, why = slots.slot_shift_verdict(38, 39, 59, 59)
        self.assertEqual(verdict, "shifted")
        self.assertIn("38 -> 39 (+1)", why)
        self.assertEqual(slots.slot_shift_verdict(38, 38, 59, 59)[0], "ok")

    def test_an_insertion_allows_a_move_up_to_its_size(self):
        self.assertEqual(slots.slot_shift_verdict(38, 39, 59, 60)[0], "ok")
        self.assertEqual(slots.slot_shift_verdict(38, 38, 59, 60)[0], "ok")
        self.assertEqual(slots.slot_shift_verdict(38, 40, 59, 60)[0], "shifted")
        self.assertEqual(slots.slot_shift_verdict(38, 37, 59, 58)[0], "ok")

    def test_neighbours_bound_the_move(self):
        # GetDataDescMap.linux 14181 -> 14182: stayed at 44 while 43 and 45 moved +1
        neighbours = [(43, 44), (45, 46)]
        self.assertEqual(slots.slot_shift_verdict(44, 44, 49, 50, neighbours)[0], "shifted")
        self.assertEqual(slots.slot_shift_verdict(44, 45, 49, 50, neighbours)[0], "ok")

    def test_the_other_platform_moving_the_same_way_is_a_layout_change(self):
        # CBaseModelEntity_DamageDecal 14181 -> 14182: +3 on both, vtable +2
        self.assertEqual(slots.slot_shift_verdict(258, 261, 300, 302)[0], "shifted")
        self.assertEqual(slots.slot_shift_verdict(258, 261, 300, 302, twin_shift=3)[0], "ok")
        self.assertEqual(slots.slot_shift_verdict(258, 261, 300, 302, twin_shift=0)[0], "shifted")

    def test_unknown_when_nothing_bounds_the_top(self):
        self.assertIsNone(slots.slot_shift_verdict(10, 11, None, None)[0])
        self.assertIsNone(slots.slot_shift_verdict(None, 11, 20, 20)[0])
        # an interface with no vtable artifact is still bounded by a known slot above
        self.assertEqual(slots.slot_shift_verdict(10, 11, None, None, [(12, 12)])[0], "shifted")


class TestOnDisk(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old = self.root / "14183" / "server"
        self.new = self.root / "14184" / "server"
        self.old.mkdir(parents=True)
        self.new.mkdir(parents=True)
        slots._FILE_CACHE.clear()

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _vtable(directory, name, platform, length):
        entries = "".join(f"  {i}: '{0x1000 + i * 16:#x}'\n" for i in range(length))
        (directory / f"{name}_vtable.{platform}.yaml").write_text(
            f"vtable_class: {name}\nvtable_entries:\n{entries}", encoding="utf-8"
        )

    @staticmethod
    def _vfunc(directory, symbol, platform, vtable, index):
        (directory / f"{symbol}.{platform}.yaml").write_text(
            f"func_name: {symbol}\nvtable_name: {vtable}\nvfunc_offset: '{index * 8:#x}'\nvfunc_index: {index}\n",
            encoding="utf-8",
        )

    def _build(self, old_windows, new_windows, linux=(39, 39)):
        for directory in (self.old, self.new):
            self._vtable(directory, "CCSPlayer_MovementServices", "windows", 59)
            self._vtable(directory, "CCSPlayer_MovementServices", "linux", 60)
        self._vfunc(self.old, "vtidx_FinishMove", "windows", "CCSPlayer_MovementServices", old_windows)
        self._vfunc(self.new, "vtidx_FinishMove", "windows", "CCSPlayer_MovementServices", new_windows)
        self._vfunc(self.old, "vtidx_FinishMove", "linux", "CCSPlayer_MovementServices", linux[0])
        self._vfunc(self.new, "vtidx_FinishMove", "linux", "CCSPlayer_MovementServices", linux[1])

    def test_relocation_verdict_rejects_the_finishmove_drift(self):
        self._build(38, 39)
        old_yaml = str(self.old / "vtidx_FinishMove.windows.yaml")
        verdict = slots.relocation_slot_verdict("windows", "CCSPlayer_MovementServices", 39, str(self.new), old_yaml)
        self.assertEqual(verdict, "shifted")
        verdict = slots.relocation_slot_verdict("windows", "CCSPlayer_MovementServices", 38, str(self.new), old_yaml)
        self.assertEqual(verdict, "ok")

    def test_relocation_verdict_cannot_judge_without_a_baseline(self):
        self._build(38, 39)
        missing = str(self.old / "nothing.windows.yaml")
        self.assertIsNone(
            slots.relocation_slot_verdict("windows", "CCSPlayer_MovementServices", 39, str(self.new), missing)
        )
        old_yaml = str(self.old / "vtidx_FinishMove.windows.yaml")
        self.assertIsNone(slots.relocation_slot_verdict("windows", "COther", 39, str(self.new), old_yaml))

    def test_a_file_written_later_in_the_run_is_seen(self):
        # the directory cache is keyed on its mtime, and a run adds artifacts as it goes
        self._build(38, 38)
        self.assertEqual(slots._twin_shift(str(self.old), str(self.new), "vtidx_FinishMove.windows.yaml", "windows"), 0)
        self._vfunc(self.old, "Other", "linux", "CCSPlayer_MovementServices", 10)
        self._vfunc(self.new, "Other", "linux", "CCSPlayer_MovementServices", 11)
        self.assertEqual(slots._twin_shift(str(self.old), str(self.new), "Other.windows.yaml", "windows"), 1)

    def test_audit_counts_and_exit(self):
        self._build(38, 39)
        self.assertEqual(slots.audit("14184", "14183", ["windows", "linux"], str(self.root), None, False), 1)
        self._build(38, 38)
        slots._FILE_CACHE.clear()
        self.assertEqual(slots.audit("14184", "14183", ["windows", "linux"], str(self.root), None, False), 0)

    def test_vtable_name_already_carrying_the_suffix(self):
        self._vtable(self.old, "CGameMoney", "linux", 50)
        self._vtable(self.new, "CGameMoney", "linux", 50)
        self.assertEqual(slots._vtable_length(str(self.new), "CGameMoney_vtable", "linux"), 50)
        self.assertEqual(slots._vtable_length(str(self.new), "CGameMoney", "linux"), 50)


if __name__ == "__main__":
    unittest.main()
