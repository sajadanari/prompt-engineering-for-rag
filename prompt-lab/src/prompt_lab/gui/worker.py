"""Background workers for API-backed GUI actions (keeps the UI responsive)."""

from __future__ import annotations

import time

import yaml
from PySide6.QtCore import QObject, Signal

from prompt_lab.assembler import assemble_messages
from prompt_lab.client import ChatResult, ProviderClient, describe_api_error
from prompt_lab.config import Config
from prompt_lab.intent_router import route_intent
from prompt_lab.logging_util import RunEntry, RunLog, write_run_log


class ApiWorker(QObject):
    """Runs single/batch chat calls off the UI thread."""

    finished_single = Signal(dict)
    finished_batch = Signal(dict)
    failed = Signal(str)
    progress = Signal(str)

    def run_single(self, config: Config, question: str, include_context: bool) -> None:
        try:
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
                self.finished_single.emit(
                    {
                        "question": question,
                        "messages": messages,
                        "answer": result.text,
                        "model": result.model,
                        "prompt_tokens": result.prompt_tokens,
                        "completion_tokens": result.completion_tokens,
                        "finish_reason": result.finish_reason,
                        "used_fallback_key": result.used_fallback_key,
                        "elapsed": 0.0,
                        "log_path": str(log_path),
                    }
                )
                return

            messages = assemble_messages(config, question, include_context=include_context)
            client = ProviderClient(config)
            self.progress.emit("Calling model…")
            start = time.monotonic()
            result = client.chat(messages)
            elapsed = time.monotonic() - start
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
            self.finished_single.emit(
                {
                    "question": question,
                    "messages": messages,
                    "answer": result.text,
                    "model": result.model,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "finish_reason": result.finish_reason,
                    "used_fallback_key": result.used_fallback_key,
                    "elapsed": elapsed,
                    "log_path": str(log_path),
                }
            )
        except Exception as exc:  # noqa: BLE001 — surface any API/IO failure to UI
            self.failed.emit(describe_api_error(exc))

    def run_batch(self, config: Config, include_context: bool) -> None:
        try:
            questions_path = config.lang_file("questions")
            raw = yaml.safe_load(questions_path.read_text(encoding="utf-8")) or {}
            questions = raw.get("questions") or []
            if not questions:
                self.failed.emit(f"No questions found in {questions_path}")
                return

            client = ProviderClient(config)
            entries: list[RunEntry] = []
            rows: list[dict] = []

            for i, item in enumerate(questions, start=1):
                question = item["q"] if isinstance(item, dict) else str(item)
                note = item.get("note", "") if isinstance(item, dict) else ""
                self.progress.emit(f"Batch {i}/{len(questions)}: {question[:60]}")

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
                    entries.append(
                        RunEntry(
                            question=question,
                            messages=messages,
                            note=f"{note} | pre-RAG route: {routed.intent}".strip(" |"),
                            result=result,
                            elapsed=0.0,
                        )
                    )
                    rows.append(
                        {
                            "index": i,
                            "question": question,
                            "note": note,
                            "answer": result.text,
                            "tokens": "0/0",
                            "error": None,
                        }
                    )
                    continue

                messages = assemble_messages(config, question, include_context=include_context)
                start = time.monotonic()
                try:
                    result = client.chat(messages)
                    elapsed = time.monotonic() - start
                    entries.append(
                        RunEntry(
                            question=question,
                            messages=messages,
                            note=note,
                            result=result,
                            elapsed=elapsed,
                        )
                    )
                    rows.append(
                        {
                            "index": i,
                            "question": question,
                            "note": note,
                            "answer": result.text,
                            "tokens": f"{result.prompt_tokens}/{result.completion_tokens}",
                            "error": None,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    elapsed = time.monotonic() - start
                    error = describe_api_error(exc)
                    entries.append(
                        RunEntry(
                            question=question,
                            messages=messages,
                            note=note,
                            error=error,
                            elapsed=elapsed,
                        )
                    )
                    rows.append(
                        {
                            "index": i,
                            "question": question,
                            "note": note,
                            "answer": "",
                            "tokens": "-",
                            "error": error,
                        }
                    )

            log_path = write_run_log(
                RunLog(
                    command="batch",
                    config=config,
                    include_context=include_context,
                    entries=entries,
                )
            )
            self.finished_batch.emit({"rows": rows, "log_path": str(log_path)})
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(describe_api_error(exc))
