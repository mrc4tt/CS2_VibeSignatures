#!/usr/bin/env python3
"""
Keep each generator's template in step with the plugin's own gamedata file.

A generator starts from a template - the plugin's file as it was when the generator was
written - and rewrites the values it has analysis for. A plugin moves on without us: it
adds keys (bot-controller gained four), drops or renames them (bot-hider renamed
SameMapTeardown to EndMatchState), and its author fixes values. Our file then ships keys
the plugin no longer reads and lacks the ones it does.

For every generator that names its source with a "# Seed source: <url>" line (one per file;
a generator whose template lives apart from its output, like SwiftlyS2's two files, writes
"# Seed source: <url> template=<path> output=<path>") this fetches
the plugin's current file and reports, per plugin:

  added      keys the plugin reads that the template lacks - with whether this repo has a
             record for them, and an alias suggestion when the plugin's signature lands on
             one of our functions (that is how EndMatchState was found to be SameMapTeardown)
  removed    keys the template has and the plugin no longer reads
  disagrees  keys we analyse whose generated value differs from the plugin author's and
             where his value points somewhere else in the binary - the check that found
             bot-hider's m_UserIDString/m_bIsHLTV misreads on 14190

-apply writes the plugin's file as the new template. Generation still writes our verified
value for every key we analyse; a key we have no record for keeps the plugin author's
value and is reported by verify_plugin_gamedata as "upstream", not verified by us.

  uv run sync_plugin_templates.py -gamever 14190            # report
  uv run sync_plugin_templates.py -gamever 14190 -apply     # and refresh the templates

Exit 0 nothing to do, 1 something changed or disagrees, 2 a fetch failed.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request

import validate_artifacts as V
import verify_plugin_gamedata as P

GENERATORS = "gamedata-generators"
SEED = re.compile(r"^#\s*Seed source:\s*(\S+)(?:\s+template=(\S+)\s+output=(\S+))?", re.M)


def sources(generators_dir=GENERATORS):
    """[(plugin, url, template path, generated file name)] for every enabled generator that names its source."""
    out = []
    for plugin in sorted(os.listdir(generators_dir)):
        module = os.path.join(generators_dir, plugin, "gamedata.py")
        if not os.path.isfile(module):
            continue
        text = open(module, encoding="utf-8").read()
        if re.search(r"^MODULE_ENABLED\s*=\s*False\b", text, re.M):
            continue
        path = re.search(r'^GAMEDATA_PATH\s*=\s*"([^"]+)"', text, re.M)
        for found in SEED.finditer(text):
            url, template, output = found.groups()
            if not url.startswith(("http://", "https://")):
                continue  # "local": the template IS the source (matchzy)
            if template and output:
                out.append((plugin, url, os.path.join(generators_dir, plugin, template), output))
            elif path:
                out.append((plugin, url, os.path.join(generators_dir, plugin, path.group(1)), path.group(1)))
    return out


def record_provenance(template_path, text):
    """Keep templates/upstream.json's sha256 for this template true after a refresh."""
    meta_path = os.path.join(os.path.dirname(template_path), "upstream.json")
    if not os.path.isfile(meta_path):
        return
    meta = json.load(open(meta_path, encoding="utf-8"))
    name = os.path.basename(template_path)
    for entry in meta.get("files", []):
        if entry.get("template") == name:
            entry["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with open(meta_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(meta, indent=2) + "\n")


def _load(path):
    """JSON or JSONC (SwiftlyS2 comments its files)."""
    return json.loads(P._strip_jsonc(open(path, encoding="utf-8").read()))


def fetch(url, timeout=30):
    request = urllib.request.Request(url, headers={"User-Agent": "CS2_VibeSignatures-template-sync/1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def _values(entry):
    for kind in ("signatures", "offsets"):
        if isinstance(entry.get(kind), dict):
            return kind, {p: entry[kind].get(p) for p in ("linux", "windows")}, entry[kind].get("library")
    # flat {"lib", "linux", "windows"} (SwiftlyS2): the value type names the kind
    values = {p: entry.get(p) for p in ("linux", "windows") if entry.get(p) is not None}
    if values:
        sample = next(iter(values.values()))
        kind = "offsets" if isinstance(sample, int) and not isinstance(sample, bool) else "signatures"
        return kind, values, entry.get("lib") or entry.get("library")
    return None, {}, None


def _module(library):
    return P.LIBRARY_TO_MODULE.get(str(library or "server"), "server")


def alias_suggestion(index, binaries, entry):
    """Our symbol whose func_va the plugin's signature lands on, on every platform it ships."""
    kind, values, library = _values(entry)
    if kind != "signatures":
        return None
    module, hits = _module(library), {}
    for platform, sig in values.items():
        if not sig:
            continue
        info = P.check_signature(binaries, module, platform, sig)
        if info.get("status") not in ("ok", "ok-midfunction"):
            return None
        hits[platform] = V._hexint(info["at"])
    if not hits:
        return None
    for name, per_platform in index.items():
        if all((per_platform.get(p) or {}).get("func_va") and V._hexint(per_platform[p]["func_va"]) == va
               for p, va in hits.items()):
            record = next(iter(per_platform.values()))
            return record.get("func_name") or record.get("_symbol") or name
    return None


def disagreements(index, binaries, plugin_file, generated_file, aliases):
    """[(key, platform, plugin value, our value, why)] for keys we analyse where the plugin
    author's value points somewhere else."""
    out = []
    for key, entry in plugin_file.items():
        ours = generated_file.get(key)
        if not isinstance(entry, dict) or not isinstance(ours, dict):
            continue
        kind, theirs, library = _values(entry)
        _kind, mine, _lib = _values(ours)
        for platform in ("linux", "windows"):
            a, b = theirs.get(platform), mine.get(platform)
            if a in (None, "") or b in (None, "") or a == b:
                continue
            record = P.resolve_record(index, key, platform, aliases)
            if record is None:
                continue
            if kind == "offsets":
                out.append((key, platform, a, b, "offset differs"))
                continue
            info = P.check_signature(binaries, _module(library), platform, a)
            ours_va = V._hexint(record.get("func_va")) if record.get("func_va") else None
            if info.get("status") in ("ok", "ok-midfunction") and ours_va is not None \
                    and V._hexint(info["at"]) != ours_va:
                out.append((key, platform, a, b, f"plugin's signature lands at {info['at']}, ours at {hex(ours_va)}"))
            elif info.get("status") not in ("ok", "ok-midfunction", "ok-globalref"):
                out.append((key, platform, a, b, f"plugin's signature is {info.get('status')} in this build"))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-gamever", required=True)
    parser.add_argument("-apply", action="store_true", help="write the plugins' files as the new templates")
    args = parser.parse_args()

    index = P.load_snapshot_index(os.path.join("gamesymbols", f"{args.gamever}.yaml"))
    P._SNAPSHOT_INDEX.update(index)
    config = os.path.join("configs", f"{args.gamever}.yaml")
    aliases = P.load_alias_map(config) if os.path.isfile(config) else {}
    if os.path.isfile(config):
        P.GENERATOR_ALIASES.update(P.load_generator_aliases(config))
    binaries = P.Binaries("bin", args.gamever)

    changed = failed = 0
    for plugin, url, template_path, relative in sources():
        try:
            text = fetch(url)
            upstream = json.loads(P._strip_jsonc(text))
        except Exception as error:  # noqa: BLE001 - one plugin's outage must not stop the others
            print(f"[{plugin}] could not fetch {url}: {error}")
            failed += 1
            continue
        template = _load(template_path)
        generated_path = os.path.join("gamedata", args.gamever, plugin, relative)
        generated = _load(generated_path) if os.path.isfile(generated_path) else {}

        added, removed = sorted(set(upstream) - set(template)), sorted(set(template) - set(upstream))
        shared = dict(P.GENERATOR_ALIASES)
        P.GENERATOR_ALIASES.update(P.generator_key_overrides(plugin, output=relative))  # this plugin's own key routing
        try:
            disagree = disagreements(index, binaries, upstream, generated, aliases)
        finally:
            P.GENERATOR_ALIASES.clear()
            P.GENERATOR_ALIASES.update(shared)
        if not (added or removed or disagree) and upstream == template:
            print(f"[{plugin}] in step with {url}")
            continue
        changed += 1
        print(f"[{plugin}] {url}")
        for key in added:
            recorded = any(P.resolve_record(index, key, p, aliases) for p in ("linux", "windows"))
            note = "ours: verified on generation" if recorded else "no record here: ships the plugin author's value"
            if not recorded:
                suggestion = alias_suggestion(index, binaries, upstream[key])
                if suggestion:
                    note += f"; its signature lands on {suggestion} - alias it in ALIAS_OVERRIDES"
            print(f"  + {key}  ({note})")
        for key in removed:
            print(f"  - {key}  (the plugin no longer reads it)")
        for key, platform, theirs, mine, why in disagree:
            print(f"  ! {key}.{platform}: plugin {theirs!r}, ours {mine!r} - {why}")
        if args.apply and upstream != template:
            text = text if text.endswith("\n") else text + "\n"
            with open(template_path, "w", encoding="utf-8") as handle:
                handle.write(text)
            record_provenance(template_path, text)
            print(f"  template refreshed: {template_path}")
    print(f"sync_plugin_templates {args.gamever}: {changed} plugin(s) changed or disagree"
          + (f", {failed} could not be fetched" if failed else ""))
    return 2 if failed else (1 if changed else 0)


if __name__ == "__main__":
    sys.exit(main())
