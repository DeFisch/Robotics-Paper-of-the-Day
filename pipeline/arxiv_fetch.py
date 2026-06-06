"""Fetch recently submitted arXiv papers for the configured categories."""

from __future__ import annotations

import datetime as dt
import re
import time
from typing import Any

import feedparser
import requests

API_URL = "https://export.arxiv.org/api/query"
_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})")


def _arxiv_id(entry_id: str) -> str:
    """Extract the bare arXiv id (e.g. 2506.01234) from an entry id URL."""
    m = _ARXIV_ID_RE.search(entry_id)
    return m.group(1) if m else entry_id.rsplit("/", 1)[-1]


def fetch_recent(categories: list[str], lookback_days: int, max_results: int) -> list[dict[str, Any]]:
    """Return papers submitted within `lookback_days`, newest first.

    arXiv has no submissions on weekends, so a small lookback window avoids
    empty days. Cross-listed papers are included as long as the entry carries
    one of the requested categories.
    """
    cat_query = " OR ".join(f"cat:{c}" for c in categories)
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=lookback_days)

    papers: list[dict[str, Any]] = []
    seen: set[str] = set()
    page_size = 100

    for start in range(0, max_results, page_size):
        params = {
            "search_query": cat_query,
            "start": start,
            "max_results": min(page_size, max_results - start),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        resp = requests.get(API_URL, params=params, timeout=30)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        if not feed.entries:
            break

        page_had_recent = False
        for e in feed.entries:
            published = _parse_dt(e.get("published"))
            if published is None:
                continue
            if published < cutoff:
                continue
            page_had_recent = True

            aid = _arxiv_id(e.id)
            if aid in seen:
                continue
            seen.add(aid)

            categories_list = [t["term"] for t in e.get("tags", []) if t.get("term")]
            papers.append(
                {
                    "id": aid,
                    "title": _clean(e.title),
                    "authors": [a.name for a in e.get("authors", [])],
                    "abstract": _clean(e.get("summary", "")),
                    "url": f"https://arxiv.org/abs/{aid}",
                    "pdf": f"https://arxiv.org/pdf/{aid}",
                    "published": published.date().isoformat(),
                    "primary_category": e.get("arxiv_primary_category", {}).get("term", ""),
                    "categories": categories_list,
                }
            )

        # Entries come newest-first; once a whole page is older than the cutoff
        # we can stop paging.
        if not page_had_recent and start > 0:
            break
        time.sleep(3)  # be polite to the arXiv API

    return papers


def _parse_dt(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()
