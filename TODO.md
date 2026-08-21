# TODO

This file contains functionality that is not implemented or not yet ready for
general use. Implemented behavior belongs in `README.md` and `AGENTS.md`.

## Release blockers

None outstanding. The bridge is identified and version-checked, the
institutional route is configuration, the live profile exists, and a tag now
means something specific -- see `RELEASING.md`. What remains below is work,
not a barrier to cutting `v0.2.0`.


## Reliability and safety

- Add structured redaction tests for URLs, report fields, exception messages,
  and subprocess output so query credentials and signed-download tokens cannot
  enter durable logs.
- Add an explicit dry-run or plan mode for attachment adoption and remote-file
  retrieval, comparable to the existing `import-bib` dry run.
- Add fault-injection tests for failures between Connector save, Zotero bridge
  reconciliation, CSV checkpointing, sync, and temporary-window cleanup.
- Clean up after a Connector save that Zotero never reported. The landing-page
  sweep only runs when adoption runs, and adoption is skipped entirely on the
  `connector-no-changes` route -- if the save is not observed inside the
  timeout, whatever it created is still left behind. This is the remaining
  half of the 2026-08-03 EBSCO artifact problem and it needs a post-run audit,
  not a longer wait.
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

- Add OpenURL/library-resolver routes to the provider interface. `providers.py`
  now covers EBSCO-shaped search pages for any institution; a provider whose
  route is an OpenURL resolver rather than a search URL still has nowhere to
  describe itself. Credentials and browser state stay out of provider files.
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
