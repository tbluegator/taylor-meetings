"""Taylor County BOCC (and VAB) via the CivicClerk public API.

CivicClerk exposes an OData JSON API at https://<tenant>.api.civicclerk.com/v1/.
Two quirks, both confirmed against Taylor County's data:
  * startDateTime is the LOCAL meeting time even though it ends in "Z".
    (Special budget hearings show 17:01 — Florida TRIM hearings must start after 5 pm.)
  * Agenda files resolve through Meetings/GetMeetingFileStream(fileId=N,plainText=false);
    plainText=true returns the agenda/packet as text (useful for Phase 2 summaries).
"""
from __future__ import annotations

import datetime as dt

from ..models import TZ, AgendaItem, Document, Meeting, clean_text, session


def api(tenant: str) -> str:
    return f"https://{tenant}.api.civicclerk.com/v1"


def file_url(tenant: str, file_id: int) -> str:
    return f"{api(tenant)}/Meetings/GetMeetingFileStream(fileId={file_id},plainText=false)"


def parse_start(raw: str) -> str:
    naive = dt.datetime.fromisoformat(raw.replace("Z", ""))
    return naive.replace(tzinfo=TZ).isoformat()


def flatten_items(items: list[dict], section: str = "") -> list[AgendaItem]:
    out: list[AgendaItem] = []
    for it in items:
        name = clean_text(it.get("agendaObjectItemName"))
        kids = it.get("childItems") or []
        if it.get("isSection"):
            out += flatten_items(kids, name.rstrip(":"))
        else:
            if name:
                out.append(AgendaItem(section=section, number=(it.get("agendaObjectItemOutlineNumber") or "").rstrip("."), text=name))
            out += flatten_items(kids, section)
    return out


def parse_event(ev: dict, cfg: dict) -> Meeting:
    tenant = cfg["tenant"]
    cat = cfg.get("categories", {}).get(ev.get("categoryName", ""), {})
    docs = [Document(label=f.get("name") or f.get("type") or "File", url=file_url(tenant, f["fileId"]))
            for f in sorted(ev.get("publishedFiles") or [], key=lambda f: f.get("sort", 0))]
    video = ev.get("mediaSourcePathMp4") or ""
    portal = f"https://{tenant}.portal.civicclerk.com/event/{ev['id']}/files"
    if video and not video.startswith("http"):
        video = f"https://{tenant}.portal.civicclerk.com/event/{ev['id']}/media"
    return Meeting(
        id=f"{cfg['id']}:{ev['id']}",
        source=cfg["id"],
        body=cat.get("name", ev.get("categoryName") or cfg["name"]),
        body_short=cat.get("short", cfg["short"]),
        title=ev.get("eventName") or "Meeting",
        start=parse_start(ev["startDateTime"]),
        location=cfg.get("location", ""),
        url=portal,
        documents=docs,
        video_url=video,
        agenda_posted=any(d.label.lower().find("agenda") >= 0 for d in docs),
    )


def fetch(cfg: dict, start: dt.date, end: dt.date, http=None) -> list[Meeting]:
    http = http or session()
    base = api(cfg["tenant"])
    params = {
        "$filter": f"startDateTime ge {start.isoformat()}T00:00:00Z and startDateTime le {end.isoformat()}T23:59:59Z",
        "$orderby": "startDateTime desc",
    }
    r = http.get(f"{base}/Events", params=params, timeout=30)
    r.raise_for_status()
    meetings = []
    for ev in r.json().get("value", []):
        if ev.get("isDeleted") or ev.get("isPublished") not in (None, "Published"):
            continue
        m = parse_event(ev, cfg)
        if ev.get("agendaId") and m.agenda_posted:
            mr = http.get(f"{base}/Meetings/{ev['agendaId']}", timeout=30)
            if mr.ok:
                m.agenda_items = flatten_items(mr.json().get("items", []))
        meetings.append(m)
    return meetings
