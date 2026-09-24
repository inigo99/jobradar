"""Finding a Chromium that Playwright can drive for the PDF.

Each Playwright release expects one exact browser build, downloaded by
``playwright install chromium``. Upgrading the ``playwright`` package without
re-running that command — or using a machine whose browsers were installed by
another tool — leaves the expected build missing, and ``launch()`` fails even
though a perfectly usable Chromium sits next to it. Printing one page to PDF
needs nothing a slightly older or newer build lacks, so when the expected
build is missing the renderer falls back to the first Chromium it can find:

1. ``JOBRADAR_CHROMIUM_PATH``, if set — the explicit choice always wins;
2. Playwright's own build;
3. any other build in Playwright's browser folder, newest first;
4. a system Chromium or Chrome on the ``PATH``.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Environment variable naming a Chromium or Chrome executable to use.
CHROMIUM_PATH_VARIABLE = "JOBRADAR_CHROMIUM_PATH"

#: Executables inside a Playwright build folder, per platform.
_BUILD_EXECUTABLES = {
    "linux": ("chrome-headless-shell-linux64/chrome-headless-shell", "chrome-linux64/chrome",
              "chrome-linux/chrome"),
    "darwin": ("chrome-headless-shell-mac-arm64/chrome-headless-shell",
               "chrome-headless-shell-mac-x64/chrome-headless-shell",
               "chrome-mac-arm64/Chromium.app/Contents/MacOS/Chromium",
               "chrome-mac/Chromium.app/Contents/MacOS/Chromium"),
    "win32": ("chrome-headless-shell-win64/chrome-headless-shell.exe", "chrome-win64/chrome.exe",
              "chrome-win/chrome.exe"),
}

#: Names a system-wide Chromium or Chrome goes by on the ``PATH``.
_SYSTEM_NAMES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome")


def playwright_browsers_dir() -> Path:
    """Where ``playwright install`` puts browsers on this machine."""
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if configured and configured != "0":
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def _revision(folder: Path) -> int:
    match = re.search(r"-(\d+)$", folder.name)
    return int(match.group(1)) if match else 0


def fallback_executables() -> list[Path]:
    """Chromium executables other than Playwright's expected one, best first."""
    found: list[Path] = []
    explicit = os.environ.get(CHROMIUM_PATH_VARIABLE, "").strip()
    if explicit:
        found.append(Path(explicit).expanduser())

    root = playwright_browsers_dir()
    platform_key = "linux" if sys.platform.startswith("linux") else sys.platform
    if root.is_dir():
        builds = sorted(
            (folder for folder in root.iterdir()
             if folder.is_dir() and folder.name.startswith(("chromium_headless_shell-", "chromium-"))),
            # Newest build first; at equal revision the headless shell, which
            # is what Playwright itself prefers for headless work.
            key=lambda folder: (_revision(folder), "headless" in folder.name),
            reverse=True,
        )
        for build in builds:
            for relative in _BUILD_EXECUTABLES.get(platform_key, ()):
                candidate = build / relative
                if candidate.is_file():
                    found.append(candidate)
                    break

    for name in _SYSTEM_NAMES:
        located = shutil.which(name)
        if located:
            found.append(Path(located))

    unique: list[Path] = []
    for path in found:
        if path not in unique:
            unique.append(path)
    return unique


def _missing_executable(exc: Exception) -> bool:
    text = str(exc).lower()
    return "executable doesn't exist" in text or "playwright install" in text


def launch_chromium(playwright: Any) -> Any:
    """Launch a headless Chromium, falling back as described in the module docstring.

    Raises the original launch error when nothing usable is found, so the
    caller's message still says what Playwright expected.
    """
    explicit = os.environ.get(CHROMIUM_PATH_VARIABLE, "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise FileNotFoundError(
                f"{CHROMIUM_PATH_VARIABLE} points to {path}, which does not exist"
            )
        return playwright.chromium.launch(executable_path=str(path))

    try:
        return playwright.chromium.launch()
    except Exception as exc:
        if not _missing_executable(exc):
            raise
        original = exc

    for candidate in fallback_executables():
        try:
            browser = playwright.chromium.launch(executable_path=str(candidate))
        except Exception as exc:  # try the next one; report the original if none work
            log.debug("Cannot launch %s: %s", candidate, exc)
            continue
        log.info("Playwright's own Chromium is not installed; printing the PDF with %s",
                 candidate)
        return browser
    raise original


def expected_executable() -> Path | None:
    """The build this Playwright version expects, or None if Playwright is absent."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as playwright:
            return Path(playwright.chromium.executable_path)
    except Exception as exc:  # the driver itself failed to start
        log.debug("Cannot ask Playwright for its browser: %s", exc)
        return None
