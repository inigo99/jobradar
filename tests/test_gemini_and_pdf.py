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
    route = respx.post(f"{BASE}/models/gemini-3.8-flash:generateContent").mock(
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
    assert body["generationConfig"]["maxOutputTokens"] == 1500
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
    assert "responseMimeType" not in body["generationConfig"]


@respx.mock
def test_gemini_json_mode(gemini_key):
    route = respx.post(f"{BASE}/models/gemini-3.8-flash:generateContent").mock(
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
    respx.post(f"{BASE}/models/gemini-3.8-flash:generateContent").mock(
        return_value=httpx.Response(200, json=_answer(
            "Answer", extra_parts=[{"text": "thinking out loud", "thought": True}]))
    )
    client = LLMClient(LLMSettings(provider="gemini"))
    assert client.complete("s", "u") == "Answer"
    client.close()


@respx.mock
def test_blocked_prompt_is_explained(gemini_key, caplog):
    respx.post(f"{BASE}/models/gemini-3.8-flash:generateContent").mock(
        return_value=httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})
    )
    client = LLMClient(LLMSettings(provider="gemini"))
    with caplog.at_level(logging.WARNING):
        assert not client.complete("s", "u")
    client.close()
    assert "SAFETY" in caplog.text


@respx.mock
def test_truncated_answer_is_flagged(gemini_key, caplog):
    respx.post(f"{BASE}/models/gemini-3.8-flash:generateContent").mock(
        return_value=httpx.Response(200, json=_answer("Half an ans", finish="MAX_TOKENS"))
    )
    client = LLMClient(LLMSettings(provider="gemini"))
    with caplog.at_level(logging.WARNING):
        assert client.complete("s", "u") == "Half an ans"
    client.close()
    assert "cut off" in caplog.text


@respx.mock
def test_invalid_key_stops_the_run(gemini_key, caplog):
    # Gemini answers a bad key with 400, not 401.
    route = respx.post(f"{BASE}/models/gemini-3.8-flash:generateContent").mock(
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
    route = respx.post(f"{BASE}/models/gemini-3.8-flash:generateContent").mock(side_effect=[
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
    assert (client.provider, client.model) == ("gemini", "gemini-3.8-flash")
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
