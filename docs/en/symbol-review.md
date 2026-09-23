# Symbol review: helping without IDA

Every CS2 update moves the functions, globals and struct members that plugins hook. The
pipeline finds almost all of them on its own. What it cannot prove ends up in a GitHub
issue, one per game version **and platform**: **"Symbol review: &lt;gamever&gt; (linux)"** and
**"Symbol review: &lt;gamever&gt; (windows)"** (label `symbol-review`). Linux and windows are
analysed by separate runs, and each run owns its own issue. Anyone with collaborator
access can settle an entry with a single comment.

## How it works

1. **The run does everything it can prove first.** Each symbol is relocated from the
   previous game version. If that fails, the built-in hunter tries strings, call graphs,
   vtable slots, sibling functions and layout fingerprints. An AI agent gets whatever is
   left. Nothing is written without evidence that passes the pipeline's checks.

2. **What is still open goes on a list.** The list holds each symbol with its kind
   (function, virtual, global, ...), the run's best candidate address with a similarity
   score, and the reason it stopped. A typical reason is "two identical twins" or "only
   weak evidence". At the end of the linux run the linux list is mirrored into the linux
   issue, and the windows run does the same for windows. Each issue has one table per
   module. When a list is empty, its issue closes itself. A closed issue is never reopened:
   if symbols are left for review later, a **new** issue is opened that links the previous
   one, and only open issues are read.

3. **You answer in a comment on that platform's issue**, one command per line:

   ```
   /confirm <Symbol> 0x<address>            a function head
   /confirm <Symbol> vfunc <Class> <index>   a vtable slot
   /confirm <Symbol> gv 0x<instruction>      the instruction loading a global
   /reject  <Symbol> <reason>                e.g. inlined, or gone from this build
   ```

   The platform is the issue's, so you never have to type it. For example, in the
   windows issue:

   ```
   /confirm CCSCustomHudLayout_SetHasClassForPlayer 0x1808d2750
   /reject  CBaseFilter_InputTestActivator inlined into the TestActivator script binding
   ```

4. **The server acts on it every 15 minutes.** It reads only comments from the
   repository's owner, members and collaborators. A confirmed address is **not** copied
   blindly. The artifact is rebuilt from the game binary itself, the same way the IDA
   hotkey does it, and it has to pass every check the pipeline applies to its own finds:
   - the byte signature matches exactly one place in the binary;
   - that place is a real function start, not the middle of one;
   - it is not the binary's entry point, a classic wrong answer;
   - for a virtual function, the class's vtable (found via RTTI) really holds it in that slot;
   - no other symbol already owns that address (one address, one name).

5. **You get a reply.** The bot keeps **one** comment per issue, always the last one: when
   there are new results, it posts the updated log at the bottom and removes the previous
   copy. The newest result is at the bottom, with a link back to the comment it answers. It shows the artifact it
   wrote, or the reason it refused. It also tells you whether your address matches the run's own
   best candidate. Your comment gets a reaction:

   | Reaction | Meaning |
   |---|---|
   | 👍 | written, validated, committed |
   | 👎 | refused (the reply says why) - nothing was written |
   | 👀 | a mix, or a `/reject` noted |

   Keep to **one** comment per person, with as many commands as you like, one per line. To
   correct an address or add another answer, **edit that comment** instead of posting a
   new one: the bot remembers which lines it already handled
   (hidden markers in its own comment), acts only on the new or changed ones, replaces its
   reaction, and marks the result "edited". Deleting a line undoes nothing already written.

6. **From there it flows on as usual.** The accepted artifact is committed and pushed.
   The next pack and gamedata generation pick it up, and the plugin files are updated
   with the next deploy. `/reject` leaves the symbol on the list, marked with who
   rejected it and why, so the next person knows what was already ruled out.

## Why not just trust the comment?

A signature can match exactly one place and still be the wrong function. That has
happened in this project: an agent reported the DLL's entry point under a game
function's name, and the signature was unique and clean. The checks in step 4 are what
stop that, whether the answer comes from a person, an agent or the pipeline itself.
Your comment is the evidence of *identity*; the checks prove *placement*.

## Finding the right address without IDA

Any disassembler works: Ghidra, Binary Ninja, radare2/rizin, or IDA Free. Open the game
binary for the platform in the table: `server.dll` for windows, `libserver.so` for linux,
and the same for `engine2`, `client` and `networksystem`. Then:

- start at the **best candidate** address in the table, if there is one;
- compare it with the same function on the other platform, or in the previous game version.
  Look at its strings, the functions it calls, its size and its vtable slot;
- for **twins**, two near-identical functions, check which helpers each one calls. The
  right one calls the same helpers as its already-found sibling. For example,
  `SetHasClassForPlayer` calls what `SetHasClass` calls.

Addresses are the virtual addresses the disassembler shows with the default image base:
`0x180000000` for windows DLLs, `0x0` for linux shared objects.

## For maintainers

```bash
uv run review_issue.py publish -gamever 14182 -platform linux   # what run_linux.sh does at the end
uv run review_issue.py publish -gamever 14182 -platform windows # what run_windows.sh does
uv run review_issue.py apply   -gamever latest -commit          # the 15-minute timer: both issues
uv run review_issue.py apply   -gamever 14182 -dry_run   # read the commands, change nothing
```

The bot acts as its own GitHub account (`miksencs2-bot`, a collaborator with write access)
when `~/.config/cs2vibe-review.env` holds its fine-grained token, either bare or as
`GH_TOKEN=...` (mode 600; `CS2VIBE_REVIEW_ENV` points elsewhere). The token is handed to
`gh` only. Without the file, `gh`'s own login is used.

The issue always goes to the repository `origin` points at. In this checkout, `gh`'s own
default is the upstream remote, so the tool never relies on it. The timer is
`cs2vibe-review.timer` on the analysis server.
