"""Watchdog: decide whether the tracker is still seeing what it should.

Errors fail the GitHub Actions run, and GitHub emails the repo owner when a
scheduled run fails. That is the whole alerting setup: no extra service.
"""
from __future__ import annotations

import datetime as dt

from .models import Meeting


def check(cfg: dict, meetings: list[Meeting], status: dict, now: dt.datetime) -> list[dict]:
    problems = []
    for src in cfg["sources"]:
        sid, name = src["id"], src["name"]
        st = status.get(sid, {})
        if not st.get("ok"):
            problems.append({"level": "error", "source": sid,
                             "message": f"{name}: could not fetch ({st.get('error', 'unknown error')}). Showing the last data we had."})
            continue
        if src["type"] == "recurring":
            continue
        mine = [m for m in meetings if m.source == sid]
        if st.get("count", 0) == 0:
            problems.append({"level": "error", "source": sid,
                             "message": f"{name}: the source answered but listed no meetings. Its website may have changed."})
            continue
        lead = dt.timedelta(days=src.get("expect_agenda_days_before", 3))
        recent_past = [m for m in mine if now - dt.timedelta(days=30) <= m.start_dt < now]
        if recent_past and not any(m.agenda_posted for m in recent_past):
            problems.append({"level": "error", "source": sid,
                             "message": f"{name}: none of the last 30 days of meetings has an agenda. The agenda links may have moved."})
        for m in mine:
            if now < m.start_dt <= now + lead and not m.agenda_posted:
                problems.append({"level": "warning", "source": sid,
                                 "message": f"{name}: no agenda posted yet for {m.start_dt:%a %b %-d} ({m.title})."})
    return problems
