"""Old Paths written devotional: source format, validation, EPUB build, Dropbox delivery.

The devo source (work/devo.md) holds commentary and passage markers only. ESV text is fetched
from the ESV API at build time and goes into the EPUB, which is delivered privately to Dropbox.
ESV text is never written anywhere in the repo or on gh-pages.

Imported by podcast.py. Standard library only, plus `requests` (already a dependency) for the
network calls.
"""
import datetime as dt
import html as htmllib
import json
import os
import re
import sys
import time
import uuid
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
SYSTEM_CA = "/etc/ssl/certs/ca-certificates.crt"
FIXTURE_DIR = ROOT / "scripts" / "fixtures"
DEVO_NAMESPACE = uuid.UUID("6f1d3c52-8a4e-4c43-9a3e-01da4ba50001")

ESV_URL = "https://api.esv.org/v3/passage/html/"
ESV_PARAMS = {
    "include-footnotes": "false",
    "include-footnote-body": "false",
    "include-audio-link": "false",
    "include-headings": "true",
    "include-first-verse-numbers": "true",
    "include-verse-numbers": "true",
    "include-passage-references": "false",
    "include-short-copyright": "false",
    "include-copyright": "false",
}
ESV_COPYRIGHT = ("Scripture quotations are from the ESV\u00ae Bible (The Holy Bible, English Standard Version\u00ae), "
                 "copyright \u00a9 2001 by Crossway, a publishing ministry of Good News Publishers. "
                 "Used by permission. All rights reserved.")

DROPBOX_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
DROPBOX_UPLOAD_URL = "https://content.dropboxapi.com/2/files/upload"
DROPBOX_LIST_URL = "https://api.dropboxapi.com/2/files/list_folder"
DROPBOX_LIST_MORE_URL = "https://api.dropboxapi.com/2/files/list_folder/continue"
DROPBOX_DELETE_URL = "https://api.dropboxapi.com/2/files/delete_v2"
DROPBOX_AUTH_URL = "https://www.dropbox.com/oauth2/authorize"

DEVO_SECRETS = ("ESV_API_KEY", "DROPBOX_APP_KEY", "DROPBOX_APP_SECRET", "DROPBOX_REFRESH_TOKEN")


class DevoError(Exception):
    pass


def log(msg):
    print(msg, file=sys.stderr)


# ------------------------------------------------------------------ references

_COUNTS = None
_ALIASES = {"psalm": "Psalms", "song of solomon": "Song of Songs", "songs of songs": "Song of Songs",
            "song of songs": "Song of Songs"}


def verse_counts():
    global _COUNTS
    if _COUNTS is None:
        _COUNTS = json.loads((ROOT / "plan" / "verse_counts.json").read_text())
    return _COUNTS


def canonical_book(name):
    counts = verse_counts()
    key = re.sub(r"\s+", " ", name.strip()).lower()
    if key in _ALIASES:
        return _ALIASES[key]
    for book in counts:
        if book.lower() == key:
            return book
    raise DevoError(f"unknown book '{name}'")


def _next_verse(book, ch, v):
    counts = verse_counts()[book]
    if v < counts[ch - 1]:
        return (ch, v + 1)
    if ch < len(counts):
        return (ch + 1, 1)
    return None


def parse_ref(ref):
    """'Jeremiah 35:1-36:10' -> ('Jeremiah', (35, 1), (36, 10)). Whole chapters expand to full verse ranges."""
    m = re.match(r"^\s*((?:[123]\s+)?[A-Za-z][A-Za-z ]*?)\s+(\d[\d:\-\u2013, ]*)\s*$", ref)
    if not m:
        raise DevoError(f"cannot read reference '{ref}'")
    book = canonical_book(m.group(1))
    counts = verse_counts()[book]
    spec = m.group(2).replace("\u2013", "-").replace(" ", "")
    if "," in spec:
        raise DevoError(f"'{ref}': comma lists are not supported; use one contiguous range per marker")
    # One-chapter books (Obadiah, Philemon, 2 John, 3 John, Jude): "3 John 1-14" means verses.
    if len(counts) == 1 and ":" not in spec:
        spec = "1:" + spec if "-" in spec or int(spec) > 1 else spec
    parts = spec.split("-")
    if len(parts) > 2:
        raise DevoError(f"cannot read reference '{ref}'")

    def chapter_ok(c):
        if not 1 <= c <= len(counts):
            raise DevoError(f"'{ref}': {book} has {len(counts)} chapters, no chapter {c}")
        return c

    def verse_ok(c, v):
        if not 1 <= v <= counts[c - 1]:
            raise DevoError(f"'{ref}': {book} {c} has {counts[c - 1]} verses, no verse {v}")
        return v

    first = parts[0]
    if ":" in first:
        c1, v1 = (int(x) for x in first.split(":"))
        chapter_ok(c1)
        verse_ok(c1, v1)
        if len(parts) == 1:
            return book, (c1, v1), (c1, v1)
        second = parts[1]
        if ":" in second:
            c2, v2 = (int(x) for x in second.split(":"))
            chapter_ok(c2)
            verse_ok(c2, v2)
        else:
            c2, v2 = c1, verse_ok(c1, int(second))
        end = (c2, v2)
    else:
        c1 = chapter_ok(int(first))
        if len(parts) == 1:
            c2 = c1
        else:
            if ":" in parts[1]:
                raise DevoError(f"cannot read reference '{ref}'")
            c2 = chapter_ok(int(parts[1]))
        return book, (c1, 1), (c2, counts[c2 - 1])
    if end < (c1, v1):
        raise DevoError(f"'{ref}': range runs backwards")
    return book, (c1, v1), end


def verse_total(book, start, end):
    counts = verse_counts()[book]
    total = 0
    c, v = start
    while (c, v) <= end:
        stop = end[1] if c == end[0] else counts[c - 1]
        total += stop - v + 1
        c, v = c + 1, 1
    return total


def fmt_pos(p):
    return f"{p[0]}:{p[1]}"


# ------------------------------------------------------------------ source parsing

MARKER_RE = re.compile(r"^\{\{\s*passage\s*:\s*(.+?)\s*\}\}\s*$", re.I)


def parse_devo(text):
    """Return {'title', 'intro': [lines], 'sections': [{'ref','line','items': [('text', [lines]) | ('passage', ref, lineno)]}]}."""
    title = None
    intro = []
    sections = []
    cur = None
    buf = []

    def flush():
        nonlocal buf
        if buf and any(l.strip() for l in buf):
            if cur is None:
                intro.extend(buf)
            else:
                cur["items"].append(("text", buf))
        buf = []

    for no, line in enumerate(text.splitlines(), 1):
        if title is None:
            if not line.strip():
                continue
            if not line.startswith("# "):
                raise DevoError(f"line {no}: the first line must be '# <title>'")
            title = line[2:].strip()
            continue
        if line.startswith("## "):
            flush()
            cur = {"ref": line[3:].strip(), "line": no, "items": []}
            sections.append(cur)
            continue
        if "{{" in line or "}}" in line:
            m = MARKER_RE.match(line.strip())
            if not m or line != line.strip():
                raise DevoError(f"line {no}: malformed passage marker (must be alone on its line as "
                                f"'{{{{passage: Book 1:1-10}}}}'): {line.strip()[:80]}")
            if cur is None:
                raise DevoError(f"line {no}: passage marker before the first '## reading' heading")
            flush()
            cur["items"].append(("passage", m.group(1), no))
            continue
        buf.append(line)
    flush()
    if title is None:
        raise DevoError("empty file; expected '# <title>' first")
    return {"title": title, "intro": intro, "sections": sections}


_WORD_RE = re.compile(r"\w[\w'\u2019\-]*")


def commentary_words(doc):
    chunks = list(doc["intro"])
    for sec in doc["sections"]:
        for item in sec["items"]:
            if item[0] == "text":
                chunks.extend(item[1])
    return len(_WORD_RE.findall("\n".join(chunks)))


def check_devo(text, readings=None, wmin=None, wmax=None, allow_short=False):
    """Return (errors, warnings, stats). readings: list of passage strings for the day."""
    errors, warnings = [], []
    try:
        doc = parse_devo(text)
    except DevoError as e:
        return [str(e)], [], {}
    if not doc["sections"]:
        errors.append("no '## <passage>' headings found")

    parsed_headings = []
    for sec in doc["sections"]:
        ref = sec["ref"]
        try:
            book, start, end = parse_ref(ref)
        except DevoError as e:
            errors.append(f"line {sec['line']}: heading: {e}")
            continue
        parsed_headings.append((ref, book, start, end))
        markers = [i for i in sec["items"] if i[0] == "passage"]
        if not markers:
            errors.append(f"'{ref}': no passage markers")
            continue
        expect = start
        prev_end = None
        for _, mref, mline in markers:
            try:
                mbook, mstart, mend = parse_ref(mref)
            except DevoError as e:
                errors.append(f"line {mline}: {e}")
                break
            if mbook != book:
                errors.append(f"line {mline}: marker '{mref}' is in {mbook}, but the heading is {book}")
                break
            if mstart != expect:
                kind = "gap" if mstart > expect else "overlap or out of order"
                errors.append(f"line {mline}: {kind} in '{ref}': expected next marker to start at "
                              f"{book} {fmt_pos(expect)}, but '{mref}' starts at {fmt_pos(mstart)}")
                break
            n = verse_total(book, mstart, mend)
            if n > 40:
                warnings.append(f"line {mline}: '{mref}' is {n} verses; split it into smaller chunks")
            prev_end = mend
            expect = _next_verse(book, *mend)
            if expect is None:
                expect = (10 ** 6, 1)  # end of the book; any further marker is an error above
        else:
            if prev_end != end:
                errors.append(f"'{ref}': markers stop at {book} {fmt_pos(prev_end)}, but the reading ends at "
                              f"{book} {fmt_pos(end)}")
        # shape: commentary, then its passage, repeated; nothing after the last passage
        kinds = [i[0] for i in sec["items"]]
        for idx, item in enumerate(sec["items"]):
            if item[0] == "passage" and (idx == 0 or kinds[idx - 1] != "text"):
                where = "the heading" if idx == 0 else f"the passage '{sec['items'][idx - 1][1]}'"
                errors.append(f"line {item[2]}: no commentary above passage '{item[1]}' in '{ref}' "
                              f"(it needs commentary between {where} and this marker)")
        if kinds and kinds[-1] == "text":
            errors.append(f"'{ref}': no commentary after a passage. Remove the text after the last marker "
                          f"or move it above the next marker.")

    if readings is not None:
        want = []
        for r in readings:
            try:
                want.append((r, parse_ref(r)))
            except DevoError as e:
                errors.append(f"today.json reading: {e}")
        have = [(ref, (book, s, e)) for ref, book, s, e in parsed_headings]
        for r, rng in want:
            if rng not in [h[1] for h in have]:
                errors.append(f"reading '{r}' from today.json has no '## ' section")
        for ref, rng in have:
            if rng not in [w[1] for w in want]:
                errors.append(f"section '## {ref}' is not one of today's readings")
        if len(have) != len(set(h[1] for h in have)):
            errors.append("a reading appears more than once")

    words = commentary_words(doc)
    wmin = int(wmin) if wmin else 0
    wmax = int(wmax) if wmax else 10 ** 9
    if words < wmin and not allow_short:
        errors.append(f"commentary is {words} words; the minimum is {wmin} (markers and headings excluded). "
                      f"Expand it, or pass --allow-short.")
    if words > wmax:
        errors.append(f"commentary is {words} words; the maximum is {wmax}. Cut whole points.")
    stats = {"title": doc["title"], "words": words, "readings": len(doc["sections"]),
             "chunks": sum(1 for s in doc["sections"] for i in s["items"] if i[0] == "passage")}
    return errors, warnings, stats


# ------------------------------------------------------------------ markdown -> XHTML

def _inline(text):
    t = escape(text)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)  # links: keep the text only
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
    t = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"<i>\1</i>", t)
    return t


def md_to_html(lines):
    """Tiny converter: paragraphs, *italic*, **bold**, > blockquotes, ### subheads, - bullets, scene breaks."""
    out = []
    para, quote, bullets = [], [], []

    def end_para():
        nonlocal para
        if para:
            out.append("<p>" + _inline(" ".join(s.strip() for s in para)) + "</p>")
        para = []

    def end_quote():
        nonlocal quote
        if quote:
            paras, cur = [], []
            for q in quote:
                if q.strip():
                    cur.append(q.strip())
                elif cur:
                    paras.append(cur)
                    cur = []
            if cur:
                paras.append(cur)
            out.append("<blockquote>" + "".join("<p>" + _inline(" ".join(p)) + "</p>" for p in paras) + "</blockquote>")
        quote = []

    def end_bullets():
        nonlocal bullets
        if bullets:
            out.append("<ul>" + "".join("<li>" + _inline(b) + "</li>" for b in bullets) + "</ul>")
        bullets = []

    for line in lines:
        s = line.strip()
        if s.startswith(">"):
            end_para()
            end_bullets()
            quote.append(s[1:].strip())
            continue
        end_quote()
        if not s:
            end_para()
            end_bullets()
        elif s.startswith("### "):
            end_para()
            end_bullets()
            out.append("<h3>" + _inline(s[4:]) + "</h3>")
        elif re.match(r"^(\*\s*){3,}$|^-{3,}$", s):
            end_para()
            end_bullets()
            out.append('<p class="brk">*&#160;&#160;*&#160;&#160;*</p>')
        elif re.match(r"^[-*] ", s):
            end_para()
            bullets.append(s[2:].strip())
        else:
            end_bullets()
            para.append(s)
    end_para()
    end_quote()
    end_bullets()
    return "\n".join(out)


# ------------------------------------------------------------------ ESV html cleaning

class _EsvCleaner(HTMLParser):
    """Turn ESV API html into simple XHTML blocks: <h3 class="ph">, <p>, <p class="po"> (poetry), <p class="bi">."""

    BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "ul", "ol", "li", "table", "tr", "section"}
    SKIP = {"script", "style", "head", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []          # finished xhtml strings
        self.frags = []           # current block fragments
        self.kind = "p"           # 'p' | 'h'
        self.cls = ""
        self.poetry_depth = 0
        self.stack = []           # (tag, info)
        self.inline_open = []     # xhtml tags currently open inside the block, e.g. 'i', 'span class="sc"'
        self.skip_depth = 0
        self.vn_buf = None

    # -- helpers
    def _classes(self, attrs):
        return (dict(attrs).get("class") or "").split()

    def _flush(self):
        if self.frags:
            inner = "".join(self.frags)
            visible = re.sub(r"<[^>]+>", "", inner).replace("\u00a0", "").strip()
            if visible:
                inner = re.sub(r"(<br\s*/>\s*)+$", "", inner.strip())
                inner = re.sub(r"^(<br\s*/>\s*)+", "", inner)
                if self.kind == "h":
                    self.blocks.append(f'<h3 class="ph">{inner}</h3>')
                else:
                    cls = f' class="{self.cls}"' if self.cls else ""
                    self.blocks.append(f"<p{cls}>{inner}</p>")
        self.frags = []

    def _close_inline(self):
        return "".join(f"</{t.split()[0]}>" for t in reversed(self.inline_open))

    def _reopen_inline(self):
        return "".join(f"<{t}>" for t in self.inline_open)

    def _break(self):
        closing = self._close_inline()
        if self.frags:
            self.frags.append(closing)
        self._flush()
        self.frags = [self._reopen_inline()] if self.inline_open else []

    # -- parser callbacks
    def handle_starttag(self, tag, attrs):
        classes = self._classes(attrs)
        if self.skip_depth or tag in self.SKIP:
            if tag not in ("br", "img", "hr"):
                self.skip_depth += 1
            return
        if tag == "sup" and "footnote" in classes:
            self.skip_depth += 1
            return
        if tag == "a" and ("va" in classes or "audio" in " ".join(classes)):
            self.skip_depth += 1
            return
        if tag == "h2" and "extra_text" in classes:
            self.skip_depth += 1
            return
        if tag == "br":
            self.frags.append("<br/>")
            return
        if tag in self.BLOCK:
            self._break()
            poetry = any(c in ("poetry", "line-group", "line", "block-indent-poetry") or c.startswith("indent") for c in classes)
            if poetry:
                self.poetry_depth += 1
            self.stack.append((tag, poetry))
            if tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
                self.kind, self.cls = "h", ""
            else:
                self.kind = "p"
                if self.poetry_depth or any(c in ("line", "line-group", "poetry") for c in classes):
                    self.cls = "po"
                elif "block-indent" in classes:
                    self.cls = "bi"
                else:
                    self.cls = ""
            return
        if tag == "b" and ("verse-num" in classes or "chapter-num" in classes):
            self.vn_buf = []
            self.stack.append((tag, "vn"))
            return
        if tag == "span" and ("small-caps" in classes or "smallcaps" in classes):
            self._open_inline('span class="sc"')
            self.stack.append((tag, "inline"))
            return
        if tag in ("i", "em"):
            self._open_inline("i")
            self.stack.append((tag, "inline"))
            return
        if tag in ("b", "strong"):
            self._open_inline("b")
            self.stack.append((tag, "inline"))
            return
        self.stack.append((tag, None))  # transparent wrapper (span, a, ...)

    def _open_inline(self, xtag):
        self.inline_open.append(xtag)
        self.frags.append(f"<{xtag}>")

    def handle_endtag(self, tag):
        if self.skip_depth:
            if tag not in ("br", "img", "hr"):
                self.skip_depth -= 1
            return
        if tag == "br":
            return
        idx = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                idx = i
                break
        if idx is None:
            return
        _, info = self.stack[idx]
        del self.stack[idx:]
        if info == "vn":
            label = re.sub(r"[\s\u00a0]+", "", "".join(self.vn_buf or []))
            self.vn_buf = None
            if label:
                self.frags.append(f'<sup class="vn">{escape(label)}</sup>\u00a0')
        elif info == "inline":
            xtag = self.inline_open.pop()
            self.frags.append(f"</{xtag.split()[0]}>")
        elif tag in self.BLOCK:
            if info:
                self.poetry_depth = max(0, self.poetry_depth - 1)
            self._break()
            self.kind = "p"
            self.cls = "po" if self.poetry_depth else ""

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.vn_buf is not None:
            self.vn_buf.append(data)
            return
        data = re.sub(r"[ \t\r\n]+", " ", data)
        if not data.strip(" ") and not self.frags:
            return
        self.frags.append(escape(data))

    def result(self):
        self._break()
        return self.blocks


def clean_esv_html(raw):
    p = _EsvCleaner()
    p.feed(raw)
    p.close()
    blocks = p.result()
    if not blocks:
        raise DevoError("ESV passage came back empty")
    xhtml = "\n".join(blocks)
    try:
        ElementTree.fromstring(f"<div>{xhtml}</div>")
    except ElementTree.ParseError as e:
        raise DevoError(f"cleaned ESV html is not well-formed: {e}")
    return xhtml


# ------------------------------------------------------------------ ESV fetch

def _slug(ref):
    return re.sub(r"[^A-Za-z0-9]+", "_", ref).strip("_")


class EsvFetcher:
    def __init__(self, fixture=None, sleep=0.5):
        self.fixture = Path(fixture) if fixture else None
        self.cache = {}
        self.sleep = sleep
        self.session = None
        self.calls = 0

    def get(self, ref):
        if ref in self.cache:
            return self.cache[ref]
        raw = self._fixture(ref) if self.fixture else self._api(ref)
        self.cache[ref] = raw
        return raw

    def _fixture(self, ref):
        for name in (f"{_slug(ref)}.html", "default.html"):
            f = self.fixture / name
            if f.exists():
                return f.read_text().replace("{ref}", escape(ref))
        raise DevoError(f"no fixture for '{ref}' in {self.fixture} (looked for {_slug(ref)}.html and default.html)")

    def _api(self, ref):
        import requests

        key = os.environ.get("ESV_API_KEY", "").strip()
        if not key:
            raise DevoError("ESV_API_KEY is not set")
        if self.session is None:
            self.session = requests.Session()
            self.session.headers["Authorization"] = f"Token {key}"
            self.session.headers["User-Agent"] = "old-paths-devo"
            if os.path.exists(SYSTEM_CA):
                self.session.verify = SYSTEM_CA
        params = dict(ESV_PARAMS, q=ref)
        last = None
        for attempt in range(1, 5):
            if self.calls:
                time.sleep(self.sleep)
            self.calls += 1
            try:
                r = self.session.get(ESV_URL, params=params, timeout=60)
            except requests.RequestException as e:
                last = f"network error {e!r}"
                time.sleep(2 * attempt)
                continue
            if r.status_code == 429:
                wait = min(int(re.sub(r"\D", "", r.headers.get("Retry-After", "") or "") or 5), 60)
                last = f"rate limited (waiting {wait}s)"
                log(f"ESV API {last} for '{ref}'")
                time.sleep(wait)
                continue
            if r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                time.sleep(2 * attempt)
                continue
            if r.status_code != 200:
                raise DevoError(f"ESV API returned HTTP {r.status_code} for '{ref}': {r.text[:200]}")
            passages = r.json().get("passages") or []
            if not passages or not passages[0].strip():
                raise DevoError(f"ESV API returned no text for '{ref}'")
            return passages[0]
        raise DevoError(f"ESV API failed for '{ref}': {last}")


# ------------------------------------------------------------------ EPUB

CSS = """\
body { margin: 0; padding: 0; font-family: serif; line-height: 1.4; }
h1 { font-size: 1.5em; margin: 0.8em 0 0.6em 0; text-align: left; page-break-after: avoid; }
h2 { font-size: 1.2em; margin: 1.2em 0 0.5em 0; }
h3 { font-size: 1.05em; font-weight: bold; margin: 1em 0 0.4em 0; }
p { margin: 0 0 0.8em 0; text-align: left; }
.sub { font-size: 0.9em; margin-bottom: 1.2em; }
blockquote { margin: 0.8em 1.5em; font-style: italic; }
blockquote p { margin: 0 0 0.6em 0; }
p.brk { text-align: center; margin: 1em 0; }
.passage { margin: 1.2em 0 1.2em 0.4em; padding: 0 0 0 0.9em; border-left: 3px solid #000000; page-break-inside: auto; }
.passage p { font-family: sans-serif; font-size: 0.92em; line-height: 1.45; margin: 0 0 0.6em 0; }
.passage p.bi { margin-left: 1.2em; }
.passage p.po { margin: 0 0 0.3em 1em; }
.passage h3.ph { font-family: sans-serif; font-size: 0.95em; font-style: italic; font-weight: normal; margin: 0.8em 0 0.3em 0; }
p.pref { font-family: sans-serif; font-size: 0.7em; font-weight: bold; letter-spacing: 0.1em; margin: 0 0 0.5em 0; }
sup.vn { font-size: 0.65em; font-weight: bold; vertical-align: super; line-height: 1; }
span.sc { font-variant: small-caps; }
.legal { font-size: 0.85em; }
"""

XHTML_HEAD = ('<?xml version="1.0" encoding="utf-8"?>\n'
              '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
              'lang="en" xml:lang="en">\n<head><meta charset="utf-8"/><title>{title}</title>'
              '<link rel="stylesheet" type="text/css" href="style.css"/></head>\n<body>\n')
XHTML_TAIL = "\n</body>\n</html>\n"


def devo_title(plan_day, date):
    d = dt.date.fromisoformat(date)
    parts = ["Old Paths Devo"]
    if plan_day:
        parts.append(f"Day {plan_day}")
    parts.append(f"{d:%a %b} {d.day}")
    return " \u00b7 ".join(parts)


def devo_filename(plan_day, date):
    return f"{date}-old-paths-devo{'-' + plan_day if plan_day else ''}.epub"


def _page(title, body):
    doc = XHTML_HEAD.format(title=escape(title)) + body + XHTML_TAIL
    try:
        ElementTree.fromstring(doc.encode("utf-8"))
    except ElementTree.ParseError as e:
        raise DevoError(f"generated page '{title}' is not well-formed XHTML: {e}")
    return doc


def build_epub(text, out_path, *, date, plan_day=None, fetcher=None):
    doc = parse_devo(text)
    fetcher = fetcher or EsvFetcher()
    book_title = devo_title(plan_day, date)

    pages = []  # (id, filename, nav label, xhtml)
    intro = md_to_html(doc["intro"])
    reading_list = "".join(f"<li>{escape(s['ref'])}</li>" for s in doc["sections"])
    title_body = (f"<h1>{escape(doc['title'])}</h1>\n<p class=\"sub\">{escape(book_title)}</p>\n{intro}\n"
                  f"<p class=\"sub\">Today's readings</p>\n<ul>{reading_list}</ul>")
    pages.append(("title", "title.xhtml", "Title", _page(doc["title"], title_body)))

    for n, sec in enumerate(doc["sections"], 1):
        parts = [f"<h1>{escape(sec['ref'])}</h1>"]
        for item in sec["items"]:
            if item[0] == "text":
                parts.append(md_to_html(item[1]))
            else:
                ref = item[1]
                log(f"fetching {ref}")
                passage = clean_esv_html(fetcher.get(ref))
                parts.append(f'<div class="passage">\n<p class="pref">ESV \u00b7 {escape(ref)}</p>\n{passage}\n</div>')
        pages.append((f"ch{n:02d}", f"ch{n:02d}.xhtml", sec["ref"], _page(sec["ref"], "\n".join(parts))))

    legal = (f"<h1>Copyright</h1>\n<p class=\"legal\">{escape(ESV_COPYRIGHT)}</p>\n"
             f"<p class=\"legal\">Commentary by Old Paths. This file is for personal use and is deleted from storage "
             f"after a short retention period.</p>")
    pages.append(("legal", "copyright.xhtml", "Copyright", _page("Copyright", legal)))

    uid = "urn:uuid:" + str(uuid.uuid5(DEVO_NAMESPACE, f"old-paths-devo-{date}"))
    modified = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = "\n".join(f'    <item id="{i}" href="{f}" media-type="application/xhtml+xml"/>' for i, f, _, _ in pages)
    spine = "\n".join(f'    <itemref idref="{i}"/>' for i, _, _, _ in pages)
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="en">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{uid}</dc:identifier>
    <dc:title>{escape(book_title)}</dc:title>
    <dc:creator>Old Paths</dc:creator>
    <dc:language>en</dc:language>
    <dc:date>{escape(date)}</dc:date>
    <meta property="dcterms:modified">{modified}</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="css" href="style.css" media-type="text/css"/>
{manifest}
  </manifest>
  <spine toc="ncx">
    <itemref idref="nav" linear="no"/>
{spine}
  </spine>
</package>
"""
    nav_items = "\n".join(f'      <li><a href="{f}">{escape(label)}</a></li>' for _, f, label, _ in pages)
    nav = (XHTML_HEAD.format(title="Contents") +
           f'<nav epub:type="toc" id="toc"><h1>Contents</h1>\n    <ol>\n{nav_items}\n    </ol></nav>' + XHTML_TAIL)
    ElementTree.fromstring(nav.encode("utf-8"))
    points = "\n".join(
        f'    <navPoint id="np{n}" playOrder="{n}"><navLabel><text>{escape(label)}</text></navLabel>'
        f'<content src="{f}"/></navPoint>' for n, (_, f, label, _) in enumerate(pages, 1))
    ncx = f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="{uid}"/></head>
  <docTitle><text>{escape(book_title)}</text></docTitle>
  <navMap>
{points}
  </navMap>
</ncx>
"""
    container = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/nav.xhtml", nav, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/toc.ncx", ncx, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/style.css", CSS, compress_type=zipfile.ZIP_DEFLATED)
        for _, f, _, xhtml in pages:
            z.writestr(f"OEBPS/{f}", xhtml, compress_type=zipfile.ZIP_DEFLATED)
    return {"title": book_title, "pages": len(pages), "bytes": out_path.stat().st_size,
            "passages_fetched": len(fetcher.cache)}


# ------------------------------------------------------------------ Dropbox

def missing_secrets():
    return [k for k in DEVO_SECRETS if not os.environ.get(k, "").strip()]


def _http():
    import requests

    s = requests.Session()
    if os.path.exists(SYSTEM_CA):
        s.verify = SYSTEM_CA
    return s


def _dropbox_error(r, what):
    return DevoError(f"Dropbox {what} failed: HTTP {r.status_code} {r.text[:300]}")


def dropbox_access_token(s=None, key=None, secret=None, refresh=None):
    s = s or _http()
    r = s.post(DROPBOX_TOKEN_URL, timeout=60, data={
        "grant_type": "refresh_token",
        "refresh_token": (refresh or os.environ["DROPBOX_REFRESH_TOKEN"]).strip(),
        "client_id": (key or os.environ["DROPBOX_APP_KEY"]).strip(),
        "client_secret": (secret or os.environ["DROPBOX_APP_SECRET"]).strip(),
    })
    if r.status_code != 200:
        raise _dropbox_error(r, "token refresh")
    return r.json()["access_token"]


def dropbox_folder(config):
    """Normalized Dropbox folder: "" is the app-folder root, else "/Folder"."""
    p = (config.get("dropbox_devo_path") or "").strip().strip("/")
    return "/" + p if p else ""


def deliver_devo(epub_path, filename, config=None, today=None):
    """Upload the EPUB to Dropbox (overwrite), then delete devo EPUBs older than devo_retention_days."""
    gone = missing_secrets()
    gone = [k for k in gone if k != "ESV_API_KEY"]
    if gone:
        raise DevoError("missing Dropbox settings: " + ", ".join(gone))
    config = config or json.loads((ROOT / "config.json").read_text())
    folder = dropbox_folder(config)
    s = _http()
    token = dropbox_access_token(s)
    path = f"{folder}/{filename}"
    with open(epub_path, "rb") as fh:
        r = s.post(DROPBOX_UPLOAD_URL, timeout=300, data=fh, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
            "Dropbox-API-Arg": json.dumps({"path": path, "mode": "overwrite", "autorename": False, "mute": True}),
        })
    if r.status_code != 200:
        raise _dropbox_error(r, f"upload to {path}")
    log(f"devo delivered to Dropbox: {path}")
    try:
        removed = prune_devos(s, token, folder, int(config.get("devo_retention_days", 14)), today)
        if removed:
            log(f"pruned {len(removed)} old devo file(s): {', '.join(removed)}")
    except Exception as e:  # pruning must never undo a good delivery
        log(f"warning: could not prune old devos ({e})")
    return path


DEVO_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[ -]old[ -]paths[ -]devo.*\.epub$", re.I)


def prune_devos(s, token, folder, retention_days, today=None):
    today = today or dt.date.today()
    cutoff = today - dt.timedelta(days=retention_days)
    headers = {"Authorization": f"Bearer {token}"}
    r = s.post(DROPBOX_LIST_URL, headers=headers, json={"path": folder}, timeout=60)
    if r.status_code == 409:
        return []
    if r.status_code != 200:
        raise _dropbox_error(r, "list folder")
    removed = []
    while True:
        data = r.json()
        for e in data.get("entries", []):
            if e.get(".tag") != "file":
                continue
            m = DEVO_NAME_RE.match(e["name"])
            if not m:
                continue
            try:
                d = dt.date.fromisoformat(m.group(1))
            except ValueError:
                continue
            if d < cutoff:
                dr = s.post(DROPBOX_DELETE_URL, headers=headers, json={"path": e["path_lower"]}, timeout=60)
                if dr.status_code == 200:
                    removed.append(e["name"])
                else:
                    log(f"warning: could not delete {e['name']}: HTTP {dr.status_code}")
        if not data.get("has_more"):
            break
        r = s.post(DROPBOX_LIST_MORE_URL, headers=headers, json={"cursor": data["cursor"]}, timeout=60)
        if r.status_code != 200:
            raise _dropbox_error(r, "list folder continue")
    return removed


def dropbox_authorize(key, secret, ask_code=input, show=print, open_url=None):
    """Interactive OAuth code flow. Returns a new refresh token. Never prints it."""
    from urllib.parse import urlencode

    url = DROPBOX_AUTH_URL + "?" + urlencode({"client_id": key, "response_type": "code",
                                             "token_access_type": "offline"})
    show("\nOpen this URL while signed in to Dropbox and click Allow (opening it in your browser now):\n\n   "
         + url + "\n")
    if open_url is None:
        import webbrowser
        open_url = webbrowser.open
    try:
        open_url(url)
    except Exception:
        pass
    code = ask_code("Paste the access code Dropbox shows you: ").strip()
    r = _http().post(DROPBOX_TOKEN_URL, timeout=60, data={
        "grant_type": "authorization_code", "code": code, "client_id": key, "client_secret": secret})
    if r.status_code != 200:
        raise DevoError(f"Dropbox code exchange failed: HTTP {r.status_code} {r.text[:300]}")
    refresh = r.json().get("refresh_token")
    if not refresh:
        raise DevoError("Dropbox did not return a refresh token. Make sure the URL used token_access_type=offline.")
    return refresh


def dropbox_check_root(key, secret, refresh, folder=""):
    """Sanity check: list the delivery folder with a fresh access token. Returns entry count."""
    s = _http()
    token = dropbox_access_token(s, key, secret, refresh)
    r = s.post(DROPBOX_LIST_URL, headers={"Authorization": f"Bearer {token}"}, json={"path": folder}, timeout=60)
    if r.status_code != 200:
        raise _dropbox_error(r, "list folder")
    return len(r.json().get("entries", []))
