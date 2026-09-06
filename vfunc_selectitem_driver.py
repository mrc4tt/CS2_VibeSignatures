"""Alt+F7 i IDA med libserver.so / server.dll loadet.

Sådan:
  1. Find CCSPlayer_WeaponServices-vtable's SelectItem-slot:
     G til Weapon_GetSlot (linux: 0x1792B90), tast X (xrefs) - vtable-referencen
     (off_XXXXXX) er slot-entry'en. Dobbeltklik den.
  2. Placér cursor PÅ den qword (slot-entry) der peger på SelectItem.
  3. Alt+F7 -> vfunc_selectitem_driver.py

Slot fra matchzy gamedata: linux = 31, windows = 30.
"""
import ida_bytes
import ida_kernwin

ns = {"__name__": "cs2vibe_vfunc_driver"}
exec(open("/home/mikkel/CS2_VibeSignatures/ida_sig_maker.py").read(), ns)

SLOT = 31  # linux: 31, windows: 30 (fra matchzy.json offsets)

slot_ea = ida_kernwin.get_screen_ea()
func_ea = ida_bytes.get_qword(slot_ea)
print(f"[vfunc] slot-entry {hex(slot_ea)} -> funktion {hex(func_ea)}")
ns["emit_vfunc_yaml"](func_ea, "CCSPlayer_WeaponServices_SelectItem", "CCSPlayer_WeaponServices", SLOT)
