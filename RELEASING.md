# Releasing

The rule this process exists to enforce: **a tag is a claim that the version
in the tag, the version in `pyproject.toml`, and the version in
`__init__.py` are the same string.** A test asserts the last two agree, and
the release workflow refuses a tag that disagrees with either.

Nothing here is published to PyPI, and a release is not a claim that the
package is turnkey. It cannot be: write-capable commands need the Zotero CLI
Bridge, a third-party plugin that pip cannot install, and the retrieval side
needs Windows, a browser, and the Zotero Connector. The workflow builds a
wheel and an sdist and attaches them to the GitHub Release so that an install
by URL resolves to a specific, downloadable artifact rather than to whatever
`main` happened to be that day.

## Cutting a release

1. Update `CHANGELOG.md`: retitle `[Unreleased]` as the new version with
   today's date, and open a fresh `[Unreleased]`. Update the link definitions
   at the bottom.
2. Set the version in **both** places:
   - `pyproject.toml` → `[project] version`
   - `src/zotero_connector_cli/__init__.py` → `__version__`
3. Run the checks locally:
   ```powershell
   python -m pytest -q tests
   python -m build
   python -m pip_audit --strict
   ```
4. Run the live profile once, against a real Zotero. CI cannot — there is no
   Zotero on a GitHub runner — so every write path in this package ships on
   the strength of this one run:
   ```powershell
   $env:ZOTERO_CONNECTOR_LIVE = "1"
   python -m pytest tests/integration -q
   ```
5. Commit, then tag and push:
   ```powershell
   git commit -am "Release 0.2.0"
   git tag v0.2.0
   git push && git push --tags
   ```

Pushing the tag runs `.github/workflows/release.yml`, which re-runs the unit
tests, verifies the tag against both version strings, audits dependencies,
builds the artifacts, and creates the GitHub Release with the changelog
section as its body.

## Version policy

Pre-1.0, so the middle number carries breaking changes.

- **Patch** — a fix that changes nothing a caller or a script may rely on.
- **Minor** — a new command or flag, a changed report field, or any change to
  what a run does to a library.
- **Major** — reserved for 1.0, which this package should not reach while the
  bridge is a third-party dependency and the EBSCO walk has no automated
  coverage.

Anything that changes what a run writes to a library is at least a minor
release, however small the diff. The landing-page sweep trashes items that
earlier versions left in place; that earns a version number even though the
items in question were litter.

Report fields are part of the interface. `AGENTS.md` documents CSV schemas and
report shapes that automated callers parse, so removing or renaming a field is
a breaking change even when no Python signature moved.

## Dependency audit

CI runs `pip-audit` on every push and weekly, and blocks a release tag on a
clean result. The dependency surface is small and deliberately so:
`zotero-core`, `bibtexparser`, `pypdf`, and `pywinauto` — the last pinned
exactly, because UI-automation behavior changes between its releases in ways
no test here would catch.
