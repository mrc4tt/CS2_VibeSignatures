import upstream_watch as U


def sig(linux=None, windows=None):
    return {"signatures": {"library": "server", "linux": linux, "windows": windows}}


def test_changed_keys_against_base():
    base = {"A": sig("11", "22"), "B": sig("33", "44"), "C": {"offsets": {"linux": 1, "windows": 2}}}
    theirs = {"A": sig("11", "99"), "B": sig("33", "44"), "C": {"offsets": {"linux": 5, "windows": 2}},
              "D": sig("55", None), "note": "not an entry"}
    assert U.changed_keys(theirs, base) == {"A": ["windows"], "C": ["linux"], "D": ["linux"]}


def test_changed_keys_without_base_takes_every_value():
    assert U.changed_keys({"A": sig("11", "")}, None) == {"A": ["linux"]}


def test_symbol_at():
    index = {"ClientPrint": {"linux": {"func_va": "0x17ff680", "func_name": "ClientPrintToController"}},
             "Other": {"windows": {"func_va": "0x17ff680"}}}
    assert U.symbol_at(index, "linux", 0x17ff680) == "ClientPrintToController"
    assert U.symbol_at(index, "windows", 0x17ff680) == "Other"
    assert U.symbol_at(index, "linux", 0x1) is None


def test_judge_offsets(monkeypatch):
    monkeypatch.setattr(U.P, "resolve_record", lambda *a, **k: None)
    entry = {"offsets": {"linux": 13, "windows": 12}}
    assert U.judge({}, None, {}, "K", "linux", entry, {"offsets": {"linux": 14}})[0] == "offset"
    assert U.judge({}, None, {}, "K", "linux", entry, {"offsets": {"linux": 13}})[0] == "agrees"
    assert U.judge({}, None, {}, "K", "linux", entry, None)[0] == "new"


def test_judge_signature_lands_elsewhere(monkeypatch):
    monkeypatch.setattr(U.P, "resolve_record", lambda *a, **k: {"func_va": "0x17ff680"})
    monkeypatch.setattr(U.P, "check_signature", lambda *a, **k: {"status": "ok", "at": "0x1cfa530"})
    verdict, text = U.judge({}, None, {}, "ClientPrint", "linux", sig("55 48"), sig("55 48 89"))
    assert verdict == "WRONG" and "0x1cfa530" in text and "0x17ff680" in text
    monkeypatch.setattr(U.P, "check_signature", lambda *a, **k: {"status": "ok", "at": "0x17ff680"})
    assert U.judge({}, None, {}, "ClientPrint", "linux", sig("55 48"), sig("55 48 89"))[0] == "agrees"
    monkeypatch.setattr(U.P, "check_signature", lambda *a, **k: {"status": "ambiguous"})
    assert U.judge({}, None, {}, "ClientPrint", "linux", sig("55 48"), sig("55 48 89"))[0] == "broken"
