"""The versions a release tag will be checked against.

Two strings claim to be this package's version. If they drift, the release
workflow rejects the tag -- but by then the mistake is already committed and
tagged, so it is cheaper to catch here.
"""

from __future__ import annotations

import pathlib
import re
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - 3.10 runs this branch in CI
    tomllib = None

import zotero_connector_cli

ROOT = pathlib.Path(__file__).resolve().parent.parent


def declared_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if tomllib is not None:
        return tomllib.loads(text)["project"]["version"]
    match = re.search(r'^version = "([^"]+)"', text, re.M)
    assert match, "pyproject.toml has no version"
    return match.group(1)


def test_the_package_and_its_metadata_agree_on_the_version():
    assert zotero_connector_cli.__version__ == declared_version()


def test_the_version_is_a_release_number_and_not_a_placeholder():
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:[.-]?[0-9A-Za-z.]+)?", zotero_connector_cli.__version__)


def test_the_changelog_has_a_section_for_the_current_version():
    # An Unreleased section is the normal state between releases; what must
    # never happen is a version with nothing said about it.
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    version = zotero_connector_cli.__version__
    assert f"## [{version}]" in changelog or "## [Unreleased]" in changelog


def test_the_changelog_links_every_version_it_names():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    named = set(re.findall(r"^## \[([^\]]+)\]", changelog, re.M))
    linked = set(re.findall(r"^\[([^\]]+)\]: https?://", changelog, re.M))
    assert named <= linked, f"unlinked changelog sections: {sorted(named - linked)}"
