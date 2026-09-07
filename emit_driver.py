"""Alt+F7 this file inside IDA (with the target binary loaded).
Edit the calls at the bottom - one emit per symbol:
    ns["emit_yaml"](0xAF8F90, "CCSPlayerPawn_SetModelFromLoadout")
"""
ns = {"__name__": "cs2vibe_emit_driver"}
exec(open("/root/CS2_VibeSignatures/ida_sig_maker.py").read(), ns)

# --- your symbols here (VA + symbol name) ---
ns["emit_yaml"](0xAF8F90, "CCSPlayerPawn_SetModelFromLoadout")
# ns["emit_yaml"](0x??????, "Next_Symbol_Name")
