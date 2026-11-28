import struct

import yaml

import audit_identity_evidence as E


def test_method_token_and_selfname():
    assert E.method_token("CBaseEntity_Think") is None  # too short to be telling
    assert E.method_token("CWorldRendererMgr_CreateWorld_Internal") == "Internal"
    assert E.names_itself("CCSGameRules_TerminateRound", {b"CCSGameRules::TerminateRound( %d )"})
    assert not E.names_itself("CCSGameRules_TerminateRound", {b"TerminateRoundDelayed"})
    assert not E.names_itself("CBaseEntity_Think", {b"Think"})


def test_registration_names():
    assert E.registration_names("SayTeam_CommandHandler") == {b"CommandHandler", b"say_team"}
    assert E.registration_names("Say_CommandHandler") == {b"CommandHandler", b"say"}
    assert E.registration_names("CBaseEntity_ScriptStopSound") == {b"ScriptStopSound"}
    assert E.registration_names("CBaseEntity_Think") == set()


class FakeBinary:
    BASE = 0x1000

    def __init__(self, data, lea=None):
        self.data = bytes(data)
        self._lea = lea or {}

    def va_to_off(self, va):
        return va - self.BASE if self.BASE <= va < self.BASE + len(self.data) else None

    def lea_targets(self):
        return self._lea


def test_registered_through_a_data_table():
    # [ptr to "ScriptStopSound"] [ptr to function] ... "ScriptStopSound\0"
    func_va, name_va = 0x1100, 0x1040
    blob = bytearray(0x200)
    blob[0x40:0x50] = b"ScriptStopSound\0"
    blob[0x08:0x10] = struct.pack("<Q", name_va)
    blob[0x10:0x18] = struct.pack("<Q", func_va)
    binary = FakeBinary(blob)
    assert E.is_registered(binary, "CBaseEntity_ScriptStopSound", func_va)
    assert not E.is_registered(binary, "CBaseEntity_ScriptEmitSound", func_va)
    assert not E.is_registered(binary, "CBaseEntity_ScriptStopSound", 0x1180)


def test_registered_through_code_that_takes_the_address():
    # lea rsi,[rip+"say_team"] ; lea rdx,[rip+func]
    blob = bytearray(0x200)
    blob[0x100:0x109] = b"say_team\0"
    site_name, site_func, func_va = 0x1080, 0x1087, 0x1180
    blob[0x80:0x87] = b"\x48\x8d\x35" + struct.pack("<i", 0x1100 - (site_name + 7))
    blob[0x87:0x8E] = b"\x48\x8d\x15" + struct.pack("<i", func_va - (site_func + 7))
    binary = FakeBinary(blob, lea={func_va: [site_func]})
    assert E.is_registered(binary, "SayTeam_CommandHandler", func_va)
    assert not E.is_registered(binary, "Say_CommandHandler", func_va)


def test_confirmed_file_is_well_formed_and_disjoint():
    data = yaml.safe_load(open(E.CONFIRMED, encoding="utf-8"))
    confirmed, unproven = E.load_confirmed()
    assert set(data) <= {"confirmed", "unproven"}
    for key, why in confirmed.items():
        assert len(why) > 30, f"{key}: a confirmation says how it was proved"
    for entry in unproven:
        symbol, _, platform = entry.rpartition(".")
        assert platform in ("linux", "windows"), entry
        assert entry not in confirmed and symbol not in confirmed, f"{entry} is both confirmed and unproven"


def test_load_confirmed_missing_file(tmp_path):
    assert E.load_confirmed(str(tmp_path / "none.yaml")) == ({}, set())
