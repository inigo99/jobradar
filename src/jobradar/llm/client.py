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
from ..errors import LLMError  # noqa: F401  (re-exported for callers of this module)

log = logging.getLogger(__name__)

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-3.8-flash",
    "google": "gemini-3.8-flash",
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


#: Environment variable(s) holding each hosted provider's key, first wins.
KEY_VARIABLES = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "openai-compatible": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "google": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}
def gemini_thinking(model: str) -> dict | None:
    """The ``thinkingConfig`` to send to ``model``, or None for none.

    Gemini "thinks" before answering, and those tokens count against
    ``maxOutputTokens``: left at the default, a 1500-token budget can be spent
    entirely on thinking and the answer come back empty or cut short.
    JobRadar's tasks (reading an ad, writing a summary) need little of it, so
    it is kept low. Gemini 2.5 sizes it in tokens (Pro cannot go below 128),
    Gemini 3 and later by level, and older models do not think at all.
    """
    name = model.lower().removeprefix("models/")
    if name.startswith(("gemini-1", "gemini-2.0")):
        return None
    if name.startswith("gemini-2.5"):
        return {"thinkingBudget": 128 if "pro" in name else 0}
    return {"thinkingLevel": "low"}


#: Providers that refuse every request without a key.
KEY_REQUIRED = frozenset({"anthropic", "openai", "gemini", "google"})


class LLMClient:
    """Thin chat wrapper with a per-run budget.

    Every call site treats a ``None`` return as "the model was unavailable" and
    falls back to the deterministic path, so a expired key or a rate limit
    degrades quality without breaking the run.
    """

    def __init__(self, settings: LLMSettings):
        self.settings = settings
        self.provider = settings.provider.strip().lower()
        self.model = settings.model or DEFAULT_MODELS.get(self.provider, "")
        self.base_url = (settings.base_url or DEFAULT_BASE_URLS.get(self.provider, "")).rstrip("/")
        self.calls_made = 0
        self._client = httpx.Client(timeout=120.0)
        self._api_key = self._resolve_key()
        #: Set when the provider refused us in a way retrying cannot fix (bad
        #: key, unknown model), so the rest of the run stops asking.
        self._fatal: str | None = None
        #: Set once a Gemini model rejects ``thinkingConfig``.
        self._gemini_thinking_refused = False

    # -- configuration -----------------------------------------------------

    def _resolve_key(self) -> str:
        for name in KEY_VARIABLES.get(self.provider, ()):  # ollama needs none
            if os.environ.get(name):
                return os.environ[name]
        return ""

    @property
    def budget_left(self) -> int:
        return max(0, self.settings.max_calls_per_run - self.calls_made)

    def problem(self) -> str | None:
        """Why this client cannot be used, in words, or None if it can."""
        if not self.settings.enabled:
            return "no provider is configured"
        if self.provider not in DEFAULT_MODELS:
            return (f"unknown provider '{self.settings.provider}' "
                    f"(expected one of: {', '.join(sorted(DEFAULT_MODELS))})")
        if not self.model:
            return f"no model is set for provider '{self.provider}'"
        if not self.base_url:
            return f"no base URL is set for provider '{self.provider}'"
        if self.provider in KEY_REQUIRED and not self._api_key:
            return f"{' or '.join(KEY_VARIABLES[self.provider])} is not set"
        if self._fatal:
            return self._fatal
        if self.budget_left <= 0:
            return f"the budget of {self.settings.max_calls_per_run} calls per run is spent"
        return None

    def usable(self) -> bool:
        return self.problem() is None

    # -- the one public call ----------------------------------------------

    def complete(self, system: str, user: str, max_tokens: int | None = None,
                 json_mode: bool = False) -> str | None:
        """Return the model's text answer, or None if it could not be obtained.

        ``json_mode`` asks providers that support it (Gemini) to return JSON
        only; the others are told so in the prompt.
        """
        if not self.usable():
            return None
        self.calls_made += 1
        tokens = max_tokens or self.settings.max_output_tokens
        try:
            if self.provider == "anthropic":
                return self._anthropic(system, user, tokens)
            if self.provider in ("gemini", "google"):
                return self._gemini(system, user, tokens, json_mode)
            return self._openai_shaped(system, user, tokens)
        except httpx.HTTPStatusError as exc:
            log.warning("Language model request failed: %s", self._explain_status(exc.response))
            return None
        except httpx.TimeoutException:
            log.warning("The language model at %s did not answer in time.", self.base_url)
            return None
        except httpx.HTTPError as exc:
            log.warning("Cannot reach the language model at %s: %s", self.base_url, exc)
            return None
        except (KeyError, IndexError, ValueError, TypeError, AttributeError) as exc:
            log.warning("Unexpected response from the language model: %s", exc)
            return None

    def _explain_status(self, response: httpx.Response) -> str:
        """A readable reason for an error status; stops the run for fatal ones."""
        status = response.status_code
        body = response.text[:2000]
        # Gemini answers a bad key with 400, not 401.
        bad_key = status in (401, 403) or (
            status == 400 and ("API_KEY_INVALID" in body or "API key not valid" in body)
        )
        if bad_key:
            self._fatal = f"{self.provider} rejected the API key (HTTP {status})"
            return self._fatal + " — check the key; no more calls will be made this run."
        if status == 404:
            self._fatal = (f"{self.provider} does not know model '{self.model}' "
                           f"or the endpoint {self.base_url} (HTTP 404)")
            return self._fatal + " — check llm.model and llm.base_url."
        if status == 429:
            return f"{self.provider} is rate-limiting requests or the quota is spent (HTTP 429)."
        if status >= 500:
            return f"{self.provider} had a server error (HTTP {status}); try again later."
        return f"{self.provider} answered HTTP {status}: {response.text[:200]}"

    def complete_json(self, system: str, user: str, max_tokens: int | None = None) -> dict | list | None:
        """Same as :meth:`complete`, but parses a JSON object out of the reply."""
        raw = self.complete(system + "\n\nReply with JSON only. No prose, no code fences.",
                            user, max_tokens, json_mode=True)
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

    def _gemini(self, system: str, user: str, max_tokens: int, json_mode: bool = False) -> str:
        config: dict = {"temperature": self.settings.temperature, "maxOutputTokens": max_tokens}
        if json_mode:
            config["responseMimeType"] = "application/json"
        thinking = gemini_thinking(self.model)
        if thinking and not self._gemini_thinking_refused:
            config["thinkingConfig"] = thinking
        body: dict = {
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": config,
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        model = self.model.removeprefix("models/")
        url = f"{self.base_url}/models/{model}:generateContent"
        headers = {"x-goog-api-key": self._api_key, "content-type": "application/json"}
        response = self._client.post(url, headers=headers, json=body)
        if (response.status_code == 400 and "thinkingConfig" in config
                and "thinking" in response.text.lower()):
            # A model that does not take this thinking setting: ask again
            # without it, and stop sending it for the rest of the run.
            log.info("Gemini model %s refused the thinking setting; retrying without it.", model)
            self._gemini_thinking_refused = True
            del config["thinkingConfig"]
            response = self._client.post(url, headers=headers, json=body)
        response.raise_for_status()
        return self._gemini_text(response.json(), max_tokens)

    def _gemini_text(self, data: dict, max_tokens: int) -> str:
        """The answer text, with a logged reason whenever there is none or it is cut."""
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            log.warning("Gemini returned no answer (%s).", reason)
            return ""
        candidate = candidates[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        # Thought summaries are marked ``thought``; they are not the answer.
        text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        finish = candidate.get("finishReason", "STOP")
        if finish == "MAX_TOKENS":
            log.warning("Gemini's answer was cut off at the output limit (%s tokens); "
                        "raise llm.max_output_tokens if this keeps happening.", max_tokens)
        elif finish not in ("STOP", "FINISH_REASON_UNSPECIFIED") and not text:
            log.warning("Gemini returned no answer (finish reason %s).", finish)
        return text

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
    """Return a usable client, or None when the user is running without a model.

    ``JOBRADAR_LLM_*`` environment variables override the stored settings;
    see :meth:`LLMSettings.effective`.
    """
    settings = settings.effective()
    if not settings.enabled:
        return None
    client = LLMClient(settings)
    problem = client.problem()
    if problem:
        log.warning(
            "Language model '%s' is configured but cannot be used: %s. "
            "Continuing without it.",
            settings.provider, problem,
        )
        client.close()
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
