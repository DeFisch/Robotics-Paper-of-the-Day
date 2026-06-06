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
- `llm.backend` — `claude_cli` (uses Claude Code on your subscription, no API
  credits) or `api` (uses the Anthropic API + `ANTHROPIC_API_KEY`).
- `llm.cli_model` — `haiku` / `sonnet` / `opus` for the `claude_cli` backend.
- `output.max_per_day` — how many papers to keep per day.

## LLM backend: subscription vs API

The scoring step runs through one of two backends, set by `llm.backend`:

- **`claude_cli` (default)** — shells out to the [Claude Code](https://claude.com/claude-code)
  CLI (`claude -p`), authenticated by your **Claude Pro/Max subscription**. No
  API credits are spent. The daily run uses Haiku (`llm.cli_model`) to stay light
  on subscription usage limits.
- **`api`** — calls the Anthropic API with `ANTHROPIC_API_KEY` (pay-as-you-go).

## Running locally

```bash
pip install -r requirements.txt

# claude_cli backend — install Claude Code and log in (or set CLAUDE_CODE_OAUTH_TOKEN)
npm install -g @anthropic-ai/claude-code
python -m pipeline.run

# Preview candidates without the LLM (no auth required)
python -m pipeline.run --no-llm --limit 80 --dry-run
```

## Automation

`.github/workflows/daily.yml` runs the pipeline daily at 13:00 UTC, commits the
updated `data/papers.json`, and GitHub Pages serves the site. It installs Claude
Code and runs the `claude_cli` backend.

**Required repo secret (for `claude_cli`):** `CLAUDE_CODE_OAUTH_TOKEN` — generate
it locally with `claude setup-token` (needs a Pro/Max plan), then add it under
Settings → Secrets and variables → Actions.

**If you switch to `backend: api`:** set `ANTHROPIC_API_KEY` instead. Optional:
`SEMANTIC_SCHOLAR_API_KEY` for higher reputation-lookup rate limits.
