# TODO

This file contains functionality that is not implemented or not yet ready for
general use. Implemented behavior belongs in `README.md` and `AGENTS.md`.

## Release blockers

- Package and document the companion Zotero CLI Bridge used by write-capable
  commands, including installation, compatibility, local-only access controls,
  and an upgrade path. The public Python package is not turnkey without it.
- Replace the hard-coded University of Twente EBSCO route with a configurable
  institutional-provider interface. Preserve the existing UT route as one
  tested configuration rather than the universal default.
- Add a live Windows integration-test profile covering Zotero Desktop, the CLI
  Bridge, a browser with Zotero Connector, temporary-item cleanup, collection
  preservation, and interrupted-run recovery.
- Define a versioning and release process: changelog, tagged GitHub releases,
  built wheel/sdist, dependency audit, and optional PyPI publication.

## Reliability and safety

- Add structured redaction tests for URLs, report fields, exception messages,
  and subprocess output so query credentials and signed-download tokens cannot
  enter durable logs.
- Add an explicit dry-run or plan mode for attachment adoption and remote-file
  retrieval, comparable to the existing `import-bib` dry run.
- Add fault-injection tests for failures between Connector save, Zotero bridge
  reconciliation, CSV checkpointing, sync, and temporary-window cleanup.
- Add a recovery command that audits stale staging files, incomplete reports,
  temporary Zotero duplicates, and interrupted CSV checkpoints without making
  changes unless explicitly requested.
- Document and test remote-host prerequisites (`ssh`, `scp`, Python 3, HTTPS
  access, and non-interactive authentication) with a diagnostic command.

## Import and metadata

- Expand `import-bib` coverage for additional BibTeX types and fields,
  corporate authors, Unicode edge cases, seasons/date ranges, ISBNs, and
  conference metadata.
- Add optional DOI metadata validation before creating records while keeping
  offline import deterministic and available.
- Support RIS and CSL JSON through the same global duplicate-detection and
  project-stream placement policy.
- Export a machine-readable conflict file for ambiguous global matches and
  provide a separate explicit resolution command.

## Retrieval extensions

- Add configurable OpenURL/library-resolver routes and institution-specific
  adapters without embedding credentials or browser state.
- Consider Unpaywall and repository lookup as transparent, lawful discovery
  routes when Zotero's native PDF finder returns no result.
- Generalize browser invocation beyond a fixed keyboard shortcut, preferably
  through a documented browser-extension/native-messaging integration.
- Evaluate cross-platform support. The current window handling and browser
  automation are intentionally Windows-specific.

## Developer experience

- Add formatting, linting, static typing, and security checks to CI after the
  codebase adopts their configurations.
- Add contribution guidelines and architecture documentation for the local
  API, privileged bridge, browser boundary, batch state machine, and reports.
- Add anonymized example CSV files and sample reports for standard,
  interactive-download, remote-SSH, and reconciliation workflows.
