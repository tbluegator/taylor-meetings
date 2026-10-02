"""Render the static site: index.html, feed.xml (RSS), meetings.ics, and JSON copies."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
from email.utils import format_datetime
from xml.sax.saxutils import escape

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import Meeting

TEMPLATES = pathlib.Path(__file__).resolve().parent.parent / "templates"
BOARD_ORDER = ["bocc", "perry", "school", "tcda"]


def _fmt_time(d: dt.datetime) -> str:
    return d.strftime("%-I:%M %p").replace(":00 ", " ").replace("AM", "a.m.").replace("PM", "p.m.")


def view(m: Meeting, now: dt.datetime) -> dict:
    s = m.start_dt
    watched = [i for i in m.agenda_items if i.topics]
    if m.source == "tcda":
        status = ("none", "Not posted online")
    elif m.agenda_posted:
        status = ("posted", "Agenda posted")
    elif s < now:
        status = ("missing", "No agenda found")
    else:
        status = ("pending", "Agenda not yet posted")
    sections: list[dict] = []
    for it in m.agenda_items:
        if not sections or sections[-1]["name"] != it.section:
            sections.append({"name": it.section, "items": []})
        sections[-1]["items"].append(it)
    return {
        "m": m, "start": s, "time": _fmt_time(s),
        "day_label": s.strftime("%a"), "date_label": s.strftime("%b %-d"),
        "long_date": s.strftime("%A, %B %-d"),
        "days_away": (s.date() - now.date()).days,
        "status": status, "watched": watched, "sections": sections,
        "minutes": any("minute" in d.label.lower() for d in m.documents),
    }


def site(cfg: dict, meetings: list[Meeting], status: dict, problems: list[dict], now: dt.datetime, out: pathlib.Path,
         standalone: bool = True) -> None:
    out.mkdir(parents=True, exist_ok=True)
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    upcoming = [view(m, now) for m in meetings if m.start_dt >= now - dt.timedelta(hours=4)
                and m.start_dt.date() <= (now + dt.timedelta(days=cfg["window"]["future_days"])).date()]
    recent = [view(m, now) for m in reversed(meetings)
              if now - dt.timedelta(days=45) <= m.start_dt < now - dt.timedelta(hours=4) and m.source != "tcda"]
    watch = [(v, i) for v in upcoming for i in v["watched"]]
    recent_watch = [(v, i) for v in recent for i in v["watched"]][:8]

    sources = []
    for src in cfg["sources"]:
        st = status.get(src["id"], {})
        sources.append({"cfg": src, "st": st,
                        "problems": [p for p in problems if p["source"] == src["id"]]})
    html = env.get_template("index.html.j2").render(
        cfg=cfg, site=cfg["site"], now=now, standalone=standalone, upcoming=upcoming, recent=recent,
        watch=watch, recent_watch=recent_watch, sources=sources, problems=problems,
        topics=list(cfg.get("topics", {}).keys()),
        boards=[s for s in cfg["sources"]], board_order=BOARD_ORDER,
        checked=now.strftime("%-I:%M %p, %a %b %-d").replace("AM", "a.m.").replace("PM", "p.m."),
    )
    (out / "index.html").write_text(html)
    (out / "feed.xml").write_text(rss(cfg, meetings, now))
    (out / "meetings.ics").write_text(ics(cfg, meetings, now))
    (out / "meetings.json").write_text(json.dumps([m.to_dict() for m in meetings], indent=1))
    (out / ".nojekyll").write_text("")


def rss(cfg: dict, meetings: list[Meeting], now: dt.datetime) -> str:
    """One entry per posted agenda, newest first. Watched-topic items lead the description."""
    posted = sorted((m for m in meetings if m.agenda_posted and m.agenda_first_seen),
                    key=lambda m: m.agenda_first_seen, reverse=True)[:40]
    items = []
    for m in posted:
        watched = [i for i in m.agenda_items if i.topics]
        desc = f"{m.body} · {m.start_dt:%A, %B %-d at %-I:%M %p}"
        if watched:
            desc += "\n\nWatched topics on this agenda:\n" + "\n".join(
                f"• [{', '.join(i.topics)}] Item {i.number}: {i.text[:240]}" for i in watched)
        desc += "\n\n" + "\n".join(f"{d.label}: {d.url}" for d in m.documents)
        title = f"{'⚑ ' if watched else ''}{m.body_short}: {m.title}, {m.start_dt:%b %-d}"
        pub = dt.datetime.fromisoformat(m.agenda_first_seen)
        items.append(f"""<item><title>{escape(title)}</title><link>{escape(m.url)}</link>
<guid isPermaLink="false">{escape(m.id)}:agenda</guid><pubDate>{format_datetime(pub)}</pubDate>
<description>{escape(desc)}</description></item>""")
    site = cfg["site"]
    return f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>{escape(site['title'])}: new agendas</title>
<link>{escape(site['base_url'])}</link><description>{escape(site['tagline'])}</description>
<lastBuildDate>{format_datetime(now)}</lastBuildDate>
{''.join(items)}
</channel></rss>
"""


def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics(cfg: dict, meetings: list[Meeting], now: dt.datetime) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Taylor Meetings//EN",
             f"X-WR-CALNAME:{_ics_escape(cfg['site']['title'])}", "X-WR-TIMEZONE:America/New_York"]
    utc = dt.timezone.utc
    for m in meetings:
        s = m.start_dt.astimezone(utc)
        e = s + dt.timedelta(hours=2)
        desc = "\n".join(([m.note] if m.note else []) + [f"{d.label}: {d.url}" for d in m.documents])
        lines += ["BEGIN:VEVENT", f"UID:{m.id.replace(':', '-')}@taylor-meetings",
                  f"DTSTAMP:{now.astimezone(utc):%Y%m%dT%H%M%SZ}",
                  f"DTSTART:{s:%Y%m%dT%H%M%SZ}", f"DTEND:{e:%Y%m%dT%H%M%SZ}",
                  f"SUMMARY:{_ics_escape(m.body_short + ': ' + m.title)}",
                  f"LOCATION:{_ics_escape(m.location)}", f"URL:{m.url}",
                  f"DESCRIPTION:{_ics_escape(desc)}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"


def _fold(line: str) -> str:
    """RFC 5545: lines longer than 75 octets continue on the next line after a space."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode()
        if len(cur) + len(b) > (75 if not out else 74):
            out.append(cur.decode())
            cur = b""
        cur += b
    out.append(cur.decode())
    return "\r\n ".join(out)
