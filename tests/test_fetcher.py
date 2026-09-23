"""``sources.base.Fetcher``: the shared HTTP client, plain and browser-backed.

Plain HTTP is covered with ``respx`` against the real ``httpx.Client``. The
browser path is covered by monkeypatching ``scrapling.fetchers`` classes
(never a real browser — that needs binaries this suite cannot assume are
installed) so we can assert exactly what JobRadar asks Scrapling for and how
it behaves when Scrapling misbehaves or is missing entirely.
"""

from __future__ import annotations

import sys
import types

import httpx
import pytest
import respx

from jobradar.config import SourceSettings
from jobradar.sources.base import Fetcher


@pytest.fixture
def settings():
    return SourceSettings(request_delay=0.0, timeout=1.0, respect_robots=False)


@pytest.fixture
def fetcher(settings, tmp_path):
    f = Fetcher(settings, cache_dir=tmp_path / "cache")
    yield f
    f.close()


class FakePage:
    """Stand-in for ``scrapling.engines.toolbelt.custom.Response``."""

    def __init__(self, status: int, body: bytes):
        self.status = status
        self.body = body


# ---------------------------------------------------------------------------
# Plain HTTP (unchanged behaviour — regression coverage for the branch the
# browser path was added next to)
# ---------------------------------------------------------------------------


@respx.mock
def test_get_plain_http_returns_body(fetcher):
    respx.get("https://example.test/jobs").mock(
        return_value=httpx.Response(200, text="<html>jobs</html>")
    )
    assert fetcher.get("https://example.test/jobs") == "<html>jobs</html>"


@respx.mock
def test_get_plain_http_4xx_returns_none(fetcher):
    respx.get("https://example.test/jobs").mock(return_value=httpx.Response(404))
    assert fetcher.get("https://example.test/jobs") is None


@respx.mock
def test_get_plain_http_caches_body(fetcher):
    route = respx.get("https://example.test/jobs").mock(
        return_value=httpx.Response(200, text="cached")
    )
    assert fetcher.get("https://example.test/jobs") == "cached"
    assert fetcher.get("https://example.test/jobs") == "cached"
    assert route.call_count == 1  # second call served from disk cache


# ---------------------------------------------------------------------------
# Browser path
# ---------------------------------------------------------------------------


def _install_fake_scrapling(monkeypatch, *, dynamic_fetch=None, stealthy_fetch=None):
    """Put a fake ``scrapling.fetchers`` module in ``sys.modules``.

    ``Fetcher._browser_get`` does ``from scrapling.fetchers import
    DynamicFetcher, StealthyFetcher`` lazily, so this is enough to control
    what it sees without a real Scrapling install.
    """
    fake_module = types.ModuleType("scrapling.fetchers")

    class _DynamicFetcher:
        fetch = staticmethod(dynamic_fetch) if dynamic_fetch else None

    class _StealthyFetcher:
        fetch = staticmethod(stealthy_fetch) if stealthy_fetch else None

    fake_module.DynamicFetcher = _DynamicFetcher
    fake_module.StealthyFetcher = _StealthyFetcher
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", fake_module)


def test_browser_dynamic_returns_decoded_body(fetcher, monkeypatch):
    calls = []

    def fake_fetch(url, **kwargs):
        calls.append((url, kwargs))
        return FakePage(200, b"<html>rendered</html>")

    _install_fake_scrapling(monkeypatch, dynamic_fetch=fake_fetch)

    body = fetcher.get("https://example.test/jobs", browser="dynamic")

    assert body == "<html>rendered</html>"
    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url == "https://example.test/jobs"
    assert kwargs["headless"] is True
    assert kwargs["real_chrome"] is False  # SourceSettings default
    assert "solve_cloudflare" not in kwargs


def test_browser_stealthy_requests_cloudflare_solving(fetcher, monkeypatch):
    calls = []

    def fake_fetch(url, **kwargs):
        calls.append(kwargs)
        return FakePage(200, b"<html>solved</html>")

    _install_fake_scrapling(monkeypatch, stealthy_fetch=fake_fetch)

    body = fetcher.get("https://example.test/ad/1", browser="stealthy")

    assert body == "<html>solved</html>"
    assert calls[0]["solve_cloudflare"] is True


def test_browser_get_passes_extra_headers(fetcher, monkeypatch):
    calls = []

    def fake_fetch(url, **kwargs):
        calls.append(kwargs)
        return FakePage(200, b"ok")

    _install_fake_scrapling(monkeypatch, dynamic_fetch=fake_fetch)

    fetcher.get("https://example.test/x", browser="dynamic", headers={"X-Test": "1"})

    assert calls[0]["extra_headers"] == {"X-Test": "1"}


def test_browser_get_honours_real_chrome_setting(settings, tmp_path, monkeypatch):
    settings.scrapling_real_chrome = True
    f = Fetcher(settings, cache_dir=tmp_path / "cache")
    calls = []

    def fake_fetch(url, **kwargs):
        calls.append(kwargs)
        return FakePage(200, b"ok")

    _install_fake_scrapling(monkeypatch, dynamic_fetch=fake_fetch)
    f.get("https://example.test/x", browser="dynamic")
    f.close()

    assert calls[0]["real_chrome"] is True


def test_browser_get_4xx_returns_none(fetcher, monkeypatch):
    _install_fake_scrapling(
        monkeypatch, dynamic_fetch=lambda url, **kw: FakePage(405, b"blocked")
    )
    assert fetcher.get("https://example.test/jobs", browser="dynamic", retries=0) is None


def test_browser_get_swallows_fetch_exceptions(fetcher, monkeypatch):
    def boom(url, **kwargs):
        raise RuntimeError("no browser binary")

    _install_fake_scrapling(monkeypatch, dynamic_fetch=boom)
    assert fetcher.get("https://example.test/jobs", browser="dynamic", retries=0) is None


def test_browser_get_without_scrapling_installed_returns_none(fetcher, monkeypatch):
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", None)  # forces ImportError
    assert fetcher.get("https://example.test/jobs", browser="dynamic", retries=0) is None


def test_browser_get_caches_result(fetcher, monkeypatch):
    calls = []

    def fake_fetch(url, **kwargs):
        calls.append(url)
        return FakePage(200, b"cache me")

    _install_fake_scrapling(monkeypatch, dynamic_fetch=fake_fetch)

    assert fetcher.get("https://example.test/jobs", browser="dynamic") == "cache me"
    assert fetcher.get("https://example.test/jobs", browser="dynamic") == "cache me"
    assert len(calls) == 1  # second call served from disk cache, no browser launch


def test_plain_http_never_imports_scrapling(fetcher, monkeypatch):
    """Sources that never pass ``browser=`` must not pay for Scrapling at all."""
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", None)
    with respx.mock:
        respx.get("https://example.test/jobs").mock(return_value=httpx.Response(200, text="ok"))
        assert fetcher.get("https://example.test/jobs") == "ok"
