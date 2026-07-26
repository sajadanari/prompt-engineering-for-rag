"""Assemble the final message list from the workspace files.

Canonical RAG layout sent as a single user message:

  <prompt>
    <system>…system_prompt + optional few-shot…</system>
    <context>…retrieved documents…</context>
    <reminder>…optional reinforcement…</reminder>
    <user>…live question…</user>
  </prompt>
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from .config import Config
from .context import load_chunks, render_context_block


def _read_optional(path: Path) -> str:
    """Read a prompt file; empty/missing file means the block is skipped."""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _unwrap_tag(text: str, tag: str) -> str:
    """Strip a single outer <tag>…</tag> if the file already wraps itself."""
    text = text.strip()
    open_t, close_t = f"<{tag}>", f"</{tag}>"
    if text.startswith(open_t) and text.endswith(close_t):
        return text[len(open_t) : -len(close_t)].strip()
    return text


def _wrap_section(tag: str, body: str) -> str:
    return f"<{tag}>\n{body.strip()}\n</{tag}>"


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

    system_parts = [_unwrap_tag(system_prompt, "system")]
    few_shot = _read_optional(config.lang_file("few_shot"))
    if few_shot:
        system_parts.append(few_shot)

    chunks = load_chunks(config.lang_file("context")) if include_context else []
    context_block = render_context_block(chunks)  # already <context>…</context>

    sections = [
        _wrap_section("system", "\n\n".join(system_parts)),
        context_block,
    ]

    reminder = _read_optional(config.lang_file("reminder"))
    if reminder:
        sections.append(_wrap_section("reminder", _unwrap_tag(reminder, "reminder")))

    sections.append(_wrap_section("user", escape(question)))

    body = "\n\n".join(sections)
    return [
        {"role": "user", "content": f"<prompt>\n{body}\n</prompt>"},
    ]
