"""ScraperAPI adapter — fetch Cloudflare-protected pages the plain session can't.

Perry's CivicPlus site sits behind a Cloudflare managed challenge: every meeting
page and agenda PDF returns a JS challenge to non-browser clients, from any IP.
Only the /calendar feeds are challenge-exempt. ScraperAPI solves the challenge
(JS execution + fingerprinting) and returns the real page.

ScraperApiSession mimics the slice of requests.Session the Perry source uses:
.get(url, timeout=...) returning an object with .status_code, .ok, .text,
.content and .raise_for_status(). It is used only for the Cloudflare-locked
resources (meeting pages, agenda PDFs); the free /calendar feed is fetched with
the normal session. Selected only when the source config asks for it AND
SCRAPERAPI_KEY is set, so local runs and tests fall back untouched.

Docs: GET https://api.scraperapi.com/?api_key=KEY&url=<target>&render=true
returns the target body directly. render=true runs the challenge JS (needed for
HTML pages); PDFs are fetched with render=false. ultra_premium=true is the
heavier anti-bot tier, enabled from config when the default doesn't clear CF.
"""
from __future__ import annotations

import os

import requests

API = "https://api.scraperapi.com/"


class ScraperResponse:
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
                f"{self.status_code} Error for url (via ScraperAPI)")


class ScraperApiSession:
    def __init__(self, token: str, ultra_premium: bool = False, timeout: int = 70):
        self.token = token
        self.ultra_premium = ultra_premium
        self.timeout = timeout
        self.api = requests.Session()

    def get(self, url: str, timeout: int | None = None, **_) -> ScraperResponse:
        # PDFs are binary: don't run the HTML renderer on them, but still route
        # through the anti-bot proxy so Cloudflare is cleared.
        binary = "/media/" in url or url.lower().endswith(".pdf")
        params = {
            "api_key": self.token,
            "url": url,
            "render": "false" if binary else "true",
        }
        if self.ultra_premium:
            params["ultra_premium"] = "true"
        r = self.api.get(API, params=params, timeout=timeout or self.timeout)
        return ScraperResponse(r.status_code, r.content)


def session_for(cfg: dict) -> ScraperApiSession | None:
    """Return a ScraperApiSession if this source is configured for it and a
    token is available, else None (caller uses the normal session)."""
    c = cfg.get("scraperapi")
    if not c:
        return None
    token = os.environ.get("SCRAPERAPI_KEY")
    if not token:
        return None
    ultra = bool(c.get("ultra_premium")) if isinstance(c, dict) else False
    return ScraperApiSession(token=token, ultra_premium=ultra)
