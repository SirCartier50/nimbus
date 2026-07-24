"""Prompt-injection detection layer (P2-1, docs/security/prompt-injection.md).

A cheap, model-independent classifier for untrusted text (user messages and,
especially, AWS tool outputs). This is a DETECTION layer, not the primary
defense — the deterministic invariants in the executor (plan-subset, managed-
only) are what actually stop an injection from acting. Detection adds signal:
log/annotate suspicious content so a weak model gets an extra "this looks like
an attack" nudge, and so we can measure injection attempts.

Design for the free-only constraint:
  * The default `HeuristicDetector` is pure-Python regex — zero dependencies,
    zero cost, runs inline. Good enough to catch the obvious "ignore previous
    instructions" family that shows up in real indirect-injection payloads.
  * `InjectionDetector` is a Protocol so a stronger free classifier can drop in
    behind the same interface without touching callers. The intended upgrade is
    **Meta Prompt Guard 2** (open 22M/86M jailbreak+injection classifier),
    served on the existing free-provider infra — see `PromptGuard2Detector`.

Nothing here blocks by itself; callers decide what to do with a verdict.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class GuardVerdict:
    flagged: bool
    score: float                       # 0.0 (clean) .. 1.0 (almost certainly injection)
    reasons: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:        # `if verdict:` reads as "is this suspicious?"
        return self.flagged


class InjectionDetector(Protocol):
    def scan(self, text: str) -> GuardVerdict: ...


# Patterns seen in real indirect-injection payloads. Each is (weight, regex,
# label); the score is the summed weight of matches, capped at 1.0. Weights are
# tuned so a single strong phrase ("ignore previous instructions") flags on its
# own, while weak individual signals need to co-occur.
_SIGNATURES: list[tuple[float, re.Pattern, str]] = [
    (0.8, re.compile(r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all)\b.{0,20}\b(instruction|prompt|rule|context|message)", re.I), "ignore-prior-instructions"),
    (0.7, re.compile(r"\bsystem\s+prompt\b", re.I), "references-system-prompt"),
    (0.6, re.compile(r"\byou\s+are\s+now\b|\bnew\s+instructions?\b|\bact\s+as\b", re.I), "role-reassignment"),
    (0.6, re.compile(r"\b(delete|destroy|terminate|drop|wipe|remove)\b.{0,20}\b(all|every|everything|each)\b", re.I), "mass-destruction-command"),
    (0.5, re.compile(r"\b(exfiltrate|leak|send|post|upload|forward)\b.{0,30}\b(credential|secret|key|token|password|data|env)", re.I), "exfil-command"),
    (0.5, re.compile(r"</?(system|assistant|instructions?|prompt)>", re.I), "fake-role-delimiter"),
    (0.4, re.compile(r"\bdo\s+not\s+tell\b|\bwithout\s+(telling|informing|asking)\b|\bdon'?t\s+mention\b", re.I), "stealth-instruction"),
    (0.4, re.compile(r"\b(curl|wget|fetch)\b.{0,40}https?://", re.I), "embedded-egress-call"),
]

_FLAG_THRESHOLD = 0.5


class HeuristicDetector:
    """Dependency-free regex detector. Conservative: tuned to catch the blatant
    injection phrasing without flagging ordinary infrastructure text."""

    def scan(self, text: str) -> GuardVerdict:
        if not text or not isinstance(text, str):
            return GuardVerdict(False, 0.0)
        score, reasons = 0.0, []
        for weight, pattern, label in _SIGNATURES:
            if pattern.search(text):
                score += weight
                reasons.append(label)
        score = min(score, 1.0)
        return GuardVerdict(score >= _FLAG_THRESHOLD, score, reasons)


class PromptGuard2Detector:
    """Seam for Meta Prompt Guard 2 (the intended free upgrade). Not wired by
    default because it needs the model served on the free-provider infra; when
    that exists, implement `scan` to call it and return its label/probability in
    the same `GuardVerdict` shape. Falls back to the heuristic until then so
    callers never have to special-case availability.

        detector = PromptGuard2Detector(endpoint=..., fallback=HeuristicDetector())
    """

    def __init__(self, endpoint=None, fallback: InjectionDetector | None = None):
        self._endpoint = endpoint
        self._fallback = fallback or HeuristicDetector()

    def scan(self, text: str) -> GuardVerdict:
        if self._endpoint is None:
            return self._fallback.scan(text)
        raise NotImplementedError(
            "Wire this to a Prompt Guard 2 endpoint on the free-provider infra "
            "(return a GuardVerdict from its jailbreak/injection probability)."
        )


# Module-level default so callers can `from utils.guard import scan`.
_DEFAULT: InjectionDetector = HeuristicDetector()


def scan(text: str) -> GuardVerdict:
    return _DEFAULT.scan(text)


def scan_tool_payload(payload) -> GuardVerdict:
    """Scan a tool-result payload (dict/list/str) for injection. Flattens the
    structure to text first, so a payload with `ignore previous instructions`
    planted in a resource name or error field is caught wherever it's nested."""
    return scan(_flatten(payload))


def _flatten(obj) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return " ".join(_flatten(v) for v in obj.values())
    if isinstance(obj, list):
        return " ".join(_flatten(v) for v in obj)
    return ""
