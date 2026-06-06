"""Author reputation lookup via the Semantic Scholar Graph API.

A paper's reputation signal is the maximum h-index / citation count among its
looked-up authors (typically the last author = PI, plus the first author).
Results are cached on disk so repeat authors aren't re-queried, which keeps us
well under Semantic Scholar's unauthenticated rate limit.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests

SEARCH_URL = "https://api.semanticscholar.org/graph/v1/author/search"
_FIELDS = "name,hIndex,citationCount,paperCount"


class Reputation:
    def __init__(self, config: dict[str, Any], cache_path: Path):
        self.enabled = bool(config.get("enabled", True))
        self.h_threshold = int(config.get("h_index_threshold", 40))
        self.cite_threshold = int(config.get("citation_threshold", 8000))
        self.check_authors = config.get("check_authors", ["last", "first"])
        self.curated = [str(s).lower() for s in config.get("curated_reputable", [])]
        self.cache_path = cache_path
        self.cache: dict[str, Any] = {}
        if cache_path.exists():
            try:
                self.cache = json.loads(cache_path.read_text())
            except json.JSONDecodeError:
                self.cache = {}
        self._api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")

    def save_cache(self) -> None:
        self.cache_path.write_text(json.dumps(self.cache, indent=2, sort_keys=True))

    def _lookup(self, name: str) -> dict[str, Any] | None:
        key = name.strip().lower()
        if key in self.cache:
            return self.cache[key]

        headers = {"x-api-key": self._api_key} if self._api_key else {}
        result: dict[str, Any] | None = None
        for attempt in range(4):
            try:
                resp = requests.get(
                    SEARCH_URL,
                    params={"query": name, "fields": _FIELDS, "limit": 1},
                    headers=headers,
                    timeout=20,
                )
                if resp.status_code == 429:
                    time.sleep(3 * (attempt + 1))
                    continue
                resp.raise_for_status()
                data = resp.json().get("data", [])
                if data:
                    a = data[0]
                    result = {
                        "name": a.get("name"),
                        "h_index": a.get("hIndex"),
                        "citations": a.get("citationCount"),
                        "papers": a.get("paperCount"),
                    }
                break
            except requests.RequestException:
                time.sleep(2 * (attempt + 1))
        self.cache[key] = result
        time.sleep(1.1)  # polite spacing for the shared rate-limit pool
        return result

    def assess(self, authors: list[str], api: bool = True) -> dict[str, Any]:
        """Return reputation signal for a paper's author list.

        Set ``api=False`` to do only the (instant) curated-name check and skip the
        Semantic Scholar lookups. Useful for core-topic papers that are kept
        regardless of reputation, where the h-index is cosmetic, not decisive.
        """
        if not authors:
            return {"reputable": False, "max_h_index": None, "max_citations": None,
                    "top_author": None, "reason": "no authors"}

        # Curated list is a hard yes — covers brand-new authors S2 hasn't indexed
        # and avoids name-disambiguation misses for famous PIs.
        for a in authors:
            al = a.lower()
            for c in self.curated:
                if c in al:
                    return {"reputable": True, "max_h_index": None, "max_citations": None,
                            "top_author": a, "reason": f"curated ({a})"}

        if not self.enabled or not api:
            return {"reputable": False, "max_h_index": None, "max_citations": None,
                    "top_author": None, "reason": "reputation disabled" if not self.enabled else "not checked"}

        targets: list[str] = []
        if "last" in self.check_authors and authors:
            targets.append(authors[-1])
        if "first" in self.check_authors and authors:
            targets.append(authors[0])
        targets = list(dict.fromkeys(targets))  # de-dupe, keep order

        best_h, best_cite, top = None, None, None
        for name in targets:
            info = self._lookup(name)
            if not info:
                continue
            h, c = info.get("h_index"), info.get("citations")
            if h is not None and (best_h is None or h > best_h):
                best_h, top = h, name
            if c is not None and (best_cite is None or c > best_cite):
                best_cite = c

        reputable = (best_h is not None and best_h >= self.h_threshold) or (
            best_cite is not None and best_cite >= self.cite_threshold
        )
        return {
            "reputable": reputable,
            "max_h_index": best_h,
            "max_citations": best_cite,
            "top_author": top,
            "reason": f"h-index {best_h}, citations {best_cite}",
        }
