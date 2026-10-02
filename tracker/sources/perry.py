"""Perry City Council via the city's CivicPlus (Drupal) website.

Meetings are found three ways, so one change on the city site doesn't blind us:
  1. /rss.xml        - the site feed lists the 10 newest meeting pages, including
                       special meetings off the regular schedule (e.g. Thu Sep 10, 2026)
  2. /meetings       - upcoming meetings table
  3. regular dates   - 2nd & 4th Tuesday URLs, tried directly
Each meeting page links the agenda PDF (/media/NNNN) and often a Dropbox packet.
This is the most fragile source: a site redesign means updating the selectors here.
"""
from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import TZ, AgendaItem, Document, Meeting, clean_text, local_iso, months_between, nth_weekdays, session

SLUG = re.compile(r"/meeting/([a-z0-9-]*?(\d{8}))\b")


def parse_listing(html: str) -> list[str]:
    """Return meeting page paths found on the upcoming-meetings page."""
    soup = BeautifulSoup(html, "lxml")
    paths = []
    for a in soup.select("a[href*='/meeting/']"):
        href = a.get("href", "")
        if SLUG.search(href) and href not in paths:
            paths.append(href)
    return paths


def parse_rss(xml: str) -> list[str]:
    import xml.etree.ElementTree as ET
    from urllib.parse import urlparse
    out = []
    if not xml or not xml.strip():
        return out                      # empty feed: fall back to other paths
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return out                      # not XML (challenge page, truncated): skip
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        if SLUG.search(link):
            out.append(urlparse(link).path)
    return out


def candidate_paths(cfg: dict, start: dt.date, end: dt.date) -> list[str]:
    sched = cfg["regular_schedule"]
    out = []
    for y, m in months_between(start, end):
        for d in nth_weekdays(y, m, sched["weekday"], sched["nths"]):
            if start <= d <= end:
                out.append(f"/perry-city-council/meeting/city-council-meeting-{d:%Y%m%d}")
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


def fetch(cfg: dict, start: dt.date, end: dt.date, http=None) -> list[Meeting]:
    http = http or session()
    listing = http.get(urljoin(cfg["base"], "/meetings"), timeout=30)
    listing.raise_for_status()
    found = parse_listing(listing.text)
    rss = http.get(urljoin(cfg["base"], "/rss.xml"), timeout=30)
    if rss.ok:
        found += parse_rss(rss.text)
    paths = list(dict.fromkeys(found + candidate_paths(cfg, start, end)))
    meetings = []
    for path in paths:
        r = http.get(urljoin(cfg["base"], path), timeout=30)
        if r.status_code == 404:
            continue            # no meeting on that regular date (holiday, cancelled)
        r.raise_for_status()
        m = parse_meeting(r.text, path, cfg)
        if not m or not (start <= m.start_dt.date() <= end):
            continue
        agenda = next((d for d in m.documents if "/media/" in d.url), None)
        if agenda:
            pdf = http.get(agenda.url, timeout=60)
            if pdf.ok and pdf.content[:4] == b"%PDF":
                try:
                    m.agenda_items = agenda_items_from_pdf(pdf.content)
                except Exception:
                    pass        # links still show; just no item-level detail
        meetings.append(m)
    return meetings
