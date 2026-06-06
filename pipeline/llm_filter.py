"""LLM relevance/quality scoring of candidate papers using the Claude API."""

from __future__ import annotations

import json
import os
import re
from typing import Any

SYSTEM_PROMPT = """You are a senior robotics researcher curating a daily reading list.
You focus on: Vision-Language-Action (VLA) models and learned robot manipulation
policies; table-top manipulation with robot arms (grasping, dexterous/bimanual
manipulation, assembly, tool use); and adjacent perception/learning work when it
is high-impact. You are skeptical of incremental, vague, or over-claimed papers.
Humanoid whole-body / locomotion work that is not really about arm/table-top
manipulation should score LOW on relevance. Survey/review papers are useful but
rarely top-relevance.

Given a paper's title, abstract, topic tags, and author-reputation signal, score it.
Return ONLY a JSON object, no prose, with these integer fields (1-10) and strings:
{
  "relevance": <1-10, how relevant to VLA / robot manipulation policies & arms>,
  "quality": <1-10, methodological soundness & likely impact from the abstract>,
  "novelty": <1-10, how novel vs incremental>,
  "topic": "<short category label>",
  "reason": "<one concise sentence on why it is or isn't worth reading>"
}"""


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _client():
    import anthropic

    return anthropic.Anthropic()


def _parse_json(text: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def score(paper: dict[str, Any], model: str, client=None) -> dict[str, Any] | None:
    """Score a single paper. Returns the parsed dict or None on failure."""
    client = client or _client()
    rep = paper.get("reputation", {})
    user = (
        f"Title: {paper['title']}\n"
        f"Authors: {', '.join(paper.get('authors', [])[:8])}\n"
        f"Topic tags: {', '.join(paper.get('topic_tags', [])) or 'none'}\n"
        f"Author reputation: {rep.get('reason', 'unknown')} "
        f"(reputable={rep.get('reputable')})\n\n"
        f"Abstract: {paper['abstract']}"
    )
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
        return _parse_json(resp.content[0].text)
    except Exception as exc:  # noqa: BLE001 - keep the daily run resilient
        print(f"  ! LLM scoring failed for {paper['id']}: {exc}")
        return None
