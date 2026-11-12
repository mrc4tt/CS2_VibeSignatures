import source2_dump as S

OLD = """\
mp_roundtime 5 (min: 0.1, max: 60, gamedll notify replicated release)
\tHow many minutes each round takes.

sv_recvbuf_messages 4 (release)
\tServer: max messages buffered.

old_name 16 (release)
\tServer: SteamNetworkingSockets will not buffer more than N kb.

ai_debug "false" (gamedll cheat)
\t<no description>
"""

NEW = """\
mp_roundtime 5 (min: 0.1, max: 30, gamedll notify replicated release)
\tHow many minutes each round takes.

new_name 16 (release)
\tServer: SteamNetworkingSockets will not buffer more than N kb.

ai_debug "true" (gamedll cheat defensive)
\t<no description>

r_frost 1 (clientdll release)
\tFrost on players.
"""


def test_parse_header_variants():
    e = S.parse_entries(OLD)
    assert e["mp_roundtime"]["default"] == "5"
    assert e["mp_roundtime"]["min"] == "0.1" and e["mp_roundtime"]["max"] == "60"
    assert e["mp_roundtime"]["flags"] == ["gamedll", "notify", "replicated", "release"]
    assert e["ai_debug"]["default"] == '"false"'
    assert e["sv_recvbuf_messages"]["help"] == ["Server: max messages buffered."]


def test_parse_command_without_default():
    e = S.parse_entries("+bugvoice (developmentonly dontrecord defensive)\n\tStart recording.\n")
    assert e["+bugvoice"]["default"] is None
    assert e["+bugvoice"]["flags"] == ["developmentonly", "dontrecord", "defensive"]


def test_diff_added_removed_changed_and_renamed():
    old, new = S.parse_entries(OLD), S.parse_entries(NEW)
    counts, lines = S.section_lines("convars", old, new)
    assert counts == "+1 -1 ~1 !2"
    text = "\n".join(lines)
    assert "~ old_name -> new_name (renamed" in text
    assert "+ r_frost 1 - Frost on players." in text
    assert "- sv_recvbuf_messages" in text
    assert "! mp_roundtime: max 60 -> 30" in text
    assert '! ai_debug: default "false" -> "true"; flags +defensive' in text


def test_no_rename_without_help_text():
    old = S.parse_entries("a 1 (release)\n\t<no description>\n")
    new = S.parse_entries("b 1 (release)\n\t<no description>\n")
    added, removed, _ = S.diff_entries(old, new)
    assert S.pair_renames(old, new, added, removed) == []


def test_network_counts():
    old = "A\n\tint x\n\nB\n\tint y\n"
    new = "A\n\tint x\n\tint z\n\nC\n\tint w\n"
    assert S.network_counts(old, new) == (1, 1, 1)


def test_previous_dump(tmp_path, monkeypatch):
    for v in ("14195", "14196", "14197", "14196b"):
        (tmp_path / v).mkdir()
    monkeypatch.setattr(S, "DUMP_DIR", tmp_path)
    assert S.previous_dump("14197") == "14196b"
    assert S.previous_dump("14196") == "14195"
    assert S.previous_dump("14195") is None
