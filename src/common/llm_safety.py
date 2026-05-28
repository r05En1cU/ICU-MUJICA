from __future__ import annotations

import re
from typing import Any, Mapping


COT_FIELD_NAMES = {
    "chain_of_thought",
    "cot",
    "internal_monologue",
    "reasoning",
    "reasoning_content",
    "thoughts",
    "thinking",
}

_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think>\s*", re.IGNORECASE | re.DOTALL)
_UNCLOSED_THINK_RE = re.compile(r"<think\b[^>]*>.*\Z", re.IGNORECASE | re.DOTALL)
_REASONING_FENCE_RE = re.compile(
    r"```(?:think|thought|thoughts|reasoning|cot)\s*.*?```\s*",
    re.IGNORECASE | re.DOTALL,
)


def strip_visible_cot(text: str) -> str:
    """Remove model-visible reasoning blocks while keeping the final answer text."""
    cleaned = _THINK_BLOCK_RE.sub("", text)
    cleaned = _UNCLOSED_THINK_RE.sub("", cleaned)
    cleaned = _REASONING_FENCE_RE.sub("", cleaned)
    return cleaned.strip()


def sanitize_llm_message(message: Mapping[str, Any]) -> dict[str, Any]:
    """Return a transcript-safe chat message without provider reasoning fields."""
    sanitized: dict[str, Any] = {}
    for key, value in message.items():
        if key in COT_FIELD_NAMES:
            continue
        if key == "content" and isinstance(value, str):
            sanitized[key] = strip_visible_cot(value)
            continue
        if key == "role":
            sanitized[key] = value
    return sanitized