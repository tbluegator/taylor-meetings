"""Perry City Council via the city's CivicPlus (Drupal) website.

The site sits behind a Cloudflare managed challenge: the meeting pages and agenda
PDFs return a JS challenge to any non-browser client, from any IP. Only the
/calendar feeds are challenge-exempt. So discovery uses the free /calendar/json
feed (no Cloudflare), and the agenda pages + PDFs are fetched through a
Cloudflare-solving service (ScraperAPI) passed in as `solver`.

Each meeting page links the agenda PDF (/media/NNNN) and often a Dropbox packet.
To keep paid solver requests low, a meeting whose agenda was already captured on
a prior run (passed in via `known`) is reused without re-fetching. Without a
solver, the source still lists the schedule from the feed, minus agendas.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import TZ, AgendaItem, Document, Meeting, clean_text, local_iso, session

SLUG = re.compile(r"/meeting/([a-z0-9-]*?(\d{8}))\b")


def parse_calendar_json(raw: str | list, start: dt.date, end: dt.date) -> list[tuple]:
    """Meetings from the Cloudflare-exempt /calendar/json feed, as
    (date, path, title) tuples in the window. The date comes from the slug
    (YYYYMMDD); the time of day is refined later from the meeting page."""
    if isinstance(raw, str):
        try:
            rows = json.loads(raw)
        except ValueError:
            # A CF-solver may return the JSON wrapped in a rendered HTML page;
            # pull the JSON array back out.
            m = re.search(r"\[.*\]", raw, re.S)
            rows = json.loads(m.group(0)) if m else []
    else:
        rows = raw
    out = []
    for r in rows:
        path = (r.get("link") or "").strip()
        m = SLUG.search(path)
        if not m:
            continue                    # irregular/old slug without a YYYYMMDD date
        day = dt.datetime.strptime(m.group(2), "%Y%m%d").date()
        if start <= day <= end:
            out.append((day, path, (r.get("title") or "").strip()))
    return out


def parse_meeting(html: str, path: str, cfg: dict) -> Meeting | None:
    soup = BeautifulSoup(html, "lxml")
    m = SLUG.search(path)
    if not m:
        return None
    day = dt.datetime.strptime(m.group(2), "%Y%m%d").date()
    main = soup.find("main") or soup
    title = clean_text(main.find("h1").get_text()) if main.find("h1") else f"City Council Meeting {day:%Y.%m.%d}"

    # Start time: CivicPlus prints e.g. "Tue, Sep 22 2026, 5 - 8pm"
    start = local_iso(day, cfg["regular_schedule"]["time"])
    tm = re.search(r"\b\d{4},\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*-\s*\d{1,2}(?::\d{2})?\s*(am|pm)", main.get_text(" "), re.I)
    if tm:
        h, mins = int(tm.group(1)), int(tm.group(2) or 0)
        ampm = (tm.group(3) or tm.group(4)).lower()
        if ampm == "pm" and h != 12:
            h += 12
        start = dt.datetime(day.year, day.month, day.day, h, mins, tzinfo=TZ).isoformat()

    docs: list[Document] = []
    for a in main.select("a[href]"):
        href = a["href"]
        label = clean_text(a.get_text())
        if "/media/" in href:
            low = label.lower()
            name = "Minutes" if "minute" in low else "Agenda" if "agenda" in low else (re.sub(r"\s+[\d.]+\s*[KMG]B$", "", label, flags=re.I) or "Document")
            docs.append(Document(name, urljoin(cfg["base"], href)))
        elif re.match(r"https?://(www\.)?dropbox\.com/", href) and not any(d.url == href for d in docs):
            docs.append(Document("Agenda Packet (Dropbox)", href))

    return Meeting(
        id=f"{cfg['id']}:{day:%Y%m%d}",
        source=cfg["id"],
        body=cfg["name"],
        body_short=cfg["short"],
        title=title,
        start=start,
        location=cfg.get("location", ""),
        url=urljoin(cfg["base"], path),
        documents=docs,
        agenda_posted=any("agenda" in d.label.lower() and "dropbox" not in d.url for d in docs),
    )


ITEM = re.compile(r"^AGENDA ITEM\s+(\d+\s*\([A-Z]\))\s*[-\u2013\u2014:]?\s*(.*)$", re.I)
TOP = re.compile(r"^(\d{1,2})\.\s+(.+)$")
SUB = re.compile(r"^([A-Z])\.\s+(.+)$")
STOP = re.compile(r"^(Pursuant to 286\.0105|In accordance with the Americans with Disabilities)", re.I)


def _heading(s: str) -> str:
    return s.title().replace("Rfqs", "RFQs") if s.isupper() else s[:1].upper() + s[1:]


def parse_agenda_text(text: str) -> list[AgendaItem]:
    """Turn Perry's agenda PDF text into items.

    Shape (Sept 2026): numbered sections ("6. GENERAL BUSINESS:"), items written as
    "AGENDA ITEM 6(A)- ...", lettered consent items ("A. ..."), and wrapped lines.
    Section headers end in a colon; boilerplate under them is skipped."""
    items: list[AgendaItem] = []
    section, top_num, current = "", "", None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or re.match(r"^Page \d+$", line):
            continue
        if STOP.match(line):
            break
        if m := ITEM.match(line):
            current = AgendaItem(section=section, number=re.sub(r"\s+", "", m.group(1)), text=m.group(2).strip())
            items.append(current)
        elif m := TOP.match(line):
            top_num, body = m.group(1), m.group(2).strip()
            if body.endswith(":"):
                section, current = _heading(body.rstrip(":").strip()), None
            else:
                section = ""
                current = AgendaItem(section=section, number=top_num, text=body)
                items.append(current)
        elif (m := SUB.match(line)) and section:
            current = AgendaItem(section=section, number=f"{top_num}{m.group(1)}", text=m.group(2).strip())
            items.append(current)
        elif current is not None:
            joiner = "" if current.text.endswith("-") else " "
            current.text = (current.text + joiner + line).strip()
    return items


def agenda_items_from_pdf(pdf_bytes: bytes) -> list[AgendaItem]:
    from io import BytesIO

    from pypdf import PdfReader
    text = "\n".join((p.extract_text() or "") for p in PdfReader(BytesIO(pdf_bytes)).pages)
    return parse_agenda_text(text)


def _feed_only(cfg: dict, day: dt.date, path: str, title: str) -> Meeting:
    """A meeting from the feed alone, when no solver is available: schedule and
    link, default time, no agenda."""
    return Meeting(
        id=f"{cfg['id']}:{day:%Y%m%d}",
        source=cfg["id"], body=cfg["name"], body_short=cfg["short"],
        title=title or f"City Council Meeting {day:%Y.%m.%d}",
        start=local_iso(day, cfg["regular_schedule"]["time"]),
        location=cfg.get("location", ""),
        url=urljoin(cfg["base"], path),
    )


def fetch(cfg: dict, start: dt.date, end: dt.date, http=None,
          solver=None, known=None) -> list[Meeting]:
    http = http or session()
    known = known or {}
    # The feed is Cloudflare-exempt only from un-flagged IPs; from a datacenter
    # runner it is challenged like everything else, so fetch it via the solver
    # when one is available.
    feed = (solver or http).get(urljoin(cfg["base"], "/calendar/json"), timeout=30)
    feed.raise_for_status()
    entries = parse_calendar_json(feed.text, start, end)
    meetings = []
    for day, path, title in entries:
        mid = f"{cfg['id']}:{day:%Y%m%d}"
        prev = known.get(mid)
        # Reuse a prior run's result once its agenda is captured, so we don't
        # spend a paid solver request re-fetching a meeting we already have.
        if prev is not None and prev.agenda_posted and prev.agenda_items:
            meetings.append(prev)
            continue
        if solver is None:
            meetings.append(_feed_only(cfg, day, path, title))
            continue
        r = solver.get(urljoin(cfg["base"], path), timeout=70)
        if getattr(r, "status_code", 0) == 404 or not r.ok:
            # Page not reachable this run: keep prior data if any, else feed-only.
            meetings.append(prev or _feed_only(cfg, day, path, title))
            continue
        m = parse_meeting(r.text, path, cfg)
        if not m:
            meetings.append(prev or _feed_only(cfg, day, path, title))
            continue
        agenda = next((d for d in m.documents if "/media/" in d.url), None)
        if agenda:
            pdf = solver.get(agenda.url, timeout=90)
            if pdf.ok and pdf.content[:4] == b"%PDF":
                try:
                    m.agenda_items = agenda_items_from_pdf(pdf.content)
                except Exception:
                    pass        # links still show; just no item-level detail
        meetings.append(m)
    return meetings
