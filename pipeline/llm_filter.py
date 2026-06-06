"""LLM relevance/quality scoring of candidate papers.

Two backends, selected by `llm.backend` in config.yaml:
  - "claude_cli": shells out to the Claude Code CLI (`claude -p`), authenticated
    by your Claude subscription via CLAUDE_CODE_OAUTH_TOKEN. No API credits.
  - "api": uses the Anthropic API via the `anthropic` SDK + ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
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


def _build_user(paper: dict[str, Any]) -> str:
    rep = paper.get("reputation", {})
    return (
        f"Title: {paper['title']}\n"
        f"Authors: {', '.join(paper.get('authors', [])[:8])}\n"
        f"Topic tags: {', '.join(paper.get('topic_tags', [])) or 'none'}\n"
        f"Author reputation: {rep.get('reason', 'unknown')} "
        f"(reputable={rep.get('reputable')})\n\n"
        f"Abstract: {paper['abstract']}"
    )


def _parse_json(text: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


class Scorer:
    """Scores papers through the configured backend."""

    def __init__(self, cfg: dict[str, Any]):
        self.backend = cfg.get("backend", "api")
        self.model = cfg.get("model")
        self.cli_model = cfg.get("cli_model")
        self._client = None
        if self.backend == "api" and os.environ.get("ANTHROPIC_API_KEY"):
            import anthropic

            self._client = anthropic.Anthropic()

    def available(self) -> bool:
        if self.backend == "api":
            return self._client is not None
        return shutil.which("claude") is not None

    def score(self, paper: dict[str, Any]) -> dict[str, Any] | None:
        if self.backend == "api":
            return self._score_api(paper)
        return self._score_cli(paper)

    def _score_api(self, paper: dict[str, Any]) -> dict[str, Any] | None:
        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=400,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": _build_user(paper)}],
            )
            return _parse_json(resp.content[0].text)
        except Exception as exc:  # noqa: BLE001 - keep the daily run resilient
            print(f"  ! API scoring failed for {paper['id']}: {exc}")
            return None

    def _score_cli(self, paper: dict[str, Any]) -> dict[str, Any] | None:
        prompt = (
            f"{SYSTEM_PROMPT}\n\n{_build_user(paper)}\n\n"
            "Return ONLY the JSON object, nothing else."
        )
        cmd = ["claude", "-p", prompt, "--output-format", "json"]
        if self.cli_model:
            cmd += ["--model", str(self.cli_model)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if proc.returncode != 0:
                print(f"  ! claude CLI failed for {paper['id']}: {proc.stderr.strip()[:200]}")
                return None
            envelope = json.loads(proc.stdout)
            if not isinstance(envelope, dict) or envelope.get("is_error"):
                return None
            return _parse_json(envelope.get("result", ""))
        except Exception as exc:  # noqa: BLE001 - keep the daily run resilient
            print(f"  ! claude CLI scoring failed for {paper['id']}: {exc}")
            return None
