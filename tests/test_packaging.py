"""The installed package must carry every data file the code reads.

``pyproject.toml`` lists them as globs, and a file in a new folder (the
translations were one) is silently left out of the wheel: everything works
from a checkout and breaks after ``pip install``.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import jobradar

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "jobradar"
DATA_FOLDERS = ("resources", "documents/templates", "web/templates", "web/static")


def _package_data_globs() -> list[str]:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"\[tool\.setuptools\.package-data\]\s*jobradar = \[(.*?)\]", text, re.S)
    assert block, "pyproject.toml has no package-data for jobradar"
    return re.findall(r'"([^"]+)"', block.group(1))


def test_every_data_file_is_in_the_package():
    globs = _package_data_globs()
    missing = []
    for folder in DATA_FOLDERS:
        for path in (PACKAGE / folder).rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".py":
                continue
            relative = path.relative_to(PACKAGE).as_posix()
            # setuptools globs do not cross folders: "a/*" matches a/x, not a/b/x.
            if not any(fnmatch.fnmatch(relative, pattern)
                       and relative.count("/") == pattern.count("/") for pattern in globs):
                missing.append(relative)
    assert not missing, f"Add these to [tool.setuptools.package-data]: {missing}"


def test_the_version_is_the_same_everywhere():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version = "([^"]+)"', text, re.M)
    assert declared and declared.group(1) == jobradar.__version__
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {jobradar.__version__} " in changelog, "CHANGELOG.md has no entry for this version"
