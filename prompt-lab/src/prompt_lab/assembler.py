"""Assemble the final message list from the workspace files.

Layout follows the canonical RAG prompt order (see the article in ../article/):
  system message (+ optional few-shot examples)  -> "system" role
  <context> block + reminder + question          -> "user" role
"""

from __future__ import annotations

from pathlib import Path

from .config import Config
from .context import load_chunks, render_context_block


def _read_optional(path: Path) -> str:
    """Read a prompt file; empty/missing file means the block is skipped."""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def assemble_messages(
    config: Config,
    question: str,
    include_context: bool = True,
) -> list[dict]:
    system_prompt = _read_optional(config.lang_file("system_prompt"))
    if not system_prompt:
        raise FileNotFoundError(
            f"System prompt is missing or empty: {config.lang_file('system_prompt')}"
        )

    few_shot = _read_optional(config.lang_file("few_shot"))
    if few_shot:
        system_prompt = f"{system_prompt}\n\n{few_shot}"

    chunks = load_chunks(config.lang_file("context")) if include_context else []
    context_block = render_context_block(chunks)

    user_parts = [context_block]
    reminder = _read_optional(config.lang_file("reminder"))
    if reminder:
        user_parts.append(reminder)
    user_parts.append(f"Question: {question}")

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]
