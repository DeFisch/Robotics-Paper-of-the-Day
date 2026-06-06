"""Daily pipeline entrypoint.

Stages: fetch arXiv -> keyword tag -> reputation pre-filter (hybrid) ->
LLM scoring on survivors -> rank & cap -> merge into data/papers.json.

Run:  python -m pipeline.run            (full run; uses ANTHROPIC_API_KEY if set)
      python -m pipeline.run --no-llm   (skip LLM; emit candidates only)
      python -m pipeline.run --limit 50 (cap fetched papers, for quick tests)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

import yaml

from . import arxiv_fetch, keyword_filter, llm_filter
from .reputation import Reputation

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PAPERS_PATH = DATA_DIR / "papers.json"
CACHE_PATH = DATA_DIR / "author_cache.json"


def load_config() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "config.yaml").read_text())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true", help="skip LLM scoring (candidates only)")
    ap.add_argument("--limit", type=int, default=None, help="cap number of fetched papers")
    ap.add_argument("--dry-run", action="store_true", help="do not write papers.json")
    args = ap.parse_args()

    cfg = load_config()
    DATA_DIR.mkdir(exist_ok=True)

    # 1. Fetch -----------------------------------------------------------------
    acfg = cfg["arxiv"]
    max_results = args.limit or acfg["max_results"]
    print(f"Fetching arXiv {acfg['categories']} (lookback {acfg['lookback_days']}d, max {max_results}) ...")
    papers = arxiv_fetch.fetch_recent(acfg["categories"], acfg["lookback_days"], max_results)
    print(f"  fetched {len(papers)} recent papers")

    # 2. Keyword tagging + focus gating ---------------------------------------
    matchers = keyword_filter.build_matchers(cfg["topics"])
    rep = Reputation(cfg["reputation"], CACHE_PATH)
    focus = cfg.get("focus", {})
    humanoid_pats = keyword_filter._compile(focus.get("humanoid_locomotion", []))
    anchor_pats = keyword_filter._compile(focus.get("manipulation_anchor", []))
    survey_pats = keyword_filter._compile(cfg.get("survey", {}).get("keywords", []))
    require_adjacent = cfg["reputation"].get("require_manipulation_adjacent", True)

    candidates: list[dict[str, Any]] = []
    dropped_offfocus = 0
    for p in papers:
        tags, is_core = keyword_filter.tag(p, matchers)
        p["topic_tags"] = tags
        p["is_core"] = is_core
        if not tags:
            continue  # nothing matched any topic group at all

        has_anchor = keyword_filter.contains(p, anchor_pats)
        is_humanoid = keyword_filter.contains(p, humanoid_pats)
        p["flags"] = ["survey"] if keyword_filter.contains(p, survey_pats) else []

        # Focus gate: drop humanoid/locomotion-dominated work that lacks a genuine
        # arm/table-top manipulation anchor (applies even to reputable authors).
        if is_humanoid and not has_anchor:
            dropped_offfocus += 1
            continue

        if is_core:
            # Core papers are kept regardless of reputation, so only the instant
            # curated-name check runs here (no Semantic Scholar API call).
            p["reputation"] = rep.assess(p["authors"], api=False)
            candidates.append(p)
        else:
            # Non-core robotics: keep only if by a reputable author AND it is
            # manipulation-adjacent (drops e.g. pure SLAM / medical by big names).
            if require_adjacent and not has_anchor:
                continue
            p["reputation"] = rep.assess(p["authors"])
            if p["reputation"].get("reputable"):
                candidates.append(p)
    rep.save_cache()
    print(f"  dropped {dropped_offfocus} off-focus (humanoid/locomotion w/o manipulation)")
    print(f"  {len(candidates)} candidates after keyword + reputation pre-filter")

    # 3. LLM scoring -----------------------------------------------------------
    lcfg = cfg["llm"]
    enabled = lcfg.get("enabled", True) and not args.no_llm
    scorer = llm_filter.Scorer(lcfg) if enabled else None
    use_llm = bool(scorer and scorer.available())
    if enabled and not use_llm:
        print(f"  ! LLM backend '{lcfg.get('backend', 'api')}' unavailable "
              f"— emitting candidates without scores")

    kept: list[dict[str, Any]] = []
    if use_llm:
        print(f"  scoring {len(candidates)} candidates via '{lcfg.get('backend', 'api')}' backend ...")
        for p in candidates:
            scores = scorer.score(p)
            p["scores"] = scores
            if not scores:
                continue
            rel, qual = scores.get("relevance", 0), scores.get("quality", 0)
            min_rel = lcfg["core_min_relevance"] if p["is_core"] else lcfg["broad_min_relevance"]
            if rel >= min_rel and qual >= lcfg["min_quality"]:
                p["verdict"] = "include"
                kept.append(p)
            else:
                p["verdict"] = "exclude"
        print(f"  {len(kept)} papers passed LLM thresholds")
    else:
        for p in candidates:
            p["scores"] = None
            p["verdict"] = "candidate"
        kept = candidates

    # 4. Rank & cap per day ----------------------------------------------------
    def sort_key(p: dict[str, Any]):
        s = p.get("scores") or {}
        return (s.get("relevance", 0), s.get("quality", 0), s.get("novelty", 0))

    kept.sort(key=sort_key, reverse=True)
    cap = cfg["output"]["max_per_day"]
    by_day: dict[str, list[dict[str, Any]]] = {}
    for p in kept:
        by_day.setdefault(p["published"], []).append(p)
    capped = [p for day in by_day.values() for p in day[:cap]]
    print(f"  {len(capped)} papers after per-day cap of {cap}")

    # 5. Merge into store ------------------------------------------------------
    store = _load_store()
    existing = {p["id"]: p for p in store["papers"]}
    new_count = 0
    for p in capped:
        if p["id"] not in existing:
            new_count += 1
        existing[p["id"]] = _slim(p)
    store["papers"] = sorted(existing.values(), key=lambda p: (p["published"], p["id"]), reverse=True)
    store["updated"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if args.dry_run:
        print(f"  [dry-run] would add {new_count} new papers (total {len(store['papers'])})")
        print(json.dumps(capped, indent=2)[:4000])
        return

    PAPERS_PATH.write_text(json.dumps(store, indent=2))
    print(f"Wrote {PAPERS_PATH} — +{new_count} new, {len(store['papers'])} total")


def _load_store() -> dict[str, Any]:
    if PAPERS_PATH.exists():
        try:
            data = json.loads(PAPERS_PATH.read_text())
            data.setdefault("papers", [])
            return data
        except json.JSONDecodeError:
            pass
    return {"updated": None, "papers": []}


def _slim(p: dict[str, Any]) -> dict[str, Any]:
    """Keep only the fields the site needs."""
    return {
        "id": p["id"],
        "title": p["title"],
        "authors": p["authors"],
        "abstract": p["abstract"],
        "url": p["url"],
        "pdf": p["pdf"],
        "published": p["published"],
        "primary_category": p.get("primary_category", ""),
        "topic_tags": p.get("topic_tags", []),
        "flags": p.get("flags", []),
        "reputation": p.get("reputation", {}),
        "scores": p.get("scores"),
        "verdict": p.get("verdict"),
    }


if __name__ == "__main__":
    main()
