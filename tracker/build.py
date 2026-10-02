"""Run every source, merge with history, check health, and render the site.

    python -m tracker.build                 # live run (what GitHub Actions does)
    python -m tracker.build --offline tests/fixtures --today 2026-10-01   # from saved samples
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import traceback

import yaml

from . import health, render, topics
from .models import TZ, Meeting, browser_session, session
from .sources import boarddocs, civicclerk, perry, recurring, youtube

FETCHERS = {
    "civicclerk": civicclerk.fetch,
    "boarddocs": boarddocs.fetch,
    "perry_civicplus": perry.fetch,
    "recurring": recurring.fetch,
}
ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_previous(path: pathlib.Path) -> dict[str, Meeting]:
    if not path.exists():
        return {}
    return {d["id"]: Meeting.from_dict(d) for d in json.loads(path.read_text())["meetings"]}


def run(cfg: dict, now: dt.datetime, http, data_dir: pathlib.Path, site_dir: pathlib.Path) -> int:
    start = (now - dt.timedelta(days=cfg["window"]["past_days"])).date()
    end = (now + dt.timedelta(days=cfg["window"]["future_days"])).date()
    previous = load_previous(data_dir / "meetings.json")
    stamp = now.isoformat(timespec="minutes")

    fresh: dict[str, Meeting] = {}
    status: dict[str, dict] = {}
    for src in cfg["sources"]:
        if src.get("enabled", True) is False:
            status[src["id"]] = {"ok": True, "paused": True, "count": 0, "checked": stamp}
            continue
        try:
            src_http = browser_session() if src.get("browser") and not getattr(http, "is_fixture", False) else http
            got = FETCHERS[src["type"]](src, start, end, http=src_http)
            if src.get("youtube_channel_id"):
                try:
                    youtube.attach(got, youtube.fetch_videos(src["youtube_channel_id"], http=http))
                except Exception as e:  # video is a nice-to-have; don't fail the source
                    print(f"[{src['id']}] video feed skipped: {e}", file=sys.stderr)
            for m in got:
                fresh[m.id] = m
            status[src["id"]] = {"ok": True, "count": len(got), "checked": stamp}
        except Exception as e:
            traceback.print_exc()
            last_ok = (load_status(data_dir).get(src["id"], {}) or {}).get("last_ok", "")
            status[src["id"]] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300], "checked": stamp, "last_ok": last_ok}
        else:
            status[src["id"]]["last_ok"] = stamp

    # Merge: fresh data wins; history keeps meetings that scrolled out of the window
    # or belong to a source that failed this run.
    merged: dict[str, Meeting] = dict(previous)
    for mid, m in fresh.items():
        old = previous.get(mid)
        m.first_seen = old.first_seen if old and old.first_seen else stamp
        if m.agenda_posted:
            m.agenda_first_seen = old.agenda_first_seen if old and old.agenda_first_seen else stamp
        merged[mid] = m
    # Drop future placeholders the source no longer lists (cancelled/rescheduled).
    for mid, m in list(merged.items()):
        st = status.get(m.source, {})
        if mid not in fresh and st.get("ok") and m.start_dt.date() >= now.date():
            del merged[mid]

    paused = {s["id"] for s in cfg["sources"] if s.get("enabled", True) is False}
    meetings = sorted((m for m in merged.values() if m.source not in paused), key=lambda m: m.start)
    topics.tag(meetings, cfg.get("topics", {}))
    problems = health.check(cfg, [m for m in meetings if start <= m.start_dt.date() <= end], status, now)

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "meetings.json").write_text(json.dumps(
        {"generated": stamp, "meetings": [m.to_dict() for m in meetings]}, indent=1))
    (data_dir / "status.json").write_text(json.dumps({"generated": stamp, "sources": status, "problems": problems}, indent=1))

    render.site(cfg, meetings, status, problems, now, site_dir)

    for p in problems:
        print(f"{p['level'].upper()}: {p['message']}")
    return 1 if any(p["level"] == "error" for p in problems) else 0


def load_status(data_dir: pathlib.Path) -> dict:
    p = data_dir / "status.json"
    return json.loads(p.read_text()).get("sources", {}) if p.exists() else {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--site", default=str(ROOT / "site"))
    ap.add_argument("--offline", help="serve requests from a fixtures folder instead of the internet")
    ap.add_argument("--today", help="pretend today is YYYY-MM-DD (for previews/tests)")
    a = ap.parse_args(argv)

    cfg = yaml.safe_load(pathlib.Path(a.config).read_text())
    now = dt.datetime.now(TZ)
    if a.today:
        d = dt.date.fromisoformat(a.today)
        now = dt.datetime(d.year, d.month, d.day, 21, 0, tzinfo=TZ)
    http = session()
    if a.offline:
        from .offline import FixtureSession
        http = FixtureSession(pathlib.Path(a.offline))
    return run(cfg, now, http, pathlib.Path(a.data), pathlib.Path(a.site))


if __name__ == "__main__":
    sys.exit(main())
