"""Bright Data Web Unlocker adapter.

Some sites (Perry's CivicPlus site) return 403 to the GitHub Actions runner's
datacenter IP no matter the headers. Web Unlocker routes the request through a
non-blocked IP and returns the page.

UnlockerSession mimics the small slice of requests.Session that the Perry
source uses: a .get(url, timeout=...) that returns an object with
.status_code, .ok, .text, .content and .raise_for_status(). It is selected
only when a source sets `unlocker: {zone: ...}` in config AND the
BRIGHTDATA_API_KEY env var is present, so local runs and tests fall back to the
normal session untouched.

Docs: POST https://api.brightdata.com/request with {zone, url, format:"raw"},
which returns the target page body directly (HTML or PDF bytes).
"""
from __future__ import annotations

import os
import sys

import requests

API = "https://api.brightdata.com/request"


class UnlockerResponse:
    def __init__(self, status_code: int, content: bytes):
        self.status_code = status_code
        self.content = content

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"{self.status_code} Client Error for url (via Web Unlocker)")


class UnlockerSession:
    def __init__(self, zone: str, token: str, timeout: int = 60):
        self.zone = zone
        self.timeout = timeout
        self._dumped = 0
        self.api = requests.Session()
        self.api.headers["Authorization"] = f"Bearer {token}"

    def get(self, url: str, timeout: int | None = None, **_) -> UnlockerResponse:
        # format=raw returns the target page body directly (bytes), which is the
        # documented primary pattern and avoids guessing a JSON wrapper shape.
        payload = {"zone": self.zone, "url": url, "format": "raw"}
        r = self.api.post(API, json=payload, timeout=timeout or self.timeout)
        # A non-2xx from the API itself (bad key, bad zone) is a real failure.
        r.raise_for_status()
        # One-time verbose dump of the first couple of responses, so the Actions
        # log shows exactly what Bright Data returns if something looks wrong.
        if self._dumped < 2:
            self._dumped += 1
            ctype = r.headers.get("content-type", "?")
            preview = r.text[:200].replace("\n", " ")
            print(f"[unlocker:dump] api_status={r.status_code} ctype={ctype} "
                  f"len={len(r.content)} preview={preview!r}", file=sys.stderr)
        resp = UnlockerResponse(r.status_code, r.content)
        low = resp.content[:300000].lower()
        has_media = "Y" if b"/media/" in low else "N"
        has_agenda = "Y" if b"agenda" in low else "N"
        print(f"[unlocker] {resp.status_code} {len(resp.content):>7}B "
              f"media={has_media} agenda={has_agenda}  {url}", file=sys.stderr)
        return resp


def session_for(cfg: dict) -> UnlockerSession | None:
    """Return an UnlockerSession if this source is configured for it and a
    token is available, else None (caller uses the normal session)."""
    u = cfg.get("unlocker")
    if not u:
        return None
    token = os.environ.get("BRIGHTDATA_API_KEY")
    if not token:
        return None
    zone = u.get("zone") if isinstance(u, dict) else str(u)
    if not zone:
        return None
    return UnlockerSession(zone=zone, token=token)
