"""The run discards a relocated virtual whose slot moved unlike its neighbours."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import audit_vtable_slots  # noqa: E402
import ida_analyze_util  # noqa: E402


def _vtable(directory: Path, length: int) -> None:
    entries = "".join(f"  {i}: '{0x1000 + i * 16:#x}'\n" for i in range(length))
    (directory / "CCSPlayer_MovementServices_vtable.windows.yaml").write_text(
        f"vtable_class: CCSPlayer_MovementServices\nvtable_entries:\n{entries}", encoding="utf-8"
    )


class TestRelocationSlotCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old = root / "14183" / "server"
        self.new = root / "14184" / "server"
        for d in (self.old, self.new):
            d.mkdir(parents=True)
            _vtable(d, 59)
        self.old_yaml = self.old / "vtidx_FinishMove.windows.yaml"
        self.old_yaml.write_text(
            "func_name: vtidx_FinishMove\nfunc_va: '0x1260'\nfunc_sig: 48 89 5C 24 ??\n"
            "vtable_name: CCSPlayer_MovementServices\nvfunc_offset: '0x130'\nvfunc_index: 38\n",
            encoding="utf-8",
        )
        audit_vtable_slots._FILE_CACHE.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, index, env=None):
        relocated = {
            "func_name": "vtidx_FinishMove",
            "func_va": hex(0x1000 + index * 16),
            "func_size": "0x10",
            "func_sig": "48 89 5C 24 ??",
            "vtable_name": "CCSPlayer_MovementServices",
            "vfunc_offset": hex(index * 8),
            "vfunc_index": index,
        }

        async def fake_relocation(**_kwargs):
            return dict(relocated)

        with mock.patch.object(ida_analyze_util, "preprocess_func_sig_via_mcp", fake_relocation), \
                mock.patch.dict(os.environ, {"CS2VIBE_RELOC_DRIFT_CHECK": "0", **(env or {})}):
            return asyncio.run(
                ida_analyze_util._try_preprocess_func_without_llm(
                    session=None,
                    target_output=str(self.new / "vtidx_FinishMove.windows.yaml"),
                    old_path=str(self.old_yaml),
                    image_base=0,
                    new_binary_dir=str(self.new),
                    platform="windows",
                    func_name="vtidx_FinishMove",
                    func_xrefs_map={},
                    vtable_relations_map={},
                    normalized_mangled_class_names={},
                )
            )

    def test_the_next_slot_is_discarded(self):
        self.assertIsNone(self._run(39))

    def test_the_same_slot_is_kept(self):
        self.assertEqual(self._run(38)["vfunc_index"], 38)

    def test_the_check_can_be_turned_off(self):
        self.assertEqual(self._run(39, {"CS2VIBE_RELOC_SLOT_CHECK": "0"})["vfunc_index"], 39)


if __name__ == "__main__":
    unittest.main()
