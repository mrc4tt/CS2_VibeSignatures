#!/usr/bin/env python3
"""Regenerate CounterStrikeSharp gamedata linux signatures from old -> new gamever.

For every CSS gamedata entry that carries a linux *signature*, this takes the
existing (old) sig, relocates it on the new gamever's libserver.so, and
regenerates a fresh minimal-unique function-head signature via the same MCP
sig-generator the main pipeline uses. Entries whose old sig no longer uniquely
matches (the function changed) are reported as broken for targeted follow-up.
Offset-type entries are reported, not regenerated (they need vtable analysis).

Usage:
  uv run regen_css_linux.py -gamever 14168 \
      [-gamedata PATH] [-module server] [-write] [-no-backup]

Defaults: -gamedata = the CSS install gamedata.json under $CSS_INSTALL
(or the repo dist copy if the install is absent). Without -write it is a
dry-run (reports what would change).
"""

import argparse
import asyncio
import json
import os
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

import ida_analyze_bin as AB
import ida_analyze_util as AU

HOST = AB.DEFAULT_HOST
PORT = AB.DEFAULT_PORT
URL = f"http://{HOST}:{PORT}/mcp"

# py_eval: count/collect matches of a masked byte pattern across the whole image.
_SEARCH_PY = r"""
import json, ida_bytes, ida_ida, ida_funcs
sig = %r
pat = ida_bytes.compiled_binpat_vec_t()
err = ida_bytes.parse_binpat_str(pat, ida_ida.inf_get_min_ea(), sig, 16)
res = {"parse_err": err, "hits": [], "func_starts": []}
if not err:
    start = ida_ida.inf_get_min_ea(); end = ida_ida.inf_get_max_ea()
    ea = start
    for _ in range(20):
        out = ida_bytes.bin_search(ea, end, pat, ida_bytes.BIN_SEARCH_FORWARD)
        hit = out[0] if isinstance(out, tuple) else out
        if hit is None or hit == ida_ida.BADADDR or hit == 0xffffffffffffffff:
            break
        res["hits"].append(hit)
        f = ida_funcs.get_func(hit)
        res["func_starts"].append(int(f.start_ea) if f else int(hit))
        ea = hit + 1
print(json.dumps(res))
"""


def gd_sig_to_search(s):
    # gamedata uses a single '?' per wildcard byte; parse_binpat_str wants '??'
    return " ".join("??" if t == "?" else t for t in s.split())


def sig_to_gd(s):
    # generator emits '??' per wildcard byte; gamedata stores a single '?'
    return " ".join("?" if t in ("??", "?") else t for t in s.split())


async def _call_text(session, name, args):
    r = await session.call_tool(name=name, arguments=args)
    txt = None
    for c in r.content:
        txt = getattr(c, "text", None)
    return txt


async def search_sig(session, gd_sig):
    txt = await _call_text(session, "py_eval", {"code": _SEARCH_PY % gd_sig_to_search(gd_sig)})
    try:
        d = json.loads(txt.strip().splitlines()[-1])
    except Exception:
        return None, []
    return d.get("hits", []), d.get("func_starts", [])


async def get_image_base(session):
    txt = await _call_text(session, "survey_binary", {"detail_level": "minimal"})
    try:
        meta = json.loads(txt).get("metadata", {})
        return int(str(meta.get("base_address", "0")), 0)
    except Exception:
        return 0


async def wait_ready(session, timeout=600):
    import time as _t

    deadline = _t.time() + timeout
    while _t.time() < deadline:
        txt = await _call_text(session, "survey_binary", {"detail_level": "minimal"})
        try:
            meta = json.loads(txt).get("metadata") if txt else None
        except Exception:
            meta = None
        if meta and (meta.get("sha256") or meta.get("md5")):
            return True
        await asyncio.sleep(3)
    return False


async def run(args, gd, binpath):
    image_base = None
    kept = regen = broken = offset = 0
    changed = {}
    broken_list = []
    offset_list = []
    async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30.0, read=300.0), trust_env=False) as hc:
        async with streamable_http_client(URL, http_client=hc) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                print("  waiting for analysis...")
                if not await wait_ready(session):
                    print("  ERROR: analysis not ready in time")
                    return None
                image_base = await get_image_base(session)
                print(f"  analysis ready (image_base={hex(image_base)})")
                for key, ent in gd.items():
                    sigs = ent.get("signatures")
                    if not (isinstance(sigs, dict) and sigs.get("linux")):
                        if "offsets" in ent:
                            offset += 1
                            offset_list.append(key)
                        continue
                    old = sigs["linux"]
                    hits, starts = await search_sig(session, old)
                    if hits is None:
                        broken += 1
                        broken_list.append((key, "parse-error"))
                        continue
                    uniq_starts = sorted(set(starts))
                    if len(hits) == 1 and len(uniq_starts) == 1:
                        fva = uniq_starts[0]
                        try:
                            res = await AU.preprocess_gen_func_sig_via_mcp(session, fva, image_base)
                        except Exception as e:
                            res = None
                            if args.debug:
                                print(f"    {key}: gen error {e!r}")
                        new_sig = res.get("func_sig") if isinstance(res, dict) else None
                        if new_sig:
                            new_gd = sig_to_gd(new_sig)
                            if new_gd != old:
                                changed[key] = new_gd
                                regen += 1
                                print(f"  REGEN   {key}")
                            else:
                                kept += 1
                                print(f"  same    {key}")
                        else:
                            # old sig still unique but couldn't regen -> keep old (still valid)
                            kept += 1
                            print(f"  keep    {key} (regen failed, old sig still unique)")
                    else:
                        broken += 1
                        reason = "no-match" if len(hits) == 0 else f"multi({len(hits)})"
                        broken_list.append((key, reason))
                        print(f"  BROKEN  {key} [{reason}]")
    return dict(
        kept=kept,
        regen=regen,
        broken=broken,
        offset=offset,
        changed=changed,
        broken_list=broken_list,
        offset_list=offset_list,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-gamever", required=True)
    ap.add_argument("-gamedata", default=None, help="gamedata.json to read/update (default: CSS install)")
    ap.add_argument("-module", default="server")
    ap.add_argument("-bindir", default="bin")
    ap.add_argument("-write", action="store_true", help="write regenerated sigs back (default: dry-run)")
    ap.add_argument("-no-backup", dest="backup", action="store_false")
    ap.add_argument("-debug", action="store_true")
    args = ap.parse_args()

    css_install = os.environ.get("CSS_INSTALL", os.path.expanduser("~/CounterStrikeSharp"))
    install_gd = os.path.join(css_install, "configs/addons/counterstrikesharp/gamedata/gamedata.json")
    dist_gd = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "dist/CounterStrikeSharp/config/addons/counterstrikesharp/gamedata/gamedata.json",
    )
    gdpath = args.gamedata or (install_gd if os.path.exists(install_gd) else dist_gd)
    if not os.path.exists(gdpath):
        print(f"Error: gamedata not found: {gdpath}")
        sys.exit(1)
    binpath = os.path.join(args.bindir, args.gamever, args.module, "libserver.so")
    if not os.path.exists(binpath):
        print(f"Error: binary not found: {binpath}")
        sys.exit(1)

    print(f"gamedata : {gdpath}")
    print(f"binary   : {binpath}")
    print(f"mode     : {'WRITE' if args.write else 'dry-run'}")

    gd = json.load(open(gdpath, encoding="utf-8"))

    AB._preflight_cleanup(args.bindir, args.gamever)
    proc = AB.start_idalib_mcp(binpath, HOST, PORT, "", args.debug)
    if proc is None:
        print("Error: failed to start idalib-mcp")
        sys.exit(1)
    try:
        stats = asyncio.run(run(args, gd, binpath))
    finally:
        AB.quit_ida_gracefully(proc, HOST, PORT, debug=args.debug)

    if stats is None:
        sys.exit(1)

    print("\n=== summary ===")
    print(f"  regenerated : {stats['regen']}")
    print(f"  unchanged   : {stats['kept']}")
    print(f"  broken sig  : {stats['broken']}  (function changed -> need targeted regen)")
    print(f"  offset-type : {stats['offset']}  (not handled here)")
    if stats["broken_list"]:
        print("\n  BROKEN (linux sig no longer unique):")
        for k, why in stats["broken_list"]:
            print(f"    {k} [{why}]")
    if stats["offset_list"]:
        print("\n  OFFSET entries (verify/regen separately):")
        for k in stats["offset_list"]:
            print(f"    {k}")

    if args.write and stats["changed"]:
        if args.backup:
            import time as _t

            bak = gdpath + ".bak." + str(int(os.path.getmtime(gdpath)))
            with open(bak, "w", encoding="utf-8") as f:
                json.dump(gd, f, indent=2)
            print(f"\n  backup -> {bak}")
        for k, v in stats["changed"].items():
            gd[k]["signatures"]["linux"] = v
        with open(gdpath, "w", encoding="utf-8") as f:
            json.dump(gd, f, indent=2)
            f.write("\n")
        print(f"  wrote {len(stats['changed'])} regenerated linux sigs -> {gdpath}")
    elif stats["changed"]:
        print(f"\n  (dry-run) {len(stats['changed'])} sigs would change; pass -write to apply")


if __name__ == "__main__":
    main()
