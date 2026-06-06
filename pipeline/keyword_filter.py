"""Tag papers with topic groups from the config keyword lists."""

from __future__ import annotations

import re
from typing import Any


def _compile(keywords: list[str]) -> list[re.Pattern]:
    pats = []
    for kw in keywords:
        kw = str(kw).strip().lower()
        if not kw:
            continue
        # Word-boundary match so "grasp" doesn't fire on "telegraph".
        pats.append(re.compile(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])"))
    return pats


def build_matchers(topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"name": t["name"], "core": bool(t.get("core")), "patterns": _compile(t.get("keywords", []))}
        for t in topics
    ]


def contains(paper: dict[str, Any], patterns: list[re.Pattern]) -> bool:
    """True if any pattern matches the paper's title or abstract."""
    haystack = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()
    return any(p.search(haystack) for p in patterns)


def tag(paper: dict[str, Any], matchers: list[dict[str, Any]]) -> tuple[list[str], bool]:
    """Return (matched_topic_names, is_core)."""
    haystack = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()
    tags: list[str] = []
    is_core = False
    for m in matchers:
        if any(p.search(haystack) for p in m["patterns"]):
            tags.append(m["name"])
            if m["core"]:
                is_core = True
    return tags, is_core
