"""Gemini as the language model, and the PDF browser fallback.

Gemini is exercised against its REST shape with ``respx``, so the suite stays
offline; the browser fallback with a stand-in for Playwright's object.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest
import respx

from jobradar.config import LLMSettings
from jobradar.documents import browser
from jobradar.llm.client import LLMClient, build_client, gemini_thinking

BASE = "https://generativelanguage.googleapis.com/v1beta"


def _answer(text: str, finish: str = "STOP", extra_parts: list | None = None) -> dict:
    parts = (extra_parts or []) + [{"text": text}]
    return {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": finish}]}


@pytest.fixture
def gemini_key(monkeypatch):
    for name in ("JOBRADAR_LLM_PROVIDER", "JOBRADAR_LLM_MODEL", "JOBRADAR_LLM_BASE_URL",
                 "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


# ---------------------------------------------------------------------------
# Requests and answers
# ---------------------------------------------------------------------------


@respx.mock
def test_gemini_request_shape(gemini_key):
    route = respx.post(f"{BASE}/models/gemini-3.5-flash:generateContent").mock(
        return_value=httpx.Response(200, json=_answer("Hello"))
    )
    client = build_client(LLMSettings(provider="gemini"))
    assert client is not None
    assert client.complete("Be brief.", "Say hello") == "Hello"
    client.close()

    request = route.calls.last.request
    assert request.headers["x-goog-api-key"] == "test-key"
    body = json.loads(request.content)
    assert body["contents"] == [{"role": "user", "parts": [{"text": "Say hello"}]}]
    assert body["systemInstruction"] == {"parts": [{"text": "Be brief."}]}
    # 1500 for the answer plus room for thinking, which Gemini bills the same way.
    assert body["generationConfig"]["maxOutputTokens"] == 1500 + 2048
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
    assert "responseMimeType" not in body["generationConfig"]


@respx.mock
def test_gemini_json_mode(gemini_key):
    route = respx.post(f"{BASE}/models/gemini-3.5-flash:generateContent").mock(
        return_value=httpx.Response(200, json=_answer('{"ok": true}'))
    )
    client = LLMClient(LLMSettings(provider="gemini"))
    assert client.complete_json("Extract.", "text") == {"ok": True}
    client.close()
    config = json.loads(route.calls.last.request.content)["generationConfig"]
    assert config["responseMimeType"] == "application/json"


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gemini-3.8-flash", {"thinkingLevel": "low"}),
        ("gemini-flash-latest", {"thinkingLevel": "low"}),
        ("gemini-2.5-flash", {"thinkingBudget": 0}),
        ("gemini-2.5-flash-lite", {"thinkingBudget": 0}),
        ("gemini-2.5-pro", {"thinkingBudget": 128}),
        ("models/gemini-2.0-flash", None),
    ],
)
def test_thinking_is_kept_low_per_model_family(model, expected):
    assert gemini_thinking(model) == expected


@respx.mock
def test_thought_parts_are_not_the_answer(gemini_key):
    respx.post(f"{BASE}/models/gemini-3.5-flash:generateContent").mock(
        return_value=httpx.Response(200, json=_answer(
            "Answer", extra_parts=[{"text": "thinking out loud", "thought": True}]))
    )
    client = LLMClient(LLMSettings(provider="gemini"))
    assert client.complete("s", "u") == "Answer"
    client.close()


@respx.mock
def test_blocked_prompt_is_explained(gemini_key, caplog):
    respx.post(f"{BASE}/models/gemini-3.5-flash:generateContent").mock(
        return_value=httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})
    )
    client = LLMClient(LLMSettings(provider="gemini"))
    with caplog.at_level(logging.WARNING):
        assert not client.complete("s", "u")
    client.close()
    assert "SAFETY" in caplog.text


@respx.mock
def test_truncated_answer_is_flagged(gemini_key, caplog):
    respx.post(f"{BASE}/models/gemini-3.5-flash:generateContent").mock(
        return_value=httpx.Response(200, json=_answer("Half an ans", finish="MAX_TOKENS"))
    )
    client = LLMClient(LLMSettings(provider="gemini"))
    with caplog.at_level(logging.WARNING):
        assert client.complete("s", "u") == ""
    client.close()
    assert "cut off" in caplog.text and "discarded" in caplog.text


@respx.mock
def test_invalid_key_stops_the_run(gemini_key, caplog):
    # Gemini answers a bad key with 400, not 401.
    route = respx.post(f"{BASE}/models/gemini-3.5-flash:generateContent").mock(
        return_value=httpx.Response(400, json={"error": {
            "code": 400, "message": "API key not valid. Please pass a valid API key.",
            "status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}})
    )
    client = LLMClient(LLMSettings(provider="gemini"))
    with caplog.at_level(logging.WARNING):
        assert client.complete("s", "u") is None
        assert client.complete("s", "u") is None
    client.close()
    assert route.call_count == 1
    assert "rejected the API key" in caplog.text


@respx.mock
def test_a_model_that_refuses_the_thinking_setting_is_asked_again(gemini_key):
    route = respx.post(f"{BASE}/models/gemini-3.5-flash:generateContent").mock(side_effect=[
        httpx.Response(400, json={"error": {"message": "Thinking level is not supported."}}),
        httpx.Response(200, json=_answer("Fine")),
        httpx.Response(200, json=_answer("Again")),
    ])
    client = LLMClient(LLMSettings(provider="gemini"))
    assert client.complete("s", "u") == "Fine"
    assert client.complete("s", "u") == "Again"
    client.close()
    bodies = [json.loads(call.request.content) for call in route.calls]
    assert "thinkingConfig" in bodies[0]["generationConfig"]
    assert all("thinkingConfig" not in body["generationConfig"] for body in bodies[1:])


# ---------------------------------------------------------------------------
# Choosing Gemini
# ---------------------------------------------------------------------------


def test_google_api_key_is_accepted(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "other-key")
    client = build_client(LLMSettings(provider="gemini"))
    assert client is not None
    client.close()


def test_environment_selects_gemini_over_stored_settings(gemini_key, monkeypatch):
    monkeypatch.setenv("JOBRADAR_LLM_PROVIDER", "gemini")
    stored = LLMSettings(provider="openai", model="gpt-4o-mini")
    client = build_client(stored)
    assert client is not None
    assert (client.provider, client.model) == ("gemini", "gemini-3.5-flash")
    assert client.base_url == BASE
    client.close()


def test_environment_model_is_used(gemini_key, monkeypatch):
    monkeypatch.setenv("JOBRADAR_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("JOBRADAR_LLM_MODEL", "gemini-2.5-pro")
    client = build_client(LLMSettings())
    assert client is not None and client.model == "gemini-2.5-pro"
    client.close()


def test_empty_or_none_environment_keeps_the_stored_choice(gemini_key, monkeypatch):
    monkeypatch.setenv("JOBRADAR_LLM_PROVIDER", "none")
    client = build_client(LLMSettings(provider="gemini", model="gemini-2.5-flash"))
    assert client is not None and client.model == "gemini-2.5-flash"
    client.close()


def test_no_llm_beats_the_environment(gemini_key, monkeypatch):
    monkeypatch.setenv("JOBRADAR_LLM_PROVIDER", "gemini")
    assert build_client(LLMSettings(switched_off=True)) is None


def test_switched_off_is_never_stored():
    assert "switched_off" not in LLMSettings(switched_off=True).model_dump()


# ---------------------------------------------------------------------------
# PDF browser fallback
# ---------------------------------------------------------------------------


class FakeChromium:
    """Playwright's ``chromium``: only builds in ``working`` launch."""

    def __init__(self, working: set[str]):
        self.working = working
        self.launched: list[str | None] = []

    def launch(self, executable_path: str | None = None):
        self.launched.append(executable_path)
        if executable_path in self.working:
            return f"browser:{executable_path}"
        if executable_path is None:
            raise RuntimeError("BrowserType.launch: Executable doesn't exist at /x/headless_shell")
        raise RuntimeError("cannot start")


class FakePlaywright:
    def __init__(self, working: set[str]):
        self.chromium = FakeChromium(working)


def test_missing_playwright_build_falls_back_to_another_chromium(tmp_path, monkeypatch):
    broken, good = tmp_path / "broken", tmp_path / "good"
    monkeypatch.delenv(browser.CHROMIUM_PATH_VARIABLE, raising=False)
    monkeypatch.setattr(browser, "fallback_executables", lambda: [broken, good])
    playwright = FakePlaywright({str(good)})
    assert browser.launch_chromium(playwright) == f"browser:{good}"
    assert playwright.chromium.launched == [None, str(broken), str(good)]


def test_nothing_usable_reports_the_original_error(monkeypatch):
    monkeypatch.delenv(browser.CHROMIUM_PATH_VARIABLE, raising=False)
    monkeypatch.setattr(browser, "fallback_executables", lambda: [])
    with pytest.raises(RuntimeError, match="Executable doesn't exist"):
        browser.launch_chromium(FakePlaywright(set()))


def test_explicit_chromium_path_wins(tmp_path, monkeypatch):
    chrome = tmp_path / "chrome"
    chrome.write_text("", encoding="utf-8")
    monkeypatch.setenv(browser.CHROMIUM_PATH_VARIABLE, str(chrome))
    playwright = FakePlaywright({str(chrome)})
    assert browser.launch_chromium(playwright) == f"browser:{chrome}"
    assert playwright.chromium.launched == [str(chrome)]


def test_explicit_chromium_path_that_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setenv(browser.CHROMIUM_PATH_VARIABLE, str(tmp_path / "nope"))
    with pytest.raises(FileNotFoundError, match=browser.CHROMIUM_PATH_VARIABLE):
        browser.launch_chromium(FakePlaywright(set()))


def test_fallback_finds_other_playwright_builds_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(browser.sys, "platform", "linux")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    monkeypatch.delenv(browser.CHROMIUM_PATH_VARIABLE, raising=False)
    monkeypatch.setattr(browser.shutil, "which", lambda _name: None)
    for folder, relative in (("chromium-1100", "chrome-linux/chrome"),
                             ("chromium-1194", "chrome-linux/chrome"),
                             ("chromium_headless_shell-1194",
                              "chrome-headless-shell-linux64/chrome-headless-shell")):
        executable = tmp_path / folder / relative
        executable.parent.mkdir(parents=True)
        executable.write_text("", encoding="utf-8")
    found = [path.relative_to(tmp_path).parts[0] for path in browser.fallback_executables()]
    assert found == ["chromium_headless_shell-1194", "chromium-1194", "chromium-1100"]


# ---------------------------------------------------------------------------
# Retries
# ---------------------------------------------------------------------------


@pytest.fixture
def no_wait(monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr("jobradar.llm.client._sleep", waits.append)
    return waits


@respx.mock
def test_busy_model_is_retried(gemini_key, no_wait):
    busy = httpx.Response(503, json={"error": {"message": "high demand"}})
    route = respx.post(f"{BASE}/models/gemini-3.5-flash:generateContent").mock(
        side_effect=[busy, busy, httpx.Response(200, json=_answer("Madrid"))]
    )
    client = LLMClient(LLMSettings(provider="gemini"))
    assert client.complete("s", "u") == "Madrid"
    client.close()
    assert route.call_count == 3
    assert no_wait == [2.0, 6.0]
    assert client.calls_made == 1  # retries do not spend the per-run budget


@respx.mock
def test_retries_give_up_and_explain(gemini_key, no_wait, caplog):
    route = respx.post(f"{BASE}/models/gemini-3.5-flash:generateContent").mock(
        return_value=httpx.Response(503, json={"error": {"message": "high demand"}})
    )
    client = LLMClient(LLMSettings(provider="gemini", fallback_models=[]))
    with caplog.at_level(logging.WARNING):
        assert client.complete("s", "u") is None
    client.close()
    assert route.call_count == 3
    assert "server error (HTTP 503)" in caplog.text


@respx.mock
def test_retry_after_is_honoured_and_long_waits_are_not(gemini_key, no_wait):
    route = respx.post(f"{BASE}/models/gemini-3.5-flash:generateContent").mock(side_effect=[
        httpx.Response(429, headers={"retry-after": "4"}),
        httpx.Response(200, json=_answer("ok")),
        httpx.Response(429, headers={"retry-after": "3600"}),
    ])
    client = LLMClient(LLMSettings(provider="gemini", fallback_models=[]))
    assert client.complete("s", "u") == "ok"
    assert client.complete("s", "u") is None  # an hour is not worth waiting
    client.close()
    assert no_wait == [4.0]
    assert route.call_count == 3


@respx.mock
def test_client_errors_are_not_retried(gemini_key, no_wait):
    route = respx.post(f"{BASE}/models/gemini-3.5-flash:generateContent").mock(
        return_value=httpx.Response(400, json={"error": {"message": "bad request"}})
    )
    client = LLMClient(LLMSettings(provider="gemini"))
    assert client.complete("s", "u") is None
    client.close()
    assert route.call_count == 1 and no_wait == []


# ---------------------------------------------------------------------------
# Falling back to other models
# ---------------------------------------------------------------------------


def _daily_quota(model: str) -> httpx.Response:
    return httpx.Response(429, json={"error": {"code": 429, "message": "quota", "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
            "quotaDimensions": {"model": model}, "quotaValue": "20"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "31s"},
    ]}})


@respx.mock
def test_daily_quota_moves_to_the_next_model_for_the_rest_of_the_run(gemini_key, no_wait, caplog):
    spent = respx.post(f"{BASE}/models/gemini-3.5-flash:generateContent").mock(
        return_value=_daily_quota("gemini-3.5-flash"))
    backup = respx.post(f"{BASE}/models/gemini-3.6-flash:generateContent").mock(
        return_value=httpx.Response(200, json=_answer("from backup")))
    client = LLMClient(LLMSettings(provider="gemini"))
    with caplog.at_level(logging.WARNING):
        assert client.complete("s", "u") == "from backup"
        assert client.complete("s", "u") == "from backup"
    client.close()
    assert spent.call_count == 1  # not retried, and not asked again
    assert backup.call_count == 2
    assert no_wait == []
    assert "daily quota for gemini-3.5-flash is spent" in caplog.text


@respx.mock
def test_busy_model_falls_back_for_this_call_only(gemini_key, no_wait):
    busy = respx.post(f"{BASE}/models/gemini-3.5-flash:generateContent").mock(side_effect=[
        httpx.Response(503), httpx.Response(503), httpx.Response(503),
        httpx.Response(200, json=_answer("primary again")),
    ])
    respx.post(f"{BASE}/models/gemini-3.6-flash:generateContent").mock(
        return_value=httpx.Response(200, json=_answer("backup")))
    client = LLMClient(LLMSettings(provider="gemini"))
    assert client.complete("s", "u") == "backup"
    assert client.complete("s", "u") == "primary again"
    client.close()
    assert busy.call_count == 4


@respx.mock
def test_retired_model_is_skipped(gemini_key):
    respx.post(f"{BASE}/models/gemini-2.5-flash:generateContent").mock(
        return_value=httpx.Response(404, json={"error": {"message": "no longer available"}}))
    respx.post(f"{BASE}/models/gemini-3.6-flash:generateContent").mock(
        return_value=httpx.Response(200, json=_answer("ok")))
    client = LLMClient(LLMSettings(provider="gemini", model="gemini-2.5-flash"))
    assert client.complete("s", "u") == "ok"
    client.close()


@respx.mock
def test_every_model_spent_stops_the_run(gemini_key, no_wait, caplog):
    for model in ("gemini-3.5-flash", "gemini-3.6-flash"):
        respx.post(f"{BASE}/models/{model}:generateContent").mock(return_value=_daily_quota(model))
    client = LLMClient(LLMSettings(provider="gemini", fallback_models=["gemini-3.6-flash"]))
    with caplog.at_level(logging.WARNING):
        assert client.complete("s", "u") is None
    client.close()
    assert not client.usable()
    assert "no gemini model is left" in (client.problem() or "")


def test_per_minute_limit_waits_as_google_says(gemini_key):
    from jobradar.llm.client import _retry_after

    response = httpx.Response(429, json={"error": {"details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "12s"}]}})
    assert _retry_after(response, 2.0) == 12.0


def test_fallbacks_from_the_environment(gemini_key, monkeypatch):
    monkeypatch.setenv("JOBRADAR_LLM_FALLBACK_MODELS", "gemini-a, gemini-b")
    client = build_client(LLMSettings(provider="gemini"))
    assert client is not None and client.models == ["gemini-3.5-flash", "gemini-a", "gemini-b"]
    client.close()
    monkeypatch.setenv("JOBRADAR_LLM_FALLBACK_MODELS", "none")
    client = build_client(LLMSettings(provider="gemini"))
    assert client is not None and client.models == ["gemini-3.5-flash"]
    client.close()


# ---------------------------------------------------------------------------
# Importing a CV with a model: skill keys must be the taxonomy's
# ---------------------------------------------------------------------------


class ScriptedModel:
    """An LLMClient stand-in that returns one fixed JSON payload."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.prompts: list[str] = []

    def complete_json(self, system: str, user: str, max_tokens: int | None = None):
        self.prompts.append(system)
        return self.payload


def _payload(evidence: dict, ceiling: dict) -> dict:
    return {
        "full_name": "Alex Morgan",
        "experience": [{"id": "nw", "organization": "Northwind Retail", "title": "Backend Engineer",
                        "start": "2022-03", "end": None,
                        "bullets": [{"id": "b1", "text": "Built REST APIs in Python with Docker, "
                                                         "cutting errors by 47%."}]}],
        "skills": [{"key": "languages", "label": "Languages", "items": ["Python", "SQL"]}],
        "evidence": evidence,
        "ceiling": ceiling,
    }


def test_made_up_skill_keys_from_the_model_do_not_replace_real_evidence():
    from jobradar.profile import import_profile
    from tests.conftest import SAMPLE_CV

    model = ScriptedModel(_payload({"languages": 0.5, "data-ml": 1.0}, {"languages": 0.8}))
    profile, _notes = import_profile(SAMPLE_CV, model)  # type: ignore[arg-type]
    assert "languages" not in profile.evidence and "data-ml" not in profile.evidence
    assert profile.evidence["python"] > 0 and profile.evidence["rest_apis"] > 0
    assert "Use exactly these skill keys" in model.prompts[0]
    assert "python" in model.prompts[0]


def test_the_model_can_refine_a_real_skill():
    from jobradar.profile import import_profile
    from tests.conftest import SAMPLE_CV

    model = ScriptedModel(_payload({"sql": 0.2}, {"sql": 0.9}))
    profile, _notes = import_profile(SAMPLE_CV, model)  # type: ignore[arg-type]
    assert profile.evidence["sql"] == 0.2
    assert profile.ceiling["sql"] == 0.9
