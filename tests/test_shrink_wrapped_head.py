"""A relocated signature on a shrink-wrapped head IDA left outside its function.

14196 linux CNetworkGameServerBase_OnKickByName starts with `cmp [rdx+438h],1; jle`
at 0x51abe0, after padding; IDA made the function start at the `push rbp` at
0x51abed and left the test outside every function. The old signature matched
0x51abe0 uniquely and the preprocessor failed because no function started there,
so an agent was paid for it on 3 of 4 builds (and wrote the mid-function address).
Pinned here, with IDA faked: the function is moved to the match, and nothing moves
without padding before it or with a jump in between.
"""

import os
import sys
import types
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import ida_analyze_util  # noqa: E402

BADADDR = 0xFFFFFFFFFFFFFFFF


class FakeFunc:
    def __init__(self, start, end):
        self.start_ea, self.end_ea = start, end


def run(heads, funcs, addr, padded=True):
    """heads: {ea: (size, flows_in)}; funcs: list of (start, end)."""
    state = {"funcs": [FakeFunc(*f) for f in funcs]}

    def get_func(ea):
        return next((f for f in state["funcs"] if f.start_ea <= ea < f.end_ea), None)

    def del_func(ea):
        state["funcs"] = [f for f in state["funcs"] if f.start_ea != ea]
        return True

    def add_func(ea):
        nxt = min((f for f in state["funcs"] if f.start_ea > ea), key=lambda f: f.start_ea, default=None)
        state["funcs"].append(FakeFunc(ea, ea + 0x13E))
        return nxt is None or nxt.start_ea >= ea + 0x13E

    flags = {ea: ("code", flows) for ea, (_size, flows) in heads.items()}
    flags[addr - 1] = ("align", False)
    order = sorted(heads)
    ida_bytes = types.SimpleNamespace(
        get_flags=lambda ea: flags.get(ea, ("data", False)),
        is_align=lambda fl: fl[0] == "align" and padded,
        is_code=lambda fl: fl[0] == "code",
        is_flow=lambda fl: fl[1],
        get_byte=lambda ea: 0xCC if padded else 0x48,
        prev_head=lambda ea, _lo: addr - 1 if ea == addr else BADADDR,
        next_head=lambda ea, hi: next((h for h in order if h > ea), hi),
    )
    ida_funcs = types.SimpleNamespace(
        get_func=get_func,
        del_func=del_func,
        add_func=add_func,
        get_next_func=lambda ea: min((f for f in state["funcs"] if f.start_ea > ea),
                                     key=lambda f: f.start_ea, default=None),
    )
    idaapi = types.SimpleNamespace(get_func=get_func, BADADDR=BADADDR)
    modules = {"idaapi": idaapi, "ida_bytes": ida_bytes, "ida_funcs": ida_funcs,
               "ida_ua": types.SimpleNamespace(), "idc": types.SimpleNamespace()}
    saved = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        scope = {"idaapi": idaapi, "addr": addr, "f": get_func(addr)}
        exec(ida_analyze_util._SHRINK_WRAPPED_HEAD_REPAIR, scope)
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    return scope["f"]


ONKICK_HEADS = {0x51ABE0: (7, False), 0x51ABE7: (6, True), 0x51ABED: (1, True)}


class ShrinkWrappedHead(unittest.TestCase):
    def test_the_function_moves_to_the_match(self):
        f = run(ONKICK_HEADS, [(0x51ABED, 0x51AD1E)], 0x51ABE0)
        self.assertIsNotNone(f)
        self.assertEqual(f.start_ea, 0x51ABE0)

    def test_no_padding_no_move(self):
        self.assertIsNone(run(ONKICK_HEADS, [(0x51ABED, 0x51AD1E)], 0x51ABE0, padded=False))

    def test_a_head_not_reached_by_fallthrough_stays(self):
        heads = {**ONKICK_HEADS, 0x51ABED: (1, False)}
        self.assertIsNone(run(heads, [(0x51ABED, 0x51AD1E)], 0x51ABE0))

    def test_a_match_inside_a_function_is_left_alone(self):
        f = run(ONKICK_HEADS, [(0x51ABD0, 0x51AD1E)], 0x51ABE0)
        self.assertEqual(f.start_ea, 0x51ABD0, "the caller's start_ea check still rejects it")


if __name__ == "__main__":
    unittest.main()
