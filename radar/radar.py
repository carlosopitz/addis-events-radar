#!/usr/bin/env python3
"""Addis Events Radar: monitor embassy and cultural-institute channels.

Usage:
  python radar/radar.py check      # fetch every channel, record new items, notify
  python radar/radar.py discover   # crawl homepages for social links, newsletters, feeds

Data lives in docs/data/ so the GitHub Pages dashboard can read it.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
SOURCES = ROOT / "sources.yaml"

UA = "Mozilla/5.0 (compatible; AddisEventsRadar/1.0; +https://github.com/carlosopitz/addis-events-radar)"
HEADERS = {"User-Agent": UA, "Accept-Language": "en,de;q=0.8,fr;q=0.6,es;q=0.6,it;q=0.5"}
TIMEOUT = 30
MAX_ITEMS = 3000          # items kept in items.json
MAX_SEEN = 600            # ids remembered per channel
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "https://carlosopitz.github.io/addis-events-radar/")
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NOTIFY_OTHER = os.environ.get("NOTIFY_OTHER", "digest")   # digest | each | off

# Words that suggest a post is about a public event (multilingual).
EVENT_WORDS = [
    # en
    "concert", "exhibition", "exhibit", "screening", "film", "cinema", "movie", "festival",
    "workshop", "lecture", "talk", "panel", "seminar", "symposium", "reading", "book launch",
    "performance", "theatre", "theater", "dance", "music", "jazz", "art ", "gallery", "open day",
    "open house", "celebration", "celebrate", "fair", "bazaar", "market", "competition", "quiz",
    "tasting", "gala", "cultural week", "culture week", "week of", "invitation", "you are invited",
    "join us", "register", "registration", "tickets", "free entrance", "free of charge", "free admission",
    "photo exhibition", "showcase", "masterclass", "recital", "opera", "choir", "poetry",
    # de
    "konzert", "ausstellung", "lesung", "vortrag", "veranstaltung", "filmvorführung", "einladung",
    "vernissage", "theaterstück",
    # fr
    "exposition", "projection", "spectacle", "conférence", "atelier", "rencontre", "soirée",
    "fête", "journée",
    # es / pt
    "concierto", "exposición", "muestra", "proyección", "taller", "conferencia", "presentación",
    "celebración", "feria", "gastronóm", "semana de", "evento", "exposição", "concerto",
    # it
    "mostra", "proiezione", "rassegna", "spettacolo", "laboratorio", "settimana", "incontro",
]
EVENT_RE = re.compile("|".join(re.escape(w) for w in EVENT_WORDS), re.I)

DEFAULT_EXCLUDE = re.compile(
    r"(mailto:|tel:|javascript:|/login|/signin|/search|/suche|/contact|/kontakt|impressum|imprint|"
    r"privacy|datenschutz|cookie|sitemap|accessibility|barrierefrei|/rss|/feed|/tag/|/tags/|"
    r"/category/|/author/|facebook\.com|twitter\.com|x\.com/|instagram\.com|youtube\.com|linkedin\.com|"
    r"t\.me/|whatsapp|\.(jpg|jpeg|png|gif|zip|mp3|mp4)$)",
    re.I,
)

SOCIAL_PATTERNS = {
    "x": re.compile(r"https?://(www\.)?(twitter|x)\.com/(?!intent|share|home|search|hashtag)([A-Za-z0-9_]{2,30})/?$", re.I),
    "facebook": re.compile(r"https?://(www\.|m\.|web\.)?facebook\.com/(?!sharer|share|dialog|plugins|tr\b)[^?#]+", re.I),
    "instagram": re.compile(r"https?://(www\.)?instagram\.com/(?!p/|reel/|explore)[A-Za-z0-9_.]{2,40}/?", re.I),
    "telegram": re.compile(r"https?://(t\.me|telegram\.me)/(?!share|joinchat)[A-Za-z0-9_]{4,40}/?$", re.I),
    "youtube": re.compile(r"https?://(www\.)?youtube\.com/(channel/|c/|user/|@)[^?#]+", re.I),
    "linkedin": re.compile(r"https?://([a-z]{2,3}\.)?linkedin\.com/(company|school|showcase)/[^?#]+", re.I),
    "tiktok": re.compile(r"https?://(www\.)?tiktok\.com/@[^?#/]+", re.I),
    "bluesky": re.compile(r"https?://bsky\.app/profile/[^?#/]+", re.I),
    "flickr": re.compile(r"https?://(www\.)?flickr\.com/(photos|people)/[^?#]+", re.I),
}
NEWSLETTER_RE = re.compile(r"newsletter|subscribe|abonn|suscrib|iscriviti|anmeld", re.I)

MONTHS = {
    # en
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
    # de
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "mai": 5, "juni": 6, "juli": 7,
    "oktober": 10, "dezember": 12,
    # fr
    "janvier": 1, "février": 2, "mars": 3, "avril": 4, "juin": 6, "juillet": 7, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
    # es
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    # it
    "gennaio": 1, "febbraio": 2, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
    "settembre": 9, "ottobre": 10, "dicembre": 12,
}
MONTH_ALT = "|".join(sorted((re.escape(m) for m in MONTHS), key=len, reverse=True))
DATE_PATTERNS = [
    (re.compile(r"\b(20\d\d)-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](20\d\d)\b"), "dmy"),
    (re.compile(rf"\b(\d{{1,2}})\.?\s*(?:de\s+)?({MONTH_ALT})\.?\s*(?:de\s+)?,?\s*(20\d\d)\b", re.I), "d_mon_y"),
    (re.compile(rf"\b({MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d\d)\b", re.I), "mon_d_y"),
]


# ----------------------------------------------------------------- helpers

def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha(s: str, n: int = 12) -> str:
    return hashlib.sha1(s.encode("utf-8", "ignore")).hexdigest()[:n]


def clean(s: str | None, limit: int | None = None) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        s = s[: limit - 1].rsplit(" ", 1)[0] + "…"
    return s


def find_date(text: str) -> str | None:
    for rx, kind in DATE_PATTERNS:
        m = rx.search(text or "")
        if not m:
            continue
        try:
            if kind == "ymd":
                y, mo, d = int(m[1]), int(m[2]), int(m[3])
            elif kind == "dmy":
                d, mo, y = int(m[1]), int(m[2]), int(m[3])
            elif kind == "d_mon_y":
                d, mo, y = int(m[1]), MONTHS[m[2].lower()], int(m[3])
            else:
                mo, d, y = MONTHS[m[1].lower()], int(m[2]), int(m[3])
            return datetime(y, mo, d).date().isoformat()
        except (ValueError, KeyError):
            continue
    return None


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(path)


def load_sources() -> list[dict]:
    raw = yaml.safe_load(SOURCES.read_text("utf-8")) or []
    out = []
    for s in raw:
        s.setdefault("links", {})
        s.setdefault("channels", [])
        s["country"] = str(s.get("country", "XX"))
        for c in s["channels"]:
            cfg = "|".join(str(c.get(k, "")) for k in ("url", "include", "exclude", "selector"))
            c["key"] = f"{s['id']}:{c['type']}:{sha(cfg, 8)}"
        out.append(s)
    return out


def fetch(url: str) -> requests.Response:
    err = None
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            return r
        except requests.RequestException as e:   # retry once
            err = e
            time.sleep(3)
    raise err  # type: ignore[misc]


def is_event(*texts: str) -> bool:
    return bool(EVENT_RE.search(" ".join(t or "" for t in texts)))


# --------------------------------------------------------------- channels

def read_feed(url: str) -> list[dict]:
    r = fetch(url)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"not a feed ({type(feed.bozo_exception).__name__})")
    items = []
    for e in feed.entries[:60]:
        link = e.get("link") or ""
        published = None
        for k in ("published_parsed", "updated_parsed"):
            if e.get(k):
                published = datetime(*e[k][:6], tzinfo=timezone.utc).date().isoformat()
                break
        items.append({
            "uid": e.get("id") or link or e.get("title", ""),
            "title": clean(e.get("title"), 220),
            "url": link,
            "summary": clean(e.get("summary") or e.get("description"), 320),
            "published": published,
        })
    return items


def read_gnews(query: str) -> list[dict]:
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en&gl=ET&ceid=ET:en"
    items = read_feed(url)
    for it in items:
        it["summary"] = ""  # Google News summaries are just the title + source
    return items


def read_telegram(channel: str) -> list[dict]:
    name = channel.rsplit("/", 1)[-1].lstrip("@")
    r = fetch(f"https://t.me/s/{name}")
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    items = []
    for msg in soup.select("div.tgme_widget_message[data-post]"):
        post = msg["data-post"]
        text_el = msg.select_one(".tgme_widget_message_text")
        text = clean(text_el.get_text(" ", strip=True) if text_el else "")
        t = msg.select_one("time[datetime]")
        published = t["datetime"][:10] if t else None
        if not text:
            text = "(photo or media post)"
        first = re.split(r"(?<=[.!?])\s|\n", text, maxsplit=1)[0]
        items.append({
            "uid": post,
            "title": clean(first, 160),
            "url": f"https://t.me/{post}",
            "summary": clean(text, 320),
            "published": published,
        })
    if not items and "tgme_channel_info" not in r.text:
        raise ValueError("channel not public or not found")
    return items


def main_area(soup: BeautifulSoup, selector: str | None):
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "form", "svg", "template"]):
        tag.decompose()
    for el in soup.select('[role="navigation"], [class*="breadcrumb"], [id*="cookie"], [class*="cookie"], '
                          '[class*="skip-link"], [class*="language"], [id*="language"]'):
        el.decompose()
    if selector:
        found = soup.select_one(selector)
        if found:
            return found
    return (soup.find("main") or soup.find(attrs={"role": "main"})
            or soup.find(id=re.compile(r"^(main|content|main-content|maincontent)$", re.I))
            or soup.body or soup)


def link_title(a) -> str:
    t = clean(a.get_text(" ", strip=True))
    if len(t) < 12:
        t = clean(a.get("title") or a.get("aria-label") or "")
    if len(t) < 12:
        img = a.find("img")
        if img and img.get("alt"):
            t = clean(img["alt"])
    if len(t) < 12:
        # look for a heading in the surrounding card
        card = a.find_parent(["article", "li", "div"])
        if card:
            h = card.find(["h1", "h2", "h3", "h4", "h5"])
            if h:
                t = clean(h.get_text(" ", strip=True))
    return t


def read_web(ch: dict) -> tuple[list[dict], str]:
    url = ch["url"]
    r = fetch(url)
    r.raise_for_status()
    final = r.url
    soup = BeautifulSoup(r.content, "lxml")
    area = main_area(soup, ch.get("selector"))
    text_hash = sha(clean(area.get_text(" ", strip=True)), 16)

    include = re.compile(ch["include"], re.I) if ch.get("include") else None
    exclude = re.compile(ch["exclude"], re.I) if ch.get("exclude") else None
    hosts = {urlparse(final).netloc.lower(), urlparse(url).netloc.lower()}
    page_norm = final.rstrip("/").lower()

    found: dict[str, dict] = {}
    for a in area.find_all("a", href=True):
        href = urljoin(final, a["href"]).split("#")[0]
        p = urlparse(href)
        if p.scheme not in ("http", "https"):
            continue
        if p.netloc.lower() not in hosts and not include:
            continue
        if href.rstrip("/").lower() in (page_norm, url.rstrip("/").lower()):
            continue
        if DEFAULT_EXCLUDE.search(href) or (exclude and exclude.search(href)):
            continue
        if include and not include.search(href):
            continue
        segs = [s for s in p.path.split("/") if s]
        if not include and len(segs) < 2 and not p.query:
            continue
        title = link_title(a)
        if len(title) < 12 or len(title.split()) < 3:
            continue
        ctx = a.find_parent(["article", "li", "tr"]) or a.parent
        ctx_text = clean(ctx.get_text(" ", strip=True)) if ctx else title
        prev = found.get(href)
        if prev and len(prev["title"]) >= len(title):
            continue
        summary = ctx_text.replace(title, "", 1).strip(" -–|·:") if ctx_text != title else ""
        found[href] = {
            "uid": href,
            "title": clean(title, 220),
            "url": href,
            "summary": clean(summary, 320),
            "published": find_date(ctx_text),
        }
    return list(found.values())[:80], text_hash


def run_channel(src: dict, ch: dict) -> dict:
    t0 = time.time()
    res = {"key": ch["key"], "source": src["id"], "type": ch["type"], "url": ch["url"],
           "label": ch.get("label"), "ok": False, "items": [], "error": None, "hash": None}
    try:
        if ch["type"] == "rss":
            res["items"] = read_feed(ch["url"])
        elif ch["type"] == "gnews":
            res["items"] = read_gnews(ch["url"])
        elif ch["type"] == "telegram":
            res["items"] = read_telegram(ch["url"])
        elif ch["type"] == "web":
            res["items"], res["hash"] = read_web(ch)
        else:
            raise ValueError(f"unknown channel type {ch['type']}")
        res["ok"] = True
    except requests.HTTPError as e:
        res["error"] = f"HTTP {e.response.status_code}"
    except Exception as e:  # noqa: BLE001
        res["error"] = f"{type(e).__name__}: {str(e)[:160]}"
    res["ms"] = int((time.time() - t0) * 1000)
    return res


# ----------------------------------------------------------------- notify

def flag(cc: str) -> str:
    if len(cc) != 2 or not cc.isalpha() or cc.upper() == "XX":
        return "📰"
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in cc.upper())


def ntfy(title: str, message: str, click: str | None = None, priority: int = 3, tags=None) -> None:
    if not NTFY_TOPIC:
        return
    body = {"topic": NTFY_TOPIC, "title": title[:250], "message": message[:3800], "priority": priority}
    if click:
        body["click"] = click
    if tags:
        body["tags"] = tags
    try:
        requests.post(NTFY_SERVER, json=body, timeout=20)
    except requests.RequestException as e:
        print(f"ntfy failed: {e}", file=sys.stderr)


def notify(new_items: list[dict], src_by_id: dict, first_run: bool, n_channels: int) -> None:
    if first_run:
        ntfy("Addis Events Radar is live",
             f"Now watching {n_channels} channels across {len(src_by_id)} sources. "
             "You'll get a push when something new appears.", click=DASHBOARD_URL, tags=["satellite"])
        return
    events = [i for i in new_items if i["event"]]
    other = [i for i in new_items if not i["event"]]
    if events:
        if len(events) <= 6:
            for it in events:
                s = src_by_id[it["source"]]
                ntfy(f"{flag(s['country'])} {s['name']}", it["title"], click=it["url"] or DASHBOARD_URL,
                     priority=4, tags=["calendar"])
        else:
            lines = [f"{flag(src_by_id[i['source']]['country'])} {i['title']}" for i in events[:10]]
            ntfy(f"{len(events)} new event posts", "\n".join(lines), click=DASHBOARD_URL, priority=4,
                 tags=["calendar"])
    if other and NOTIFY_OTHER != "off":
        if NOTIFY_OTHER == "each" and len(other) <= 6:
            for it in other:
                s = src_by_id[it["source"]]
                ntfy(f"{flag(s['country'])} {s['name']}", it["title"], click=it["url"] or DASHBOARD_URL,
                     priority=2)
        else:
            names = sorted({src_by_id[i["source"]]["name"] for i in other})
            ntfy(f"{len(other)} other updates",
                 "From: " + ", ".join(names[:12]) + (" …" if len(names) > 12 else ""),
                 click=DASHBOARD_URL, priority=2, tags=["newspaper"])


# ------------------------------------------------------------------ check

def write_feed(items: list[dict], src_by_id: dict) -> None:
    entries = [i for i in items if not i.get("baseline")][:100]
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0"><channel>',
        "<title>Addis Events Radar</title>",
        f"<link>{html.escape(DASHBOARD_URL)}</link>",
        "<description>New posts from embassies and cultural institutes in Addis Ababa</description>",
    ]
    for it in entries:
        s = src_by_id.get(it["source"], {"name": it["source"], "country": "XX"})
        dt = datetime.fromisoformat(it["first_seen"])
        parts.append(
            "<item>"
            f"<title>{html.escape(s['name'] + ': ' + it['title'])}</title>"
            f"<link>{html.escape(it['url'] or DASHBOARD_URL)}</link>"
            f"<guid isPermaLink=\"false\">{it['id']}</guid>"
            f"<pubDate>{format_datetime(dt)}</pubDate>"
            f"<description>{html.escape(it.get('summary') or '')}</description>"
            "</item>"
        )
    parts.append("</channel></rss>")
    (DATA / "feed.xml").write_text("\n".join(parts), "utf-8")


def cmd_check() -> None:
    sources = load_sources()
    src_by_id = {s["id"]: s for s in sources}
    state = load_json(DATA / "state.json", {"channels": {}})
    items: list[dict] = load_json(DATA / "items.json", [])
    first_run = not state["channels"]
    live_keys = {c["key"] for s in sources for c in s["channels"]}
    state["channels"] = {k: v for k, v in state["channels"].items() if k in live_keys}
    items = [i for i in items if i["channel"] in live_keys]
    known_ids = {i["id"] for i in items}

    jobs = [(s, c) for s in sources for c in s["channels"]]
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda sc: run_channel(*sc), jobs))

    stamp = now_iso()
    new_items: list[dict] = []
    status = {}
    for res in results:
        cst = state["channels"].setdefault(res["key"], {"initialized": False, "seen": [], "hash": None})
        baseline = not cst["initialized"]
        seen = set(cst["seen"])
        fresh = []
        if res["ok"]:
            # page-change fallback for web pages where no article links could be found
            if res["type"] == "web" and not res["items"] and res["hash"]:
                if cst.get("hash") and cst["hash"] != res["hash"]:
                    s = src_by_id[res["source"]]
                    res["items"] = [{"uid": f"hash:{res['hash']}", "title": f"{s['name']}: page was updated",
                                     "url": res["url"], "summary": "The monitored page changed; open it to see what is new.",
                                     "published": stamp[:10]}]
                cst["hash"] = res["hash"]
            for it in res["items"]:
                iid = sha(f"{res['source']}|{it['uid']}")
                if iid in seen or iid in known_ids:
                    continue
                seen.add(iid)
                item = {
                    "id": iid,
                    "source": res["source"],
                    "channel": res["key"],
                    "type": res["type"],
                    "title": it["title"] or "(untitled)",
                    "url": it["url"],
                    "summary": it.get("summary", ""),
                    "published": it.get("published"),
                    "first_seen": stamp,
                    "baseline": baseline,
                    "event": is_event(it["title"], it.get("summary", "")),
                }
                fresh.append(item)
                known_ids.add(iid)
            cst["initialized"] = True
            cst["seen"] = list(seen)[-MAX_SEEN:]
            cst["last_ok"] = stamp
            if fresh and not baseline:
                cst["last_new"] = stamp
        else:
            cst["last_error"] = stamp
        new_items.extend(fresh)
        status[res["key"]] = {
            "source": res["source"], "type": res["type"], "url": res["url"], "label": res.get("label"),
            "ok": res["ok"], "error": res["error"], "found": len(res["items"]), "new": len(fresh),
            "ms": res["ms"], "checked": stamp, "last_ok": cst.get("last_ok"), "last_new": cst.get("last_new"),
            "sample": [i["title"] for i in res["items"][:5]],
        }

    # newest first; keep the store bounded
    items = sorted(new_items, key=lambda i: (i["published"] or "", i["title"]), reverse=True) + items
    items = items[:MAX_ITEMS]

    save_json(DATA / "items.json", items)
    save_json(DATA / "state.json", state)
    save_json(DATA / "status.json", {"checked": stamp, "channels": status})
    save_json(DATA / "sources.json", {"generated": stamp, "sources": [
        {k: v for k, v in s.items() if k != "channels"} | {"channels": [
            {"key": c["key"], "type": c["type"], "url": c["url"], "label": c.get("label")} for c in s["channels"]]}
        for s in sources]})
    write_feed(items, src_by_id)

    real_new = [i for i in new_items if not i["baseline"]]
    ok = sum(1 for r in results if r["ok"])
    print(f"{stamp}: {ok}/{len(results)} channels ok, {len(new_items)} new items "
          f"({len(real_new)} after baseline, {sum(i['event'] for i in real_new)} event-like)")
    for r in results:
        if not r["ok"]:
            print(f"  FAIL {r['key']}: {r['error']}  {r['url']}")
    notify(real_new, src_by_id, first_run, len(results))


# --------------------------------------------------------------- discover

def discover_one(src: dict) -> dict:
    out = {"id": src["id"], "checked": now_iso(), "links": {}, "feeds": [], "newsletter": [], "error": None}
    pages = [src.get("homepage")] + [c["url"] for c in src["channels"] if c["type"] == "web"]
    pages = [p for i, p in enumerate(pages) if p and p not in pages[:i]][:3]
    for page in pages:
        try:
            r = fetch(page)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            out["error"] = f"{page}: {type(e).__name__} {str(e)[:120]}"
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for ln in soup.find_all("link", rel=True, href=True):
            typ = (ln.get("type") or "").lower()
            if "alternate" in [x.lower() for x in ln["rel"]] and ("rss" in typ or "atom" in typ):
                u = urljoin(r.url, ln["href"])
                if u not in out["feeds"]:
                    out["feeds"].append(u)
        for a in soup.find_all("a", href=True):
            href = urljoin(r.url, a["href"].strip())
            for kind, rx in SOCIAL_PATTERNS.items():
                if rx.match(href):
                    out["links"].setdefault(kind, [])
                    h = href.rstrip("/")
                    if h not in out["links"][kind]:
                        out["links"][kind].append(h)
            label = clean(a.get_text(" ", strip=True))
            if (NEWSLETTER_RE.search(label) or NEWSLETTER_RE.search(href)) and href.startswith("http") \
                    and not any(rx.match(href) for rx in SOCIAL_PATTERNS.values()):
                if href not in out["newsletter"] and len(out["newsletter"]) < 3:
                    out["newsletter"].append(href)
    return out


def cmd_discover() -> None:
    sources = load_sources()
    with ThreadPoolExecutor(max_workers=8) as pool:
        found = list(pool.map(discover_one, sources))
    save_json(DATA / "discovered.json", {"checked": now_iso(), "sources": {f["id"]: f for f in found}})
    for f in found:
        kinds = ", ".join(f"{k}:{len(v)}" for k, v in f["links"].items())
        print(f"{f['id']:16} feeds={len(f['feeds'])} news={len(f['newsletter'])} {kinds} {f['error'] or ''}")


def cmd_ping() -> None:
    if not NTFY_TOPIC:
        sys.exit("NTFY_TOPIC secret is not set")
    ntfy("Addis Events Radar: test", "Notifications are working. Tap to open the dashboard.",
         click=DASHBOARD_URL, tags=["white_check_mark"])
    print("test notification sent")


def cmd_snapshot() -> None:
    """Save the raw HTML of each monitored page (debug aid for tuning include rules)."""
    out = ROOT / "debug"
    out.mkdir(exist_ok=True)
    index = {}
    for s in load_sources():
        for c in s["channels"]:
            if c["type"] not in ("web", "rss"):
                continue
            name = re.sub(r"[^a-z0-9]+", "-", c["key"].lower()) + ".html"
            try:
                r = fetch(c["url"])
                (out / name).write_bytes(r.content)
                index[c["key"]] = {"url": c["url"], "final": r.url, "status": r.status_code,
                                   "bytes": len(r.content), "file": name}
            except Exception as e:  # noqa: BLE001
                index[c["key"]] = {"url": c["url"], "error": f"{type(e).__name__}: {str(e)[:160]}"}
    (out / "index.json").write_text(json.dumps(index, indent=1), "utf-8")
    print(json.dumps(index, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    {"check": cmd_check, "discover": cmd_discover, "ping": cmd_ping, "snapshot": cmd_snapshot}[cmd]()
