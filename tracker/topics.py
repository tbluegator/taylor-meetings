"""Topic watch list: tag agenda items whose text mentions a watched phrase."""
from __future__ import annotations

import re

from .models import Meeting


def compile_topics(topics: dict[str, list[str]]) -> dict[str, re.Pattern]:
    return {name: re.compile(r"\b(" + "|".join(re.escape(p) for p in phrases) + r")", re.I)
            for name, phrases in topics.items()}


def tag(meetings: list[Meeting], topics: dict[str, list[str]]) -> None:
    pats = compile_topics(topics)
    for m in meetings:
        found = []
        for item in m.agenda_items:
            item.topics = [name for name, p in pats.items() if p.search(item.text)]
            found += [t for t in item.topics if t not in found]
        m.topics = found
