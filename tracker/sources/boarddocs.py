"""School Board of Taylor County via BoardDocs.

BoardDocs serves a JSON meeting list at BD-GETMeetingsListForSEO and each agenda
as an HTML fragment from BD-GetAgenda (POST). Note: BoardDocs' robots.txt asks
crawlers to stay out. This makes a handful of targeted requests per run for
public records; keep the schedule modest.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from bs4 import BeautifulSoup

from ..models import TZ, AgendaItem, Document, Meeting, clean_text, session


def base(cfg: dict) -> str:
    return f"https://go.boarddocs.com/{cfg['site']}/Board.nsf"


def parse_time(description: str) -> tuple[int, int]:
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m", description or "", re.I)
    if not m:
        return 17, 15
    h, mnt = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3).lower() == "p" and h != 12:
        h += 12
    return h, mnt


def parse_list(raw: str | list, cfg: dict) -> list[Meeting]:
    rows = json.loads(raw) if isinstance(raw, str) else raw
    out = []
    for r in rows:
        day = dt.date.fromisoformat(r["Date"][:10])
        h, mnt = parse_time(r.get("Description", ""))
        loc = re.sub(r"\s*\d{1,2}(:\d{2})?\s*[ap]\.?m\.?\s*$", "", r.get("Description", ""), flags=re.I).strip()
        out.append(Meeting(
            id=f"{cfg['id']}:{r['Unique']}",
            source=cfg["id"],
            body=cfg["name"],
            body_short=cfg["short"],
            title=r.get("Name", "School Board Meeting").strip(),
            start=dt.datetime(day.year, day.month, day.day, h, mnt, tzinfo=TZ).isoformat(),
            location=loc or cfg.get("location", ""),
            url=f"{base(cfg)}/goto?open&id={r['Unique']}",
        ))
    return out


def parse_agenda(html: str) -> list[AgendaItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[AgendaItem] = []
    section = ""
    for el in soup.select("dt.category, li.item"):
        if el.name == "dt":
            section = clean_text(el.select_one(".category-name").get_text() if el.select_one(".category-name") else el.get_text())
            section = re.sub(r"^\d+\s*-?\s*", "", section)
            continue
        title = clean_text(el.select_one(".title").get_text() if el.select_one(".title") else el.get("xtitle", ""))
        m = re.match(r"^(\d+\.\d+)\s*-?\s*(.*)$", title)
        number, text = (m.group(1), m.group(2)) if m else ("", title)
        kind = clean_text(el.select_one(".actiontype").get_text()).rstrip(", ") if el.select_one(".actiontype") else ""
        if kind:
            text = f"{text} ({kind})"
        items.append(AgendaItem(section=section, number=number, text=text))
    return items


def fetch(cfg: dict, start: dt.date, end: dt.date, http=None) -> list[Meeting]:
    http = http or session()
    r = http.get(f"{base(cfg)}/BD-GETMeetingsListForSEO?open", timeout=30)
    r.raise_for_status()
    meetings = [m for m in parse_list(r.text, cfg) if start <= m.start_dt.date() <= end]
    for m in meetings:
        native = m.id.split(":", 1)[1]
        a = http.post(f"{base(cfg)}/BD-GetAgenda?open",
                      data={"id": native, "current_committee_id": cfg["committee_id"]}, timeout=30)
        if a.ok and a.text.strip():
            m.agenda_items = parse_agenda(a.text)
            m.agenda_posted = bool(m.agenda_items)
        if m.agenda_posted:
            m.documents = [Document("Agenda (BoardDocs)", m.url)]
    return meetings
