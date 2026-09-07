"""IDA boundary tests using minimal IDAPython stubs; no licensed IDA required."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

import ida_sig_maker_batch as batch


ROOT = Path(__file__).resolve().parents[1]


def load_ida_script():
    names = (
        "ida_auto ida_bytes ida_funcs ida_ida ida_idaapi ida_kernwin ida_name ida_nalt ida_segment ida_ua idautils idc"
    ).split()
    stubs = {name: MagicMock() for name in names}
    stubs["ida_kernwin"].action_handler_t = object
    stubs["ida_idaapi"].BADADDR = -1
    stubs["ida_ida"].inf_get_procname.return_value = "metapc"
    stubs["ida_name"].get_name_ea.return_value = -1
    stubs["idautils"].Names.return_value = []
    stubs["ida_segment"].SEGPERM_EXEC = 1
    stubs["ida_nalt"].get_input_file_path.return_value = "/tmp/bin/v1/server/libserver.so"
    stubs["ida_auto"].auto_wait.return_value = True
    stubs["ida_ida"].inf_is_64bit.return_value = True
    for i, name in enumerate(("o_void", "o_displ", "o_mem", "o_near", "o_far", "o_imm")):
        setattr(stubs["ida_ua"], name, i)
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("sig_maker_under_test", ROOT / "ida_sig_maker.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class MakerTests(unittest.TestCase):
    def setUp(self):
        self.m = load_ida_script()

    def test_import_does_not_run_queue(self):
        self.m.ida_auto.auto_wait.assert_not_called()
        self.assertEqual(
            self.m.parse_queue(" # comment\nCEconItemView_operator=\nA\nA\n"), ["CEconItemView_operator=", "A"]
        )

    def test_overlapping_matches(self):
        scan = object.__new__(self.m.Scan)
        scan.regions = [(0x1000, b"\xaa\xaa\xaa")]
        self.assertEqual(scan.matches("AA AA"), [0x1000, 0x1001])
        with self.assertRaises(ValueError):
            scan.matches("?? ??")

    def test_ambiguous_names_rejected(self):
        self.m.ida_name.get_name_ea.side_effect = lambda _, name: {"foo": 10, "bar": 20}[name]
        with self.assertRaisesRegex(ValueError, "found 2"):
            self.m.resolve("foo", {"names": ["bar"]}, MagicMock())

    def test_unique_pattern_can_find_unnamed_function(self):
        scan = MagicMock()
        scan.matches.return_value = [100]
        self.assertEqual(self.m.resolve("foo", {"pattern": "AA BB"}, scan), 100)

    def test_conflicting_evidence_rejected(self):
        self.m.ida_name.get_name_ea.return_value = 200
        scan = MagicMock()
        scan.matches.return_value = [100]
        with self.assertRaisesRegex(ValueError, "found 0"):
            self.m.resolve("foo", {"pattern": "AA BB"}, scan)

    def test_signature_stops_at_function_boundary(self):
        self.m.ida_funcs.get_func.return_value = types.SimpleNamespace(start_ea=100, end_ea=104)
        self.m.ida_ua.decode_insn.return_value = 5
        with self.assertRaisesRegex(ValueError, "No unique"):
            self.m.signature(100, MagicMock())
        self.m.ida_bytes.get_bytes.assert_not_called()

    def test_signature_does_not_invent_unreadable_bytes(self):
        self.m.ida_funcs.get_func.return_value = types.SimpleNamespace(start_ea=100, end_ea=120)
        self.m.ida_ua.decode_insn.return_value = 5
        self.m.ida_bytes.get_bytes.return_value = None
        with self.assertRaisesRegex(ValueError, "Unreadable"):
            self.m.signature(100, MagicMock())

    def test_short_unique_function(self):
        self.m.ida_funcs.get_func.return_value = types.SimpleNamespace(start_ea=100, end_ea=101)
        self.m.ida_ua.decode_insn.return_value = 1
        self.m.ida_ua.insn_t.return_value = types.SimpleNamespace(ops=[])
        self.m.ida_bytes.get_bytes.return_value = b"\xc3"
        scan = MagicMock()
        scan.matches.return_value = [100]
        self.assertEqual(self.m.signature(100, scan), "C3")

    def test_member_cannot_be_emitted_as_function_by_default(self):
        with self.assertRaisesRegex(ValueError, "typed instruction"):
            self.m.emit_symbol("Inventory_m_pSOCache", {}, {}, MagicMock())

    def test_typed_member_reads_current_displacement(self):
        scan = MagicMock()
        scan.matches.return_value = [100]
        self.m.ida_ua.decode_insn.return_value = 7
        self.m.ida_ua.insn_t.return_value = types.SimpleNamespace(
            ops=[types.SimpleNamespace(type=self.m.ida_ua.o_displ, addr=0x78)]
        )
        self.m.ida_bytes.is_code.return_value = True
        rule = {
            "kind": "structmember",
            "pattern": "48 8B 80 ?? ?? ?? ??",
            "struct_name": "Inventory",
            "member_name": "m_cache",
            "operand": 0,
            "size": 8,
        }
        with patch.object(self.m, "write_yaml") as write:
            self.m.emit_symbol("Inventory_m_cache", rule, {}, scan)
        data = write.call_args.args[0]
        self.assertEqual(data["offset"], "0x78")
        self.assertNotIn("func_name", data)

    def test_vfunc_reads_slot_pointer(self):
        self.m.ida_name.get_name_ea.return_value = 0x1000
        self.m.ida_bytes.get_qword.return_value = 0x2000
        rule = {"kind": "vfunc", "address_point_name": "table_slots", "index": 3, "vtable_name": "Owner"}
        with patch.object(self.m, "emit_vfunc_yaml") as emit:
            self.m.emit_symbol("Owner_Method", rule, {}, MagicMock())
        self.m.ida_bytes.get_qword.assert_called_once_with(0x1018)
        emit.assert_called_once_with(0x2000, "Owner_Method", "Owner", 3, {})

    def test_bad_filename_rejected(self):
        for name in ("../escape", "C:\\escape", "a/b"):
            with self.assertRaises(ValueError):
                self.m.safe_symbol(name)

    def test_module_scope_and_failure_report(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(self.m, "Scan"),
            patch.object(self.m, "emit_symbol", side_effect=ValueError("not found")) as emit,
        ):
            report_path = str(Path(folder) / "report.json")
            report = self.m.main(
                queue="other!Ignore\nserver!Target",
                output_dir=folder,
                module="server",
                platform="linux",
                report_path=report_path,
            )
            self.assertEqual(len(report["results"]), 1)
            self.assertEqual(report["results"][0]["status"], "unresolved")
            self.assertEqual(json.loads(Path(report_path).read_text())["results"], report["results"])
            emit.assert_called_once()

    def test_yaml_only_in_artifact_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            self.m.ida_nalt.get_input_file_path.return_value = str(Path(folder) / "bin/v1/server/server.dll")
            target = self.m.detect_target()
            output = self.m.write_yaml({"func_name": "Foo", "func_sig": "AA ??"}, "Foo", target)
            self.assertEqual(Path(output), Path(folder) / "bin_artifacts/v1/server/Foo.windows.yaml")
            self.assertFalse((Path(folder) / "bin").exists())
            self.assertIn('func_sig: "AA ??"', Path(output).read_text())


class BatchTests(unittest.TestCase):
    def test_default_queue_can_be_read_without_ida(self):
        self.assertIn("UpdateItemView", batch.default_queue())

    def test_recursive_cross_platform_discovery(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("server/server.dll", "server/linux/libserver.so", "engine2/engine2.DLL"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            jobs = batch.discover(root)
            self.assertEqual(
                {(module, platform) for _, module, platform in jobs},
                {("server", "windows"), ("server", "linux"), ("engine2", "windows")},
            )

    def test_output_collision_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "server").mkdir()
            (root / "server/a.dll").touch()
            (root / "server/b.dll").touch()
            with self.assertRaisesRegex(ValueError, "Multiple"):
                batch.discover(root)

    def test_timeout_continues_next_binary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "bin/v1"
            root.mkdir(parents=True)
            (root / "a.dll").touch()
            (root / "b.so").touch()
            args = types.SimpleNamespace(
                input=root,
                queue=None,
                rules=None,
                output=None,
                report_dir=None,
                ida=sys.executable,
                timeout=1,
                dry_run=False,
            )
            with patch.object(batch.subprocess, "run", side_effect=batch.subprocess.TimeoutExpired("ida", 1)) as run:
                self.assertEqual(batch.run(args), 1)
                self.assertEqual(run.call_count, 2)
            report = json.loads((Path(folder) / "sig_maker_reports/v1/summary.json").read_text())
            self.assertEqual([row["status"] for row in report], ["failed", "failed"])

    def test_successful_job_uses_isolated_database_and_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "bin/v1"
            root.mkdir(parents=True)
            (root / "server.dll").touch()
            args = types.SimpleNamespace(
                input=root,
                queue=None,
                rules=None,
                output=None,
                report_dir=None,
                ida=sys.executable,
                timeout=1,
                dry_run=False,
            )

            def fake_ida(command, **kwargs):
                self.assertIn("-A", command)
                self.assertIn("-Srunner.py", command)
                self.assertIn(f"-o{kwargs['cwd'] / 'analysis.i64'}", command)
                job = json.loads(Path(kwargs["env"]["CS2_SIG_MAKER_JOB"]).read_text())
                self.assertEqual(job["platform"], "windows")
                self.assertEqual(Path(job["output_dir"]), Path(folder) / "bin_artifacts/v1/server")
                Path(job["report_path"]).write_text(json.dumps({"results": [{"symbol": "Foo", "status": "written"}]}))
                return types.SimpleNamespace(returncode=0)

            with patch.object(batch.subprocess, "run", side_effect=fake_ida):
                self.assertEqual(batch.run(args), 0)
            self.assertFalse((root / "analysis.i64").exists())

    def test_no_report_is_failure_even_with_zero_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "bin/v1"
            root.mkdir(parents=True)
            (root / "server.dll").touch()
            args = types.SimpleNamespace(
                input=root,
                queue=None,
                rules=None,
                output=None,
                report_dir=None,
                ida=sys.executable,
                timeout=1,
                dry_run=False,
            )
            with patch.object(batch.subprocess, "run", return_value=types.SimpleNamespace(returncode=0)):
                self.assertEqual(batch.run(args), 1)


if __name__ == "__main__":
    unittest.main()
