"""Scrapfly adapter — fetch Cloudflare-locked pages and PDFs for Perry.

Perry's CivicPlus site is behind a Cloudflare managed challenge; only the
/calendar feeds are challenge-exempt, and even those are challenged from a
datacenter IP. Scrapfly's asp=true clears the challenge (escalating to a real
browser as needed) and, unlike a plain unlocker, returns binary files too.

Response is a JSON envelope. result.content is:
  - the page text (content_encoding "utf-8") for HTML/JSON, or
  - base64 bytes (content_encoding "base64") for small binaries, or
  - a download URL (format "blob") for large binaries like agenda PDFs.
ScrapflySession.get(url) hides all that behind the small requests-like response
the Perry source expects (.status_code/.ok/.text/.content/.raise_for_status).
Selected only when the source config asks for it AND SCRAPFLY_KEY is set.
"""
from __future__ import annotations

import base64
import os

import requests

API = "https://api.scrapfly.io/scrape"


class ScrapflyResponse:
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
            raise requests.HTTPError(f"{self.status_code} Error for url (via Scrapfly)")


class ScrapflySession:
    def __init__(self, token: str, timeout: int = 150):
        self.token = token
        self.timeout = timeout
        self.api = requests.Session()

    def get(self, url: str, timeout: int | None = None, **_) -> ScrapflyResponse:
        # asp clears Cloudflare (auto-escalating to a browser); it returns both
        # HTML and binary, so no render_js is forced (keeps credit cost down).
        params = {"key": self.token, "url": url, "asp": "true", "country": "us"}
        r = self.api.get(API, params=params, timeout=timeout or self.timeout)
        r.raise_for_status()
        res = (r.json() or {}).get("result", {}) or {}
        status = int(res.get("status_code") or 200)
        content = res.get("content") or ""
        fmt = res.get("format")
        enc = res.get("content_encoding")
        if fmt == "blob":
            # Very large binary offloaded: content is a download URL (needs key).
            dl = self.api.get(content, params={"key": self.token},
                              timeout=timeout or self.timeout)
            dl.raise_for_status()
            return ScrapflyResponse(status, dl.content)
        # Binary (e.g. a PDF) comes back base64 in content with format "binary";
        # note content_encoding reports the envelope ("utf-8"), not the content.
        if fmt == "binary" or enc == "base64":
            return ScrapflyResponse(status, base64.b64decode(content))
        return ScrapflyResponse(status, content.encode("utf-8"))


def session_for(cfg: dict) -> ScrapflySession | None:
    """Return a ScrapflySession if this source is configured for it and a token
    is available, else None (caller uses the normal session)."""
    if not cfg.get("scrapfly"):
        return None
    token = os.environ.get("SCRAPFLY_KEY")
    if not token:
        return None
    return ScrapflySession(token=token)
