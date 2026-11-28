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

        self.segments = [(self.BASE, len(self.data), 0, True)]

    def enclosing(self, va, limit=0x8000):
        return va & ~0xF, (va & ~0xF) + 0x10

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


def test_class_evidence_vtable_and_ctor(monkeypatch):
    vtable_va, method_va, ctor_va, dtor_va = 0x1100, 0x1040, 0x1060, 0x1010
    blob = bytearray(0x200)
    # ctor body: lea rax,[rip+vtable]
    blob[0x60:0x67] = b"\x48\x8d\x05" + struct.pack("<i", vtable_va - (ctor_va + 7))
    binary = FakeBinary(blob)
    monkeypatch.setattr(E, "class_vtables", lambda *a: [(vtable_va, [dtor_va, method_va])] if a[4] == "CThing" else [])
    args = ("bin", "1", "server", "linux")
    assert E.class_evidence(*args, "CThing_Method", method_va, binary, 0x10) == "vtable"
    assert E.class_evidence(*args, "CThing_Method", 0x1080, binary, 0x10) is None
    assert E.class_evidence(*args, "CThing_CThing", ctor_va, binary, 0x10) == "ctor"
    assert E.class_evidence(*args, "CThing_ctor", ctor_va, binary, 0x10) == "ctor"
    # a destructor also stores the vtable, but is an entry of it
    assert E.class_evidence(*args, "CThing_CThing", dtor_va, binary, 0x10) is None
    assert E.class_evidence(*args, "COther_Method", method_va, binary, 0x10) is None
    assert E.class_evidence(*args, "FreeFunction", method_va, binary, 0x10) is None


def test_call_setup_separates_neighbouring_registrations():
    # lea rdx,f1; lea rsi,"NameOne"; call; lea rdx,f2; lea rsi,"NameTwo"; call
    blob = bytearray(0x200)
    blob[0x100:0x108] = b"NameOne\0"
    blob[0x110:0x118] = b"NameTwo\0"
    f1, f2 = 0x1180, 0x1190

    def lea(reg, at, target):
        return b"\x48\x8d" + bytes([reg]) + struct.pack("<i", target - (at + 7))

    code, at = b"", 0x1080
    site1 = at; code += lea(0x15, at, f1); at += 7
    code += lea(0x35, at, 0x1100); at += 7
    code += b"\xe8\x00\x00\x00\x00"; at += 5
    site2 = at; code += lea(0x15, at, f2); at += 7
    code += lea(0x35, at, 0x1110); at += 7
    code += b"\xe8\x00\x00\x00\x00"
    blob[0x80:0x80 + len(code)] = code
    binary = FakeBinary(blob, lea={f1: [site1], f2: [site2]})
    assert E._names_in_call_setup(binary, site1) == {b"NameOne"}
    assert E._names_in_call_setup(binary, site2) == {b"NameTwo"}
