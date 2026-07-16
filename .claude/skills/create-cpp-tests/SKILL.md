---
name: create-cpp-tests
description: |
  Create a new cpp_tests entry for validating a C++ interface vtable layout against binary reference YAMLs.
  Creates the .cpp test file in cpp_tests/ and appends a configs/<GAMEVER>.yaml entry under cpp_tests:.
  Use when a user asks to add vtable layout validation for a new hl2sdk_cs2 interface class.
disable-model-invocation: true
---

# Create cpp_tests for Interface Vtable Validation

Create a `cpp_tests/<interface_lowercase>.cpp` test file and append a matching `configs/<GAMEVER>.yaml`
entry so that `run_cpp_tests.py` can compile the header with clang, dump the vtable layout,
and compare it against reference YAML files from the binary analysis.

Resolve `GAMEVER` from the user's explicit request or `CS2VIBE_GAMEVER`, set the edit target to
`configs/$GAMEVER.yaml`, and stop if that exact file does not exist.

## When to Use

- User asks to create cpp_tests for an interface (e.g., "create cpp_tests for ILoopMode")
- User provides or references a header file from `hl2sdk_cs2/`

## Inputs

The user will provide some or all of:

| Field | Required | Description | Example |
|-------|----------|-------------|---------|
| **Interface name** | Yes | The abstract class to validate | `ILoopMode` |
| **Header path** | Yes | Path to the header in hl2sdk_cs2 | `hl2sdk_cs2/public/iloopmode.h` |
| **Alias symbols** | No | Concrete class name(s) used in binary YAML files | `CLoopModeGame` |
| **Reference modules** | No | Modules where vtable YAMLs live | `client`, `server` |

## Step-by-Step Procedure

### Step 1: Read the target header

Read the header file to understand:
- What `#include` directives it uses
- What types are referenced in virtual method signatures
- Whether it inherits from another interface (e.g., `IAppSystem`)

### Step 2: Identify compilation dependencies

Check if the header's transitive includes will compile cleanly with the standard include set:
- `hl2sdk_cs2/game/shared`
- `hl2sdk_cs2/public`
- `hl2sdk_cs2/public/tier0`
- `hl2sdk_cs2/public/tier1`

Common issues to watch for:
- **Missing types** referenced in method signatures (e.g., `CSplitScreenSlot` needs `<tier1/convar.h>`)
- **Heavy transitive includes** that pull in protobuf or other unavailable deps (e.g., `eiface.h` -> protobuf chain)

For heavy transitive includes, pre-define include guards to block them and forward-declare/stub the minimum needed types. See the `inetworkmessages.cpp` and `inetworksystem.cpp` examples for this technique:

```cpp
// Example: blocking heavy include chains
#define EIFACE_H
#define INETCHANNEL_H
enum NetChannelBufType_t : int8 {};
```

### Step 3: Create the cpp test file

Create `cpp_tests/<interface_lowercase>.cpp` following this template:

```cpp
#include <tier0/platform.h>
#undef RESTRICT
#define RESTRICT

// Add any extra includes needed for types in the interface signatures
// Add any include-guard stubs to block heavy transitive includes

#include <path/to/interface_header.h>

InterfaceName * instanceptr();

int main() {

    instanceptr()->SomeMethod();

    return 0;
}
```

Key rules:
- Always start with the `platform.h` + `RESTRICT` preamble
- The extern function declaration (e.g., `ILoopMode * loopmode();`) forces the compiler to emit vtable info
- `main()` must call at least one virtual method to trigger vtable layout dump
- Pick a simple void-returning method with no complex args for the call in `main()`

### Step 4: Determine alias_symbols and reference_modules

If the user didn't provide these, discover them:

1. **alias_symbols**: Search for existing vtable YAML files:
   ```
   bin/**/*<ClassName>*vtable*
   ```
   The `vtable_class` field in those YAMLs gives the alias symbol (typically the concrete class name like `CLoopModeGame` for `ILoopMode`).

2. **reference_modules**: The subdirectories under `bin/{gamever}/` where vtable YAMLs exist (e.g., `client`, `server`, `engine`, `networksystem`).

### Step 5: Append configs/<GAMEVER>.yaml entry

Append a new entry at the end of the `cpp_tests:` section in `configs/<GAMEVER>.yaml`:

```yaml
  - name: {InterfaceName}_MSVC
    symbol: {InterfaceName}
    alias_symbols:                          # omit this block if no aliases
      - {ConcreteClassName}
    cpp: cpp_tests/{interface_lowercase}.cpp
    headers:
    - {header_path} # Used by the fix-cppheaders SKILL
    target: x86_64-pc-windows-msvc
    include_directories:
      - hl2sdk_cs2/game/shared
      - hl2sdk_cs2/public
      - hl2sdk_cs2/public/tier0
      - hl2sdk_cs2/public/tier1
    defines:
      - COMPILER_MSVC=1
      - COMPILER_MSVC64=1
      - _MSVC_STL_USE_ABORT_AS_DOOM_FUNCTION
    additional_compiler_options:
      - fms-extensions
      - fms-compatibility
      - Xclang
      - fdump-vtable-layouts
    reference_modules:
      - {module1} # bin/{gamever}/{module1}/{AliasOrSymbol}_*.{platform}.yaml
      - {module2}
```

Notes:
- `include_directories`, `defines`, and `additional_compiler_options` are always the same standard set
- `reference_modules` comments should document the YAML file naming pattern
- If no `alias_symbols`, the reference YAML files use the `symbol` name directly

### Step 6: Run post-change gates

Run the repository update and validation skills in this exact order:

1. **ALWAYS** Use SKILL `/post-change-update` with `phase=before-validation` and
   `gamever=<gamever>` from `.env` -> `CS2VIBE_GAMEVER`.
2. **ALWAYS** Use SKILL `/post-change-validation` with the same `gamever`.
3. Only after validation succeeds, **ALWAYS** Use SKILL `/post-change-update` with
   `phase=after-validation` and the same `gamever`.

`/post-change-validation` runs `run_cpp_tests.py` and requires real runnable tests. Expected success includes
compilation plus a clean vtable/record-layout comparison.

If validation reports a compile, configuration, layout, or environment failure, **STOP the entire task** and
report its reason. Do not edit the test, retry validation, pack the snapshot, or commit during that task.

### Step 7: Commit

Never commit directly to `main`; switch to or create `dev` first. Review `git status --short`, then explicitly
stage only the new test, its config entry, changed tracked gamedata, and the snapshot:

```bash
git add cpp_tests/{interface_lowercase}.cpp configs/<GAMEVER>.yaml
git add <changed-dist-gamedata-files> gamesymbols/<gamever>.yaml
git commit -m "test(cpp-tests): add {InterfaceName} layout validation" -m "Co-Authored-By: Codex (GPT-5.x)"
```

Never use `git add -A` and never enter this step unless all three post-change gate calls succeeded.

## Checklist

- [ ] New cpp test follows the platform/RESTRICT preamble and calls a virtual method
- [ ] `configs/<GAMEVER>.yaml` entry contains the correct symbol, aliases, header, and reference modules
- [ ] `/post-change-update phase=before-validation` succeeds for the selected game version
- [ ] `/post-change-validation` succeeds for the same game version
- [ ] `/post-change-update phase=after-validation` packs `gamesymbols/<gamever>.yaml`
- [ ] All task-related files are explicitly staged and committed on `dev`

## Reference: Existing Examples

| Test Name | Interface | Header | Has Aliases | Has Include Stubs | Reference Modules |
|-----------|-----------|--------|-------------|-------------------|-------------------|
| `IGameSystem_MSVC` | `IGameSystem` | `igamesystem.h` | No | No | server, client |
| `INetworkMessages_MSVC` | `INetworkMessages` | `inetworkmessages.h` | `CNetworkMessages` | Yes (EIFACE_H, INETCHANNEL_H) | networksystem, engine, server, client |
| `ILoopMode_MSVC` | `ILoopMode` | `iloopmode.h` | `CLoopModeGame` | No (just extra `convar.h` include) | client, server |
