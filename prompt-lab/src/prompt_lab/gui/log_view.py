"""Structured HTML preview for prompt-lab run/batch Markdown logs."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor, QTextOption
from PySide6.QtWidgets import QTextBrowser

_FENCE_RE = re.compile(r"^```[^\n]*\n(.*?)^```\s*$", re.DOTALL | re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
_BULLET_RE = re.compile(r"^[-*]\s+(.+)$")
_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)

_CSS = """
body {
    font-family: 'Segoe UI', Tahoma, sans-serif;
    font-size: 13px;
    color: #1e293b;
    background-color: #ffffff;
    margin: 0;
    padding: 0;
}
h1 {
    font-size: 18px;
    font-weight: 700;
    color: #0f172a;
    margin: 0 0 12px 0;
}
h2 {
    font-size: 14px;
    font-weight: 600;
    color: #0f172a;
    margin: 0 0 10px 0;
}
.card {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 12px 14px;
    margin: 0 0 14px 0;
}
.card.meta { background-color: #f8fafc; }
.card.response { border-color: #cbd5e1; }
.card.error {
    background-color: #fef2f2;
    border-color: #fecaca;
}
.card.details { background-color: #f8fafc; }
.badge {
    display: inline-block;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: #475569;
    background-color: #e2e8f0;
    border-radius: 4px;
    padding: 2px 8px;
    margin: 0 0 8px 0;
}
.badge.system { background-color: #e0e7ff; color: #3730a3; }
.badge.user { background-color: #dbeafe; color: #1e40af; }
.badge.assistant { background-color: #dcfce7; color: #166534; }
.note {
    color: #64748b;
    font-style: italic;
    margin-top: 6px;
}
.prose {
    white-space: pre-wrap;
    word-wrap: break-word;
    line-height: 1.5;
}
.role-panel {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 10px 12px;
    margin: 0 0 10px 0;
}
.role-body {
    font-family: Consolas, 'Cascadia Mono', 'Courier New', monospace;
    font-size: 12px;
    color: #0f172a;
    white-space: pre-wrap;
    word-wrap: break-word;
    line-height: 1.4;
}
table.kv {
    border-collapse: collapse;
    width: 100%;
    margin: 0;
}
table.kv th, table.kv td {
    border: 1px solid #e2e8f0;
    padding: 6px 10px;
    text-align: left;
    vertical-align: top;
}
table.kv th {
    background-color: #f1f5f9;
    color: #475569;
    font-weight: 600;
    width: 32%;
}
table.kv td { color: #0f172a; background-color: #ffffff; }
.muted { color: #94a3b8; }
"""


@dataclass
class RoleBlock:
    role: str
    content: str


@dataclass
class LogEntryView:
    question_title: str = "Question"
    question: str = ""
    note: str = ""
    roles: list[RoleBlock] = field(default_factory=list)
    response: str = ""
    error: str = ""
    details: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ParsedLog:
    title: str = "prompt-lab log"
    meta: list[tuple[str, str]] = field(default_factory=list)
    entries: list[LogEntryView] = field(default_factory=list)


def configure_log_browser(browser: QTextBrowser) -> None:
    """Readable defaults: wrap long lines, no horizontal scroll."""
    browser.setOpenExternalLinks(True)
    browser.setReadOnly(True)
    browser.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
    browser.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    browser.document().setDocumentMargin(16)

    body = QFont("Segoe UI")
    body.setStyleHint(QFont.StyleHint.SansSerif)
    body.setPointSize(10)
    browser.setFont(body)


def show_log_text(browser: QTextBrowser, markdown: str) -> None:
    """Parse a prompt-lab log and render a structured HTML preview."""
    parsed = parse_run_log(markdown)
    browser.setHtml(build_log_html(parsed))
    browser.moveCursor(QTextCursor.MoveOperation.Start)


# Back-compat alias used by older call sites
show_log_markdown = show_log_text


def parse_run_log(md: str) -> ParsedLog:
    text = md.replace("\r\n", "\n").strip()
    if not text:
        return ParsedLog(title="(empty log)")

    # Fallback: not a prompt-lab log — still show escaped body
    if not text.lstrip().startswith("#"):
        return ParsedLog(
            title="Log",
            entries=[LogEntryView(response=text)],
        )

    title_match = _H1_RE.search(text)
    title = title_match.group(1).strip() if title_match else "prompt-lab log"

    # Split after H1
    rest = text
    if title_match:
        rest = text[title_match.end() :].lstrip("\n")

    meta, rest = _consume_kv_table(rest)

    # Split batch entries on horizontal rules
    chunks = re.split(r"\n---\n", rest)
    entries: list[LogEntryView] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        entries.append(_parse_entry(chunk))

    if not entries:
        entries.append(LogEntryView(response=rest.strip() or "(no content)"))

    return ParsedLog(title=title, meta=meta, entries=entries)


def _consume_kv_table(text: str) -> tuple[list[tuple[str, str]], str]:
    lines = text.split("\n")
    i = 0
    # skip blanks
    while i < len(lines) and not lines[i].strip():
        i += 1
    rows: list[tuple[str, str]] = []
    if i < len(lines) and _TABLE_ROW_RE.match(lines[i].strip()):
        # header + separator + data rows
        i += 1
        if i < len(lines) and re.match(r"^\|[\s\-:|]+\|\s*$", lines[i].strip()):
            i += 1
        while i < len(lines):
            m = _TABLE_ROW_RE.match(lines[i].strip())
            if not m:
                break
            cells = [c.strip() for c in m.group(1).split("|")]
            if len(cells) >= 2 and cells[0].lower() not in ("field", ""):
                rows.append((cells[0], _strip_md_inline(cells[1])))
            i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        return rows, "\n".join(lines[i:])
    return [], text


def _parse_entry(chunk: str) -> LogEntryView:
    entry = LogEntryView()
    sections = _split_h2_sections(chunk)

    for heading, body in sections:
        key = heading.strip().lower()
        body = body.strip()

        if key.startswith("question"):
            entry.question_title = heading.strip() or "Question"
            note_m = re.search(r"\*Note:\s*(.*?)\*", body, re.DOTALL)
            if note_m:
                entry.note = note_m.group(1).strip()
                body = (body[: note_m.start()] + body[note_m.end() :]).strip()
            entry.question = body
        elif key.startswith("assembled prompt"):
            entry.roles = _parse_roles(body)
        elif key == "response":
            entry.response = _unwrap_fence_or_text(body)
        elif key == "error":
            entry.error = _unwrap_fence_or_text(body)
        elif key.startswith("result detail"):
            entry.details = _parse_details(body)
        else:
            # Unknown section — append to response for visibility
            if body:
                entry.response = (entry.response + "\n\n" + f"{heading}\n{body}").strip()

    return entry


def _split_h2_sections(chunk: str) -> list[tuple[str, str]]:
    """Split on ## headings, ignoring ## lines that appear inside fenced code."""
    sections: list[tuple[str, str]] = []
    current_heading = "Content"
    current_lines: list[str] = []
    in_fence = False

    for line in chunk.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            current_lines.append(line)
            continue
        if not in_fence and stripped.startswith("## "):
            body = "\n".join(current_lines).strip()
            if current_heading != "Content" or body:
                sections.append((current_heading, body))
            current_heading = stripped[3:].strip()
            current_lines = []
            continue
        current_lines.append(line)

    body = "\n".join(current_lines).strip()
    if current_heading != "Content" or body:
        sections.append((current_heading, body))
    return sections


def _parse_roles(body: str) -> list[RoleBlock]:
    """Split on ### role headings, ignoring ### inside fenced code."""
    roles: list[RoleBlock] = []
    current_role: str | None = None
    current_lines: list[str] = []
    in_fence = False

    def flush() -> None:
        nonlocal current_role, current_lines
        if current_role is None:
            current_lines = []
            return
        roles.append(
            RoleBlock(role=current_role, content=_unwrap_fence_or_text("\n".join(current_lines)))
        )
        current_role = None
        current_lines = []

    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            current_lines.append(line)
            continue
        if not in_fence and stripped.startswith("### "):
            flush()
            current_role = stripped[4:].strip()
            current_lines = []
            continue
        current_lines.append(line)

    flush()
    return roles


def _unwrap_fence_or_text(body: str) -> str:
    body = body.strip()
    m = _FENCE_RE.search(body)
    if m and body.lstrip().startswith("```"):
        return m.group(1).rstrip("\n")
    # Entire body is one fence
    if body.startswith("```"):
        lines = body.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).rstrip("\n")
    return body


def _parse_details(body: str) -> list[tuple[str, str]]:
    body = body.strip()
    rows, _rest = _consume_kv_table(body)
    if rows:
        return rows

    # Bullet form: "- model: `gpt-5-mini`" or "- tokens: 1 in / 2 out"
    parsed: list[tuple[str, str]] = []
    for line in body.split("\n"):
        m = _BULLET_RE.match(line.strip())
        if not m:
            continue
        item = m.group(1).strip()
        if ":" in item:
            key, value = item.split(":", 1)
            parsed.append((key.strip(), _strip_md_inline(value.strip())))
        else:
            parsed.append((item, ""))
    return parsed


def _strip_md_inline(value: str) -> str:
    value = value.strip()
    if value.startswith("`") and value.endswith("`") and value.count("`") == 2:
        return value[1:-1]
    return value.replace("`", "")


def build_log_html(parsed: ParsedLog) -> str:
    parts: list[str] = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<style>{_CSS}</style></head><body>",
        f"<h1>{_esc(parsed.title)}</h1>",
    ]

    if parsed.meta:
        parts.append(_kv_card("Run metadata", parsed.meta, css_class="meta"))

    for entry in parsed.entries:
        if entry.question:
            q_body = f'<div class="prose" dir="auto">{_esc(entry.question)}</div>'
            if entry.note:
                q_body += f'<div class="note" dir="auto">{_esc(entry.note)}</div>'
            parts.append(_card(entry.question_title or "Question", q_body))

        if entry.roles:
            role_html = []
            for role in entry.roles:
                badge_class = role.role.lower() if role.role.lower() in ("system", "user", "assistant") else ""
                role_html.append(
                    "<div class='role-panel'>"
                    f"<div class='badge {badge_class}'>{_esc(role.role)}</div>"
                    f"<div class='role-body'>{_esc(role.content)}</div>"
                    "</div>"
                )
            parts.append(_card("Assembled prompt", "".join(role_html)))

        if entry.error:
            parts.append(
                _card(
                    "Error",
                    f'<div class="prose" dir="auto">{_esc(entry.error)}</div>',
                    css_class="error",
                )
            )
        elif entry.response:
            parts.append(
                _card(
                    "Response",
                    f'<div class="prose" dir="auto">{_esc(entry.response)}</div>',
                    css_class="response",
                )
            )

        if entry.details:
            parts.append(_kv_card("Result details", entry.details, css_class="details"))

    parts.append("</body></html>")
    return "".join(parts)


def _card(title: str, inner_html: str, css_class: str = "") -> str:
    cls = f"card {css_class}".strip()
    return f'<div class="{cls}"><h2>{_esc(title)}</h2>{inner_html}</div>'


def _kv_card(title: str, rows: list[tuple[str, str]], css_class: str = "") -> str:
    cells = []
    for key, value in rows:
        cells.append(
            f"<tr><th>{_esc(key)}</th><td dir='auto'>{_esc(value)}</td></tr>"
        )
    table = f"<table class='kv'>{''.join(cells)}</table>"
    return _card(title, table, css_class=css_class)


def _esc(text: str) -> str:
    return html.escape(text, quote=True)
