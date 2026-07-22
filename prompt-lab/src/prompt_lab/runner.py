"""Run assembled prompts and display results with rich."""

from __future__ import annotations

import time

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .assembler import assemble_messages
from .client import ChatResult, ProviderClient, describe_api_error
from .config import Config

console = Console()


def print_messages(messages: list[dict]) -> None:
    """Pretty-print the assembled prompt (dry-run view)."""
    for message in messages:
        style = "cyan" if message["role"] == "system" else "green"
        console.print(
            Panel(
                message["content"],
                title=f"[bold]{message['role'].upper()}[/bold]",
                border_style=style,
            )
        )


def _print_result(result: ChatResult, elapsed: float) -> None:
    console.print(Panel(result.text, title="[bold]RESPONSE[/bold]", border_style="magenta"))
    meta = (
        f"model: [bold]{result.model}[/bold]  |  "
        f"tokens: {result.prompt_tokens} in / {result.completion_tokens} out  |  "
        f"time: {elapsed:.1f}s"
    )
    if result.used_fallback_key:
        meta += "  |  [yellow]fallback API key used[/yellow]"
    console.print(meta)
    if not result.text.strip() and result.finish_reason == "length":
        console.print(
            "[yellow]Empty response: the token budget was exhausted before any "
            "visible text (reasoning models spend tokens internally). "
            "Increase generation.max_tokens in workspace/config.yaml.[/yellow]"
        )


def run_single(
    config: Config,
    question: str,
    include_context: bool = True,
    show_prompt: bool = False,
) -> ChatResult:
    """Assemble, send, and display one question."""
    messages = assemble_messages(config, question, include_context=include_context)
    if show_prompt:
        print_messages(messages)

    client = ProviderClient(config)
    start = time.monotonic()
    try:
        result = client.chat(messages)
    except Exception as exc:  # surface a short, actionable message
        console.print(f"[red]Request failed:[/red] {describe_api_error(exc)}")
        raise SystemExit(1)
    _print_result(result, time.monotonic() - start)
    return result


def run_batch(config: Config, include_context: bool = True) -> None:
    """Run every question in questions.yaml and print a summary table."""
    questions_path = config.lang_file("questions")
    raw = yaml.safe_load(questions_path.read_text(encoding="utf-8")) or {}
    questions = raw.get("questions") or []
    if not questions:
        console.print(f"[yellow]No questions found in {questions_path}[/yellow]")
        return

    client = ProviderClient(config)
    table = Table(title=f"Batch run — {config.model} ({config.language})", show_lines=True)
    table.add_column("#", width=3)
    table.add_column("Question", max_width=40)
    table.add_column("Response", max_width=70)
    table.add_column("Tokens", width=12)

    for i, item in enumerate(questions, start=1):
        question = item["q"] if isinstance(item, dict) else str(item)
        note = item.get("note", "") if isinstance(item, dict) else ""
        console.print(f"[dim]({i}/{len(questions)}) {question}[/dim]")

        messages = assemble_messages(config, question, include_context=include_context)
        try:
            result = client.chat(messages)
            answer = result.text
            tokens = f"{result.prompt_tokens}/{result.completion_tokens}"
        except Exception as exc:
            answer = f"[red]ERROR: {describe_api_error(exc)}[/red]"
            tokens = "-"

        label = f"{question}\n[dim italic]{note}[/dim italic]" if note else question
        table.add_row(str(i), label, answer, tokens)

    console.print(table)
