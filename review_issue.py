#!/usr/bin/env python3
"""review_issue.py - let people without IDA confirm what the run could not prove.

The run leaves what neither its hunter nor an agent could prove in
manual_todo/<gamever>/<module>.<platform>.txt. This tool mirrors that list into one
GitHub issue per gamever and acts on review comments:

    uv run review_issue.py publish -gamever 14182          # create / refresh the issue
    uv run review_issue.py apply   -gamever 14182 -commit  # act on /confirm and /reject

Comment grammar (one command per line, any number per comment):

    /confirm <Symbol> [linux|windows] 0x<address>              a function head
    /confirm <Symbol> [linux|windows] vfunc <Class> <index>     a vtable slot
    /confirm <Symbol> [linux|windows] gv 0x<instruction>        the instruction loading a global
    /reject  <Symbol> [linux|windows] <reason>

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
from pathlib import Path

REPO = Path(__file__).resolve().parent
LABEL = "symbol-review"
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
PLATFORMS = ("linux", "windows")
COMMAND_RE = re.compile(r"^\s*/(confirm|reject)\s+([A-Za-z_][A-Za-z0-9_]*)\s*(.*?)\s*$", re.M)
MAX_BODY = 60000


def resolve_gamever(gamever):
    """'latest' -> the newest gamever that has a manual list (what a timer wants)."""
    if gamever != "latest":
        return gamever
    import hunt_core

    root = REPO / "manual_todo"
    versions = [d.name for d in root.iterdir() if d.is_dir()] if root.is_dir() else []
    return max(versions, key=hunt_core.version_key) if versions else None


def title_for(gamever):
    return f"Symbol review: {gamever}"


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
    done = subprocess.run(["gh", *args], cwd=REPO, input=stdin, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {done.stderr.strip()[-400:]}")
    return done.stdout


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


def read_todo(gamever, root=REPO):
    rows = []
    folder = Path(root) / "manual_todo" / str(gamever)
    for path in sorted(folder.glob("*.txt")) if folder.is_dir() else ():
        module, platform = path.stem.rsplit(".", 1)
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split(None, 2)
            if len(parts) < 2:
                continue
            row = {"module": module, "platform": platform, "symbol": parts[0], "task": parts[1], "path": str(path)}
            row.update(parse_detail(parts[2] if len(parts) > 2 else ""))
            rows.append(row)
    return rows


def render_body(gamever, rows):
    lines = [
        f"The {gamever} run could not prove these symbols on its own: the hunter's evidence was too weak "
        "and no agent got it right. If you can tell which function (or slot, or global) is the right "
        "one, say so in a comment - no IDA needed if you can read the candidate's code in any "
        "disassembler.",
        "",
        "**How to answer** (one command per line; only the repository's collaborators are read):",
        "",
        "```",
        "/confirm <Symbol> [linux|windows] 0x<address>            a function head",
        "/confirm <Symbol> [linux|windows] vfunc <Class> <index>   a vtable slot",
        "/confirm <Symbol> [linux|windows] gv 0x<instruction>      the instruction loading a global",
        "/reject  <Symbol> [linux|windows] <reason>                e.g. inlined, or gone from this build",
        "```",
        "",
        "A confirm is not trusted blindly: the artifact is rebuilt from the binary and must pass the "
        "same checks as everything else (unique signature, function boundary, not the entry point, "
        "vtable slot via RTTI, one address one name). You get a reply either way, usually within 15 "
        "minutes. Full guide: [docs/en/symbol-review.md](../blob/main/docs/en/symbol-review.md).",
        "",
    ]
    if not rows:
        lines.append("**Nothing left - every symbol has an artifact.**")
        return "\n".join(lines)
    groups = {}
    for row in rows:
        groups.setdefault((row["module"], row["platform"]), []).append(row)
    for (module, platform), items in sorted(groups.items()):
        lines += [f"### {module} ({platform}) - {len(items)}", "",
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

def find_issue(gamever):
    found = json.loads(gh("issue", "list", "--label", LABEL, "--state", "all", "--limit", "50",
                          "--json", "number,title,state"))
    for issue in found:
        if issue["title"] == title_for(gamever):
            return issue
    return None


def publish(gamever, rows=None):
    rows = read_todo(gamever) if rows is None else rows
    body = render_body(gamever, rows)
    issue = find_issue(gamever)
    if issue is None:
        if not rows:
            print(f"[review] nothing to review for {gamever}")
            return None
        gh("label", "create", LABEL, "--color", "D4C5F9", "--description",
           "Symbols the run could not prove on its own", "--force")
        url = gh("issue", "create", "--title", title_for(gamever), "--label", LABEL, "--body-file", "-", stdin=body).strip()
        print(f"[review] opened {url} ({len(rows)} symbols)")
        return url
    number = str(issue["number"])
    gh("issue", "edit", number, "--body-file", "-", stdin=body)
    if rows and issue["state"] == "CLOSED":
        gh("issue", "reopen", number)
    if not rows and issue["state"] == "OPEN":
        gh("issue", "close", number, "--comment", "Every symbol now has an artifact - closing.")
    print(f"[review] refreshed #{number} ({len(rows)} symbols)")
    return number


def issue_comments(number):
    out = gh("api", f"repos/{{owner}}/{{repo}}/issues/{number}/comments", "--paginate",
             "--jq", ".[] | {id, body, author_association, login: .user.login}")
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def my_login():
    return gh("api", "user", "--jq", ".login").strip()


def reacted_by(comment_id, login):
    out = gh("api", f"repos/{{owner}}/{{repo}}/issues/comments/{comment_id}/reactions", "--jq", ".[].user.login")
    return login in out.split()


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


def apply(gamever, commit=False, dry_run=False):
    issue = find_issue(gamever)
    if issue is None:
        print(f"[review] no review issue for {gamever}")
        return 0
    number = str(issue["number"])
    me = my_login()
    written = []
    for comment in issue_comments(number):
        commands = parse_commands(comment["body"])
        if not commands or comment["login"] == me and comment["body"].startswith("**review bot**"):
            continue
        if comment["author_association"] not in TRUSTED:
            continue
        if reacted_by(comment["id"], me):
            continue
        rows = read_todo(gamever)
        replies, ok, refused = [], 0, 0
        for verb, symbol, platform, tokens in commands:
            row, problem = target_row(rows, symbol, platform)
            if problem:
                replies.append(f"- `{symbol}`: {problem}")
                refused += 1
                continue
            if verb == "reject":
                if not dry_run:
                    reject(row, comment["login"], " ".join(tokens))
                replies.append(f"- `{symbol}` ({row['platform']}): noted as rejected - it stays on the list for another look")
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
        gh("issue", "comment", number, "--body-file", "-",
           stdin=f"**review bot** - re @{comment['login']}:\n\n" + "\n".join(replies))
        react(comment["id"], "+1" if ok and not refused else "-1" if refused and not ok else "eyes")
    if written and commit and not dry_run:
        paths = [str(p.relative_to(REPO)) for p in written]
        # the server's tree carries a run's uncommitted output: only these paths are
        # committed, and the branch is brought up to date first so the push is a fast-forward
        subprocess.run(["git", "pull", "-q", "--ff-only", "origin", "main"], cwd=REPO, check=False)
        subprocess.run(["git", "add", "--", *paths], cwd=REPO, check=True)
        subprocess.run(["git", "commit", "-q", "-m",
                        f"feat({gamever}): {len(paths)} symbol(s) confirmed in review #{number}", "--", *paths],
                       cwd=REPO, check=True)
        subprocess.run(["git", "push", "-q", "origin", "HEAD"], cwd=REPO, check=True)
        print(f"[review] committed and pushed {len(paths)} artifact(s)")
    if not dry_run:
        # the todo list drops entries whose artifact now exists; refresh the issue from it
        import ida_analyze_bin

        for path in (REPO / "manual_todo" / str(gamever)).glob("*.txt"):
            module, platform = path.stem.rsplit(".", 1)
            ida_analyze_bin.update_manual_todo(str(path), str(REPO / "bin_artifacts" / str(gamever) / module), platform, {})
        publish(gamever)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("publish", "apply"):
        p = sub.add_parser(name)
        p.add_argument("-gamever", required=True)
        if name == "apply":
            p.add_argument("-commit", action="store_true", help="commit and push the artifacts written")
            p.add_argument("-dry_run", action="store_true", help="read the commands, change nothing")
    args = ap.parse_args()
    args.gamever = resolve_gamever(args.gamever)
    if not args.gamever:
        print("[review] no manual list yet - nothing to do")
        return 0
    if args.command == "publish":
        publish(args.gamever)
        return 0
    return apply(args.gamever, commit=args.commit, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
