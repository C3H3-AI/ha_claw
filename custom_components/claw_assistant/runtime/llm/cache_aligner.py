from __future__ import annotations

import hashlib
import re

_VOLATILE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"current\s+time\s+is", re.IGNORECASE),
    re.compile(r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", re.IGNORECASE),
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\b", re.IGNORECASE),
    re.compile(r"(?:online|active|exposed|available)\s*[:=]\s*\d+", re.IGNORECASE),
    re.compile(r"\b(?:now|currently|as of)\b.*\b\d", re.IGNORECASE),
    re.compile(r"uptime|last\s+seen|just\s+now|seconds?\s+ago|minutes?\s+ago",
               re.IGNORECASE),
)

_VOLATILE_TAIL_HEADER = "## Volatile Context (do not cache)"


def is_volatile_line(line: str) -> bool:
    return any(p.search(line) for p in _VOLATILE_PATTERNS)


def extract_volatile(text: str) -> tuple[str, list[str]]:
    if not text:
        return "", []
    stable: list[str] = []
    volatile: list[str] = []
    for line in text.splitlines():
        if line.strip() and is_volatile_line(line):
            volatile.append(line.strip())
        else:
            stable.append(line)
    while stable and not stable[-1].strip():
        stable.pop()
    return "\n".join(stable), volatile


def align(text: str) -> str:
    stable, volatile = extract_volatile(text)
    if not volatile:
        return text
    tail = "\n".join(volatile)
    if not stable.strip():
        return f"{_VOLATILE_TAIL_HEADER}\n{tail}"
    return f"{stable}\n\n{_VOLATILE_TAIL_HEADER}\n{tail}"


def prefix_fingerprint(text: str, *, prefix_chars: int = 4000) -> str:
    head = (text or "")[:prefix_chars]
    return hashlib.sha1(head.encode("utf-8", "replace")).hexdigest()[:16]

class CacheAligner:

    def __init__(self) -> None:
        self._last_fp: str | None = None
        self.drift_count = 0

    def check_stability(self, text: str) -> tuple[bool, str]:
        fp = prefix_fingerprint(text)
        stable = self._last_fp is None or self._last_fp == fp
        if self._last_fp is not None and not stable:
            self.drift_count += 1
        self._last_fp = fp
        return stable, fp

    def reset(self) -> None:
        self._last_fp = None
        self.drift_count = 0
