"""A stand-in for requests.Session that answers from saved sample files.
Used for tests and for building a preview without touching the live sites."""
from __future__ import annotations

import pathlib
import re
from urllib.parse import unquote


class FakeResponse:
    def __init__(self, status: int, body: bytes = b""):
        self.status_code = status
        self.content = body
        self.text = body.decode("utf-8", "replace")
        self.ok = 200 <= status < 300

    def json(self):
        import json
        return json.loads(self.text)

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code} (fixture)")


class FixtureSession:
    is_fixture = True

    def __init__(self, folder: pathlib.Path):
        self.folder = folder

    def _file(self, name: str) -> FakeResponse:
        p = self.folder / name
        return FakeResponse(200, p.read_bytes()) if p.exists() else FakeResponse(404)

    def get(self, url: str, params=None, timeout=None, **kw) -> FakeResponse:
        url = unquote(url)
        if "api.civicclerk.com" in url and url.endswith("/Events"):
            return self._file("civicclerk_events.json")
        if m := re.search(r"api\.civicclerk\.com/v1/Meetings/(\d+)$", url):
            return self._file(f"civicclerk_meeting_{m.group(1)}.json")
        if "BD-GETMeetingsListForSEO" in url:
            return self._file("boarddocs_meetings.json")
        if url.endswith("cityofperry.net/rss.xml"):
            return self._file("perry_rss.xml")
        if m := re.search(r"cityofperry\.net/media/(\d+)$", url):
            return self._file(f"media_{m.group(1)}.pdf")
        if url.rstrip("/").endswith("cityofperry.net/meetings"):
            return self._file("perry_meetings.html")
        if m := re.search(r"/meeting/[a-z-]*?(\d{8})$", url):
            return self._file(f"perry_meeting_{m.group(1)}.html")
        if "youtube.com/feeds" in url and params:
            return self._file(f"youtube_{params.get('channel_id')}.xml")
        return FakeResponse(404)

    def post(self, url: str, data=None, timeout=None, **kw) -> FakeResponse:
        if "BD-GetAgenda" in url:
            r = self._file(f"boarddocs_agenda_{(data or {}).get('id')}.html")
            return r if r.ok else FakeResponse(200, b"")
        return FakeResponse(404)
