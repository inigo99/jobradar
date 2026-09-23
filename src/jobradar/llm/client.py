"""A small, provider-agnostic chat client.

Supported providers, all over their HTTP APIs so no SDK is required:

``anthropic``          api.anthropic.com/v1/messages
``openai``             api.openai.com/v1/chat/completions
``gemini``             generativelanguage.googleapis.com/v1beta/models/...
``openai-compatible``  any base URL with the same shape (vLLM, LM Studio,
                       OpenRouter, Together, Groq, ...)
``ollama``             a local Ollama server, which serves the OpenAI shape

Two things here exist to protect the user rather than the code: a hard cap on
calls per run, so an unattended cron job cannot spend an unbounded amount of
money; and a strict JSON extraction path, so a chatty model cannot corrupt the
pipeline by wrapping its answer in prose.
"""

from __future__ import annotations

import json
import logging
import os
import re

import httpx

from ..config import LLMSettings

log = logging.getLogger(__name__)

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.5-flash",
    "google": "gemini-2.5-flash",
    "openai-compatible": "",
    "ollama": "llama3.1",
}

DEFAULT_BASE_URLS = {
    "anthropic": "https://api.anthropic.com/v1",
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "google": "https://generativelanguage.googleapis.com/v1beta",
    "ollama": "http://localhost:11434/v1",
}


class LLMError(RuntimeError):
    """Raised when the provider is misconfigured; never during normal failure."""


class LLMClient:
    """Thin chat wrapper with a per-run budget.

    Every call site treats a ``None`` return as "the model was unavailable" and
    falls back to the deterministic path, so a expired key or a rate limit
    degrades quality without breaking the run.
    """

    def __init__(self, settings: LLMSettings):
        self.settings = settings
        self.provider = settings.provider.lower()
        self.model = settings.model or DEFAULT_MODELS.get(self.provider, "")
        self.base_url = (settings.base_url or DEFAULT_BASE_URLS.get(self.provider, "")).rstrip("/")
        self.calls_made = 0
        self._client = httpx.Client(timeout=120.0)
        self._api_key = self._resolve_key()

    # -- configuration -----------------------------------------------------

    def _resolve_key(self) -> str:
        if self.provider == "anthropic":
            return os.environ.get("ANTHROPIC_API_KEY", "")
        if self.provider in ("openai", "openai-compatible"):
            return os.environ.get("OPENAI_API_KEY", "")
        if self.provider in ("gemini", "google"):
            return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
        return ""  # ollama needs none

    @property
    def budget_left(self) -> int:
        return max(0, self.settings.max_calls_per_run - self.calls_made)

    def usable(self) -> bool:
        if not self.settings.enabled or not self.model:
            return False
        if self.provider in ("anthropic", "openai", "gemini", "google") and not self._api_key:
            return False
        return self.budget_left > 0

    # -- the one public call ----------------------------------------------

    def complete(self, system: str, user: str, max_tokens: int | None = None) -> str | None:
        """Return the model's text answer, or None if it could not be obtained."""
        if not self.usable():
            return None
        self.calls_made += 1
        tokens = max_tokens or self.settings.max_output_tokens
        try:
            if self.provider == "anthropic":
                return self._anthropic(system, user, tokens)
            if self.provider in ("gemini", "google"):
                return self._gemini(system, user, tokens)
            return self._openai_shaped(system, user, tokens)
        except httpx.HTTPError as exc:
            log.warning("Language model request failed: %s", exc)
            return None
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            log.warning("Unexpected response from the language model: %s", exc)
            return None

    def complete_json(self, system: str, user: str, max_tokens: int | None = None) -> dict | list | None:
        """Same as :meth:`complete`, but parses a JSON object out of the reply."""
        raw = self.complete(system + "\n\nReply with JSON only. No prose, no code fences.",
                            user, max_tokens)
        return extract_json(raw) if raw else None

    # -- providers ---------------------------------------------------------

    def _anthropic(self, system: str, user: str, max_tokens: int) -> str:
        response = self._client.post(
            f"{self.base_url}/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": self.settings.temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        response.raise_for_status()
        blocks = response.json().get("content", [])
        return "".join(block.get("text", "") for block in blocks if block.get("type") == "text")

    def _gemini(self, system: str, user: str, max_tokens: int) -> str:
        body: dict = {
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": self.settings.temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        response = self._client.post(
            f"{self.base_url}/models/{self.model}:generateContent",
            headers={
                "x-goog-api-key": self._api_key,
                "content-type": "application/json",
            },
            json=body,
        )
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(part.get("text", "") for part in parts if "text" in part)

    def _openai_shaped(self, system: str, user: str, max_tokens: int) -> str:
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        response = self._client.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": self.settings.temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        response.raise_for_status()
        choices = response.json().get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content") or ""

    def close(self) -> None:
        self._client.close()


def build_client(settings: LLMSettings) -> LLMClient | None:
    """Return a usable client, or None when the user is running without a model."""
    if not settings.enabled:
        return None
    client = LLMClient(settings)
    if not client.usable():
        log.info(
            "Language model configured (%s) but not usable — missing key or model. "
            "Continuing with the deterministic pipeline.",
            settings.provider,
        )
        return None
    return client


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> dict | list | None:
    """Pull the first JSON value out of a model reply.

    Models wrap JSON in code fences and preambles no matter how firmly they are
    told not to, so this tries the whole string, then any fenced block, then the
    outermost braces or brackets.
    """
    if not text:
        return None
    candidates = [text.strip()]
    candidates.extend(match.strip() for match in _FENCE.findall(text))
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if 0 <= start < end:
            candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, (dict, list)):
                return parsed
        except json.JSONDecodeError:
            continue
    return None