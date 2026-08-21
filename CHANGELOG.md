# Changelog

Notable changes to `zotero-connector-cli`. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This tool writes to someone's real Zotero library and drives their browser, so
entries name the behavior that changed rather than only the code that moved.

## [Unreleased]

### Added

- `merge-duplicates`: repairs works the library already holds more than once.
  Writes an editable plan and changes nothing until `--apply`. Groups sharing
  a DOI or citation key are proposed for merging; title-only groups are
  reported for a person to decide.
- `providers`: lists the institutional routes available for the PDF fallback
  and which one would run.
- A live Windows integration profile under `tests/integration`, off unless
  `ZOTERO_CONNECTOR_LIVE=1`. It covers the write paths that had no automated
  coverage at all, including the bridge scripts.

### Changed

- The PDF fallback is no longer hard-coded to one University of Twente EBSCO
  URL. A provider is a named record resolved from `--provider`, a provider
  file's own default, `ZOTERO_CONNECTOR_PROVIDER`, then the built-in
  `utwente-ebsco` route. UT survives as a tested reference configuration and
  as the fallback that keeps existing installs working. A provider whose
  `searchBase` is not https is refused: an EZproxy route carries a session
  cookie.
- Every retrieval result records which provider ran. A report saying "no PDF
  access" means something different depending on whose subscription was
  searched.
- `doctor` reports the CLI Bridge plugin's id and version and whether it is a
  version this package has been tested against, instead of reporting that
  something answered on the port.

### Fixed

- A Connector save that produced a provider landing page rather than a PDF is
  now trashed however many candidates the save produced. The cleanup was
  written for exactly one candidate, so a save producing none or several fell
  through it — six `webpage` items titled "EBSCO", all snapshots of one viewer
  URL, survived a 2026-08-03 run that way. A candidate carrying a real PDF is
  still treated as a mismatch rather than litter, and annotated work is never
  discarded.

## [0.1.0] - 2026-08-06

### Added

- First release. Triggers the installed Zotero Connector from a Windows
  command line, without reading browser cookies, profiles, passwords or
  extension storage.
- Route cascade for retrieval: Zotero's native Find Available PDF, the
  publisher page, the institutional EBSCO route, an interactive-download mode
  for pages that need a human, and an optional SSH fallback for lawful remote
  sources.
- `import-bib`: BibTeX streams into one project collection, matched globally
  so an existing canonical item is filed rather than duplicated, with
  ambiguous matches failing closed.
- A resumable batch runner over a project CSV, with atomic JSON and CSV
  checkpoints and a machine-local lock so two runs cannot share one CSV.
- Attachment adoption that verifies a PDF before attaching it, attaches only
  to the canonical parent, preserves collection membership, and closes the
  exact browser window it opened.

[Unreleased]: https://github.com/brenobeirigo/zotero-connector-cli/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/brenobeirigo/zotero-connector-cli/releases/tag/v0.1.0
