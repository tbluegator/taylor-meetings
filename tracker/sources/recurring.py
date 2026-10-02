"""Boards that publish nothing online: list their standing meetings from a schedule."""
from __future__ import annotations

import datetime as dt

from ..models import Document, Meeting, local_iso, months_between, nth_weekdays


def fetch(cfg: dict, start: dt.date, end: dt.date, http=None) -> list[Meeting]:
    sched = cfg["schedule"]
    out = []
    for y, m in months_between(start, end):
        for d in nth_weekdays(y, m, sched["weekday"], sched["nths"]):
            if start <= d <= end:
                out.append(Meeting(
                    id=f"{cfg['id']}:{d:%Y%m%d}",
                    source=cfg["id"],
                    body=cfg["name"],
                    body_short=cfg["short"],
                    title="Regular Board Meeting (standing schedule)",
                    start=local_iso(d, sched["time"]),
                    location=cfg.get("location", ""),
                    url=cfg.get("info_url", ""),
                    documents=[Document("Meeting info & Zoom link", cfg["info_url"])] if cfg.get("info_url") else [],
                    note=cfg.get("note", ""),
                ))
    return out
