#!/usr/bin/env python3
"""Generate offsets-anchors.json — the re-find recipe for every `offsets` entry
in the tracked gamedata files.

A bare `{"offsets": {"linux": 102, "windows": 103}}` carries no clue about WHICH
function/member that slot is, so it can't be regenerated on a new game version.
This map fixes that: per offset symbol it records how to relocate the target on a
fresh binary, so the regen-gamedata-linux skill (and, later, the headless
cs2-sig-tracker) can re-derive the index.

Source of truth = the AST-importable constants in
`ida_preprocessor_scripts/find-*.py` (same idea as recipe_import_from_ida_dir):

    FUNC_VTABLE_RELATIONS  (func, vtable_class)   -> kind=vtable
    FUNC_XREFS[].xref_strings                     -> anchor string to locate func
    TARGET_STRUCT_MEMBER_NAMES                    -> kind=structoffset
    TARGET_GLOBALVAR_NAMES                        -> kind=global

The 10 clean vtable offsets classify automatically. The other 8 CSS offset
entries are heterogeneous (some struct members, some globals, some vtable slots
whose class relation isn't declared) and are curated in CURATED below with
needs_review=true where a human must confirm the class/kind once.

Run:  python3 gen_offset_anchors.py        # writes offsets-anchors.json here
      python3 gen_offset_anchors.py --print # stdout only

Re-run whenever the preprocessor scripts change; the curated block only covers
symbols the scripts don't self-describe.
"""
import ast
import glob
import json
import os

REPO = os.path.expanduser("~/CS2_VibeSignatures")
SCRIPTS = os.path.join(REPO, "ida_preprocessor_scripts")
GAMEDATA = {
    "CSS": os.path.expanduser(
        "~/CounterStrikeSharp/configs/addons/counterstrikesharp/gamedata/gamedata.json"
    ),
    "matchzy": os.path.expanduser("~/customGIT/matchzy/gamedata/matchzy.json"),
    "weaponpaints": os.path.expanduser("~/customGIT/weaponpaints/gamedata/weaponpaints.json"),
}

# Curated recipes for the 8 CSS offset entries the preprocessor scripts don't
# self-classify. Each: kind, plus how to relocate the target. needs_review=true
# = confirm the class/kind against the binary the first time you regen.
CURATED = {
    "CCSGameRules_FindPickerEntity": {
        "kind": "vtable", "vtable_class": "CCSGameRules",
        "source_script": "find-CCSGameRules_FindPickerEntity.py",
        "note": "virtual; CCSGameRules primary vtable. Confirmed on 14171: slot 27 resolves into .text.",
        "needs_review": False,
    },
    "CTakeDamageInfo_HitGroup": {
        "kind": "structoffset", "struct": "CTakeDamageInfo", "member": "m_iHitGroup",
        "source_script": "find-CTakeDamageInfo_HitGroupInfo.py",
        "anchor_func": "TraceAttack",
        "note": "member offset (104=0x68), NOT a vtable index. RECIPE: relocate TraceAttack via its sig on the NEW build first (reference YAML func_va is stale across builds), then decompile it and read the m_iHitGroup member access displacement. Confirmed the stale-VA trap on 14171.",
        "needs_review": True,
    },
    "CBaseEntity_IsPlayerPawn": {
        "kind": "vtable", "vtable_class": "CBaseEntity",
        "source_script": "find-CBaseEntity_IsPlayerPawn.py",
        "note": "declared via FUNC_VTABLE_RELATIONS if present; else CBaseEntity primary vtable slot.",
        "needs_review": False,
    },
    "GameEntitySystem": {
        "kind": "structoffset", "struct": "CGameResourceService", "member": "m_pGameEntitySystem",
        "source_script": "find-CGameEntitySystem_ctor.py",
        "note": "MEMBER offset on CGameResourceService (80 linux / 88 win): *(CGameEntitySystem**)(service+80). CSS cgameresourceserviceserver.h. 14171 head-start: CGameEntitySystem primary vtable 0x249cb18; ctors 0x16a5250 + 0x16e0920 (both set *(_QWORD*)a1=&off_249CB28); heap object is 8448 bytes; creation factory 0x16fea60 registers it under string \"server_entities\". The service+80 store is INDIRECT (via register call to qword_28bac38), not a plain inline ctor(service+80) — needs anchor-relocation + deeper decompile (LLM/reference-YAML tier), not a one-shot walk. NOTE: those VAs are 14171-specific, illustrative only.",
        "needs_review": True,
    },
    "GameEventManager": {
        "kind": "structoffset", "struct": None, "member": None,
        "source_script": None,
        "note": "MEMBER offset (93), NOT a vtable index: CGameEventManager primary vtable has only 17 slots on 14171, so 93 cannot be a slot there. Likely a member offset on a session/service object. Reclassify with the real owning struct; investigate CSS usage of GetOffset('GameEventManager').",
        "needs_review": True,
    },
    "CEntityResourceManifest_AddResource": {
        "kind": "vtable", "vtable_class": "IEntityResourceManifest",
        "source_script": None,
        "note": "vtable slot (0 linux / 2 win) of IEntityResourceManifest::AddResource. CSS: VirtualFunction.CreateVoid<nint,string>(Handle, GetOffset(...)) (ResourceManifest.cs), 3 AddResource overloads in game_system.h. Abstract interface -> no plain RTTI typeinfo string on 14171 (all name variants 0 matches). Resolve via the concrete manifest impl's vtable, or accept the small stable index (0/2).",
        "needs_review": True,
    },
    "CheckTransmitPlayerSlot": {
        "kind": "structoffset", "struct": "CCheckTransmitInfo", "member": "m_nPlayerSlot",
        "source_script": "find-CCheckTransmitInfo_m_nPlayerSlot.py",
        "anchor_func": "CSource2GameEntities_CheckTransmit",
        "note": "member offset. CONFIRMED 576 on 14171: CheckTransmit decompile reads *(uint*)(info + 576) -> slot-convert. Anchor = CheckTransmit func (RTTI ISource2GameEntities slot 13).",
        "needs_review": False,
    },
    "SetStateChanged": {
        "kind": "vtable", "vtable_class": "CBaseEntity",
        "source_script": None,
        "note": "CONFIRMED slot 29 on 14171. Entity networkable dispatcher: CSS CALL_VIRTUAL(void,29,pEntity,&CNetworkStateChangedInfo) (schema.cpp). slot29 func takes (entity, info*), routes through the transmit component at entity+56, else marks dirty flags. MUST validate on a CONCRETE entity vtable (CBaseEntity / CCSPlayerController share the same slot29 func); the abstract CEntityInstance primary vtable has a nullsub placeholder at slot 29.",
        "needs_review": False,
    },
    "ISource2GameEntities::CheckTransmit": {
        "kind": "vtable", "vtable_class": "CSource2GameEntities",
        "source_script": "find-CSource2GameEntities_CheckTransmit.py",
        "note": "interface vtable slot (13 linux / 12 win). Anchor func = CSource2GameEntities::CheckTransmit.",
        "needs_review": False,
    },
}


def _literal(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def import_scripts():
    """AST-import per-symbol data from every find-*.py. No IDA imports executed."""
    vtable_rel = {}   # func -> vtable_class
    xrefs = {}        # func -> [strings]
    struct_members = set()  # struct member symbol names seen
    globalvars = set()
    for p in glob.glob(os.path.join(SCRIPTS, "find-*.py")):
        try:
            tree = ast.parse(open(p, encoding="utf-8").read())
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            name = getattr(node.targets[0], "id", "")
            val = _literal(node.value)
            if val is None:
                continue
            if name == "FUNC_VTABLE_RELATIONS":
                for tup in val:
                    if isinstance(tup, (list, tuple)) and len(tup) >= 2:
                        vtable_rel.setdefault(tup[0], tup[1])
            elif name == "FUNC_XREFS":
                for d in val:
                    if isinstance(d, dict) and d.get("xref_strings"):
                        xrefs.setdefault(d["func_name"], d["xref_strings"])
            elif name == "TARGET_STRUCT_MEMBER_NAMES":
                for s in val:
                    struct_members.add(s)
            elif name == "TARGET_GLOBALVAR_NAMES":
                for s in val:
                    globalvars.add(s)
    return vtable_rel, xrefs, struct_members, globalvars


def build():
    vtable_rel, xrefs, _sm, _gv = import_scripts()
    out = {"_comment": "Re-find recipe per offsets entry. kind: vtable|structoffset|global. "
                       "Generated by gen_offset_anchors.py from ida_preprocessor_scripts + CURATED. "
                       "linux first; windows uses MSVC RTTI (resolve separately).",
           "files": {}}
    for tag, path in GAMEDATA.items():
        if not os.path.exists(path):
            continue
        gd = json.load(open(path, encoding="utf-8"))
        entries = {}
        for sym, ent in gd.items():
            if "offsets" not in ent:
                continue
            rec = {"offsets": ent["offsets"]}
            if sym in vtable_rel:
                rec["kind"] = "vtable"
                rec["vtable_class"] = vtable_rel[sym]
                rec["anchor_strings"] = xrefs.get(sym, [])
                rec["func_find"] = "find-" + sym  # skill/recipe that locates the target func
                rec["needs_review"] = False
            elif sym in CURATED:
                rec.update(CURATED[sym])
                if "anchor_strings" not in rec:
                    rec["anchor_strings"] = xrefs.get(sym, [])
            else:
                rec["kind"] = "unknown"
                rec["needs_review"] = True
                rec["note"] = "no vtable_relation and not curated — classify manually (vtable/structoffset/global)."
            entries[sym] = rec
        out["files"][tag] = entries
    return out


def main():
    import sys
    data = build()
    txt = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if "--print" in sys.argv:
        print(txt)
        return
    dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), "offsets-anchors.json")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(txt)
    # short summary
    for tag, entries in data["files"].items():
        kinds = {}
        review = 0
        for r in entries.values():
            kinds[r.get("kind", "?")] = kinds.get(r.get("kind", "?"), 0) + 1
            review += 1 if r.get("needs_review") else 0
        print("%-12s %2d offsets  %s  needs_review=%d" % (tag, len(entries), kinds, review))
    print("wrote", dst)


if __name__ == "__main__":
    main()
