"""ScraperAPI adapter — Cloudflare-cleared HTML/JSON fetches for Perry.

Carries the frequent per-run fetches (the /calendar feed and meeting pages):
render=true clears Cloudflare and returns the page. Cheaper per call than
Scrapfly, so it handles everything except the agenda PDFs — those need
Scrapfly, whose free tier returns binary. Gated on `scraperapi` config +
SCRAPERAPI_KEY; without them the caller falls back to the normal session.
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
            raise requests.HTTPError(f"{self.status_code} Error for url (via ScraperAPI)")


class ScraperApiSession:
    def __init__(self, token: str, timeout: int = 90):
        self.token = token
        self.timeout = timeout
        self.api = requests.Session()

    def get(self, url: str, timeout: int | None = None, **_) -> ScraperResponse:
        params = {"api_key": self.token, "url": url, "render": "true"}
        r = self.api.get(API, params=params, timeout=timeout or self.timeout)
        return ScraperResponse(r.status_code, r.content)


def session_for(cfg: dict) -> ScraperApiSession | None:
    if not cfg.get("scraperapi"):
        return None
    token = os.environ.get("SCRAPERAPI_KEY")
    if not token:
        return None
    return ScraperApiSession(token=token)
