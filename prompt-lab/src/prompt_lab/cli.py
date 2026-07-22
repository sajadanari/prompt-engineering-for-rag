"""prompt-lab CLI — test and iterate on RAG prompts from your terminal."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .assembler import assemble_messages
from .client import ProviderClient, describe_api_error
from .config import (
    LANG_FILES,
    SUPPORTED_LANGUAGES,
    WORKSPACE_DIR,
    ConfigError,
    load_config,
)
from .runner import print_messages, run_batch, run_single
from .workspace import init_workspace

app = typer.Typer(
    name="prompt-lab",
    help="A lab for testing RAG prompts against any OpenAI-compatible provider.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

# Shared option definitions
LangOption = typer.Option(None, "--lang", "-l", help="Prompt language (en|fa). Overrides config.yaml.")
ModelOption = typer.Option(None, "--model", "-m", help="Model id. Overrides config.yaml.")
NoContextOption = typer.Option(
    False, "--no-context", help="Send an empty <context> block (tests fallback behavior)."
)


def _load(lang: str | None, model: str | None):
    try:
        return load_config(language=lang, model=model)
    except ConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


@app.command()
def init(
    lang: str = typer.Option("all", "--lang", "-l", help="Language templates to copy: en, fa, or all."),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing workspace files."),
):
    """Create the editable workspace by copying the sample templates."""
    languages = list(SUPPORTED_LANGUAGES) if lang == "all" else [lang]
    try:
        copied = init_workspace(languages, force=force)
    except ConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    if copied:
        console.print(f"[green]Copied {len(copied)} file(s) into {WORKSPACE_DIR}:[/green]")
        for name in copied:
            console.print(f"  + {name}")
    else:
        console.print("[yellow]Nothing copied — files already exist. Use --force to overwrite.[/yellow]")
    console.print("\nEdit the files in [bold]workspace/[/bold], then try:  [bold]prompt-lab run \"your question\"[/bold]")


@app.command()
def run(
    question: str = typer.Argument(..., help="The user question to send."),
    lang: str = LangOption,
    model: str = ModelOption,
    no_context: bool = NoContextOption,
    show_prompt: bool = typer.Option(
        False, "--show-prompt", "-p", help="Also print the assembled prompt before the response."
    ),
):
    """Assemble the prompt from workspace files and send one question."""
    config = _load(lang, model)
    run_single(config, question, include_context=not no_context, show_prompt=show_prompt)


@app.command()
def batch(
    lang: str = LangOption,
    model: str = ModelOption,
    no_context: bool = NoContextOption,
):
    """Run every question in questions.yaml and print a results table."""
    config = _load(lang, model)
    run_batch(config, include_context=not no_context)


@app.command("show-prompt")
def show_prompt(
    question: str = typer.Argument("What is your refund policy?", help="Question to embed in the prompt."),
    lang: str = LangOption,
    no_context: bool = NoContextOption,
):
    """Dry run: print the fully assembled messages WITHOUT calling the API."""
    config = _load(lang, None)
    try:
        messages = assemble_messages(config, question, include_context=not no_context)
    except (ConfigError, FileNotFoundError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    print_messages(messages)
    total_chars = sum(len(m["content"]) for m in messages)
    console.print(f"[dim]~{total_chars} characters across {len(messages)} messages (no API call made).[/dim]")


@app.command()
def models(
    filter: str = typer.Option("", "--filter", "-f", help="Only show model ids containing this substring."),
):
    """List models available on the configured provider."""
    config = _load(None, None)
    client = ProviderClient(config)
    try:
        ids = client.list_models()
    except Exception as exc:
        console.print(f"[red]Could not list models:[/red] {describe_api_error(exc)}")
        raise typer.Exit(1)

    if filter:
        ids = [m for m in ids if filter.lower() in m.lower()]
    for model_id in ids:
        marker = "  [green]<- current[/green]" if model_id == config.model else ""
        console.print(f"{model_id}{marker}")
    console.print(f"[dim]{len(ids)} model(s).[/dim]")


@app.command()
def info():
    """Show the effective configuration and workspace file paths."""
    config = _load(None, None)

    table = Table(title=f"prompt-lab v{__version__}", show_header=False)
    table.add_column("key", style="bold")
    table.add_column("value")
    table.add_row("base_url", config.base_url)
    table.add_row("model", config.model)
    table.add_row("language", config.language)
    table.add_row("api key", f"set ({config.api_key[:6]}...)" if config.api_key else "[red]missing[/red]")
    table.add_row("fallback key", "set" if config.api_key_fallback else "not set")
    table.add_row("temperature", str(config.temperature))
    table.add_row("max_tokens", str(config.max_tokens))
    console.print(table)

    files = Table(title="Workspace files (edit these)", show_header=True)
    files.add_column("role")
    files.add_column("path")
    files.add_column("exists")
    for key in LANG_FILES:
        path = config.lang_file(key)
        files.add_row(key, str(path), "[green]yes[/green]" if path.exists() else "[red]NO[/red]")
    console.print(files)


if __name__ == "__main__":
    app()
