---
name: find-CNetChan_ParseNetMessageShowFilter-AND-g_pLoggingChannel
description: |
  Find and identify the CNetChan_ParseNetMessageShowFilter function and the g_pLoggingChannel global variable
  in CS2 binary using IDA Pro MCP. Use this skill when reverse engineering CS2 networksystem.dll or
  libnetworksystem.so to locate the show-filter string parser by decompiling the known
  CNetChan_ParseMessagesDemoInternal anchor and inspecting its sole direct callee, and to locate the module's
  logging channel global that gates the anchor's debug/spew path.
  Trigger: CNetChan_ParseNetMessageShowFilter, g_pLoggingChannel
disable-model-invocation: true
---

# Find CNetChan_ParseNetMessageShowFilter and g_pLoggingChannel

Locate `CNetChan_ParseNetMessageShowFilter` and `g_pLoggingChannel` in CS2 `networksystem.dll` or
`libnetworksystem.so` using IDA Pro MCP tools.

## Method

### 1. Load CNetChan_ParseMessagesDemoInternal from YAML

**ALWAYS** Use SKILL `/get-func-from-yaml` with `func_name=CNetChan_ParseMessagesDemoInternal`.

If the skill returns an error, **STOP** and report to user.

Otherwise, extract:
- `func_va` of `CNetChan_ParseMessagesDemoInternal`

### 2. Decompile the Anchor

```text
mcp__ida-pro-mcp__decompile addr="<CNetChan_ParseMessagesDemoInternal_func_va>"
```

List the direct (non-vtable) callees of the anchor.

### 3. Identify CNetChan_ParseNetMessageShowFilter Among the Callees

Decompile every direct callee of the anchor and look for the one matching this exact signature and body shape:

```c
__int64 __fastcall ParseNetMessageShowFilter(unsigned __int8 *a1, _DWORD *a2, int *a3)
{
  *a2 = 0;
  if ( *a1 == '0' && !a1[1] ) return *a1;
  if ( *a1 == '2' && !a1[1] ) { *a2 = 2; return *a1; }
  if ( *a1 == '1' && !a1[1] ) { *a2 = 1; return *a1; }
  // split a1 on separators " ", ";", "," ...
  // for each token: call into the CNetworkMessages singleton to resolve a
  // partial message name to a NetMessageInfo_t, read its network-group id,
  // and append the id to *a3 if not already present ...
}
```

Identification rules, in order of strength:

1. **Three parameters**: `(unsigned char *pszFilter, int *pnSingleGroup, <group-array-header> *pGroupList)`. There is no `this` pointer — this is effectively a static/free helper.
2. **Single-char fast path**: the very first instructions compare `*pszFilter` against the literal bytes `0x30` (`'0'`), `0x32` (`'2'`), `0x31` (`'1'`) and early-return with `*pnSingleGroup` set to `0`/`2`/`1` respectively when the filter string is exactly one of those digits.
3. **Tokenizer fallback**: otherwise the function splits the string using a 3-element separator set built from two 8-byte string pointers packed into an XMM register (`" "` and `";"`) plus a third pointer (`","`), then iterates tokens.
4. **Per-token lookup**: for each token it calls a function taking `(pNetworkMessagesSingleton, pszToken)` that walks a hash-bucket chain and does a partial/prefix string match — this callee is `CNetworkMessages_FindNetworkMessagePartial` (see the sibling skill `find-CNetworkMessages_FindNetworkMessagePartial`). The call is **devirtualized** (a direct `call`, not `call qword ptr [reg+off]`) because the singleton's concrete type is known at compile time in this translation unit.
5. **Exclusive caller**: profiling the candidate (`func_profile`/xrefs) shows exactly **one** caller in the whole module, and that caller is the anchor itself, which calls it **twice** (once per filter-string source it holds). This 1-caller/2-call-sites signature is a strong, version-resistant fingerprint — it survives even if the anchor's surrounding code is heavily refactored.

The callee that satisfies these rules is `CNetChan_ParseNetMessageShowFilter`.

> Linux 14168 reference: the anchor `CNetChan_ParseMessagesDemoInternal` (`0x28e5c0`) calls `sub_28E030`
> (`0x28e030`, size `0x577`) twice — once per filter-string global it holds — and `sub_28E030` is otherwise
> uncalled anywhere else in the module. `sub_28E030` in turn calls `sub_2A9F80` (`CNetworkMessages_FindNetworkMessagePartial`,
> vtable slot 14) once per token.

### 4. Identify g_pLoggingChannel

Within the **same anchor** decompile from step 2, find the 4-byte global (a `LoggingChannelID_t`, stored as a
plain `int`/`.bss` dword, *not* a real pointer despite the `g_p` prefix) that is:

- Loaded via a RIP-relative reference (`lea reg, <global>` followed by `mov reg32, [reg]`, or a folded
  `mov reg32, cs:<global>` depending on codegen) at **dozens of call sites** throughout the anchor.
- Passed as the first argument to a pair of recurring helper patterns:
  - an "is channel enabled at verbosity N" check: `IsChannelEnabled(<global>, <verbosity>)` returning bool,
  - a "log to channel" call: `Log(<global>, <verbosity>, "<fmt>", ...)`.
- Used specifically on the anchor's **debug/show-filter spew path** — the branch that only executes when the
  current message's network-group id was found in the group list produced by `CNetChan_ParseNetMessageShowFilter`
  in step 3 (i.e. it gates the verbose per-message bit-dump/log output that `net_showmsg`-style filtering exists
  to produce).

Cross-check (do this — it is a strong independent confirmation): load the `CNetworkMessages` vtable via
`/get-vtable-from-yaml` with `class_name=CNetworkMessages` and decompile its entries looking for a **zero-argument,
one-line** accessor whose entire body is `return (unsigned int)<global>;`. That accessor (`GetLoggingChannel`) must
read the **exact same** global address you found above. If both signals agree, you have `g_pLoggingChannel`.

> Linux 14168 reference: the global is `dword_4E2AFC` at VA `0x4e2afc` (`.bss`, 4 bytes). It is referenced from
> well over a hundred call sites across the module (not just the anchor). `CNetworkMessages` vtable slot 35
> (`vtable + 0x10 + 35*8`, function `sub_2a4310`) is a one-line accessor: `return (unsigned int)dword_4E2AFC;` —
> confirming the identification.

### 5. Generate Function Signature for CNetChan_ParseNetMessageShowFilter

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<ParseNetMessageShowFilter_func_addr>` to
generate a robust and unique `func_sig`.

### 6. Generate Global Variable Signature for g_pLoggingChannel

**ALWAYS** Use SKILL `/generate-signature-for-globalvar` with `addr=<g_pLoggingChannel_addr>`. Pick one of the
many instructions in the anchor (or any other referencing function) that loads the global via a RIP-relative
`lea`/`mov` as the anchor instruction for signature generation.

### 7. Write CNetChan_ParseNetMessageShowFilter as YAML

**ALWAYS** Use SKILL `/write-func-as-yaml`.

Required parameters:
- `func_name`: `CNetChan_ParseNetMessageShowFilter`
- `func_addr`: `<ParseNetMessageShowFilter_func_addr>`
- `func_sig`: The validated signature from step 5

### 8. Write g_pLoggingChannel as YAML

**ALWAYS** Use SKILL `/write-globalvar-as-yaml`.

Required parameters:
- `gv_name`: `g_pLoggingChannel`
- `gv_addr`: `<g_pLoggingChannel_addr>`
- The signature/instruction data from step 6

## Function Characteristics

### CNetChan_ParseNetMessageShowFilter

- **Purpose**: Parses a `net_showmsg`/demo show-filter style string (either a single digit `"0"`/`"1"`/`"2"`
  meaning "show none"/"show unreliable"/"show all", or a `,`/`;`/space-separated list of partial network-message
  names) into a list of unique network-group ids used to decide which messages get verbose debug spew.
- **Binary**: `networksystem.dll` / `libnetworksystem.so`
- **Parameters**: `(unsigned char *pszFilter, int *pnSingleGroupOut, <growable-int-array> *pGroupListOut)` — no
  `this` pointer.
- **Return value**: the first byte of the filter string (an artifact of the early-return fast path); callers
  ignore it and only consume the two output parameters.
- **Callees**: `CNetworkMessages_FindNetworkMessagePartial` (devirtualized direct call), plus generic
  string-split/`CUtlVector`-growth helpers.

### g_pLoggingChannel

- **Purpose**: Holds the `LoggingChannelID_t` handle for the `networksystem` module's registered logging channel
  (obtained once, elsewhere, via the imported `LoggingSystem_RegisterLoggingChannel`). Used as the first argument
  to essentially every `IsChannelEnabled`/`Log`-style spew call in the module, including the show-filter/debug
  message-dump path in `CNetChan_ParseMessagesDemoInternal`.
- **Binary**: `networksystem.dll` / `libnetworksystem.so`
- **Type**: 4-byte integer (`.bss`), despite the `g_p` naming convention it is **not** a pointer.
- **Also exposed via**: `CNetworkMessages`/`INetworkMessages` vtable accessor `GetLoggingChannel()` (a one-line
  `return <global>;`), which is a useful independent cross-check.

## Discovery Strategy

1. Load the already-resolved `CNetChan_ParseMessagesDemoInternal` anchor from YAML.
2. Decompile it and enumerate its direct callees.
3. Identify `CNetChan_ParseNetMessageShowFilter` by its distinctive 3-parameter signature, single-digit fast
   path, 3-way string tokenizer, per-token devirtualized call into `CNetworkMessages_FindNetworkMessagePartial`,
   and — most importantly — being the anchor's *only* callee with exactly one caller in the whole binary, called
   twice from that one caller.
4. Identify `g_pLoggingChannel` as the pervasively-referenced logging-channel-id global used throughout the same
   anchor's debug-spew path, and cross-check it against the `CNetworkMessages::GetLoggingChannel()` vtable
   accessor, which trivially returns the same global.

This is robust because:
- The anchor (`CNetChan_ParseMessagesDemoInternal`) is already reliably located via its own distinctive string
  xref, independent of this skill.
- "Exactly one caller, called twice" is a strong, code-shape-independent fingerprint for the show-filter parser
  that survives minor recompilation/inlining changes better than a fixed byte offset would.
- `g_pLoggingChannel` is corroborated two independent ways: (a) its usage pattern in the anchor, and (b) a
  trivial one-line vtable accessor that returns the identical global — an accidental disagreement between the
  two is extremely unlikely.

## Output YAML Format

The output YAML filenames depend on the platform:
- `networksystem.dll` -> `CNetChan_ParseNetMessageShowFilter.windows.yaml`, `g_pLoggingChannel.windows.yaml`
- `libnetworksystem.so` -> `CNetChan_ParseNetMessageShowFilter.linux.yaml`, `g_pLoggingChannel.linux.yaml`

`CNetChan_ParseNetMessageShowFilter.{platform}.yaml` fields: `func_name`, `func_va`, `func_rva`, `func_size`, `func_sig`.

`g_pLoggingChannel.{platform}.yaml` fields: `gv_name`, `gv_va`, `gv_rva`, `gv_sig`, `gv_sig_va`, `gv_inst_offset`, `gv_inst_length`, `gv_inst_disp`.
