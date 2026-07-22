# prompt-lab — a RAG Prompt Testing Lab

A command-line lab for **testing and iterating on RAG prompts** against any OpenAI-compatible provider. Edit your system prompt, few-shot examples, and simulated retrieval context as plain files, then run questions against them and see exactly how the model behaves.

Retrieval is **simulated by design**: there is no vector database and no semantic search. The chunks in `context.yaml` *are* the "search results" — as if retrieval already happened. This isolates the variable you are actually testing: **the prompt**.

The prompt structure (system message → few-shot → XML `<context>` → reminder → question) follows the companion article in [`../article/`](../article/README.md), which explains the reasoning behind every block.

---

## Requirements

- Python 3.10+
- An API key for any OpenAI-compatible provider (preconfigured for [AvalAI](https://docs.avalai.ir/fa/quickstart))

## Installation

```powershell
cd prompt-lab
python -m venv .venv
.\.venv\Scripts\activate        # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -e .
```

Set your API key:

```powershell
copy .env.example .env          # then edit .env and paste your key
```

`.env` is gitignored — keys never enter version control. An optional `*_FALLBACK` key is tried automatically if the primary key fails authentication.

## Quickstart

```powershell
# 1. Create your editable workspace from the sample templates
prompt-lab init

# 2. Verify configuration and file paths
prompt-lab info

# 3. Inspect the assembled prompt WITHOUT calling the API
prompt-lab show-prompt "How much does the Pro plan cost?"

# 4. Send a real question
prompt-lab run "How much does the Pro plan cost?"

# 5. Run the whole sample test suite
prompt-lab batch
```

Then open `workspace/`, edit any file, and re-run. That loop — **edit → run → observe** — is the whole tool.

## Desktop GUI

A PySide6 window wraps the same core (assemble / run / batch / logs) without blocking the UI during API calls.

```powershell
# from prompt-lab/ with the venv active (after pip install -e .)
prompt-lab-gui
# or:
python -m prompt_lab.gui
```

Use the toolbar to pick language/model and toggle context, edit workspace files in the left tabs, then **Show prompt**, **Run**, or **Batch**. Editors are saved to disk before each action. Logs appear under the **Logs** tab (same `logs/*.md` files as the CLI).

---

## Run logs

Every `run` and `batch` that hits the API writes a Markdown log under `logs/` (gitignored — never committed):

- Single run: `logs/YYYYMMDD-HHMMSS-run.md`
- Batch: `logs/YYYYMMDD-HHMMSS-batch.md` (all questions in one file)

Each log includes timestamp, model, language, base_url, generation settings, whether context was included, the **full assembled prompt** (system + user messages), the **model response** (or error), tokens, finish reason, and elapsed time. API keys are never written.

`show-prompt` does **not** create a log (dry run, no API call). The console prints the log path after each `run` / `batch`.

---

## How It Works

```text
workspace/en/system_prompt.md ──┐
workspace/en/few_shot.md ───────┤→  system message
                                │
workspace/en/context.yaml ──────┤→  <context> XML block   ┐
workspace/en/reminder.md ───────┤→  reminder text          ├→ user message
your question ──────────────────┘→  "Question: ..."        ┘
                                          │
                                          ▼
                              POST {base_url}/chat/completions
```

- Chunks from `context.yaml` are rendered as `<document id= title= type= date= ...>` blocks, in file order (order = injection order, so you can experiment with chunk positioning).
- Chunk text is XML-escaped so it can never break out of the `<context>` block.
- An empty or missing `few_shot.md` / `reminder.md` simply skips that block — delete their contents to A/B test their effect.

## Workspace Files (what you edit)

Created by `prompt-lab init`; gitignored, yours to break and rebuild (`init --force` restores the samples).

| File | Role |
|---|---|
| `workspace/config.yaml` | Provider, model, language, generation parameters |
| `workspace/<lang>/system_prompt.md` | The system message (grounding rules, citations, fallback, scope…) |
| `workspace/<lang>/few_shot.md` | Behavior demonstrations appended to the system message (optional) |
| `workspace/<lang>/context.yaml` | Simulated retrieved chunks with metadata |
| `workspace/<lang>/reminder.md` | Reinforcement block placed after the context (optional) |
| `workspace/<lang>/questions.yaml` | Question set for `prompt-lab batch` |

`<lang>` is `en` or `fa` — both ship with complete samples, including a **conflicting-sources pair** (old vs. new pricing) and a **poisoned chunk** (injection probe) so you can test the hard cases immediately.

## Command Reference

| Command | Description |
|---|---|
| `prompt-lab init [--lang en\|fa\|all] [--force]` | Copy sample templates into `workspace/`. Never overwrites without `--force`. |
| `prompt-lab run "question" [options]` | Assemble the prompt and send one question. |
| `prompt-lab batch [options]` | Run every question in `questions.yaml`; print a results table. |
| `prompt-lab show-prompt ["question"]` | Dry run — print the assembled messages, no API call. |
| `prompt-lab models [-f substring]` | List models available on the provider. |
| `prompt-lab info` | Show effective config and workspace file status. |

Common options for `run` / `batch` / `show-prompt`:

| Option | Effect |
|---|---|
| `-l, --lang en\|fa` | Use the other language's prompt set (overrides config) |
| `-m, --model <id>` | Use a different model for this run (overrides config) |
| `--no-context` | Send an **empty** `<context>` — tests your empty-retrieval fallback |
| `-p, --show-prompt` | (run only) Also print the assembled prompt before the response |

### Examples

```powershell
# Persian prompt set, one question
prompt-lab run -l fa "قیمت پلن حرفه‌ای چقدر است؟"

# Compare two models on the same prompt
prompt-lab run -m gpt-5-mini "Can I schedule backups on the Basic plan?"
prompt-lab run -m gpt-5-nano "Can I schedule backups on the Basic plan?"

# Test fallback behavior with empty retrieval
prompt-lab run --no-context "How much does the Pro plan cost?"

# Injection probe (chunk 5 in the sample context is poisoned)
prompt-lab run "How do I change my backup schedule?"

# Full sample suite in Persian
prompt-lab batch -l fa
```

## Configuration Reference (`workspace/config.yaml`)

| Key | Default | Meaning |
|---|---|---|
| `provider.base_url` | `https://api.avalai.ir/v1` | Any OpenAI-compatible endpoint |
| `provider.api_key_env` | `AVALAI_API_KEY` | Env var (in `.env`) holding the key; `<name>_FALLBACK` is auto-tried on auth failure |
| `provider.model` | `gpt-5-mini` | Default model (override per run with `-m`) |
| `language` | `en` | Which prompt set to use (`en` / `fa`; override with `-l`) |
| `generation.temperature` | `null` | Left unset for models that only accept the default |
| `generation.max_tokens` | `4000` | Completion budget. **Reasoning models (gpt-5 family) spend part of this internally** — keep it generous or responses get truncated |
| `generation.extra_params` | `{}` | Raw extra parameters passed through to the API |
| `request_timeout` | `120` | HTTP timeout, seconds |

### Switching providers

Change two lines in `config.yaml` and add the key to `.env`:

```yaml
provider:
  base_url: "https://api.openai.com/v1"     # or OpenRouter, Ollama, ...
  api_key_env: "OPENAI_API_KEY"
  model: "gpt-4.1-mini"
```

```dotenv
# .env
OPENAI_API_KEY=sk-...
```

Anything speaking the OpenAI chat-completions protocol works: OpenAI, AvalAI, OpenRouter, Groq, local Ollama (`http://localhost:11434/v1`), vLLM, etc.

### Adding a new language

1. Create `templates/<lang>/` with the five files (copy `en/` as a starting skeleton).
2. Add the language code to `SUPPORTED_LANGUAGES` in `src/prompt_lab/config.py`.
3. `prompt-lab init --lang <lang>` and go.

## What to Experiment With

The sample templates are built to make the interesting failures reproducible:

- **Grounding:** delete the `## Grounding rules` block from `system_prompt.md`, then ask about two-factor authentication (not in context) — watch the model start guessing.
- **Fallback:** run with `--no-context` before and after removing the fallback procedures.
- **Conflicting sources:** ask "How much does the Pro plan cost?" — chunks 1 and 4 disagree ($12 in 2026 vs $10 in 2025). Remove the `## Conflicting sources` block and compare.
- **Prompt injection:** ask "How do I change my backup schedule?" — chunk 5 is a poisoned ticket. Remove the `## Untrusted content policy` and `reminder.md` and see if the model stays safe.
- **Few-shot value:** empty `few_shot.md` and re-run the batch — compare fallback consistency.
- **Chunk ordering:** reorder `context.yaml` entries to move the relevant chunk into the middle; observe *Lost in the Middle* effects on long contexts.

Each experiment maps to a part of the [companion article](../article/README.md), which explains the *why*.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `API key env var ... is empty` | Copy `.env.example` to `.env` and set the key. |
| `Authentication failed (both keys...)` | Both primary and fallback keys rejected — verify the keys and that `base_url` matches the provider they belong to. |
| `Provider returned HTTP 404 ... model` | Model id not available — run `prompt-lab models` and pick one (e.g. `-f mini` for light models). |
| Empty response, `finish_reason: length` warning | Reasoning models consumed the whole token budget internally — raise `generation.max_tokens`. |
| `temperature` error from provider | Some models accept only the default — leave `generation.temperature: null`. |
| Persian text garbled on Windows | Handled automatically (stdout is forced to UTF-8); if it persists, use Windows Terminal instead of legacy `cmd`. |
| `Config not found ... Run prompt-lab init` | The workspace doesn't exist yet — run `prompt-lab init`. |

## Project Layout

```text
prompt-lab/
  src/prompt_lab/
    cli.py          # Typer CLI (init/run/batch/show-prompt/models/info)
    config.py       # config.yaml + .env loading
    client.py       # OpenAI-compatible client with key fallback
    context.py      # context.yaml -> XML <context> rendering
    assembler.py    # message assembly (system + few-shot + context + reminder + question)
    runner.py       # execution + rich output
    logging_util.py # Markdown run/batch logs under logs/
    workspace.py    # template copying
  templates/        # git-tracked samples (en/ + fa/) — never edited in place
  workspace/        # YOUR editable copies (gitignored, created by init)
  logs/             # run/batch Markdown logs (gitignored)
  .env              # YOUR keys (gitignored)
```
