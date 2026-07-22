"""Simulated retrieval: load chunks from context.yaml and render the <context> block.

Retrieval is assumed to have already happened — the YAML file *is* the
"semantic search result". The user edits it freely to test how the prompt
behaves with different evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import yaml

from .config import ConfigError


@dataclass
class Chunk:
    """One simulated retrieved chunk with its metadata."""

    id: int
    text: str
    title: str = ""
    type: str = ""
    section: str = ""
    date: str = ""
    url: str = ""


def load_chunks(path: Path) -> list[Chunk]:
    if not path.exists():
        raise ConfigError(f"Context file not found: {path}\nRun `prompt-lab init` first.")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = raw.get("chunks") or []
    if not isinstance(items, list):
        raise ConfigError(f"'chunks' in {path.name} must be a list.")

    chunks: list[Chunk] = []
    for i, item in enumerate(items, start=1):
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            raise ConfigError(f"Chunk #{i} in {path.name} is missing a 'text' field.")
        chunks.append(
            Chunk(
                id=int(item.get("id", i)),
                text=str(item["text"]).strip(),
                title=str(item.get("title", "")),
                type=str(item.get("type", "")),
                section=str(item.get("section", "")),
                date=str(item.get("date", "")),
                url=str(item.get("url", "")),
            )
        )

    ids = [c.id for c in chunks]
    if len(ids) != len(set(ids)):
        raise ConfigError(f"Duplicate chunk ids in {path.name}; ids must be unique.")
    return chunks


def render_context_block(chunks: list[Chunk]) -> str:
    """Render chunks as the XML <context> block (escaped so text can't break tags)."""
    if not chunks:
        return "<context>\n</context>"

    parts = ["<context>"]
    for chunk in chunks:
        attrs = [f"id={quoteattr(str(chunk.id))}"]
        for name in ("title", "type", "section", "date", "url"):
            value = getattr(chunk, name)
            if value:
                attrs.append(f"{name}={quoteattr(value)}")
        parts.append(f'  <document {" ".join(attrs)}>')
        parts.append("    " + escape(chunk.text).replace("\n", "\n    "))
        parts.append("  </document>")
    parts.append("</context>")
    return "\n".join(parts)
