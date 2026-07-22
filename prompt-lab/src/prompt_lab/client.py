"""Thin wrapper around the OpenAI SDK for any OpenAI-compatible provider."""

from __future__ import annotations

from dataclasses import dataclass

from openai import APIStatusError, AuthenticationError, OpenAI

from .config import Config


@dataclass
class ChatResult:
    """Normalized response for display layers."""

    text: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    used_fallback_key: bool
    finish_reason: str | None = None


class ProviderClient:
    """Chat + model-listing against the configured endpoint, with key fallback."""

    def __init__(self, config: Config):
        self.config = config
        self._client = self._make_client(config.api_key)
        self._used_fallback = False

    def _make_client(self, api_key: str) -> OpenAI:
        return OpenAI(
            base_url=self.config.base_url,
            api_key=api_key,
            timeout=self.config.request_timeout,
        )

    def _switch_to_fallback(self) -> bool:
        """Swap to the fallback key once, if one is configured."""
        if self._used_fallback or not self.config.api_key_fallback:
            return False
        self._client = self._make_client(self.config.api_key_fallback)
        self._used_fallback = True
        return True

    def chat(self, messages: list[dict]) -> ChatResult:
        params: dict = {"model": self.config.model, "messages": messages}
        if self.config.temperature is not None:
            params["temperature"] = self.config.temperature
        if self.config.max_tokens is not None:
            # max_completion_tokens is the current param; some providers still
            # want max_tokens — extra_params in config.yaml can override.
            params["max_completion_tokens"] = self.config.max_tokens
        params.update(self.config.extra_params)

        try:
            response = self._client.chat.completions.create(**params)
        except AuthenticationError:
            if not self._switch_to_fallback():
                raise
            response = self._client.chat.completions.create(**params)

        usage = getattr(response, "usage", None)
        choice = response.choices[0]
        return ChatResult(
            text=choice.message.content or "",
            model=response.model or self.config.model,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            used_fallback_key=self._used_fallback,
            finish_reason=getattr(choice, "finish_reason", None),
        )

    def list_models(self) -> list[str]:
        try:
            models = self._client.models.list()
        except AuthenticationError:
            if not self._switch_to_fallback():
                raise
            models = self._client.models.list()
        return sorted(m.id for m in models.data)


def describe_api_error(exc: Exception) -> str:
    """Short, actionable message for common API failures."""
    if isinstance(exc, AuthenticationError):
        return (
            "Authentication failed (both keys, if a fallback was set). "
            "Check your .env keys and the provider's base_url."
        )
    if isinstance(exc, APIStatusError):
        return f"Provider returned HTTP {exc.status_code}: {exc.message}"
    return str(exc)
