"""Pre-RAG intent routing for cheap social/identity turns.

Greeting and identity questions do not need the full retrieved context
(or an LLM call). This cuts token cost before launch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_GREETING_TOKENS = {
    "hi",
    "hello",
    "hey",
    "thanks",
    "thank",
    "you",
    "سلام",
    "درود",
    "خوبی",
    "چطوری",
    "ممنون",
    "ممنونم",
    "مرسی",
    "صبح",
    "عصر",
    "شب",
    "بخیر",
}

_IDENTITY_RE = re.compile(
    r"""(?ix)
    (?:
        who\s+are\s+you|what\s+are\s+you|what\s+model|
        تو\s*کی\s*هستی|شما\s*کی\s*هستید|چه\s*مدلی|مدل\s*چیستی
    )
    """
)


@dataclass(frozen=True)
class RoutedReply:
    intent: str
    text: str


def _is_greeting(question: str) -> bool:
    # Keep letters/digits only; strip Latin + Arabic/Persian punctuation (incl. ؟).
    cleaned = re.sub(r"[^\w\u0621-\u06D3\s]+", " ", question, flags=re.UNICODE)
    cleaned = re.sub(r"[\u061B\u061F\u060C\u06D4]", " ", cleaned)  # ؛ ؟ ، ۔
    parts = [p.lower() for p in cleaned.split() if p]
    if not parts or len(parts) > 5:
        return False
    return all(p in _GREETING_TOKENS for p in parts)


def route_intent(question: str) -> RoutedReply | None:
    """Return a canned reply for greeting/identity, else None (use RAG)."""
    q = (question or "").strip()
    if not q:
        return None

    if _is_greeting(q):
        if re.search(r"[\u0600-\u06FF]", q):
            return RoutedReply(
                intent="greeting",
                text="سلام، ممنونم! خوبم و آماده‌ام کمکتون کنم. بگید روی کدوم فرآیند یا فرم کار می‌کنید.",
            )
        return RoutedReply(
            intent="greeting",
            text="Hi — thanks for reaching out. Tell me which MIDHCO process or form you're working on and I'll help.",
        )

    if _IDENTITY_RE.search(q) and len(q) < 80:
        if re.search(r"[\u0600-\u06FF]", q):
            return RoutedReply(
                intent="identity",
                text="من دستیار هوشمند میدکو هستم. بگید روی کدام فرآیند یا فرم کار می‌کنید تا راهنمایی کنم.",
            )
        return RoutedReply(
            intent="identity",
            text="I'm the MIDHCO smart assistant. Tell me which MIDHCO process or form you're working on and I'll help.",
        )

    return None
