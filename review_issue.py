#!/usr/bin/env python3
"""review_issue.py - let people without IDA confirm what the run could not prove.

The run leaves what neither its hunter nor an agent could prove in
manual_todo/<gamever>/<module>.<platform>.txt. This tool mirrors that list into one
GitHub issue per gamever AND platform - linux and windows are analysed by separate runs,
so each gets its own issue - and acts on review comments:

    uv run review_issue.py publish -gamever 14182 -platform linux   # create / refresh
    uv run review_issue.py apply   -gamever 14182 -commit           # both platforms' issues

Comment grammar (one command per line, any number per comment; the platform is the issue's):

    /confirm <Symbol> 0x<address>              a function head
    /confirm <Symbol> vfunc <Class> <index>     a vtable slot
    /confirm <Symbol> gv 0x<instruction>        the instruction loading a global
    /reject  <Symbol> <reason>

Only comments by the repository's owner, members and collaborators are read. A confirm
is never written as-is: the artifact is built from the warm IDB with emit_artifact.py
(the same code as Ctrl-Alt-E) and must pass validate_artifacts (unique signature, clean
boundary, not the entry point, RTTI slot) and the one-address-one-name check before it is
copied into bin_artifacts/. Processed comments get a reaction (+1 written, -1 refused,
eyes noted), which is also how a later apply knows to skip them.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
# gh runs with the environment this process started with. ida_analyze_bin (imported for
# update_manual_todo) calls load_dotenv(), and .env carries a GITHUB_TOKEN that gh then
# prefers over its own login - an invalid one on both machines, which surfaced as
# "HTTP 401: Bad credentials" on every call after that import.
_GH_ENV = dict(os.environ)
LABEL = "symbol-review"
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
PLATFORMS = ("linux", "windows")
COMMAND_RE = re.compile(r"^\s*/(confirm|reject)\s+([A-Za-z_][A-Za-z0-9_]*)\s*(.*?)\s*$", re.M)
MAX_BODY = 60000
# the bot keeps ONE comment per issue and edits it, newest result first
BOT_MARK = "<!-- review-bot -->"
BOT_HEADER = f"{BOT_MARK}\n**review bot** - results, newest at the bottom (reactions on your comment: :+1: written, :-1: refused, :eyes: mixed or noted)"


def resolve_gamever(gamever):
    """'latest' -> the newest gamever that has a manual list (what a timer wants)."""
    if gamever != "latest":
        return gamever
    import hunt_core

    root = REPO / "manual_todo"
    versions = [d.name for d in root.iterdir() if d.is_dir()] if root.is_dir() else []
    return max(versions, key=hunt_core.version_key) if versions else None


def title_for(gamever, platform):
    # CS2VIBE_REVIEW_TITLE_PREFIX="[TEST] " keeps a live test out of the real issues
    return f"{os.environ.get('CS2VIBE_REVIEW_TITLE_PREFIX', '')}Symbol review: {gamever} ({platform})"


def repo_slug():
    """owner/name of THIS fork's origin. gh's own default picks the upstream remote in this
    checkout, which would post the review to someone else's repository."""
    explicit = os.environ.get("CS2VIBE_REVIEW_REPO")
    if explicit:
        return explicit
    url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=REPO, capture_output=True, text=True,
                         check=True).stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    if not m:
        raise RuntimeError(f"origin is not a GitHub repository: {url}")
    return m.group(1)


def gh(*args, stdin=None):
    slug = repo_slug()
    args = [a.replace("{owner}/{repo}", slug) for a in args]
    if args and args[0] in ("issue", "label"):
        args = [args[0], args[1], "-R", slug, *args[2:]]
    for attempt in range(3):
        done = subprocess.run(["gh", *args], cwd=REPO, input=stdin, capture_output=True, text=True, env=_GH_ENV)
        if done.returncode == 0:
            return done.stdout
        # GitHub answers a sound token with an occasional 401/5xx; measured once in a live test
        if attempt < 2 and re.search(r"HTTP (401|5\d\d)|timeout|connection", done.stderr, re.I):
            time.sleep(5 * (attempt + 1))
            continue
        break
    raise RuntimeError(f"gh {' '.join(args[:3])}: {done.stderr.strip()[-400:]}")


def gh_api(method, path, payload=None):
    """REST only: in a live test gh's GraphQL commands (issue list/create) answered 401 several
    times in a row while REST calls with the same token kept working."""
    args = ["api", "-X", method, path.replace("{repo}", repo_slug())]
    stdin = None
    if payload is not None:
        args += ["--input", "-"]
        stdin = json.dumps(payload)
    out = gh(*args, stdin=stdin)
    return json.loads(out) if out.strip() else None


# ----------------------------------------------------------------------------- the list

def parse_detail(detail):
    """'agent failed | func | best 0x1808d1cf0 (0.58) | why' -> parts."""
    parts = [p.strip() for p in detail.split(" | ")]
    flags = []
    while parts and parts[0] in ("agent failed",):
        flags.append(parts.pop(0))
    category = parts.pop(0) if parts else "?"
    va, score = None, None
    if parts and parts[0].startswith("best "):
        m = re.match(r"best (0x[0-9a-fA-F]+)(?: \(([0-9.]+)\))?", parts.pop(0))
        if m:
            va, score = m.group(1), m.group(2)
    return {"flags": flags, "category": category, "candidate": va, "score": score, "why": " | ".join(parts)}


def read_todo(gamever, root=REPO, platform=None):
    rows = []
    folder = Path(root) / "manual_todo" / str(gamever)
    for path in sorted(folder.glob("*.txt")) if folder.is_dir() else ():
        module, file_platform = path.stem.rsplit(".", 1)
        if platform and file_platform != platform:
            continue
        platform_of_file = file_platform
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split(None, 2)
            if len(parts) < 2:
                continue
            row = {"module": module, "platform": platform_of_file, "symbol": parts[0], "task": parts[1], "path": str(path)}
            row.update(parse_detail(parts[2] if len(parts) > 2 else ""))
            rows.append(row)
    return rows


def guide_url():
    try:
        return f"https://github.com/{repo_slug()}/blob/main/docs/en/symbol-review.md"
    except Exception:
        return "docs/en/symbol-review.md"


def render_body(gamever, platform, rows):
    binaries = "server.dll, engine2.dll, client.dll, ..." if platform == "windows" else "libserver.so, libengine2.so, libclient.so, ..."
    lines = [
        f"The {gamever} **{platform}** run ({binaries}) could not prove these symbols on its own: the hunter's evidence was too weak "
        "and no agent got it right. If you can tell which function (or slot, or global) is the right "
        "one, say so in a comment - no IDA needed if you can read the candidate's code in any "
        "disassembler.",
        "",
        "**How to answer** (one command per line; only the repository's collaborators are read):",
        "",
        "```",
        "/confirm <Symbol> 0x<address>            a function head",
        "/confirm <Symbol> vfunc <Class> <index>   a vtable slot",
        "/confirm <Symbol> gv 0x<instruction>      the instruction loading a global",
        "/reject  <Symbol> <reason>                e.g. inlined, or gone from this build",
        "```",
        "",
        "A confirm is not trusted blindly: the artifact is rebuilt from the binary and must pass the "
        "same checks as everything else. You get a reply either way, usually within 15 minutes.",
        "",
        "<details><summary><b>How it works</b></summary>",
        "",
        "1. **The run does everything it can prove first.** Each symbol is relocated from the previous "
        "game version; if that fails, the built-in hunter tries strings, call graphs, vtable slots, "
        "sibling functions and layout fingerprints, and an AI agent gets whatever is left.",
        f"2. **What is still open is listed below**, with the run's best candidate and why it stopped. "
        f"The {platform} run refreshes this issue; when the list is empty, the issue closes itself, "
        f"and a later round opens a new one.",
        "3. **You answer in a comment**, with the commands above. The platform is this issue's.",
        "4. **The server acts on it every 15 minutes.** Only comments from the owner, members and "
        "collaborators are read. The artifact is rebuilt from the game binary and must pass: the "
        "signature matches exactly one place; that place is a real function start; it is not the "
        "binary's entry point; a virtual function really sits in that vtable slot (via RTTI); no other "
        "symbol already owns the address.",
        "5. **You get a reply** in the bot's one comment, always the last on this issue (newest at the bottom), with the artifact "
        "written or the reason it was refused, and whether your "
        "address matches the run's best candidate. Your comment gets a reaction: :+1: written, "
        ":-1: refused, :eyes: mixed or a `/reject` noted. You can **edit** your comment: only new or changed "
        "lines are acted on, and the reaction is replaced.",
        "6. **From there it flows on as usual:** committed, packed, generated into the plugin gamedata "
        "files and deployed. A `/reject` keeps the symbol listed, marked with who rejected it and why.",
        "",
        "Full guide, including how to find the right address without IDA: "
        f"[docs/en/symbol-review.md]({guide_url()})",
        "",
        "</details>",
        "",
    ]
    if not rows:
        lines.append("**Nothing left - every symbol has an artifact.**")
        return "\n".join(lines)
    groups = {}
    for row in rows:
        groups.setdefault((row["module"], row["platform"]), []).append(row)
    for (module, platform), items in sorted(groups.items()):
        lines += [f"### {module} - {len(items)}", "",
                  "| Symbol | Kind | Best candidate | Why the run stopped |", "|---|---|---|---|"]
        for row in items:
            candidate = f"`{row['candidate']}`" + (f" ({row['score']})" if row["score"] else "") if row["candidate"] else "-"
            why = (", ".join(row["flags"]) + "; " if row["flags"] else "") + row["why"]
            why = why.replace("|", "\\|")[:220]
            lines.append(f"| `{row['symbol']}` | {row['category']} | {candidate} | {why} |")
        lines.append("")
    body = "\n".join(lines)
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY] + "\n\n_(truncated - see manual_todo/ on the server for the rest)_"
    return body


# ----------------------------------------------------------------------------- github

def _issues(gamever, platform, state):
    found = gh_api("GET", f"repos/{{repo}}/issues?labels={LABEL}&state={state}&per_page=100") or []
    return [{"number": i["number"], "title": i["title"], "state": i["state"].upper()}
            for i in found if i["title"] == title_for(gamever, platform) and "pull_request" not in i]


def _remembered_path(gamever, platform):
    return REPO / "manual_todo" / str(gamever) / f"review-issue.{platform}"


def remembered_closed(gamever, platform):
    """The issue this machine used last, when it has been closed since: the previous round."""
    path = _remembered_path(gamever, platform)
    number = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    if not number.isdigit():
        return None
    current = gh_api("GET", f"repos/{{repo}}/issues/{number}") or {}
    return {"number": int(number)} if current.get("state") == "closed" else None


def remember_issue(gamever, platform, number):
    path = _remembered_path(gamever, platform)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{number}\n", encoding="utf-8")


def find_issue(gamever, platform):
    """The OPEN review issue, if any. A closed one is history: a new round gets a new issue.

    GitHub's issue LIST lags behind changes in both directions (live test: an issue closed
    seconds earlier was still listed as open, and a new one was missing from the list), so
    the number this machine last used is read directly first, and anything the list offers
    is confirmed with a direct read too."""
    path = _remembered_path(gamever, platform)
    if path.is_file():
        number = path.read_text(encoding="utf-8").strip()
        current = gh_api("GET", f"repos/{{repo}}/issues/{number}") if number.isdigit() else None
        if current and current.get("state") == "open" and current.get("title") == title_for(gamever, platform):
            return {"number": int(number), "title": current["title"], "state": "OPEN"}
    for issue in _issues(gamever, platform, "open"):
        current = gh_api("GET", f"repos/{{repo}}/issues/{issue['number']}") or {}
        if current.get("state") == "open":
            return issue
    return None


def previous_issue(gamever, platform):
    closed = _issues(gamever, platform, "closed")
    return max(closed, key=lambda i: i["number"]) if closed else None


def publish(gamever, platform=None, rows=None):
    """One issue per platform; without `platform`, both."""
    if platform is None:
        return [publish(gamever, one) for one in PLATFORMS]
    rows = read_todo(gamever, platform=platform) if rows is None else rows
    body = render_body(gamever, platform, rows)
    issue = find_issue(gamever, platform)
    if issue is None:
        if not rows:
            print(f"[review] nothing to review for {gamever} {platform}")
            return None
        try:
            gh_api("POST", "repos/{repo}/labels",
                   {"name": LABEL, "color": "D4C5F9", "description": "Symbols the run could not prove on its own"})
        except RuntimeError as error:
            if "already_exists" not in str(error) and "422" not in str(error):
                raise
        earlier = remembered_closed(gamever, platform) or previous_issue(gamever, platform)
        if earlier:
            body = f"Previous round: #{earlier['number']} (closed - its comments are not read any more).\n\n" + body
        created = gh_api("POST", "repos/{repo}/issues",
                         {"title": title_for(gamever, platform), "body": body, "labels": [LABEL]})
        remember_issue(gamever, platform, created["number"])
        print(f"[review] opened {created['html_url']} ({platform}, {len(rows)} symbols)")
        return created["html_url"]
    number = str(issue["number"])
    update = {"body": body}
    if not rows:
        log_id, sections = bot_log(number)
        write_bot_log(number, log_id, sections + ["Every symbol now has an artifact - closing.\n"])
        update["state"] = "closed"
    gh_api("PATCH", f"repos/{{repo}}/issues/{number}", update)
    print(f"[review] refreshed #{number} ({platform}, {len(rows)} symbols)")
    return number


def issue_comments(number):
    out = gh("api", f"repos/{{owner}}/{{repo}}/issues/{number}/comments", "--paginate",
             "--jq", ".[] | {id, body, author_association, login: .user.login, url: .html_url}")
    return [json.loads(line) for line in out.splitlines() if line.strip()]


DONE_RE = re.compile(r"<!-- done:(\d+):([0-9a-f,]*) -->")


def line_key(verb, symbol, platform, tokens):
    """A stable id for one command line, so an edited comment is compared line by line."""
    import hashlib

    text = " ".join([verb, symbol, platform or "", *tokens]).strip()
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def done_lines(sections):
    """{comment id: {line keys already handled}} from the bot log's hidden markers."""
    done = {}
    for section in sections:
        for comment_id, keys in DONE_RE.findall(section):
            done.setdefault(int(comment_id), set()).update(k for k in keys.split(",") if k)
    return done


def bot_log(number, comments=None):
    """(comment id, [sections]) of the bot's one comment on the issue, or (None, [])."""
    for comment in comments if comments is not None else issue_comments(number):
        if BOT_MARK in (comment.get("body") or ""):
            body = comment["body"].split("\n", 2)
            rest = body[2] if len(body) > 2 else ""
            sections = [part for part in rest.split("\n---\n") if part.strip()]
            return comment["id"], sections
    return None, []


def write_bot_log(number, comment_id, sections):
    """Post the log as the issue's LAST comment and delete the previous copy, so the one
    bot comment always sits below the comments it answers. Posted before the delete: a
    failure in between leaves two copies, never none. Returns the new comment's id."""
    body = BOT_HEADER + "\n" + "\n---\n".join(sections)
    while len(body) > MAX_BODY and len(sections) > 1:
        sections = sections[1:]  # the oldest results go first
        body = BOT_HEADER + "\n" + "\n---\n".join(sections)
    created = gh_api("POST", f"repos/{{repo}}/issues/{number}/comments", {"body": body}) or {}
    if comment_id is not None:
        gh_api("DELETE", f"repos/{{repo}}/issues/comments/{comment_id}")
    return created.get("id")


def my_login():
    return gh("api", "user", "--jq", ".login").strip()


def reacted_by(comment_id, login):
    out = gh("api", f"repos/{{owner}}/{{repo}}/issues/comments/{comment_id}/reactions", "--jq", ".[].user.login")
    return login in out.split()


def my_reactions(comment_id, login):
    out = gh("api", f"repos/{{owner}}/{{repo}}/issues/comments/{comment_id}/reactions",
             "--jq", ".[] | [.id, .user.login] | @tsv")
    return [int(line.split("\t")[0]) for line in out.splitlines() if line.split("\t")[-1] == login]


def replace_reaction(comment_id, content, login):
    """An edited comment gets a fresh verdict: the bot's earlier reaction goes."""
    for reaction_id in my_reactions(comment_id, login):
        gh("api", "-X", "DELETE", f"repos/{{owner}}/{{repo}}/issues/comments/{comment_id}/reactions/{reaction_id}")
    react(comment_id, content)


def react(comment_id, content):
    gh("api", "-X", "POST", f"repos/{{owner}}/{{repo}}/issues/comments/{comment_id}/reactions", "-f", f"content={content}")


# ----------------------------------------------------------------------------- commands

def parse_commands(body):
    """[(verb, symbol, platform or None, args)] from one comment."""
    out = []
    for verb, symbol, rest in COMMAND_RE.findall(body or ""):
        tokens = rest.split()
        platform = tokens.pop(0) if tokens and tokens[0] in PLATFORMS else None
        out.append((verb, symbol, platform, tokens))
    return out


def rule_args(tokens):
    """emit_artifact.py arguments for a confirm, or (None, why)."""
    if tokens and re.fullmatch(r"0x[0-9a-fA-F]+", tokens[0]):
        return ["-kind", "func", "-ea", tokens[0]], None
    if len(tokens) >= 3 and tokens[0] == "vfunc" and tokens[2].isdigit():
        return ["-kind", "vfunc", "-class", tokens[1], "-index", tokens[2]], None
    if len(tokens) >= 2 and tokens[0] == "gv" and re.fullmatch(r"0x[0-9a-fA-F]+", tokens[1]):
        return ["-kind", "gv", "-ea", tokens[1]], None
    return None, "could not read the address: use `0x<address>`, `vfunc <Class> <index>` or `gv 0x<instruction>`"


def target_row(rows, symbol, platform):
    matches = [r for r in rows if r["symbol"] == symbol and (platform is None or r["platform"] == platform)]
    if not matches:
        return None, f"`{symbol}` is not on the list" + (f" for {platform}" if platform else "")
    if len(matches) > 1:
        return None, f"`{symbol}` is open on {' and '.join(r['platform'] for r in matches)} - add the platform"
    return matches[0], None


def duplicate_owner(gamever, module, platform, symbol, va):
    """Another artifact already at this func_va (one address, one name)."""
    folder = REPO / "bin_artifacts" / str(gamever) / module
    for path in folder.glob(f"*.{platform}.yaml"):
        if path.name == f"{symbol}.{platform}.yaml":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^func_va:\s*'?(0x[0-9a-fA-F]+)", text, re.M)
        if m and int(m.group(1), 16) == va:
            return path.name[: -len(f".{platform}.yaml")]
    return None


def build_artifact(gamever, row, args, runner=subprocess.run):
    """(path in bin_artifacts or None, message)."""
    symbol, module, platform = row["symbol"], row["module"], row["platform"]
    with tempfile.TemporaryDirectory(prefix="cs2_review_") as scratch:
        stage = Path(scratch) / str(gamever) / module
        stage.mkdir(parents=True)
        done = runner([sys.executable, str(REPO / "emit_artifact.py"), "-gamever", str(gamever), "-module", module,
                       "-platform", platform, "-symbol", symbol, *args, "-outdir", str(stage)],
                      cwd=REPO, capture_output=True, text=True, timeout=3600)
        out = stage / f"{symbol}.{platform}.yaml"
        tail = "\n".join((done.stdout or "").splitlines()[-6:])
        if done.returncode != 0 or not out.is_file():
            return None, f"the checks refused it (exit {done.returncode}):\n```\n{tail}\n```"
        text = out.read_text(encoding="utf-8")
        m = re.search(r"^func_va:\s*'?(0x[0-9a-fA-F]+)", text, re.M)
        va = int(m.group(1), 16) if m else None
        owner = duplicate_owner(gamever, module, platform, symbol, va) if va is not None else None
        if owner:
            return None, f"`{hex(va)}` is already `{owner}` - one address, one name"
        dest_dir = REPO / "bin_artifacts" / str(gamever) / module
        dest = dest_dir / out.name
        shutil.copyfile(out, dest)
        mirror = REPO / "bin" / str(gamever) / module
        if mirror.is_dir():
            shutil.copyfile(out, mirror / out.name)
        note = ""
        if row.get("candidate") and va is not None:
            note = (" It matches the run's best candidate." if int(row["candidate"], 16) == va
                    else f" (The run's best candidate was `{row['candidate']}`.)")
        return dest, f"written and validated.{note}\n```yaml\n{text.strip()}\n```"


def reaction_for(ok, refused, noted):
    """+1 everything written, -1 everything refused, eyes for a mix or a noted /reject."""
    if ok and not refused and not noted:
        return "+1"
    if refused and not ok and not noted:
        return "-1"
    return "eyes"


def reject(row, login, reason):
    """Keep the entry, but record who rejected which candidate and why."""
    path = Path(row["path"])
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        if not line.startswith("#") and line.split()[:1] == [row["symbol"]]:
            line = f"{line} | rejected by @{login}: {reason or 'no reason given'}"
        out.append(line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def apply(gamever, commit=False, dry_run=False, platform=None):
    me = my_login()
    written = []
    failure = None
    for one in (platform,) if platform else PLATFORMS:
        try:
            _apply_issue(gamever, one, me, dry_run, written)
        except Exception as error:
            # a comment already has its reaction once its artifact is written, so the
            # artifacts must still be committed or the next run would never see them again
            failure = error
            print(f"[review] {one}: stopped early ({error}) - committing what was written")
            break
    if written and commit and not dry_run:
        paths = [str(p.relative_to(REPO)) for p in written]
        # the server's tree carries a run's uncommitted output: only these paths are
        # committed, and the branch is brought up to date first so the push is a fast-forward
        subprocess.run(["git", "pull", "-q", "--ff-only", "origin", "main"], cwd=REPO, check=False)
        subprocess.run(["git", "add", "--", *paths], cwd=REPO, check=True)
        subprocess.run(["git", "commit", "-q", "-m",
                        f"feat({gamever}): {len(paths)} symbol(s) confirmed in symbol review", "--", *paths],
                       cwd=REPO, check=True)
        subprocess.run(["git", "push", "-q", "origin", "HEAD"], cwd=REPO, check=True)
        print(f"[review] committed and pushed {len(paths)} artifact(s)")
    if not dry_run:
        # the todo list drops entries whose artifact now exists; refresh the issues from it
        import ida_analyze_bin

        for path in (REPO / "manual_todo" / str(gamever)).glob("*.txt"):
            module, file_platform = path.stem.rsplit(".", 1)
            ida_analyze_bin.update_manual_todo(str(path), str(REPO / "bin_artifacts" / str(gamever) / module),
                                               file_platform, {})
        for one in (platform,) if platform else PLATFORMS:
            try:
                if find_issue(gamever, one) is not None or read_todo(gamever, platform=one):
                    publish(gamever, one)
            except Exception as error:
                print(f"[review] {one}: issue not refreshed ({error}) - the next run refreshes it")
    if failure is not None:
        raise failure
    return 0


def _apply_issue(gamever, platform, me, dry_run, written):
    issue = find_issue(gamever, platform)
    if issue is None:
        print(f"[review] no {platform} review issue for {gamever}")
        return written
    number = str(issue["number"])
    comments = issue_comments(number)
    log_id, log_sections = bot_log(number, comments)
    done = done_lines(log_sections)
    new_sections = []
    for comment in comments:
        commands = parse_commands(comment["body"])
        if not commands or BOT_MARK in comment["body"]:
            continue
        if comment["author_association"] not in TRUSTED:
            continue
        seen = done.get(int(comment["id"]))
        if seen is None and reacted_by(comment["id"], me):
            continue  # handled before the log kept line markers
        keyed = [(line_key(*command), command) for command in commands]
        pending = [(key, command) for key, command in keyed if not seen or key not in seen]
        if not pending:
            continue
        edited = seen is not None
        rows = read_todo(gamever, platform=platform)
        replies, ok, refused, noted = [], 0, 0, 0
        for _key, (verb, symbol, named_platform, tokens) in pending:
            if named_platform and named_platform != platform:
                replies.append(f"- `{symbol}`: this is the {platform} issue - post {named_platform} answers in its own issue")
                refused += 1
                continue
            row, problem = target_row(rows, symbol, platform)
            if problem:
                replies.append(f"- `{symbol}`: {problem}")
                refused += 1
                continue
            if verb == "reject":
                if not dry_run:
                    reject(row, comment["login"], " ".join(tokens))
                replies.append(f"- `{symbol}` ({row['platform']}): noted as rejected - it stays on the list for another look")
                noted += 1
                continue
            args, problem = rule_args(tokens)
            if problem:
                replies.append(f"- `{symbol}`: {problem}")
                refused += 1
                continue
            if dry_run:
                replies.append(f"- `{symbol}` ({row['platform']}): would build with {' '.join(args)}")
                continue
            path, message = build_artifact(gamever, row, args)
            replies.append(f"- `{symbol}` ({row['platform']}): {message}")
            if path:
                written.append(path)
                ok += 1
            else:
                refused += 1
        print("\n".join(replies))
        if dry_run:
            continue
        handled = sorted((seen or set()) | {key for key, _ in keyed})
        what = (f" - edited: {len(pending)} new or changed line(s); lines already handled are not repeated"
                if edited else "")
        new_sections.append(f"re @{comment['login']} ([comment]({comment.get('url', '')})){what}:\n\n"
                            + "\n".join(replies) + f"\n<!-- done:{comment['id']}:{','.join(handled)} -->\n")
        done[int(comment["id"])] = set(handled)
        # the log first, then the reaction: a reacted comment is never read again, so its
        # result must already be recorded
        log_id = write_bot_log(number, log_id, log_sections + new_sections)
        if edited:
            replace_reaction(comment["id"], reaction_for(ok, refused, noted), me)
        else:
            react(comment["id"], reaction_for(ok, refused, noted))
    return written


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("publish", "apply"):
        p = sub.add_parser(name)
        p.add_argument("-gamever", required=True)
        p.add_argument("-platform", choices=PLATFORMS, help="only this platform's issue (default: both)")
        if name == "apply":
            p.add_argument("-commit", action="store_true", help="commit and push the artifacts written")
            p.add_argument("-dry_run", action="store_true", help="read the commands, change nothing")
    args = ap.parse_args()
    args.gamever = resolve_gamever(args.gamever)
    if not args.gamever:
        print("[review] no manual list yet - nothing to do")
        return 0
    if args.command == "publish":
        publish(args.gamever, args.platform)
        return 0
    return apply(args.gamever, commit=args.commit, dry_run=args.dry_run, platform=args.platform)


if __name__ == "__main__":
    sys.exit(main())
