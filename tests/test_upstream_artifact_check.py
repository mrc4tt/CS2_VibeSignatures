import upstream_artifact_check as U


def test_split_name():
    assert U.split_name("CCSBot_Idle.linux.yaml") == ("CCSBot_Idle", "linux")
    assert U.split_name("A.b.windows.yaml") == ("A.b", "windows")
    assert U.split_name("CCSBot_Idle.yaml") is None
    assert U.split_name("notes.linux.txt") is None


def test_compare_ignores_spelling_and_missing_fields():
    assert U.compare({"func_va": "0xC183F0"}, {"func_va": "0xc183f0", "func_sig": "55"}) == {}
    assert U.compare({"vfunc_index": 260}, {"vfunc_index": "260", "func_va": "0x1"}) == {}
    assert U.compare({"func_va": "0xc18410", "func_size": "0x1"}, {"func_va": "0xc183f0", "func_size": "0x2"}) \
        == {"func_va": ("0xc18410", "0xc183f0")}
    assert U.compare({"offset": "0xaf8"}, {"offset": "0xaf0"}) == {"offset": ("0xaf8", "0xaf0")}


def test_names_itself():
    assert U.names_itself("A", {"func_name": "A"})
    assert not U.names_itself("A", {"func_name": "B"})
    assert U.names_itself("S_m_x", {"struct_name": "S", "member_name": "m_x"})
    assert U.names_itself("A", {"vfunc_index": 3})


def test_judge_findings_accept_stale_and_skips():
    ours = {
        ("server", "Same", "linux"): {"func_va": "0x10"},
        ("server", "Wrong", "linux"): {"func_va": "0x20"},
        ("server", "Known", "linux"): {"vfunc_index": 5},
        ("server", "Known", "windows"): {"vfunc_index": 4},
        ("server", "OnlyLinux", "linux"): {"func_va": "0x30"},
        ("server", "OnlyLinux", "windows"): {"func_va": "0x31"},
        ("server", "Misfiled", "linux"): {"func_va": "0x40"},
        ("server", "OursOnly", "linux"): {"func_va": "0x50"},
    }
    theirs = {
        ("server", "Same", "linux"): {"func_va": "0x10"},
        ("server", "Wrong", "linux"): {"func_va": "0x21"},
        ("server", "Known", "linux"): {"vfunc_index": 6},
        ("server", "Known", "windows"): {"vfunc_index": 4},
        ("server", "OnlyLinux", "linux"): {"func_va": "0x3f"},
        ("server", "OnlyLinux", "windows"): {"func_va": "0x3e"},
        ("server", "Misfiled", "linux"): {"func_name": "Other", "func_va": "0x41"},
        ("server", "TheirsOnly", "linux"): {"func_va": "0x60"},
    }
    accept = {"Known": "reason", "OnlyLinux.linux": "linux only", "Gone": "no longer differs"}
    findings, accepted, stale, shared, skipped = U.judge(ours, theirs, accept)
    assert [(f[1], f[2]) for f in findings] == [("OnlyLinux", "windows"), ("Wrong", "linux")]
    assert [(a[1], a[2], a[4]) for a in accepted] == [("Known", "linux", "reason"), ("OnlyLinux", "linux", "linux only")]
    assert stale == ["Gone"]
    assert shared == 7 and skipped == 1


def test_accept_file_loads_and_every_entry_has_a_reason():
    accept = U.load_accept()
    assert accept, "upstream_artifact_accept.yaml is missing or empty"
    for key, reason in accept.items():
        assert len(reason) > 20, f"{key}: an accept entry carries its evidence"
