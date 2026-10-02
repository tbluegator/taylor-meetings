"""Parser and pipeline tests against samples captured from the live sources on 2026-10-01.
If a source changes its format, the matching test here is the first thing to update."""
import datetime as dt
import json
import pathlib

import yaml

from tracker import build, topics
from tracker.models import TZ
from tracker.offline import FixtureSession
from tracker.sources import boarddocs, civicclerk, perry, recurring

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
LIVE_CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
# Tests exercise every source, even ones paused in the live config.
CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
for _s in CFG["sources"]:
    _s.pop("enabled", None)
SRC = {s["id"]: s for s in CFG["sources"]}
START, END = dt.date(2026, 8, 2), dt.date(2026, 12, 15)


def test_civicclerk_times_are_local_and_files_link():
    ms = civicclerk.fetch(SRC["bocc"], START, END, http=FixtureSession(FIX))
    oct5 = next(m for m in ms if m.id == "bocc:147")
    assert oct5.start == "2026-10-05T18:00:00-04:00"          # "Z" in the API is really local time
    assert [d.label for d in oct5.documents] == ["Agenda", "Agenda Packet"]
    assert "GetMeetingFileStream(fileId=617" in oct5.documents[0].url
    vab = next(m for m in ms if m.id == "bocc:212")
    assert vab.body_short == "VAB"
    budget = next(m for m in ms if m.id == "bocc:210")
    assert budget.start.startswith("2026-09-14T17:01")          # TRIM hearing after 5 pm


def test_civicclerk_agenda_items_flatten_and_clean():
    ms = civicclerk.fetch(SRC["bocc"], START, END, http=FixtureSession(FIX))
    sep22 = next(m for m in ms if m.id == "bocc:159")
    first = sep22.agenda_items[0]
    assert (first.section, first.number, first.text) == ("AGENDA", "1", "Prayer")   # HTML span stripped
    item11 = next(i for i in sep22.agenda_items if i.number == "11")
    assert "​" not in item11.text
    assert sep22.video_url.endswith(".mp4")


def test_unpublished_agenda_is_not_shown():
    ms = civicclerk.fetch(SRC["bocc"], START, END, http=FixtureSession(FIX))
    sep29 = next(m for m in ms if m.id == "bocc:172")
    assert not sep29.agenda_posted and sep29.agenda_items == []


def test_boarddocs_list_and_agenda():
    ms = boarddocs.fetch(SRC["school"], START, END, http=FixtureSession(FIX))
    oct6 = next(m for m in ms if m.id == "school:DYCP6Y63285C")
    assert oct6.start == "2026-10-06T17:15:00-04:00"
    assert oct6.location.endswith("Perry FL")
    assert oct6.agenda_posted
    salary = next(i for i in oct6.agenda_items if i.number == "12.26")
    assert salary.section == "Personnel" and salary.text == "Approval of Salary Schedule"


def test_boarddocs_parse_time():
    # Normal 12-hour times.
    assert boarddocs.parse_time("Perry FL5:15 p.m.") == (17, 15)
    assert boarddocs.parse_time("starts 9 a.m.") == (9, 0)
    assert boarddocs.parse_time("noon 12 p.m.") == (12, 0)
    assert boarddocs.parse_time("midnight 12 a.m.") == (0, 0)
    # No time -> default.
    assert boarddocs.parse_time("no time listed") == (17, 15)
    # Malformed hours must fall back, not overflow past 23 (the live crash).
    assert boarddocs.parse_time("Perry FL 13:00 p.m.") == (17, 15)
    assert boarddocs.parse_time("Meeting at 17:15 p.m.") == (17, 15)
    # Every result must be a valid time of day.
    for desc in ["5:15 p.m.", "13:00 pm", "99 pm", "12 a.m.", ""]:
        h, mnt = boarddocs.parse_time(desc)
        dt.datetime(2026, 1, 1, h, mnt, tzinfo=TZ)


PERRY_NOW = dt.datetime(2026, 10, 1, 21, 0, tzinfo=TZ)   # matches the fixture capture


def test_perry_finds_special_meeting_via_feed():
    fix = FixtureSession(FIX)
    ms = perry.fetch(SRC["perry"], START, END, http=fix, page_solver=fix, pdf_solver=fix, now=PERRY_NOW)
    ids = {m.id for m in ms}
    assert "perry:20260910" in ids        # a Thursday, off the regular schedule
    assert "perry:20260908" not in ids    # regular date not in the feed, not invented


def test_perry_feed_only_without_solver():
    # No page solver (no API key): still lists the schedule from the feed, no agendas.
    ms = perry.fetch(SRC["perry"], START, END, http=FixtureSession(FIX), page_solver=None)
    sep22 = next(m for m in ms if m.id == "perry:20260922")
    assert sep22.url.endswith("city-council-meeting-20260922")
    assert sep22.agenda_items == [] and not sep22.agenda_posted


def test_perry_documents_and_agenda_pdf():
    fix = FixtureSession(FIX)
    ms = perry.fetch(SRC["perry"], START, END, http=fix, page_solver=fix, pdf_solver=fix, now=PERRY_NOW)
    sep22 = next(m for m in ms if m.id == "perry:20260922")
    labels = [d.label for d in sep22.documents]
    assert labels == ["Agenda Packet (Dropbox)", "Agenda"]
    nums = [i.number for i in sep22.agenda_items]
    assert nums[:3] == ["1", "2", "3A"] and "6(P)" in nums and nums[-1] == "10"
    millage = next(i for i in sep22.agenda_items if i.number == "6(D)")
    assert "Final Millage" in millage.text and "FISCAL YEAR OPERATION" in millage.text
    assert not any("political forum" in i.text for i in sep22.agenda_items)   # boilerplate skipped
    aug11 = next(m for m in ms if m.id == "perry:20260811")
    assert aug11.documents[0].label == "Agenda"


def test_recurring_third_thursday():
    ms = recurring.fetch(SRC["tcda"], dt.date(2026, 10, 1), dt.date(2026, 11, 30))
    assert [m.start[:10] for m in ms] == ["2026-10-15", "2026-11-19"]


def test_topics_tag_data_center_consent_item():
    ms = civicclerk.fetch(SRC["bocc"], START, END, http=FixtureSession(FIX))
    topics.tag(ms, CFG["topics"])
    oct5 = next(m for m in ms if m.id == "bocc:147")
    item13 = next(i for i in oct5.agenda_items if i.number == "13")
    assert "Data centers" in item13.topics and "Taxes & reserves" in item13.topics
    assert item13.section == "CONSENT ITEMS"


def test_full_build_and_watchdog(tmp_path):
    now = dt.datetime(2026, 10, 1, 21, 0, tzinfo=TZ)
    code = build.run(CFG, now, FixtureSession(FIX), tmp_path / "data", tmp_path / "site")
    assert code == 0
    for f in ["index.html", "feed.xml", "meetings.ics", "meetings.json"]:
        assert (tmp_path / "site" / f).exists()
    html = (tmp_path / "site" / "index.html").read_text()
    assert "On upcoming agendas: watched topics" in html and "46,508.00" in html
    ics = (tmp_path / "site" / "meetings.ics").read_bytes()
    assert b"\r\n" in ics and all(len(l) <= 75 for l in ics.split(b"\r\n"))

    # Second run where the county source breaks: history is kept and the run fails loudly.
    class Broken(FixtureSession):
        def get(self, url, **kw):
            if "civicclerk" in url:
                raise ConnectionError("county API down")
            return super().get(url, **kw)
    code = build.run(CFG, now, Broken(FIX), tmp_path / "data", tmp_path / "site")
    assert code == 1
    data = json.loads((tmp_path / "data" / "meetings.json").read_text())
    assert any(m["id"] == "bocc:147" for m in data["meetings"])
    status = json.loads((tmp_path / "data" / "status.json").read_text())
    assert status["sources"]["bocc"]["ok"] is False and status["sources"]["bocc"]["last_ok"]


def test_watchdog_flags_parser_drift(tmp_path):
    """If Perry's pages stop yielding agenda links, the run should fail, not go quiet."""
    class NoLinks(FixtureSession):
        def get(self, url, **kw):
            r = super().get(url, **kw)
            if "/meeting/" in url and r.ok:
                r.text = r.text.replace("/media/", "/moved/")
            return r
    now = dt.datetime(2026, 10, 1, 21, 0, tzinfo=TZ)
    code = build.run(CFG, now, NoLinks(FIX), tmp_path / "data", tmp_path / "site")
    status = json.loads((tmp_path / "data" / "status.json").read_text())
    assert code == 1
    assert any(p["source"] == "perry" and p["level"] == "error" for p in status["problems"])


def test_paused_source_is_skipped_quietly(tmp_path):
    """A source with enabled: false is not fetched, not health-checked, and not shown."""
    import copy
    cfg = copy.deepcopy(CFG)
    next(s for s in cfg["sources"] if s["id"] == "perry")["enabled"] = False

    class NoPerry(FixtureSession):
        def get(self, url, **kw):
            assert "cityofperry" not in url, "paused source was fetched"
            return super().get(url, **kw)
    now = dt.datetime(2026, 10, 1, 21, 0, tzinfo=TZ)
    code = build.run(cfg, now, NoPerry(FIX), tmp_path / "data", tmp_path / "site")
    assert code == 0
    status = json.loads((tmp_path / "data" / "status.json").read_text())
    assert status["sources"]["perry"]["paused"] is True
    assert not any(p["source"] == "perry" for p in status["problems"])
    data = json.loads((tmp_path / "data" / "meetings.json").read_text())
    assert not any(m["source"] == "perry" for m in data["meetings"])
    html = (tmp_path / "site" / "index.html").read_text()
    assert "Paused" in html and 'id="f-perry"' not in html
