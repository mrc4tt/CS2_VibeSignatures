import pytest

import audit_twin_identity as T

pytest.importorskip("capstone")


class FakeBinary:
    """One executable segment at BASE holding `data`."""

    BASE = 0x1000

    def __init__(self, data):
        self.data = bytes(data)
        self.segments = [(self.BASE, len(self.data), 0, True)]

    def va_to_off(self, va):
        return va - self.BASE if self.BASE <= va < self.BASE + len(self.data) else None


def setter(state_offset, rip=0x11223344, jmp=0x100):
    # mov rax,[rip+x]; lea rsi,[rdi+state]; mov [rdi+0x5c8],rax; jmp rel32
    return (bytes.fromhex("488b05") + rip.to_bytes(4, "little") + bytes.fromhex("488db7") + state_offset.to_bytes(4, "little")
            + bytes.fromhex("488987c8050000") + b"\xe9" + jmp.to_bytes(4, "little"))


PAD = b"\xcc" * 6
SIZE = len(setter(0))


def binary(*offsets, rip=0x11223344):
    blob = b"".join(setter(o, rip=rip + i, jmp=0x100 - i * 0x20) + PAD for i, o in enumerate(offsets))
    return FakeBinary(blob)


def va(index):
    return FakeBinary.BASE + index * (SIZE + len(PAD))


def test_decode_masks_operands_and_keeps_only_non_address_ones():
    skeleton, operands = T.decode(setter(0x210), 0x1000)
    assert skeleton[:3] == (0x48, 0x8B, 0x05) and skeleton[3:7] == (None,) * 4
    assert [(kind, value.hex()) for _i, kind, value in operands] == [("disp", "10020000"), ("disp", "c8050000")]
    assert T.decode(setter(0x210)[:-2], 0x1000) is None  # cut mid-instruction


def test_same_twin_is_ok_even_when_addresses_moved():
    old, new = binary(0x210, 0x498), binary(0x210, 0x498, rip=0x55667788)
    assert T.twin_verdict(new, va(0), SIZE, old, va(0), SIZE)[0] == "OK"


def test_record_on_the_other_twin_is_swapped():
    old, new = binary(0x210, 0x498), binary(0x210, 0x498, rip=0x55667788)
    verdict, why = T.twin_verdict(new, va(1), SIZE, old, va(0), SIZE)
    assert verdict == "SWAPPED" and hex(va(0)) in why and "10020000 -> 98040000" in why


def test_layout_change_is_moved_not_swapped():
    old, new = binary(0x210, 0x498), binary(0x218, 0x4A0)
    assert T.twin_verdict(new, va(0), SIZE, old, va(0), SIZE)[0] == "MOVED"


def test_unknown_size_long_body_and_changed_stream_are_skipped():
    old, new = binary(0x210, 0x498), binary(0x210, 0x498)
    assert T.twin_verdict(new, va(0), 0, old, va(0), SIZE)[0] == "SKIP"
    assert T.twin_verdict(new, va(0), T.MAX_TWIN_SIZE + 1, old, va(0), SIZE)[0] == "SKIP"
    other = FakeBinary(bytes.fromhex("4883ec28" "488b07" "ff5060" "4883c428" "c3"))
    assert T.twin_verdict(other, 0x1000, len(other.data), old, va(0), SIZE)[0] == "SKIP"


def test_accepted_entries_name_a_pair_and_carry_a_reason():
    for pair, entries in T.ACCEPTED.items():
        new, _, old = pair.partition(":")
        assert new and old
        for label, why in entries.items():
            assert "/" in label and label.rsplit(".", 1)[1] in ("linux", "windows") and len(why) > 20


def test_two_twins_with_the_previous_operands_decide_nothing():
    old, new = binary(0x210, 0x498), binary(0x210, 0x498, 0x210)
    verdict, why = T.twin_verdict(new, va(1), SIZE, old, va(0), SIZE)
    assert verdict == "MOVED" and "undecided" in why


def test_swapped_twin_address_reads_the_verdict():
    old, new = binary(0x210, 0x498), binary(0x210, 0x498, rip=0x55667788)
    _verdict, why = T.twin_verdict(new, va(1), SIZE, old, va(0), SIZE)
    assert T.swapped_twin_address(why) == va(0)
    assert T.swapped_twin_address("same operands") is None


def test_relocation_twin_verdict_cannot_judge_without_a_previous_function(tmp_path):
    assert T.relocation_twin_verdict("linux", "0x1000", "0x1a", str(tmp_path), str(tmp_path / "none.yaml")) == (None, None)
    record = tmp_path / "X.linux.yaml"
    record.write_text("vtable_va: '0x10'\nfunc_va: '0x20'\n")
    assert T.relocation_twin_verdict("linux", "0x1000", "0x1a", str(tmp_path), str(record)) == (None, None)
    assert T.relocation_twin_verdict("linux", None, "0x1a", str(tmp_path), str(record)) == (None, None)
