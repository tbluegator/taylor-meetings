"""Shared data shapes and helpers."""
from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import asdict, dataclass, field
from html import unescape
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("America/New_York")
USER_AGENT = "TaylorMeetings/1.0 (personal civic project; polite, a few requests per run)"


@dataclass
class Document:
    label: str          # "Agenda", "Agenda Packet", "Minutes"...
    url: str


@dataclass
class AgendaItem:
    section: str
    number: str
    text: str
    topics: list[str] = field(default_factory=list)


@dataclass
class Meeting:
    id: str                       # stable: "<source>:<native id>"
    source: str                   # config source id
    body: str                     # display name of the board
    body_short: str
    title: str
    start: str                    # ISO 8601 local time with offset
    location: str = ""
    url: str = ""                 # official page for this meeting
    documents: list[Document] = field(default_factory=list)
    video_url: str = ""
    agenda_items: list[AgendaItem] = field(default_factory=list)
    agenda_posted: bool = False
    note: str = ""
    topics: list[str] = field(default_factory=list)
    first_seen: str = ""          # when this tracker first saw it
    agenda_first_seen: str = ""   # when the agenda first appeared

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Meeting":
        d = dict(d)
        d["documents"] = [Document(**x) for x in d.get("documents", [])]
        d["agenda_items"] = [AgendaItem(**x) for x in d.get("agenda_items", [])]
        return Meeting(**d)

    @property
    def start_dt(self) -> dt.datetime:
        return dt.datetime.fromisoformat(self.start)


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def clean_text(s: str | None) -> str:
    """Strip tags, zero-width chars and extra whitespace from agenda HTML snippets."""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = unescape(s).replace("​", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def nth_weekdays(year: int, month: int, weekday: int, nths: list[int]) -> list[dt.date]:
    """Dates of the nth occurrences of a weekday (Mon=0) in a month, e.g. 2nd & 4th Tuesday."""
    days = [d for d in calendar.Calendar().itermonthdates(year, month)
            if d.month == month and d.weekday() == weekday]
    return [days[n - 1] for n in nths if n - 1 < len(days)]


def months_between(start: dt.date, end: dt.date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m > 12:
            y, m = y + 1, 1


def local_iso(d: dt.date, hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    return dt.datetime(d.year, d.month, d.day, h, m, tzinfo=TZ).isoformat()
