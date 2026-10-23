#!/usr/bin/env python3
"""
Do the plugins call the shipped functions with as many arguments as the binary reads?

A plugin declares how it calls a gamedata function in its own source:

  MemoryFunctionVoid<IntPtr, string> SetModelFunc = new(() => GameData.GetSignature("CBaseModelEntity_SetModel"));
  VirtualFunction.CreateVoid<IntPtr, CsTeam>(Handle, GameData.GetOffset("CCSPlayerController_ChangeTeam"))

audit_arg_fingerprint.py says what the function in THIS build reads before writing:
which argument registers and stack slots. When the function reads more than the
plugin passes, it reads garbage - the crash a correct address cannot prevent, and the
one that comes with a game update that adds a parameter. The fingerprint is a lower
bound, so the opposite (a plugin passing more) is not reported.

Positions: linux counts integer/pointer and float arguments separately (rdi.. and
xmm0..); windows numbers every argument once (rcx/xmm0, rdx/xmm1, ...). float/double
declare a float argument, everything else an integer or pointer one.

  uv run audit_plugin_declarations.py -gamever 14190
  uv run audit_plugin_declarations.py -gamever 14190 -root ~/customGIT -root ~/CounterStrikeSharp/managed

Exit 0 every declaration covers what the function reads, 1 at least one does not.
"""

import argparse
import os
import re
import sys

import audit_arg_fingerprint as A
import validate_artifacts as V
import verify_plugin_gamedata as P

DEFAULT_ROOTS = ("~/CounterStrikeSharp/managed", "~/customGIT", "~/plugins")
SKIP_DIRS = {"bin", "obj", ".git", "node_modules"}
FLOAT_TYPES = {"float", "double", "single", "system.single", "system.double"}

# Declarations that pass fewer arguments on purpose, with the reason. A known shortfall is
# listed, not counted - the same treatment as an [Obsolete] binding.
KNOWN_SHORT = {
    # CounterStrikeSharp VirtualFunctions.cs:110 - a compatibility alias older plugins (WC3)
    # HOOK with (entity, info); DynamicHook reads parameters by index, so the declared
    # arity does not matter there, and direct calls are pointed at the 3-argument
    # CBaseEntity_TakeDamageOldFunc.
    "CBaseEntity_TakeDamage": "hook-only compatibility alias; call CBaseEntity_TakeDamageOld",
}

KEY = r'GameData\.Get(?P<kind>Signature|Offset)\(\s*"(?P<key>[^"]+)"\s*\)'
GEN = r"<(?P<generics>[^;{}()]*?)>"
PATTERNS = (
    # MemoryFunctionVoid<...> Name = new(GameData.GetSignature("K")) / new(() => GameData...)
    re.compile(r"MemoryFunction(?P<flavour>Void|WithReturn)" + GEN + r"\s+\w+\s*=\s*new\s*\(\s*(?:\(\)\s*=>\s*)?" + KEY, re.S),
    # new MemoryFunctionVoid<...>(GameData.GetSignature("K"))
    re.compile(r"new\s+MemoryFunction(?P<flavour>Void|WithReturn)" + GEN + r"\s*\(\s*(?:\(\)\s*=>\s*)?" + KEY, re.S),
    # VirtualFunction.CreateVoid<...>(handle, GameData.GetOffset("K"))
    re.compile(r"VirtualFunction\.Create(?P<flavour>Void)?" + GEN + r"\s*\([^;]{0,200}?" + KEY, re.S),
)


def split_generics(text):
    """'IntPtr, Func<int, int>, string' -> ['IntPtr', 'Func<int, int>', 'string']."""
    out, depth, current = [], 0, ""
    for ch in text:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        out.append(current.strip())
    return out


def declarations(roots):
    """[{key, kind, params, file, line}] for every gamedata-backed function a plugin declares."""
    found = []
    for root in roots:
        root = os.path.expanduser(root)
        for base, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and "Test" not in d]
            for name in names:
                if not name.endswith(".cs"):
                    continue
                path = os.path.join(base, name)
                try:
                    text = open(path, encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                for pattern in PATTERNS:
                    for match in pattern.finditer(text):
                        generics = split_generics(match.group("generics"))
                        void = match.group("flavour") == "Void"
                        params = generics if void else generics[:-1]
                        # an [Obsolete] declaration is a known shortfall kept for binary
                        # compatibility (CSS's CBasePlayerController_SetPawnFunc passes two of
                        # SetPawn's four flags, beside a SetPawnFullFunc that passes all)
                        preceding = text[max(0, match.start() - 400):match.start()]
                        last_decl = max(preceding.rfind(";"), preceding.rfind("}"))
                        obsolete = "[Obsolete" in preceding[last_decl + 1:]
                        found.append({"key": match.group("key"), "kind": match.group("kind").lower(),
                                      "params": params, "file": path, "obsolete": obsolete,
                                      "line": text.count("\n", 0, match.start()) + 1})
    unique = {}
    for item in found:
        unique.setdefault((item["key"], tuple(item["params"]), item["file"]), item)
    return list(unique.values())


def declared_counts(params, platform):
    floats = sum(1 for p in params if p.strip().lower() in FLOAT_TYPES)
    if platform == "windows":
        return {"positions": len(params)}
    return {"int": len(params) - floats, "float": floats}


def observed_counts(fp, platform):
    if platform == "windows":
        int_pos = [A.INT_ARGS["windows"].index(r) + 1 for r in fp["int"]]
        float_pos = [int(r[3:]) + 1 for r in fp["float"]]
        return {"positions": max([0] + int_pos + float_pos + ([4 + fp["stack"]] if fp["stack"] else []))}
    ints = max([0] + [A.INT_ARGS["linux"].index(r) + 1 for r in fp["int"]])
    if fp["stack"]:
        ints = max(ints, 6 + fp["stack"])
    return {"int": ints, "float": max([0] + [int(r[3:]) + 1 for r in fp["float"]])}


def record_for(index, key, platform):
    record = P.resolve_record(index, key, platform)
    if record is None and "::" in key:
        record = P.resolve_record(index, key.replace("::", "_"), platform)
    return record


def audit(gamever, roots):
    index = P.load_snapshot_index(os.path.join("gamesymbols", f"{gamever}.yaml"))
    config = os.path.join("configs", f"{gamever}.yaml")
    if os.path.isfile(config):
        P.GENERATOR_ALIASES.update(P.load_generator_aliases(config))
    # plugin keys routed by their own generator; the source trees here span several plugins
    from gamedata_utils import enabled_generator_key_overrides
    for overrides in enabled_generator_key_overrides().values():
        P.GENERATOR_ALIASES.update({P.fold(key): symbol for key, symbol in overrides.items()})
    binaries = P.Binaries("bin", gamever)
    rows, unresolved = [], set()
    for decl in declarations(roots):
        for platform in ("linux", "windows"):
            record = record_for(index, decl["key"], platform)
            if not record or not record.get("func_va"):
                unresolved.add(decl["key"])
                continue
            blob, info, _ = binaries.get(record.get("_module") or "server", platform)
            if blob is None:
                continue
            fp = A.fingerprint(blob, info, V._hexint(record["func_va"]), platform)
            if not fp:
                continue
            declared, observed = declared_counts(decl["params"], platform), observed_counts(fp, platform)
            short = [k for k in observed if observed[k] > declared.get(k, 0)]
            rows.append(dict(decl, platform=platform, declared=declared, observed=observed,
                             reads=fp["int"] + fp["float"], stack=fp["stack"], short=short))
    return rows, sorted(unresolved)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-gamever", required=True)
    parser.add_argument("-root", action="append", default=None,
                        help="plugin source tree (repeatable); default: " + ", ".join(DEFAULT_ROOTS))
    parser.add_argument("-v", action="store_true", help="also list the declarations that match")
    args = parser.parse_args()
    if A.capstone is None:
        print("audit_plugin_declarations: capstone is required", file=sys.stderr)
        return 2
    rows, unresolved = audit(args.gamever, args.root or DEFAULT_ROOTS)
    for r in rows:
        r["known"] = r["obsolete"] or r["key"] in KNOWN_SHORT
    bad = [r for r in rows if r["short"] and not r["known"]]
    known = [r for r in rows if r["short"] and r["known"]]
    for r in (rows if args.v else bad + known):
        where = f"{os.path.relpath(r['file'], os.path.expanduser('~'))}:{r['line']}"
        verdict = ("known" if r["known"] else "SHORT") if r["short"] else "ok"
        print(f"{verdict:5} {r['key']}.{r['platform']}: plugin passes {r['declared']}, function reads "
              f"{r['observed']} ({'+'.join(r['reads']) or '-'}{' +%d stack' % r['stack'] if r['stack'] else ''})"
              f"  [{where}]")
    print(f"audit_plugin_declarations {args.gamever}: {len(rows)} declaration(s) checked on their platforms, "
          f"{len(bad)} pass fewer arguments than the function reads"
          + (f" ({len(known)} more known: [Obsolete] or KNOWN_SHORT)" if known else "")
          + (f"; no function record for {len(unresolved)} key(s)" if unresolved else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
