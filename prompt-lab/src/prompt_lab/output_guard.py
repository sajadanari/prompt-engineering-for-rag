"""Post-generation output guards for production-minded lab runs.

Prompt defenses reduce injection risk; this layer catches residual leaks
(e.g. external phishing URLs) before the user sees the response.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# http(s) URLs and common bare "visit example.com/path" phishing shapes.
_URL_RE = re.compile(
    r"""(?ix)
    (?:
        https?://[^\s<>\)\]\"']+
      | www\.[^\s<>\)\]\"']+
      | (?<![@\w])(?:[a-z0-9-]+\.)+(?:example|xyz|top|zip|mov|tk|ml|ga|cf|gq)
        (?:/[^\s<>\)\]\"']*)?
    )
    """
)

_REPLACEMENT = "[link removed]"


@dataclass(frozen=True)
class GuardResult:
    text: str
    redacted_urls: tuple[str, ...]


def sanitize_output(text: str) -> GuardResult:
    """Redact external/suspicious URLs from model output."""
    if not text:
        return GuardResult(text="", redacted_urls=())

    found: list[str] = []

    def _sub(match: re.Match[str]) -> str:
        found.append(match.group(0))
        return _REPLACEMENT

    cleaned = _URL_RE.sub(_sub, text)
    # Collapse awkward double spaces left by redaction.
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return GuardResult(text=cleaned, redacted_urls=tuple(found))
