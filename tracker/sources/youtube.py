"""Attach meeting videos from a YouTube channel's public RSS feed.

Matching is by date: a video published on the meeting day or within the next
three days is attached to that board's meeting. If a board posts two meetings
in one week, check the result once and tighten `max_lag_days` if needed.
"""
from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET

from ..models import Meeting, session

NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
MEETINGISH = re.compile(r"meeting|council|board|workshop|hearing|session", re.I)


def parse_feed(xml: str) -> list[dict]:
    root = ET.fromstring(xml)
    out = []
    for e in root.findall("a:entry", NS):
        out.append({
            "title": e.findtext("a:title", "", NS),
            "url": e.find("a:link", NS).get("href"),
            "published": dt.datetime.fromisoformat(e.findtext("a:published", "", NS)),
        })
    return out


def attach(meetings: list[Meeting], videos: list[dict], max_lag_days: int = 3) -> None:
    for m in sorted(meetings, key=lambda m: m.start):
        if m.video_url:
            continue
        day = m.start_dt.date()
        for v in videos:
            if not MEETINGISH.search(v["title"]):
                continue
            lag = (v["published"].astimezone(m.start_dt.tzinfo).date() - day).days
            if 0 <= lag <= max_lag_days and not v.get("used"):
                m.video_url, v["used"] = v["url"], True
                break


def fetch_videos(channel_id: str, http=None) -> list[dict]:
    http = http or session()
    r = http.get("https://www.youtube.com/feeds/videos.xml", params={"channel_id": channel_id}, timeout=30)
    r.raise_for_status()
    return parse_feed(r.text)
