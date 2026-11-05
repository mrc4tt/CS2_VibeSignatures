#!/usr/bin/env python3
"""Server owners' own gamedata files, kept here and brought up to date every build.

A file is uploaded once and gets two secret links, no account:

  read link    /api/files/<id>/<filename>   what a server fetches (curl/wget at start-up)
  manage link  sig.miksen.me/my-file#<token> history, replace, webhook, delete

The id IS the read secret (128 bits from secrets). The manage token is never stored:
only its sha256 is, as the name of a file in by_manage/ that holds the id, so a copy of
this directory does not hand out the right to change or delete anyone's file.

Layout under ROOT (CS2VIBE_USER_FILES, default /var/lib/cs2vibe-files, systemd's
StateDirectory for cs2vibe-verify):

  files/<id>/original   the text as uploaded (or last replaced)
  files/<id>/current    what the read link serves: original plus every update since
  files/<id>/meta.json  filename, created, baseline_build, last_fetch, history, webhook
  by_manage/<sha256>    the id
  .lock                 fcntl lock every writer takes

The service (cs2vibe-verify) and user_gamedata.py (root, from autopilot) both write
here; a write by root is chowned to the directory's owner so the service can still read
and replace it. The file's text is the user's: it is never published, logged or copied
anywhere else. Reports outside this directory carry key names and our own values only.
"""

import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import time

ROOT = os.environ.get("CS2VIBE_USER_FILES", "/var/lib/cs2vibe-files")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
MAX_FILES = 2000
MAX_HISTORY = 50
# A file nobody fetched for this long is dropped: the link is dead weight, and the
# user's text should not sit here for ever because they forgot it.
EXPIRE_DAYS = 90
# last_fetch is a write on a GET; once an hour is enough to know a file is alive.
FETCH_TOUCH_SECONDS = 3600
WEBHOOK_RE = re.compile(r"^https://(?:discord\.com|discordapp\.com|ptb\.discord\.com|canary\.discord\.com)"
                        r"/api/webhooks/\d{5,25}/[A-Za-z0-9_-]{20,100}$")
DEFAULT_FILENAME = "gamedata.json"


class StoreError(Exception):
    """A request this store refuses; the message is safe to show the caller."""


def _root(root=None):
    return root or ROOT


def clean_filename(name):
    """A filename that is safe in a path and a URL, keeping the user's extension."""
    base = os.path.basename(str(name or "")).strip()
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")[:100]
    return base or DEFAULT_FILENAME


def check_webhook(url):
    if url in (None, ""):
        return None
    if not isinstance(url, str) or not WEBHOOK_RE.match(url.strip()):
        raise StoreError("webhook must be a Discord webhook URL (https://discord.com/api/webhooks/...)")
    return url.strip()


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


@contextlib.contextmanager
def locked(root=None):
    root = _root(root)
    os.makedirs(os.path.join(root, "files"), exist_ok=True)
    os.makedirs(os.path.join(root, "by_manage"), exist_ok=True)
    with open(os.path.join(root, ".lock"), "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield root
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _owner_fix(path, root):
    """root writing for the service: hand the file to whoever owns the store."""
    if os.geteuid() != 0:
        return
    try:
        st = os.stat(root)
        os.chown(path, st.st_uid, st.st_gid)
    except OSError:
        pass


def _write(path, data, root):
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(data)
    os.chmod(tmp, 0o600)
    _owner_fix(tmp, root)
    os.replace(tmp, path)


def _dir(root, file_id):
    if not isinstance(file_id, str) or not ID_RE.match(file_id):
        raise StoreError("unknown file")
    return os.path.join(root, "files", file_id)


def _read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def load_meta(file_id, root=None):
    root = _root(root)
    path = os.path.join(_dir(root, file_id), "meta.json")
    try:
        return json.loads(_read(path))
    except FileNotFoundError:
        raise StoreError("unknown file") from None


def _save_meta(file_id, meta, root):
    _write(os.path.join(_dir(root, file_id), "meta.json"), json.dumps(meta, indent=1, sort_keys=True), root)


def count(root=None):
    try:
        return sum(1 for name in os.listdir(os.path.join(_root(root), "files")) if ID_RE.match(name))
    except FileNotFoundError:
        return 0


def list_ids(root=None):
    try:
        return sorted(name for name in os.listdir(os.path.join(_root(root), "files")) if ID_RE.match(name))
    except FileNotFoundError:
        return []


def create(text, filename, build, fmt=None, webhook=None, root=None, now=None):
    """-> (id, manage token). The token is shown once and never stored."""
    webhook = check_webhook(webhook)
    now = int(now or time.time())
    with locked(root) as root:
        if count(root) >= MAX_FILES:
            raise StoreError("the store is full, try again later")
        os.makedirs(os.path.join(root, "files"), exist_ok=True)
        while True:
            file_id = secrets.token_urlsafe(16)
            if ID_RE.match(file_id) and not os.path.exists(_dir(root, file_id)):
                break
        token = secrets.token_urlsafe(32)
        folder = _dir(root, file_id)
        os.makedirs(folder, mode=0o700)
        _owner_fix(folder, root)
        _write(os.path.join(folder, "original"), text, root)
        _write(os.path.join(folder, "current"), text, root)
        meta = {"filename": clean_filename(filename), "format": fmt, "created": now, "updated": now,
                "baseline_build": build, "last_fetch": None, "history": [], "webhook": webhook}
        _save_meta(file_id, meta, root)
        _write(os.path.join(root, "by_manage", token_hash(token)), file_id, root)
    return file_id, token


def resolve_token(token, root=None):
    """The id a manage token controls, or StoreError."""
    if not isinstance(token, str) or not TOKEN_RE.match(token):
        raise StoreError("unknown manage token")
    try:
        file_id = _read(os.path.join(_root(root), "by_manage", token_hash(token))).strip()
    except FileNotFoundError:
        raise StoreError("unknown manage token") from None
    load_meta(file_id, root)
    return file_id


def fetch(file_id, root=None, now=None):
    """-> (filename, text) for the read link, noting the fetch at most once an hour."""
    root = _root(root)
    folder = _dir(root, file_id)
    try:
        text = _read(os.path.join(folder, "current"))
    except FileNotFoundError:
        raise StoreError("unknown file") from None
    meta = load_meta(file_id, root)
    now = int(now or time.time())
    if not meta.get("last_fetch") or now - int(meta["last_fetch"]) >= FETCH_TOUCH_SECONDS:
        with locked(root):
            try:
                meta = load_meta(file_id, root)
            except StoreError:
                return meta["filename"], text
            meta["last_fetch"] = now
            _save_meta(file_id, meta, root)
    return meta["filename"], text


def public_meta(file_id, root=None):
    """What the manage page shows: everything but the webhook's secret part."""
    meta = load_meta(file_id, root)
    out = {key: meta.get(key) for key in ("filename", "format", "created", "updated", "baseline_build",
                                         "last_fetch", "history")}
    out["id"] = file_id
    out["webhook"] = bool(meta.get("webhook"))
    return out


def current_text(file_id, root=None):
    return _read(os.path.join(_dir(_root(root), file_id), "current"))


def replace(file_id, text=None, filename=None, build=None, fmt=None, webhook=..., root=None, now=None):
    """A new upload under the same links: history restarts from it."""
    now = int(now or time.time())
    if webhook is not ...:
        webhook = check_webhook(webhook)
    with locked(root) as root:
        meta = load_meta(file_id, root)
        folder = _dir(root, file_id)
        if text is not None:
            _write(os.path.join(folder, "original"), text, root)
            _write(os.path.join(folder, "current"), text, root)
            meta["baseline_build"] = build
            meta["format"] = fmt
            meta["history"] = [{"build": build, "at": now, "event": "replaced", "changes": [],
                                "unresolved": []}]
        if filename:
            meta["filename"] = clean_filename(filename)
        if webhook is not ...:
            meta["webhook"] = webhook
        meta["updated"] = now
        _save_meta(file_id, meta, root)
        return meta


def record_update(file_id, build, text, changes, unresolved, root=None, now=None):
    """The build's update: new current text (when it changed), one history entry."""
    now = int(now or time.time())
    with locked(root) as root:
        meta = load_meta(file_id, root)
        if text is not None and text != current_text(file_id, root):
            _write(os.path.join(_dir(root, file_id), "current"), text, root)
            meta["updated"] = now
        history = [h for h in meta.get("history") or [] if h.get("build") != build or h.get("event") == "replaced"]
        history.append({"build": build, "at": now, "event": "update", "changes": changes, "unresolved": unresolved})
        meta["history"] = history[-MAX_HISTORY:]
        meta["baseline_build"] = build
        _save_meta(file_id, meta, root)
        return meta


def delete(file_id, token=None, root=None):
    with locked(root) as root:
        folder = _dir(root, file_id)
        if not os.path.isdir(folder):
            raise StoreError("unknown file")
        for name in os.listdir(folder):
            os.unlink(os.path.join(folder, name))
        os.rmdir(folder)
        manage = os.path.join(root, "by_manage")
        if token:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(os.path.join(manage, token_hash(token)))
        else:
            for name in os.listdir(manage):
                path = os.path.join(manage, name)
                with contextlib.suppress(OSError):
                    if _read(path).strip() == file_id:
                        os.unlink(path)


def expire(root=None, now=None, days=EXPIRE_DAYS):
    """Delete every file neither fetched nor uploaded for `days`. -> deleted ids."""
    now = int(now or time.time())
    gone = []
    for file_id in list_ids(root):
        try:
            meta = load_meta(file_id, root)
        except (StoreError, ValueError):
            continue
        seen = max(int(meta.get("last_fetch") or 0), int(meta.get("updated") or 0), int(meta.get("created") or 0))
        if now - seen > days * 86400:
            delete(file_id, root=root)
            gone.append(file_id)
    return gone
