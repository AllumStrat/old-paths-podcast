"""One-command credential setup for the Old Paths devo: GitHub secrets + Kobo (KOReader) cloud storage.

Secrets are only ever held in memory, sent to `gh secret set` on stdin, and written to the Kobo's
KOReader cloudstorage.lua. Nothing is printed or logged.
"""
import getpass
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import devo

DEFAULT_REPO = "AllumStrat/old-paths-podcast"
DEFAULT_KOBO = "/Volumes/KOBOeReader"
SERVER_NAME = "Old Paths Devo"
KOBO_DEST = "/mnt/onboard/Devo"
LUA_HEADER = "-- we can read Lua syntax here!\n"


# ------------------------------------------------------------------ Lua (LuaSettings subset)

class LuaError(ValueError):
    pass


_ESC = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t", "\0": "\\0"}


def lua_quote(s):
    return '"' + "".join(_ESC.get(c, c) for c in s) + '"'


def _lua_scalar(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return lua_quote(v)
    raise LuaError(f"cannot serialize {type(v).__name__}")


def _lua_key(k):
    return f"[{k}]" if isinstance(k, int) and not isinstance(k, bool) else f"[{lua_quote(str(k))}]"


def lua_serialize(value, indent=0):
    """dict -> Lua table text (4-space indent like LuaSettings). Lists become [1]..[n]."""
    if isinstance(value, list):
        value = {i + 1: v for i, v in enumerate(value)}
    if not isinstance(value, dict):
        return _lua_scalar(value)
    if not value:
        return "{}"
    pad, pad2 = " " * indent, " " * (indent + 4)
    lines = ["{"]
    for k, v in value.items():
        lines.append(f"{pad2}{_lua_key(k)} = {lua_serialize(v, indent + 4)},")
    lines.append(pad + "}")
    return "\n".join(lines)


_UNESC = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "'": "'", "0": "\0", "a": "\a",
          "b": "\b", "f": "\f", "v": "\v", "\n": "\n"}
_NUM = re.compile(r"-?(?:0[xX][0-9a-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+)")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class _Parser:
    def __init__(self, text):
        self.t, self.i = text, 0

    def err(self, msg):
        raise LuaError(f"{msg} at offset {self.i}")

    def ws(self):
        t = self.t
        while self.i < len(t):
            if t[self.i].isspace():
                self.i += 1
            elif t.startswith("--", self.i):
                if t.startswith("--[[", self.i):
                    j = t.find("]]", self.i)
                    if j < 0:
                        self.err("unterminated comment")
                    self.i = j + 2
                else:
                    j = t.find("\n", self.i)
                    self.i = len(t) if j < 0 else j + 1
            else:
                break

    def peek(self):
        self.ws()
        return self.t[self.i] if self.i < len(self.t) else ""

    def expect(self, ch):
        if self.peek() != ch:
            self.err(f"expected {ch!r}")
        self.i += 1

    def string(self):
        q = self.t[self.i]
        self.i += 1
        out = []
        while self.i < len(self.t):
            c = self.t[self.i]
            if c == q:
                self.i += 1
                return "".join(out)
            if c == "\\":
                self.i += 1
                if self.i >= len(self.t):
                    break
                e = self.t[self.i]
                if e in _UNESC:
                    out.append(_UNESC[e])
                    self.i += 1
                elif e.isdigit():
                    m = re.compile(r"\d{1,3}").match(self.t, self.i)
                    out.append(chr(int(m.group())))
                    self.i = m.end()
                else:
                    self.err("unsupported escape")
            else:
                out.append(c)
                self.i += 1
        self.err("unterminated string")

    def value(self):
        c = self.peek()
        if c == "":
            self.err("unexpected end")
        if c == "{":
            return self.table()
        if c in "\"'":
            return self.string()
        m = _NUM.match(self.t, self.i)
        if m:
            self.i = m.end()
            txt = m.group()
            return int(txt, 16) if txt.lower().lstrip("-").startswith("0x") else (
                float(txt) if re.search(r"[.eE]", txt) else int(txt))
        m = _IDENT.match(self.t, self.i)
        if m and m.group() in ("true", "false", "nil"):
            self.i = m.end()
            return {"true": True, "false": False, "nil": None}[m.group()]
        self.err("unsupported value")

    def table(self):
        self.expect("{")
        out, n = {}, 1
        while True:
            c = self.peek()
            if c == "}":
                self.i += 1
                return out
            if c == "":
                self.err("unterminated table")
            if c == "[":
                self.i += 1
                key = self.value()
                self.expect("]")
                self.expect("=")
                if not isinstance(key, (str, int)) or isinstance(key, bool):
                    self.err("unsupported key")
                out[key] = self.value()
            else:
                m = _IDENT.match(self.t, self.i)
                after = m and self.t[m.end():].lstrip()[:1] == "=" and self.t[m.end():].lstrip()[:2] != "=="
                if m and after and m.group() not in ("true", "false", "nil"):
                    self.i = m.end()
                    self.expect("=")
                    out[m.group()] = self.value()
                else:
                    out[n] = self.value()
                    n += 1
            if self.peek() in (",", ";"):
                self.i += 1


def lua_parse_settings(text):
    """Parse LuaSettings output ('-- comment' lines, then `return { ... }`) to a dict."""
    p = _Parser(text)
    try:
        p.ws()
        if not text.startswith("return", p.i):
            p.err("expected 'return'")
        p.i += len("return")
        val = p.table()
        p.ws()
        if p.i != len(text):
            p.err("trailing content")
    except (IndexError, RecursionError, ValueError) as e:
        if isinstance(e, LuaError):
            raise
        raise LuaError(f"malformed Lua ({type(e).__name__})")
    return val


def lua_dumps_settings(data):
    return LUA_HEADER + "return " + lua_serialize(data) + "\n"


def read_settings(path):
    path = Path(path)
    if not path.exists() or not path.read_text().strip():
        return {}
    return lua_parse_settings(path.read_text())


def upsert_server(data, entry):
    """Replace the cs_servers entry whose name matches, else append. Returns data."""
    servers = data.get("cs_servers")
    if servers is None:
        servers = data["cs_servers"] = {}
    if isinstance(servers, list):
        servers = data["cs_servers"] = {i + 1: v for i, v in enumerate(servers)}
    if not isinstance(servers, dict):
        raise LuaError("cs_servers is not a table")
    for k, v in servers.items():
        if isinstance(v, dict) and v.get("name") == entry["name"]:
            servers[k] = entry
            return data
    nums = [k for k in servers if isinstance(k, int)]
    servers[(max(nums) if nums else 0) + 1] = entry
    return data


def server_entry(key, secret, refresh):
    return {"type": "dropbox", "name": SERVER_NAME, "password": refresh, "address": f"{key}:{secret}",
            "url": "/", "sync_source_folder": "/", "sync_dest_folder": KOBO_DEST}


MANUAL_STEPS = """In KOReader: Cloud storage -> + -> Dropbox, then fill in:
   Name:      Old Paths Devo
   Password:  the Dropbox refresh token
   Address:   APPKEY:APPSECRET
   URL:       /
   (then long-press the entry -> Synchronize settings: source folder /, destination folder /mnt/onboard/Devo)
   Or re-run `python3 scripts/podcast.py devo-setup --kobo-only` with the Kobo plugged in."""


def write_kobo(kobo, key, secret, refresh, log=print):
    """Write the cloud-storage entry into KOReader's settings on a mounted Kobo. Returns True if written."""
    kobo = Path(kobo)
    settings_dir = kobo / ".adds" / "koreader" / "settings"
    if not settings_dir.is_dir():
        log(f"KOReader settings folder not found at {settings_dir}. Open KOReader on the Kobo once, then re-run.")
        log(MANUAL_STEPS)
        return False
    cfg = settings_dir / "cloudstorage.lua"
    try:
        data = read_settings(cfg)
        upsert_server(data, server_entry(key, secret, refresh))
        out = lua_dumps_settings(data)
        lua_parse_settings(out)  # must round-trip before we touch the file
    except (LuaError, OSError, UnicodeDecodeError) as e:
        log(f"Could not safely edit {cfg.name} ({e}); left untouched.")
        log(MANUAL_STEPS)
        return False
    if cfg.exists():
        bak = cfg.with_name(f"cloudstorage.lua.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        bak.write_bytes(cfg.read_bytes())
        log(f"  backed up to {bak.name}")
    tmp = cfg.with_name(cfg.name + ".tmp")
    tmp.write_text(out)
    os.replace(tmp, cfg)
    (kobo / "Devo").mkdir(exist_ok=True)
    log(f"  wrote '{SERVER_NAME}' to {cfg.name}; created Devo/")
    return True


# ------------------------------------------------------------------ GitHub

def gh_ok():
    try:
        return subprocess.run(["gh", "auth", "status"], capture_output=True, text=True).returncode == 0
    except FileNotFoundError:
        return False


def repo_slug():
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True,
                             check=True).stdout.strip()
        m = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?/?$", url)
        if m:
            return m.group(1)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return DEFAULT_REPO


def gh_secret_set(name, value, repo):
    subprocess.run(["gh", "secret", "set", name, "--repo", repo], input=value, text=True,
                   check=True, capture_output=True)


# ------------------------------------------------------------------ the command

def run(kobo=None, kobo_only=False, ask=input, ask_secret=getpass.getpass, log=print):
    kobo_path = Path(kobo or DEFAULT_KOBO)
    repo = None
    esv = ""
    if not kobo_only:
        log("1/6 Checking GitHub login")
        if not gh_ok():
            log("   gh is not logged in. Run `gh auth login`, then re-run this command.")
            return 1
        repo = repo_slug()
        log(f"   OK ({repo})")
        log("2/6 ESV")
        esv = ask_secret("   ESV API key (Enter to skip if already set): ").strip()
    log("3/6 Dropbox")
    key = ask("   Dropbox app key: ").strip()
    secret = ask_secret("   Dropbox app secret: ").strip()
    if not key or not secret:
        log("   App key and secret are required.")
        return 1
    refresh = devo.dropbox_authorize(key, secret, ask_code=ask, show=log)
    log("   Dropbox authorized.")
    if not kobo_only:
        log("4/6 Setting GitHub secrets")
        items = [("DROPBOX_APP_KEY", key), ("DROPBOX_APP_SECRET", secret), ("DROPBOX_REFRESH_TOKEN", refresh)]
        if esv:
            items.insert(0, ("ESV_API_KEY", esv))
        for name, val in items:
            try:
                gh_secret_set(name, val, repo)
            except subprocess.CalledProcessError as e:
                log(f"   x failed to set {name} (gh exit {e.returncode})")
                return 1
            log(f"   ✓ set {name}")
        log("5/6 Checking Dropbox access")
        try:
            n = devo.dropbox_check_root(key, secret, refresh)
            log(f"   OK (app folder lists fine, {n} item(s))")
        except Exception as e:
            log(f"   Dropbox check failed: {e}")
            log("   If this is a permissions error, enable files.metadata.read, files.content.read and "
                "files.content.write on the app's Permissions tab, then re-run this command.")
    log("6/6 Kobo")
    if kobo_path.is_dir():
        if write_kobo(kobo_path, key, secret, refresh, log=lambda m: log("   " + m.lstrip())):
            log(f"\n   Eject the Kobo, then in KOReader: Cloud storage → long-press '{SERVER_NAME}' → Sync now.")
    else:
        log(f"   No Kobo mounted at {kobo_path}.")
        log("   " + MANUAL_STEPS.replace("\n", "\n   "))
    log("\nDone.")
    return 0
