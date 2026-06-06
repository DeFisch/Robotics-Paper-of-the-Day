# 🤖 Robotics Paper of the Day

A bot that scrapes newly published arXiv robotics papers every day, filters out
the irrelevant/trivial ones, and publishes the best to a webpage.

**Live site:** enable GitHub Pages (Settings → Pages → Deploy from branch → `main` / root).

## How the filter works (hybrid)

1. **Scrape** — pull recently submitted `cs.RO` papers from the arXiv API.
2. **Keyword tag** — tag each paper with topic groups from `config.yaml`
   (VLA / robot policy, table-top manipulation, perception, general robotics).
3. **Reputation pre-filter** — look up author h-index / citation count via the
   [Semantic Scholar API](https://api.semanticscholar.org) (cached in
   `data/author_cache.json`), plus a curated list of well-known PIs.
   - **Core-topic** papers (VLA / manipulation) are kept as candidates on topic alone.
   - **Non-core** robotics (perception, locomotion, etc.) is kept **only if** written
     by a reputable author. ← your rule.
4. **LLM scoring** — Claude reads each candidate's title + abstract and scores
   `relevance`, `quality`, `novelty` (1–10) with a one-line reason. Papers below the
   thresholds in `config.yaml` are dropped.
5. **Rank & publish** — survivors are ranked, capped per day, and merged into
   `data/papers.json`, which the static site renders.

## Tuning the criteria

Everything lives in **`config.yaml`** — no code changes needed:

- `topics` — keyword groups and which are `core`.
- `reputation.h_index_threshold` / `citation_threshold` — the reputable-author bar.
- `reputation.curated_reputable` — always-include PI names.
- `llm.core_min_relevance` / `broad_min_relevance` / `min_quality` — inclusion bar.
- `llm.model` — `claude-haiku-4-5-20251001` (cheap) or `claude-sonnet-4-6` (sharper).
- `output.max_per_day` — how many papers to keep per day.

## Running locally

```bash
pip install -r requirements.txt

# Full run (needs an Anthropic API key for LLM scoring)
export ANTHROPIC_API_KEY=sk-ant-...
python -m pipeline.run

# Preview candidates without the LLM (no key required)
python -m pipeline.run --no-llm --limit 80 --dry-run
```

## Automation

`.github/workflows/daily.yml` runs the pipeline daily at 13:00 UTC, commits the
updated `data/papers.json`, and GitHub Pages serves the site.

**Required repo secret:** `ANTHROPIC_API_KEY` (Settings → Secrets and variables →
Actions). Optional: `SEMANTIC_SCHOLAR_API_KEY` for higher reputation-lookup rate limits.
