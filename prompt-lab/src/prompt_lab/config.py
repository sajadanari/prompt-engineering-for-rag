"""Configuration loading: workspace/config.yaml + .env secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Project root = prompt-lab/ (two levels up from this file's package dir)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = PROJECT_ROOT / "templates"
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
CONFIG_FILE = WORKSPACE_DIR / "config.yaml"

SUPPORTED_LANGUAGES = ("en", "fa")

# Files expected inside each language folder of the workspace.
LANG_FILES = {
    "system_prompt": "system_prompt.md",
    "few_shot": "few_shot.md",
    "reminder": "reminder.md",
    "context": "context.yaml",
    "questions": "questions.yaml",
}


class ConfigError(RuntimeError):
    """Raised for missing/invalid configuration; message is user-facing."""


@dataclass
class Config:
    """Effective runtime configuration."""

    base_url: str
    model: str
    language: str
    api_key: str
    api_key_fallback: str | None
    temperature: float | None = None
    max_tokens: int | None = None
    request_timeout: float = 120.0
    extra_params: dict = field(default_factory=dict)

    @property
    def lang_dir(self) -> Path:
        return WORKSPACE_DIR / self.language

    def lang_file(self, key: str) -> Path:
        return self.lang_dir / LANG_FILES[key]


def load_config(language: str | None = None, model: str | None = None) -> Config:
    """Load config.yaml + .env, applying CLI overrides for language/model."""
    if not CONFIG_FILE.exists():
        raise ConfigError(
            f"Config not found: {CONFIG_FILE}\n"
            "Run `prompt-lab init` first to create your editable workspace."
        )

    raw = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
    provider = raw.get("provider", {})
    generation = raw.get("generation", {})

    # .env sits at the project root; loaded once here.
    load_dotenv(PROJECT_ROOT / ".env")

    key_env = provider.get("api_key_env", "AVALAI_API_KEY")
    api_key = os.environ.get(key_env, "")
    if not api_key:
        raise ConfigError(
            f"API key env var '{key_env}' is empty.\n"
            f"Copy .env.example to .env and set {key_env}=<your key>."
        )

    lang = (language or raw.get("language") or "en").lower()
    if lang not in SUPPORTED_LANGUAGES:
        raise ConfigError(
            f"Unsupported language '{lang}'. Supported: {', '.join(SUPPORTED_LANGUAGES)}"
        )

    return Config(
        base_url=provider.get("base_url", "https://api.avalai.ir/v1"),
        model=model or provider.get("model", "gpt-5-mini"),
        language=lang,
        api_key=api_key,
        api_key_fallback=os.environ.get(f"{key_env}_FALLBACK") or None,
        temperature=generation.get("temperature"),
        max_tokens=generation.get("max_tokens"),
        request_timeout=float(raw.get("request_timeout", 120)),
        extra_params=generation.get("extra_params") or {},
    )
