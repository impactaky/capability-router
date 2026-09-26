"""Jev (TypeSafe AI System One) client for per-item Score questions.

Contract (docs.typesafe.ai, checked 2026-09-22):
  POST https://api.typesafe.ai/v1/systemone
  Authorization: Bearer $TYPESAFE_API_KEY
  body: {"state": <task text>, "model": "jev-latest",
         "questions": {<item>: {"type": "score", "instructions": ..., "criteria": [none..high]}}}
  answer: {"type": "score", "score": float, "confidence": float,
           "probabilities": {"0": p0, "1": p1, ...}, "legend": {...}}

The router only needs, per item, the most probable level plus the
distribution for --explain. Any object with an `estimate(task) -> dict[item, AxisEstimate]`
method can stand in for the live client (see FixedLevels, FixtureJev).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import Capabilities

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"


@dataclass(frozen=True)
class AxisEstimate:
    level: str
    probabilities: dict[str, float]
    confidence: float | None
    score: float | None


class Estimator(Protocol):
    name: str

    def estimate(self, task: str) -> dict[str, AxisEstimate]: ...


def build_questions(caps: Capabilities) -> dict[str, dict]:
    """Build the Jev `questions` map from the capability definition (no model names involved).

    Each item asks its `question` (or a default built from `measures`) and lists its level
    descriptions none to high, with the level's anchor `examples` appended when it has them.
    """
    questions: dict[str, dict] = {}
    for item in caps.items.values():
        questions[item.name] = {
            "type": "score",
            "instructions": item.question_text(),
            "criteria": [item.criteria_for(lv) for lv in caps.levels],
        }
    return questions


def answer_to_estimate(caps: Capabilities, answer: dict) -> AxisEstimate:
    probs_raw = answer.get("probabilities") or {}
    probs = {caps.levels[int(k)]: float(v) for k, v in probs_raw.items() if int(k) < len(caps.levels)}
    if probs:
        level = max(probs.items(), key=lambda kv: kv[1])[0]
    elif answer.get("score") is not None:
        idx = min(len(caps.levels) - 1, max(0, round(float(answer["score"]))))
        level = caps.levels[idx]
    else:
        raise ValueError("score answer has neither probabilities nor score")
    return AxisEstimate(
        level=level,
        probabilities=probs,
        confidence=_opt(answer.get("confidence")),
        score=_opt(answer.get("score")),
    )


class JevClient:
    name = "jev"

    def __init__(
        self,
        caps: Capabilities,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.caps = caps
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "TYPESAFE_API_KEY is not set; pass --levels or --jev-fixture to route without Jev"
            )
        self.base_url = (base_url or os.environ.get("TYPESAFE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("TYPESAFE_DEFAULT_MODEL") or DEFAULT_MODEL
        self.timeout = timeout

    def request_body(self, task: str) -> dict:
        return {"state": task, "model": self.model, "questions": build_questions(self.caps)}

    def estimate(self, task: str) -> dict[str, AxisEstimate]:
        import httpx  # imported lazily so offline modes never need it

        resp = httpx.post(
            f"{self.base_url}/v1/systemone",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=self.request_body(task),
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Jev request failed: HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        answers = data.get("answers") or {}
        out: dict[str, AxisEstimate] = {}
        for axis in self.caps.items:
            if axis not in answers:
                raise RuntimeError(f"Jev response has no answer for item {axis!r}")
            out[axis] = answer_to_estimate(self.caps, answers[axis])
        return out


class FixedLevels:
    """Offline estimator: levels given on the command line (`--levels <item>=<level>,...`)."""

    name = "fixed"

    def __init__(self, caps: Capabilities, levels: dict[str, str]) -> None:
        for axis, lv in levels.items():
            if axis not in caps.items:
                raise ValueError(f"unknown item {axis!r}; known: {', '.join(caps.items)}")
            if lv not in caps.levels:
                raise ValueError(f"unknown level {lv!r} for item {axis!r}; known: {', '.join(caps.levels)}")
        self.caps = caps
        self.levels = levels

    def estimate(self, task: str) -> dict[str, AxisEstimate]:
        return {
            axis: AxisEstimate(
                level=self.levels.get(axis, "none"),
                probabilities={self.levels.get(axis, "none"): 1.0},
                confidence=None,
                score=None,
            )
            for axis in self.caps.items
        }


class FixtureJev:
    """Offline estimator replaying recorded Jev responses from a JSON file.

    Fixture format: {"<task text>": <Jev response body>, ..., "default": <Jev response body>}.
    """

    name = "fixture"

    def __init__(self, caps: Capabilities, path: Path) -> None:
        self.caps = caps
        self.fixture = json.loads(Path(path).read_text(encoding="utf-8"))

    def estimate(self, task: str) -> dict[str, AxisEstimate]:
        body = self.fixture.get(task) or self.fixture.get("default")
        if body is None:
            raise KeyError(f"fixture has no entry for task and no 'default': {task[:60]!r}")
        answers = body.get("answers") or {}
        return {axis: answer_to_estimate(self.caps, answers[axis]) for axis in self.caps.items}


def parse_levels(spec: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"bad --levels entry {item!r}; expected item=level")
        axis, lv = item.split("=", 1)
        out[axis.strip()] = lv.strip()
    return out


def _opt(v) -> float | None:
    return None if v is None else float(v)
