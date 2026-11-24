#!/usr/bin/env python3
"""Old Paths podcast pipeline.

Commands
  next              Print today's plan day, readings, and series context (JSON). No token needed.
  transcript        Print a previous episode's script. No token needed.
  stage             Push today's finished episode to a claude/episode-DATE branch. No token needed.
  publish-incoming  (GitHub Action) Make the audio for staged episodes and publish them.
  publish           Publish directly from work/ (needs GH_TOKEN).
  feed       Rebuild and upload feed.xml from the saved state.
  bootstrap  One-time setup: upload cover art and seed the series state.
  devo-check   Validate work/devo.md (markers cover each reading, word count). No token needed.
  devo-build   Build the Kobo devo EPUB from a devo.md (fetches ESV text; needs ESV_API_KEY or --fixture).
  devo-stage   Push devo-only days (backfills, reruns) to a claude/devo-TIMESTAMP branch. --dry-run skips the push.
  publish-devos  (GitHub Action) Build and deliver the devos staged in incoming-devo/.
  devo-setup   One-time interactive setup: GitHub secrets (ESV, Dropbox) and the Kobo's KOReader cloud storage.
               (dropbox-auth is an alias.)

Environment variables (only for publish, publish-incoming, feed, bootstrap)
  GH_TOKEN or GITHUB_TOKEN        token with contents and pages write access
  GH_REPO or GITHUB_REPOSITORY    owner/repo, for example jacob/old-paths-podcast
Optional
  PAGES_URL  only if your GitHub Pages address is not https://OWNER.github.io/REPO
Devo delivery (publish-incoming, devo-build): ESV_API_KEY, DROPBOX_APP_KEY, DROPBOX_APP_SECRET,
  DROPBOX_REFRESH_TOKEN. If unset, publish-incoming skips the devo with a warning.
"""
import argparse
import asyncio
import datetime as dt
import email.utils
import json
import os
import re
import ssl
import sys
import uuid
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import devo

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
CONFIG = json.loads((ROOT / "config.json").read_text())
PLAN = json.loads((ROOT / "plan" / "navigators.json").read_text())
DAYS = PLAN["days"]
IDS = [d["id"] for d in DAYS]
TZ = ZoneInfo(CONFIG["timezone"])
SYSTEM_CA = "/etc/ssl/certs/ca-certificates.crt"
STATE_KEY = "state/series.json"
NAMESPACE = uuid.UUID("6f1d3c52-8a4e-4c43-9a3e-01da4ba50000")


def env(name, *fallbacks):
    for key in (name,) + fallbacks:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    sys.exit(f"Missing environment variable {name}. See README.md.")


def now():
    return dt.datetime.now(TZ)


# ---------------------------------------------------------------- storage (GitHub)
#
# Text files (feed.xml, cover.png, state, transcripts, notes) live on the repo's
# gh-pages branch and are served by GitHub Pages. Each MP3 is attached to its own
# GitHub Release, so deleting the release after the retention window truly frees
# the space (deleting a committed file would leave it in git history forever).

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
DATA_BRANCH = "gh-pages"


class GitHub:
    def __init__(self):
        import requests

        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {env('GH_TOKEN', 'GITHUB_TOKEN')}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "old-paths-podcast",
        })
        if os.path.exists(SYSTEM_CA):
            self.s.verify = SYSTEM_CA  # trusts sandbox proxies as well as public CAs
        self.repo = repo_name()

    def req(self, method, url, ok=(200, 201, 204), **kw):
        if url.startswith("/"):
            url = f"{API}/repos/{self.repo}{url}"
        r = self.s.request(method, url, timeout=300, **kw)
        if r.status_code not in ok:
            raise SystemExit(f"GitHub API {method} {url} failed: {r.status_code} {r.text[:500]}")
        return r

    # ---- branch and files

    def branch_sha(self):
        r = self.req("GET", f"/git/ref/heads/{DATA_BRANCH}", ok=(200, 404))
        return r.json()["object"]["sha"] if r.status_code == 200 else None

    def ensure_branch(self):
        if self.branch_sha():
            return
        blob = self.req("POST", "/git/blobs", json={"content": "Old Paths feed data\n", "encoding": "utf-8"}).json()["sha"]
        tree = self.req("POST", "/git/trees", json={"tree": [
            {"path": "README.md", "mode": "100644", "type": "blob", "sha": blob}]}).json()["sha"]
        commit = self.req("POST", "/git/commits", json={"message": "Create feed branch", "tree": tree, "parents": []}).json()["sha"]
        self.req("POST", "/git/refs", json={"ref": f"refs/heads/{DATA_BRANCH}", "sha": commit})

    def get_text(self, path):
        r = self.req("GET", f"/contents/{path}", ok=(200, 404), params={"ref": DATA_BRANCH},
                     headers={"Accept": "application/vnd.github.raw+json"})
        return r.content.decode("utf-8") if r.status_code == 200 else None

    def commit(self, files, message):
        """Write several files to the data branch in one commit. files: {path: bytes|str}; value None deletes."""
        import base64

        head = self.branch_sha()
        base_tree = self.req("GET", f"/git/commits/{head}").json()["tree"]["sha"]
        entries = []
        for path, body in files.items():
            if body is None:
                entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
                continue
            if isinstance(body, str):
                body = body.encode("utf-8")
            blob = self.req("POST", "/git/blobs", json={"content": base64.b64encode(body).decode(),
                                                       "encoding": "base64"}).json()["sha"]
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob})
        tree = self.req("POST", "/git/trees", json={"base_tree": base_tree, "tree": entries}).json()["sha"]
        commit = self.req("POST", "/git/commits", json={"message": message, "tree": tree, "parents": [head]}).json()["sha"]
        self.req("PATCH", f"/git/refs/heads/{DATA_BRANCH}", json={"sha": commit})

    # ---- releases (audio)

    def upload_episode(self, tag, title, body, mp3_path):
        rel = self.req("POST", "/releases", json={"tag_name": tag, "name": title, "body": body[:100000],
                                                   "make_latest": "false"}).json()
        name = Path(mp3_path).name
        with open(mp3_path, "rb") as fh:
            asset = self.req("POST", f"{UPLOADS}/repos/{self.repo}/releases/{rel['id']}/assets",
                             params={"name": name}, data=fh,
                             headers={"Content-Type": "audio/mpeg"}).json()
        return rel["id"], asset["browser_download_url"]

    def release_exists(self, tag):
        return self.req("GET", f"/releases/tags/{tag}", ok=(200, 404)).status_code == 200

    def delete_episode(self, release_id, tag):
        self.req("DELETE", f"/releases/{release_id}", ok=(204, 404))
        self.req("DELETE", f"/git/refs/tags/{tag}", ok=(204, 404, 422))

    def delete_branch(self, name):
        self.req("DELETE", f"/git/refs/heads/{name}", ok=(204, 404, 422))

    # ---- pages

    def request_pages_build(self):
        self.req("POST", "/pages/builds", ok=(201, 403, 404, 409, 422))

    def enable_pages(self):
        r = self.req("GET", "/pages", ok=(200, 404))
        if r.status_code == 200:
            return r.json().get("html_url")
        r = self.req("POST", "/pages", ok=(201, 403, 404, 409, 422),
                     json={"source": {"branch": DATA_BRANCH, "path": "/"}})
        if r.status_code == 201:
            return r.json().get("html_url")
        print("note: could not turn on GitHub Pages automatically. In the repo, open Settings, then Pages, "
              f"and choose 'Deploy from a branch' with branch '{DATA_BRANCH}' and folder '/ (root)'.", file=sys.stderr)
        return None


def client():
    return GitHub()


def repo_name():
    """owner/repo from the environment, else from the git remote (works in Claude Code's cloud sandbox)."""
    for key in ("GH_REPO", "GITHUB_REPOSITORY"):
        if os.environ.get(key, "").strip():
            return os.environ[key].strip()
    import subprocess

    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.strip()
        parts = [p for p in re.split(r"[/:]", url.removesuffix(".git")) if p]
        return f"{parts[-2]}/{parts[-1]}"
    except Exception:
        sys.exit("Could not work out the GitHub repo. Set GH_REPO=owner/repo.")


def pages_url(path=""):
    base = os.environ.get("PAGES_URL", "").strip()
    if not base:
        owner, name = repo_name().split("/", 1)
        base = f"https://{owner.lower()}.github.io/{name}"
    return base.rstrip("/") + ("/" + path if path else "/")


def load_state(c):
    text = c.get_text(STATE_KEY)
    return json.loads(text) if text else None


def load_state_readonly():
    """Read series state without an API token: from the gh-pages branch via git, else from GitHub Pages."""
    import subprocess
    import urllib.request

    try:
        subprocess.run(["git", "fetch", "-q", "origin", f"+{DATA_BRANCH}:refs/remotes/origin/{DATA_BRANCH}"],
                       cwd=ROOT, check=True, capture_output=True, timeout=120)
        out = subprocess.run(["git", "show", f"origin/{DATA_BRANCH}:{STATE_KEY}"], cwd=ROOT, check=True,
                             capture_output=True, timeout=60)
        return json.loads(out.stdout.decode("utf-8"))
    except Exception as e:
        print(f"note: could not read state through git ({e}); trying GitHub Pages", file=sys.stderr)
    try:
        url = pages_url(STATE_KEY) + f"?t={int(dt.datetime.now().timestamp())}"
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"note: could not read state from {pages_url(STATE_KEY)} ({e})", file=sys.stderr)
    return None


def real_episodes(state):
    return [e for e in state.get("episodes", []) if not e.get("seed")]


# ---------------------------------------------------------------- plan

def plan_day(day_id):
    return DAYS[IDS.index(day_id)]


def next_id(day_id):
    i = IDS.index(day_id)
    return IDS[(i + 1) % len(IDS)]


def read_jump():
    path = ROOT / "plan" / "jump_to.txt"
    if not path.exists():
        return None
    lines = [l.strip() for l in path.read_text().splitlines() if l.strip() and not l.strip().startswith("#")]
    if not lines:
        return None
    value = lines[-1]
    if value not in IDS:
        print(f"warning: plan/jump_to.txt value '{value}' is not a valid plan day; ignoring", file=sys.stderr)
        return None
    return value


# ---------------------------------------------------------------- next

def cmd_next(args):
    state = load_state_readonly()
    if state is None:
        sys.exit("No series state found. Has bootstrap been run? (see README.md)")

    jump = read_jump()
    jump_applied = None
    day_id = state["next_plan_day"]
    if jump and jump != state.get("last_jump_applied"):
        day_id, jump_applied = jump, jump
        print(f"note: jumping to plan day {jump} from plan/jump_to.txt", file=sys.stderr)

    today = args.date or now().date().isoformat()
    episodes = state.get("episodes", [])
    if any(e["date"] == today for e in real_episodes(state)) and not args.force:
        print(json.dumps({"status": "already_published_today", "date": today}))
        sys.exit(3)

    day = plan_day(day_id)
    tomorrow = plan_day(next_id(day_id))
    recent_sources = {}
    for ep in episodes[-12:]:
        for name in ep.get("authors", []):
            recent_sources[name] = recent_sources.get(name, 0) + 1

    context = {
        "status": "ok",
        "date": today,
        "weekday": dt.date.fromisoformat(today).strftime("%A"),
        "episode_number": len(episodes) + 1,
        "plan_day": day_id,
        "jump_applied": jump_applied,
        "plan_position": f"Day {IDS.index(day_id) + 1} of {len(IDS)} (Month {day_id.split('-')[0]}, Day {day_id.split('-')[1]})",
        "readings": day["readings"],
        "next_plan_day_preview": tomorrow["readings"],
        "recent_episodes": [
            {k: ep.get(k) for k in ("number", "date", "plan_day", "title", "readings", "summary", "threads")}
            for ep in episodes[-6:]
        ],
        "previous_transcript_path": episodes[-1].get("transcript_path") if episodes else None,
        "authors_quoted_in_last_12_episodes": dict(sorted(recent_sources.items(), key=lambda kv: -kv[1])),
        "target_words": [CONFIG["target_words_min"], CONFIG["target_words_max"]],
    }
    WORK.mkdir(exist_ok=True)
    (WORK / "today.json").write_text(json.dumps(context, indent=1))
    print(json.dumps(context, indent=1))


def cmd_transcript(args):
    import subprocess

    state = load_state_readonly() or {}
    eps = state.get("episodes", [])
    if not eps:
        sys.exit("No episodes yet.")
    ep = eps[-1] if args.which == "last" else next((e for e in eps if e["date"] == args.which), None)
    if not ep or not ep.get("transcript_path"):
        sys.exit("Transcript not found.")
    out = subprocess.run(["git", "show", f"origin/{DATA_BRANCH}:{ep['transcript_path']}"], cwd=ROOT,
                         capture_output=True)
    if out.returncode == 0:
        print(out.stdout.decode("utf-8"))
    else:
        import urllib.request
        with urllib.request.urlopen(pages_url(ep["transcript_path"]), timeout=60) as r:
            print(r.read().decode("utf-8"))


# ---------------------------------------------------------------- tts

def clean_for_speech(text):
    text = re.sub(r"^\s*#+\s*", "", text, flags=re.M)        # markdown headings
    text = re.sub(r"[*_`]+", "", text)                        # emphasis marks
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)           # links
    text = text.replace("\u2014", ", ").replace("\u2013", " to ")
    text = re.sub(r"\bLORD\b", "Lord", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def patch_edge_tts_ssl():
    """edge-tts pins certifi's bundle; on Linux sandboxes behind a TLS proxy, use the system bundle."""
    if not os.path.exists(SYSTEM_CA):
        return
    import edge_tts.communicate as communicate

    communicate._SSL_CTX = ssl.create_default_context(cafile=SYSTEM_CA)


async def _synthesize(text, out_path):
    import edge_tts

    await edge_tts.Communicate(text, CONFIG["edge_voice"], rate=CONFIG["edge_rate"]).save(str(out_path))


def synthesize(text, out_path):
    if CONFIG.get("tts", "edge") == "kokoro":
        try:
            return synthesize_kokoro(text, out_path)
        except Exception as e:  # keep publishing on schedule; the Edge voice is the fallback
            print(f"Kokoro failed ({e!r}); falling back to Edge TTS", file=sys.stderr)
    patch_edge_tts_ssl()
    last = None
    for attempt in range(1, 4):
        try:
            asyncio.run(_synthesize(text, out_path))
            if out_path.exists() and out_path.stat().st_size > 10_000:
                return
            last = RuntimeError("TTS produced an empty or tiny file")
        except Exception as e:  # network hiccups from the TTS service
            last = e
        print(f"TTS attempt {attempt} failed: {last}", file=sys.stderr)
    raise SystemExit(f"Text-to-speech failed after 3 attempts: {last}")


ESPEAK_LIBS = ["/opt/homebrew/lib/libespeak-ng.dylib", "/usr/local/lib/libespeak-ng.dylib"]
ESPEAK_DATA_DIRS = ["/usr/lib/x86_64-linux-gnu/espeak-ng-data", "/usr/lib/aarch64-linux-gnu/espeak-ng-data",
                    "/usr/share/espeak-ng-data", "/opt/homebrew/share/espeak-ng-data", "/usr/local/share/espeak-ng-data"]


def use_system_espeak():
    """misaki points phonemizer at espeakng-loader's bundled espeak-ng, whose baked-in data path
    is broken in some wheels. Prefer a system espeak-ng (apt or Homebrew) when one is installed."""
    import ctypes.util

    import misaki.espeak  # noqa: F401  (sets the bundled paths on import; overridden below)
    from phonemizer.backend.espeak.wrapper import EspeakWrapper

    lib = ctypes.util.find_library("espeak-ng") or next((l for l in ESPEAK_LIBS if os.path.exists(l)), None)
    data = next((d for d in ESPEAK_DATA_DIRS if os.path.exists(os.path.join(d, "phontab"))), None)
    if lib and data:
        EspeakWrapper.set_library(lib)
        EspeakWrapper.set_data_path(data)


def synthesize_kokoro(text, out_path):
    """Render with the Kokoro-82M open model on the CPU, paragraph by paragraph, then encode to MP3."""
    import subprocess

    import numpy as np
    import soundfile as sf

    use_system_espeak()
    from kokoro import KPipeline

    voice = CONFIG["voice"]
    pipe = KPipeline(lang_code=voice[0], repo_id="hexgrad/Kokoro-82M", device="cpu")
    pause = np.zeros(int(24000 * 0.45), dtype=np.float32)
    parts = []
    for para in (p.strip() for p in re.split(r"\n\s*\n", text)):
        if not para:
            continue
        for _, _, audio in pipe(para, voice=voice, speed=float(CONFIG.get("voice_speed", 1.0))):
            if audio is not None:
                parts.append(np.asarray(audio, dtype=np.float32))
        parts.append(pause)
    if not parts:
        raise RuntimeError("Kokoro produced no audio")

    wav = Path(out_path).with_suffix(".wav")
    sf.write(str(wav), np.concatenate(parts), 24000)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav), "-ac", "1", "-b:a", "64k", str(out_path)],
                   check=True)
    wav.unlink()


def mp3_duration(path):
    from mutagen.mp3 import MP3

    return int(MP3(str(path)).info.length)


# ---------------------------------------------------------------- publish

def episode_guid(date):
    return str(uuid.uuid5(NAMESPACE, f"old-paths-{date}"))


def show_notes_text(meta):
    parts = []
    if meta.get("show_notes"):
        parts.append(meta["show_notes"].strip())
    if meta.get("sources"):
        parts.append("Sources quoted:")
        for src in meta["sources"]:
            line = " - " + ", ".join(x for x in (src.get("author"), src.get("work")) if x)
            if src.get("url"):
                line += f" ({src['url']})"
            parts.append(line)
    return "\n".join(parts)


def add_episode(state, *, date, day_id, meta, tag, release_id, mp3_url, size, duration, published, devo_info=None):
    number = len(state["episodes"]) + 1
    readings = meta.get("readings") or ([r["passage"] for r in plan_day(day_id)["readings"]] if day_id in IDS else [])
    state["episodes"].append({
        "number": number,
        "date": date,
        "published": published,
        "plan_day": day_id,
        "readings": readings,
        "title": meta["title"],
        "summary": meta.get("summary", ""),
        "threads": meta.get("threads", []),
        "authors": sorted({src.get("author", "").strip() for src in meta.get("sources", []) if src.get("author")}),
        "description": (", ".join(readings) + "\n\n" + show_notes_text(meta)).strip(),
        "tag": tag,
        "release_id": release_id,
        "mp3_url": mp3_url,
        "bytes": size,
        "duration": duration,
        "transcript_path": f"transcripts/{tag}.txt",
        "notes_path": f"notes/{tag}.md",
        "guid": episode_guid(tag),
        "audio_deleted": False,
    })
    if devo_info:
        state["episodes"][-1].update(devo_info)
    return state["episodes"][-1]


def prune(c, state):
    """Delete the audio (the GitHub Release) for episodes older than the retention window."""
    cutoff = now().date() - dt.timedelta(days=int(CONFIG["retention_days"]))
    removed = 0
    for ep in state["episodes"]:
        if not ep.get("audio_deleted") and dt.date.fromisoformat(ep["date"]) < cutoff:
            c.delete_episode(ep["release_id"], ep["tag"])
            ep["audio_deleted"] = True
            removed += 1
    return removed


def validate(raw, meta, allow_short=False):
    for field in ("title", "summary", "threads", "sources"):
        if field not in meta:
            sys.exit(f"meta.json is missing '{field}'")
    words = len(raw.split())
    lo, hi = CONFIG["target_words_min"], CONFIG["target_words_max"]
    if words < lo * 0.85 and not allow_short:
        sys.exit(f"Script is {words} words; target is {lo}-{hi}. Expand it, or pass --allow-short.")
    if words > hi * 1.1 and not allow_short:
        sys.exit(f"Script is {words} words; target is {lo}-{hi}. Cut it down, or pass --allow-short.")
    return words


def publish_episode(c, *, date, raw, meta, research="", plan_day_id=None, jump_applied=None, force=False,
                    devo_info=None):
    state = load_state(c)
    if state is None:
        sys.exit("No series state found. Run bootstrap first.")
    if any(e["date"] == date for e in real_episodes(state)) and not force:
        print(f"An episode for {date} already exists; skipping.", file=sys.stderr)
        return None
    if jump_applied:
        state["last_jump_applied"] = jump_applied
    day_id = plan_day_id or state["next_plan_day"]
    tag = f"ep-{date}" + ("" if not force else "-" + now().strftime("%H%M%S"))
    if c.release_exists(tag):
        tag = f"ep-{date}-{day_id}"  # an earlier episode was re-dated and still holds this tag

    WORK.mkdir(exist_ok=True)
    mp3 = WORK / f"old-paths-{date}.mp3"
    synthesize(clean_for_speech(raw), mp3)
    size, duration = mp3.stat().st_size, mp3_duration(mp3)
    print(f"audio: {size/1e6:.1f} MB, {duration//60}:{duration%60:02d}", file=sys.stderr)

    release_id, mp3_url = c.upload_episode(tag, meta["title"], show_notes_text(meta), mp3)
    ep = add_episode(state, date=date, day_id=day_id, meta=meta, tag=tag, release_id=release_id, mp3_url=mp3_url,
                     size=size, duration=duration, published=email.utils.format_datetime(now()),
                     devo_info=devo_info)
    state["next_plan_day"] = next_id(day_id) if day_id in IDS else state["next_plan_day"]
    removed = prune(c, state)
    files = {
        ep["transcript_path"]: raw,
        ep["notes_path"]: show_notes_text(meta) + ("\n\n---\nResearch notes\n\n" + research if research else ""),
        STATE_KEY: json.dumps(state, indent=1),
        "feed.xml": build_feed(state),
    }
    c.commit(files, f"Episode {ep['number']}: {meta['title']}")
    c.request_pages_build()
    result = {"status": "published", "episode": ep["number"], "plan_day": day_id,
              "next_plan_day": state["next_plan_day"], "audio": mp3_url,
              "feed": pages_url("feed.xml"), "pruned_old_episodes": removed}
    print(json.dumps(result, indent=1))
    return result


def cmd_publish(args):
    """Publish directly (needs GH_TOKEN). Used for manual runs."""
    raw = Path(args.script).read_text()
    meta = json.loads(Path(args.meta).read_text())
    print(f"script words: {validate(raw, meta, args.allow_short)}", file=sys.stderr)
    research = Path(args.research).read_text() if args.research and Path(args.research).exists() else ""
    today = {}
    if (WORK / "today.json").exists():
        today = json.loads((WORK / "today.json").read_text())
    publish_episode(client(), date=args.date or today.get("date") or now().date().isoformat(), raw=raw, meta=meta,
                    research=research, plan_day_id=today.get("plan_day"), jump_applied=today.get("jump_applied"),
                    force=args.force)


def devo_limits():
    return CONFIG.get("devo_words_min", 1800), CONFIG.get("devo_words_max", 3200)


def run_devo_check(path, readings, allow_short=False, quiet=False):
    """Print errors and warnings for a devo.md; return (ok, stats)."""
    wmin, wmax = devo_limits()
    errors, warnings, stats = devo.check_devo(Path(path).read_text(), readings, wmin, wmax, allow_short)
    for w in warnings:
        print(f"devo warning: {w}", file=sys.stderr)
    for e in errors:
        print(f"devo ERROR: {e}", file=sys.stderr)
    if not errors and not quiet:
        print(f"devo ok: {stats['words']} commentary words, {stats['readings']} readings, "
              f"{stats['chunks']} passage chunks ({wmin}-{wmax} allowed)", file=sys.stderr)
    return not errors, stats


def stage_devo(today, folder, allow_short):
    """Copy work/devo.md into the staging folder if it passes devo-check. Never blocks the podcast."""
    import shutil

    src = WORK / "devo.md"
    if not src.exists():
        print("WARNING: work/devo.md not found; staging the podcast without a devo.", file=sys.stderr)
        return False
    readings = [r["passage"] for r in today.get("readings", [])] or None
    ok, _ = run_devo_check(src, readings, allow_short)
    if not ok:
        print("WARNING: work/devo.md failed devo-check; staging the podcast WITHOUT the devo. "
              "Fix the errors above and run stage again to include it.", file=sys.stderr)
        return False
    shutil.copy(src, folder / "devo.md")
    return True


def cmd_devo_check(args):
    readings = None
    today_file = Path(args.today)
    if args.readings:
        readings = [r.strip() for r in args.readings.split(";") if r.strip()]
    elif today_file.exists():
        readings = [r["passage"] for r in json.loads(today_file.read_text()).get("readings", [])]
    else:
        print(f"note: {today_file} not found; skipping the check against today's readings", file=sys.stderr)
    ok, _ = run_devo_check(args.file, readings, args.allow_short)
    sys.exit(0 if ok else 1)


def cmd_devo_build(args):
    text = Path(args.file).read_text()
    date, plan_day = args.date, args.plan_day
    today_file = WORK / "today.json"
    if (not date or not plan_day) and today_file.exists():
        today = json.loads(today_file.read_text())
        date = date or today.get("date")
        plan_day = plan_day or today.get("plan_day")
    date = date or now().date().isoformat()
    try:
        info = devo.build_epub(text, args.out, date=date, plan_day=plan_day,
                               fetcher=devo.EsvFetcher(fixture=args.fixture))
    except devo.DevoError as e:
        sys.exit(f"devo-build failed: {e}")
    filename = devo.devo_filename(plan_day, date)
    print(json.dumps(dict(info, out=str(args.out), filename=filename), indent=1))
    if args.deliver:
        try:
            devo.deliver_devo(args.out, filename)  # prune relative to the real today, not the devo date
        except devo.DevoError as e:
            sys.exit(f"devo delivery failed: {e}")


def cmd_devo_setup(args):
    import devo_setup

    try:
        rc = devo_setup.run(kobo=args.kobo, kobo_only=args.kobo_only)
    except (devo.DevoError, KeyboardInterrupt, EOFError) as e:
        sys.exit(str(e) or "cancelled")
    sys.exit(rc)


def process_devo(folder, plan):
    """Build the EPUB for a staged devo and deliver it to Dropbox.
    Returns (devo_info for the state entry or None, problem string or None). Never raises."""
    src = folder / "devo.md"
    text = src.read_text()
    date, plan_day = folder.name, plan.get("plan_day")
    info = {}  # only the title and delivery flag go in the public state; the devo source is never published
    try:
        doc = devo.parse_devo(text)
        info["devo_title"] = doc["title"]
    except devo.DevoError as e:
        return None, f"devo.md is unreadable: {e}"
    try:
        errors, warnings, _ = devo.check_devo(text, plan.get("readings") or None, allow_short=True)
        for w in warnings:
            print(f"devo warning: {w}", file=sys.stderr)
        if errors:
            raise devo.DevoError("devo.md failed validation: " + "; ".join(errors))
        missing = devo.missing_secrets()
        if missing:
            print(f"::warning title=Devo skipped::Devo not built because these secrets are unset: {', '.join(missing)}",
                  flush=True)
            info["devo_delivered"] = False
            return info, None
        epub = WORK / devo.devo_filename(plan_day, date)
        WORK.mkdir(exist_ok=True)
        built = devo.build_epub(text, epub, date=date, plan_day=plan_day, fetcher=devo.EsvFetcher())
        print(f"devo built: {built['title']} ({built['bytes']//1024} KB, {built['passages_fetched']} passages)")
        devo.deliver_devo(epub, epub.name, CONFIG)
        epub.unlink(missing_ok=True)  # never leave ESV text lying around
        info["devo_delivered"] = True
        return info, None
    except BaseException as e:  # a devo problem must never stop the podcast
        if isinstance(e, KeyboardInterrupt):
            raise
        info["devo_delivered"] = False
        return info, f"{type(e).__name__}: {e}"


def cmd_stage(args):
    """Scheduled-task side: package today's episode and push it to a claude/episode-DATE branch.
    The GitHub Action on that branch does the audio, release, feed, and cleanup."""
    import shutil
    import subprocess

    today = json.loads((WORK / "today.json").read_text())
    raw = (WORK / "script.txt").read_text()
    meta = json.loads((WORK / "meta.json").read_text())
    words = validate(raw, meta, args.allow_short)
    date = args.date or today["date"]
    folder = ROOT / "incoming" / date
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy(WORK / "script.txt", folder / "script.txt")
    shutil.copy(WORK / "meta.json", folder / "meta.json")
    if (WORK / "research.md").exists():
        shutil.copy(WORK / "research.md", folder / "research.md")
    (folder / "plan.json").write_text(json.dumps({"plan_day": today["plan_day"],
                                                  "jump_applied": today.get("jump_applied"),
                                                  "readings": [r["passage"] for r in today.get("readings", [])]},
                                                 indent=1))
    devo_staged = stage_devo(today, folder, args.allow_short)
    branch = f"claude/episode-{date}"

    def git(*a):
        print("+ git " + " ".join(a), file=sys.stderr)
        subprocess.run(["git", *a], cwd=ROOT, check=True)

    git("checkout", "-B", branch)
    git("add", "-f", f"incoming/{date}")
    git("-c", "user.name=Old Paths", "-c", "user.email=old-paths@users.noreply.github.com",
        "commit", "-m", f"Stage episode for {date}: {meta['title']}")
    git("push", "-f", "-u", "origin", branch)
    print(json.dumps({"status": "staged", "date": date, "branch": branch, "words": words,
                      "devo": "staged" if devo_staged else "NOT staged (see warnings above)",
                      "feed": pages_url("feed.xml"),
                      "note": "The 'Publish episode' GitHub Action now makes the audio and updates the feed (about 5-10 minutes)."},
                     indent=1))


DEVO_STAGE_DIR = "incoming-devo"


def git_out(*a, env_extra=None, input=None):
    import subprocess

    e = dict(os.environ, **(env_extra or {}))
    r = subprocess.run(["git", *a], cwd=ROOT, check=True, capture_output=True, text=True, env=e, input=input)
    return r.stdout.strip()


def cmd_devo_stage(args):
    """Push devos (backfills, reruns) to a claude/devo-TIMESTAMP branch. The branch differs from main only by
    incoming-devo/<date>/{devo.md,plan.json}. The publish-devo Action builds and delivers them, then removes the branch."""
    import subprocess
    import tempfile

    root = Path(args.root)
    days = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    deletes = [n.strip() for n in (args.delete or []) if n.strip()]
    if not days and not deletes:
        sys.exit(f"devo-stage: no date folders found in {root}")
    wmin, wmax = devo_limits()
    files, failed = {}, False
    if deletes:
        files[f"{DEVO_STAGE_DIR}/_delete.txt"] = ("\n".join(deletes) + "\n").encode()
    for d in days:
        try:
            dt.date.fromisoformat(d.name)
        except ValueError:
            sys.exit(f"devo-stage: folder '{d.name}' is not named YYYY-MM-DD")
        if not (d / "devo.md").exists() or not (d / "plan.json").exists():
            sys.exit(f"devo-stage: {d.name} needs both devo.md and plan.json")
        plan = json.loads((d / "plan.json").read_text())
        if plan.get("date") and plan["date"] != d.name:
            sys.exit(f"devo-stage: {d.name}/plan.json says date {plan['date']}")
        print(f"checking {d.name}", file=sys.stderr)
        ok, _ = run_devo_check(d / "devo.md", plan.get("readings") or None, args.allow_short)
        failed = failed or not ok
        files[f"{DEVO_STAGE_DIR}/{d.name}/devo.md"] = (d / "devo.md").read_bytes()
        files[f"{DEVO_STAGE_DIR}/{d.name}/plan.json"] = (d / "plan.json").read_bytes()
    if failed:
        sys.exit("devo-stage: refusing to stage; fix the devo-check errors above.")
    branch = "claude/devo-" + now().strftime("%Y%m%d%H%M%S")
    # Build the commit with a temporary index so the working tree and current branch are untouched.
    try:
        parent = git_out("rev-parse", "--verify", "-q", "origin/main")
    except subprocess.CalledProcessError:
        parent = git_out("rev-parse", "--verify", "main")
    with tempfile.TemporaryDirectory() as tmp:
        idx = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git_out("read-tree", parent, env_extra=idx)
        for path, body in files.items():
            blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=ROOT, check=True,
                                  capture_output=True, input=body).stdout.decode().strip()
            git_out("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env_extra=idx)
        tree = git_out("write-tree", env_extra=idx)
    commit = git_out("-c", "user.name=Old Paths", "-c", "user.email=old-paths@users.noreply.github.com",
                     "commit-tree", tree, "-p", parent, "-m",
                     f"Stage devo(s): {', '.join(d.name for d in days) or 'deletes only'}")
    if args.dry_run:
        print(json.dumps({"status": "dry-run", "branch": branch, "commit": commit, "base": parent,
                          "files": sorted(files)}, indent=1))
        return
    git_out("update-ref", f"refs/heads/{branch}", commit)
    print("+ git push -f -u origin " + branch, file=sys.stderr)
    subprocess.run(["git", "push", "-f", "-u", "origin", branch], cwd=ROOT, check=True)
    print(branch)


def publish_devos(folder=None, fetcher_factory=None, deliver=None, gh=None):
    """Build and deliver every staged incoming-devo/<date>/. Returns a list of problems. Never raises per devo."""
    folder = Path(folder) if folder else ROOT / DEVO_STAGE_DIR
    fetcher_factory = fetcher_factory or devo.EsvFetcher
    deliver = deliver or devo.deliver_devo
    days = sorted(p for p in folder.glob("*") if p.is_dir()) if folder.exists() else []
    if not days:
        print(f"Nothing staged in {folder.name}/.")
    wmin, wmax = devo_limits()
    problems = []
    del_file = folder / "_delete.txt"
    if del_file.exists():
        names = [n.strip() for n in del_file.read_text().splitlines() if n.strip()]
        try:
            for n in devo.delete_devos(names, CONFIG):
                print(f"deleted from Dropbox: {n}")
        except Exception as e:
            problems.append(f"delete: {type(e).__name__}: {e}")
            print(f"DEVO DELETE FAILED: {e}", file=sys.stderr)
    for d in days:
        try:
            text = (d / "devo.md").read_text()
            plan = json.loads((d / "plan.json").read_text()) if (d / "plan.json").exists() else {}
            date, plan_day = d.name, plan.get("plan_day")
            errors, warnings, _ = devo.check_devo(text, plan.get("readings") or None, wmin, wmax, allow_short=True)
            for w in warnings:
                print(f"devo warning ({date}): {w}", file=sys.stderr)
            if errors:
                raise devo.DevoError("devo.md failed validation: " + "; ".join(errors))
            gone = devo.missing_secrets()
            if gone:
                raise devo.DevoError("missing secrets: " + ", ".join(gone))
            epub = WORK / devo.devo_filename(plan_day, date)
            WORK.mkdir(exist_ok=True)
            built = devo.build_epub(text, epub, date=date, plan_day=plan_day, fetcher=fetcher_factory())
            print(f"devo built: {built['title']} ({built['bytes']//1024} KB, {built['passages_fetched']} passages)")
            try:
                deliver(epub, epub.name, CONFIG)  # prunes relative to the real today
            finally:
                epub.unlink(missing_ok=True)  # never leave ESV text lying around
            print(f"devo delivered: {date}")
        except BaseException as e:
            if isinstance(e, KeyboardInterrupt):
                raise
            problems.append(f"{d.name}: {type(e).__name__}: {e}")
            print(f"DEVO FAILED for {d.name}: {e}", file=sys.stderr)
    branch = os.environ.get("SOURCE_BRANCH", "")
    if branch.startswith("claude/devo-"):
        (gh or client()).delete_branch(branch)
        print(f"deleted staging branch {branch}")
    return problems


def cmd_publish_devos(args):
    """GitHub Action side: build and deliver staged devos, then delete the staging branch."""
    problems = publish_devos()
    if problems:
        for prob in problems:
            print(f"::error title=Devo failed::{prob.replace(chr(10), ' ')[:500]}", flush=True)
        sys.exit("Some devos failed:\n  " + "\n  ".join(problems))


def cmd_publish_incoming(args):
    """GitHub Action side: publish every staged episode in incoming/, then delete the staging branch."""
    c = client()
    devo_problems = []
    folders = sorted(p for p in (ROOT / "incoming").glob("*") if p.is_dir()) if (ROOT / "incoming").exists() else []
    if not folders:
        print("Nothing staged in incoming/.")
    for folder in folders:
        raw = (folder / "script.txt").read_text()
        meta = json.loads((folder / "meta.json").read_text())
        plan = json.loads((folder / "plan.json").read_text()) if (folder / "plan.json").exists() else {}
        research = (folder / "research.md").read_text() if (folder / "research.md").exists() else ""
        validate(raw, meta, allow_short=True)
        devo_info = None
        if (folder / "devo.md").exists():
            # Before the slow audio step, and fenced off so it can never block the podcast.
            devo_info, problem = process_devo(folder, plan)
            if problem:
                devo_problems.append(f"{folder.name}: {problem}")
                print(f"DEVO FAILED for {folder.name}: {problem}", file=sys.stderr)
        else:
            print(f"::warning title=No devo::No devo.md was staged for {folder.name}", flush=True)
        publish_episode(c, date=folder.name, raw=raw, meta=meta, research=research,
                        plan_day_id=plan.get("plan_day"), jump_applied=plan.get("jump_applied"),
                        devo_info=devo_info)
    branch = os.environ.get("SOURCE_BRANCH", "")
    if branch.startswith("claude/episode-"):
        c.delete_branch(branch)
        print(f"deleted staging branch {branch}")
    if devo_problems:
        for prob in devo_problems:
            msg = prob.replace("\n", " ").replace("\r", " ")[:500]
            print(f"::error title=Devo failed (podcast published)::{msg}", flush=True)
        sys.exit("The podcast was published, but the devo failed:\n  " + "\n  ".join(devo_problems))


# ---------------------------------------------------------------- feed

def fmt_duration(seconds):
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def cdata(text):
    return "<![CDATA[" + text.replace("]]>", "]] >") + "]]>"


def build_feed(state):
    cfg = CONFIG
    items = []
    for ep in reversed(state["episodes"]):
        if ep.get("audio_deleted"):
            continue
        items.append(f"""    <item>
      <title>{escape(ep['title'])}</title>
      <description>{cdata(ep['description'])}</description>
      <itunes:summary>{cdata(ep['description'])}</itunes:summary>
      <enclosure url="{escape(ep['mp3_url'])}" length="{ep['bytes']}" type="audio/mpeg"/>
      <guid isPermaLink="false">{ep['guid']}</guid>
      <pubDate>{ep['published']}</pubDate>
      <itunes:duration>{fmt_duration(ep['duration'])}</itunes:duration>
      <itunes:episode>{ep['number']}</itunes:episode>
      <itunes:explicit>false</itunes:explicit>
    </item>""")
    owner = (f"<itunes:owner><itunes:name>{escape(cfg['author'])}</itunes:name>"
             f"<itunes:email>{escape(cfg['owner_email'])}</itunes:email></itunes:owner>") if cfg.get("owner_email") else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:googleplay="http://www.google.com/schemas/play-podcasts/1.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{escape(cfg['show_title'])}</title>
    <link>{escape(pages_url())}</link>
    <atom:link href="{escape(pages_url('feed.xml'))}" rel="self" type="application/rss+xml"/>
    <description>{escape(cfg['show_description'])}</description>
    <language>{cfg['language']}</language>
    <itunes:subtitle>{escape(cfg['show_subtitle'])}</itunes:subtitle>
    <itunes:author>{escape(cfg['author'])}</itunes:author>
    {owner}
    <itunes:image href="{escape(pages_url('cover.png'))}"/>
    <itunes:category text="Religion &amp; Spirituality"><itunes:category text="Christianity"/></itunes:category>
    <itunes:explicit>false</itunes:explicit>
    <itunes:type>episodic</itunes:type>
    <googleplay:block>yes</googleplay:block>
    <lastBuildDate>{email.utils.format_datetime(now())}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>
"""


def cmd_feed(args):
    c = client()
    state = load_state(c)
    if state is None:
        sys.exit("No series state found.")
    c.commit({"feed.xml": build_feed(state)}, "Rebuild feed")
    print(pages_url("feed.xml"))


# ---------------------------------------------------------------- bootstrap

def cmd_bootstrap(args):
    c = client()
    c.ensure_branch()
    if load_state(c) and not args.force:
        sys.exit("Series state already exists. Pass --force to overwrite it.")
    if args.start not in IDS:
        sys.exit(f"--start must be a plan day like 10-14; got {args.start}")

    state = {"created": now().isoformat(), "next_plan_day": args.start, "last_jump_applied": read_jump(), "episodes": []}
    files = {"cover.png": (ROOT / "seed" / "cover.png").read_bytes(), ".nojekyll": ""}

    if args.seed_mp3 and Path(args.seed_mp3).exists():
        meta = json.loads(Path(args.seed_meta).read_text())
        date = meta.get("date") or now().date().isoformat()
        tag = f"ep-{date}"
        mp3 = Path(args.seed_mp3)
        release_id, mp3_url = c.upload_episode(tag, meta["title"], show_notes_text(meta), mp3)
        published = email.utils.format_datetime(dt.datetime.fromisoformat(date + "T06:00:00").replace(tzinfo=TZ))
        ep = add_episode(state, date=date, day_id=meta.get("plan_day", "seed"), meta=meta, tag=tag,
                         release_id=release_id, mp3_url=mp3_url, size=mp3.stat().st_size,
                         duration=mp3_duration(mp3), published=published)
        ep["seed"] = True
        if Path(args.seed_script).exists():
            files[ep["transcript_path"]] = Path(args.seed_script).read_text()
        files[ep["notes_path"]] = show_notes_text(meta)

    files[STATE_KEY] = json.dumps(state, indent=1)
    files["feed.xml"] = build_feed(state)
    c.commit(files, "Bootstrap Old Paths feed")
    site = c.enable_pages()
    c.request_pages_build()
    print(json.dumps({"status": "bootstrapped", "next_plan_day": state["next_plan_day"],
                      "episodes": len(state["episodes"]), "pages_site": site or pages_url(),
                      "feed": pages_url("feed.xml"),
                      "note": "GitHub Pages can take a few minutes to go live the first time."}, indent=1))


# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("next")
    n.add_argument("--force", action="store_true", help="run even if an episode already exists for today")
    n.add_argument("--date", help="treat this date (YYYY-MM-DD) as today")
    n.set_defaults(func=cmd_next)

    st = sub.add_parser("stage", help="push today's finished episode to a claude/episode-DATE branch")
    st.add_argument("--date")
    st.add_argument("--allow-short", action="store_true")
    st.set_defaults(func=cmd_stage)

    pi = sub.add_parser("publish-incoming", help="(GitHub Action) publish staged episodes")
    pi.set_defaults(func=cmd_publish_incoming)

    ds = sub.add_parser("devo-stage", help="push devo-only days (backfills, reruns) to a claude/devo-TIMESTAMP branch")
    ds.add_argument("root", help="folder of YYYY-MM-DD subfolders, each with devo.md and plan.json")
    ds.add_argument("--delete", action="append", metavar="FILENAME",
                    help="also delete this devo EPUB from Dropbox (repeatable)")
    ds.add_argument("--allow-short", action="store_true", help="skip the minimum word count")
    ds.add_argument("--dry-run", action="store_true", help="check and build the commit, but do not push")
    ds.set_defaults(func=cmd_devo_stage)

    pd = sub.add_parser("publish-devos", help="(GitHub Action) build and deliver staged incoming-devo/ days")
    pd.set_defaults(func=cmd_publish_devos)

    dc = sub.add_parser("devo-check", help="validate a devo.md (markers cover each reading, word count)")
    dc.add_argument("file", nargs="?", default="work/devo.md")
    dc.add_argument("--today", default="work/today.json", help="today.json holding the day's readings")
    dc.add_argument("--readings", help="semicolon-separated readings, overrides --today")
    dc.add_argument("--allow-short", action="store_true", help="skip the minimum word count")
    dc.set_defaults(func=cmd_devo_check)

    db = sub.add_parser("devo-build", help="build the devo EPUB (fetches ESV text from the ESV API)")
    db.add_argument("file", nargs="?", default="work/devo.md")
    db.add_argument("--out", required=True, help="output .epub path")
    db.add_argument("--fixture", help="folder of canned passage html; no network (for tests)")
    db.add_argument("--date", help="YYYY-MM-DD for the title (default: work/today.json, else today)")
    db.add_argument("--plan-day", help="plan day like 10-14 for the title (default: work/today.json)")
    db.add_argument("--deliver", action="store_true", help="also upload the EPUB to Dropbox (needs the Dropbox secrets)")
    db.set_defaults(func=cmd_devo_build)

    da = sub.add_parser("devo-setup", aliases=["dropbox-auth"],
                        help="one-time interactive setup of GitHub secrets and the Kobo (secrets never printed)")
    da.add_argument("--kobo", help="Kobo mount path (default /Volumes/KOBOeReader)")
    da.add_argument("--kobo-only", action="store_true",
                    help="skip ESV/GitHub; re-authorize Dropbox and write only the Kobo config")
    da.set_defaults(func=cmd_devo_setup)

    t = sub.add_parser("transcript")
    t.add_argument("which", nargs="?", default="last", help="'last' or a date like 2026-10-19")
    t.set_defaults(func=cmd_transcript)

    pub = sub.add_parser("publish")
    pub.add_argument("--script", default="work/script.txt")
    pub.add_argument("--meta", default="work/meta.json")
    pub.add_argument("--research", default="work/research.md")
    pub.add_argument("--date")
    pub.add_argument("--allow-short", action="store_true")
    pub.add_argument("--force", action="store_true")
    pub.set_defaults(func=cmd_publish)

    f = sub.add_parser("feed")
    f.set_defaults(func=cmd_feed)

    b = sub.add_parser("bootstrap")
    b.add_argument("--start", default="10-14", help="first plan day the daily task should produce")
    b.add_argument("--seed-mp3", default=str(ROOT / "seed" / "episode-000.mp3"))
    b.add_argument("--seed-script", default=str(ROOT / "seed" / "episode-000.txt"))
    b.add_argument("--seed-meta", default=str(ROOT / "seed" / "episode-000.json"))
    b.add_argument("--force", action="store_true")
    b.set_defaults(func=cmd_bootstrap)

    args = p.parse_args()
    os.chdir(ROOT)
    args.func(args)


if __name__ == "__main__":
    main()
