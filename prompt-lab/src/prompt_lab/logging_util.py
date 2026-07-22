"""Write human-readable Markdown logs for API-backed prompt tests.

Logs never include API keys. Directory is gitignored (prompt-lab/logs/).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .client import ChatResult
from .config import PROJECT_ROOT, Config

LOGS_DIR = PROJECT_ROOT / "logs"


@dataclass
class RunEntry:
    """One question/response pair inside a run or batch log."""

    question: str
    messages: list[dict]
    note: str = ""
    result: ChatResult | None = None
    error: str | None = None
    elapsed: float | None = None


@dataclass
class RunLog:
    """Metadata + entries for a single log file."""

    command: str  # "run" | "batch"
    config: Config
    include_context: bool
    entries: list[RunEntry] = field(default_factory=list)


def _stamp() -> tuple[str, str]:
    """Return (filename stamp, ISO timestamp)."""
    now = datetime.now().astimezone()
    return now.strftime("%Y%m%d-%H%M%S"), now.isoformat(timespec="seconds")


def _md_escape_cell(value: object) -> str:
    text = "—" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _render_messages(messages: list[dict]) -> str:
    parts: list[str] = []
    for message in messages:
        role = message.get("role", "unknown")
        content = message.get("content") or ""
        # Fenced so nested Markdown in prompts stays literal; GUI wraps long lines.
        parts.append(f"### {role}\n\n```text\n{content.rstrip()}\n```")
    return "\n\n".join(parts)


def _render_entry(entry: RunEntry, index: int | None = None) -> str:
    title = f"## Question {index}" if index is not None else "## Question"
    blocks = [title, "", entry.question]
    if entry.note:
        blocks.extend(["", f"*Note: {entry.note}*"])

    blocks.extend(["", "## Assembled prompt", "", _render_messages(entry.messages)])

    if entry.error:
        blocks.extend(["", "## Error", "", f"```text\n{entry.error}\n```"])
    else:
        response = (entry.result.text if entry.result else "").rstrip()
        blocks.extend(["", "## Response", "", response or "_(empty)_"])

    if entry.result is not None:
        r = entry.result
        detail_rows = [
            ("model", r.model),
            ("tokens", f"{r.prompt_tokens} in / {r.completion_tokens} out"),
            ("finish_reason", r.finish_reason),
            ("used_fallback_key", r.used_fallback_key),
        ]
        if entry.elapsed is not None:
            detail_rows.append(("elapsed", f"{entry.elapsed:.1f}s"))
        blocks.extend(
            [
                "",
                "## Result details",
                "",
                "| Field | Value |",
                "|---|---|",
            ]
        )
        for key, value in detail_rows:
            blocks.append(f"| {key} | {_md_escape_cell(value)} |")
    elif entry.elapsed is not None:
        blocks.extend(
            [
                "",
                "## Result details",
                "",
                "| Field | Value |",
                "|---|---|",
                f"| elapsed | {entry.elapsed:.1f}s |",
            ]
        )

    return "\n".join(blocks)


def write_run_log(log: RunLog) -> Path:
    """Write a Markdown log file and return its path. Never logs API keys."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    file_stamp, iso_stamp = _stamp()
    path = LOGS_DIR / f"{file_stamp}-{log.command}.md"
    cfg = log.config

    header_rows = [
        ("timestamp", iso_stamp),
        ("command", log.command),
        ("language", cfg.language),
        ("model", cfg.model),
        ("base_url", cfg.base_url),
        ("temperature", cfg.temperature),
        ("max_tokens", cfg.max_tokens),
        ("include_context", log.include_context),
        ("entries", len(log.entries)),
    ]

    lines = [
        f"# prompt-lab {log.command} — {iso_stamp}",
        "",
        "| Field | Value |",
        "|---|---|",
    ]
    for key, value in header_rows:
        lines.append(f"| {key} | {_md_escape_cell(value)} |")
    lines.append("")

    if len(log.entries) == 1:
        lines.append(_render_entry(log.entries[0]))
    else:
        for i, entry in enumerate(log.entries, start=1):
            lines.append(_render_entry(entry, index=i))
            lines.append("")
            lines.append("---")
            lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path
