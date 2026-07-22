"""Run assembled prompts and display results with rich."""

from __future__ import annotations

import time
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .assembler import assemble_messages
from .client import ChatResult, ProviderClient, describe_api_error
from .config import Config
from .intent_router import route_intent
from .logging_util import RunEntry, RunLog, write_run_log

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


def _print_result(result: ChatResult, elapsed: float, log_path: Path | None = None) -> None:
    console.print(Panel(result.text, title="[bold]RESPONSE[/bold]", border_style="magenta"))
    meta = (
        f"model: [bold]{result.model}[/bold]  |  "
        f"tokens: {result.prompt_tokens} in / {result.completion_tokens} out  |  "
        f"time: {elapsed:.1f}s"
    )
    if result.used_fallback_key:
        meta += "  |  [yellow]fallback API key used[/yellow]"
    console.print(meta)
    if log_path is not None:
        console.print(f"[dim]log: {log_path}[/dim]")
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
    routed = route_intent(question)
    if routed is not None:
        result = ChatResult(
            text=routed.text,
            model=f"intent-router:{routed.intent}",
            prompt_tokens=0,
            completion_tokens=0,
            used_fallback_key=False,
            finish_reason="stop",
        )
        messages = [
            {
                "role": "system",
                "content": f"[intent-router] handled as {routed.intent}; RAG pipeline skipped.",
            },
            {"role": "user", "content": question},
        ]
        log_path = write_run_log(
            RunLog(
                command="run",
                config=config,
                include_context=False,
                entries=[
                    RunEntry(
                        question=question,
                        messages=messages,
                        result=result,
                        elapsed=0.0,
                        note=f"pre-RAG route: {routed.intent}",
                    )
                ],
            )
        )
        if show_prompt:
            print_messages(messages)
        _print_result(result, 0.0, log_path=log_path)
        return result

    messages = assemble_messages(config, question, include_context=include_context)
    if show_prompt:
        print_messages(messages)

    client = ProviderClient(config)
    start = time.monotonic()
    try:
        result = client.chat(messages)
        elapsed = time.monotonic() - start
    except Exception as exc:  # surface a short, actionable message
        elapsed = time.monotonic() - start
        error = describe_api_error(exc)
        log_path = write_run_log(
            RunLog(
                command="run",
                config=config,
                include_context=include_context,
                entries=[
                    RunEntry(
                        question=question,
                        messages=messages,
                        error=error,
                        elapsed=elapsed,
                    )
                ],
            )
        )
        console.print(f"[red]Request failed:[/red] {error}")
        console.print(f"[dim]log: {log_path}[/dim]")
        raise SystemExit(1)

    log_path = write_run_log(
        RunLog(
            command="run",
            config=config,
            include_context=include_context,
            entries=[
                RunEntry(
                    question=question,
                    messages=messages,
                    result=result,
                    elapsed=elapsed,
                )
            ],
        )
    )
    _print_result(result, elapsed, log_path=log_path)
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

    entries: list[RunEntry] = []

    for i, item in enumerate(questions, start=1):
        question = item["q"] if isinstance(item, dict) else str(item)
        note = item.get("note", "") if isinstance(item, dict) else ""
        console.print(f"[dim]({i}/{len(questions)}) {question}[/dim]")

        routed = route_intent(question)
        if routed is not None:
            result = ChatResult(
                text=routed.text,
                model=f"intent-router:{routed.intent}",
                prompt_tokens=0,
                completion_tokens=0,
                used_fallback_key=False,
                finish_reason="stop",
            )
            messages = [
                {
                    "role": "system",
                    "content": f"[intent-router] handled as {routed.intent}; RAG pipeline skipped.",
                },
                {"role": "user", "content": question},
            ]
            answer = result.text
            tokens = "0/0"
            entries.append(
                RunEntry(
                    question=question,
                    messages=messages,
                    note=f"{note} | pre-RAG route: {routed.intent}".strip(" |"),
                    result=result,
                    elapsed=0.0,
                )
            )
            label = f"{question}\n[dim italic]{note}[/dim italic]" if note else question
            table.add_row(str(i), label, answer, tokens)
            continue

        messages = assemble_messages(config, question, include_context=include_context)
        start = time.monotonic()
        try:
            result = client.chat(messages)
            elapsed = time.monotonic() - start
            answer = result.text
            tokens = f"{result.prompt_tokens}/{result.completion_tokens}"
            entries.append(
                RunEntry(
                    question=question,
                    messages=messages,
                    note=note,
                    result=result,
                    elapsed=elapsed,
                )
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            error = describe_api_error(exc)
            answer = f"[red]ERROR: {error}[/red]"
            tokens = "-"
            entries.append(
                RunEntry(
                    question=question,
                    messages=messages,
                    note=note,
                    error=error,
                    elapsed=elapsed,
                )
            )

        label = f"{question}\n[dim italic]{note}[/dim italic]" if note else question
        table.add_row(str(i), label, answer, tokens)

    log_path = write_run_log(
        RunLog(
            command="batch",
            config=config,
            include_context=include_context,
            entries=entries,
        )
    )
    console.print(table)
    console.print(f"[dim]log: {log_path}[/dim]")
