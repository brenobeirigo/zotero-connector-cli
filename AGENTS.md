# Agent runbook

This repository provides the `zotero-connector` Windows CLI. Use it when PDFs
must be attached to existing Zotero bibliographic items without creating active
duplicates or moving snapshots onto the canonical records.

## Batch project retrieval

Use `batch-csv` for a project queue. It is deterministic local software and
does not require model monitoring or an API service.

```powershell
zotero-connector doctor

zotero-connector batch-csv `
  --csv "<project-output>\pdf-status.csv" `
  --browser edge `
  --update-csv
```

The default selection is every row whose `status` equals `missing_pdf`.
Required and recognized columns are:

- `zotero_key` — required canonical parent-item key.
- `access_url` — optional authenticated article URL. Without it, the runner
  tries only Zotero's native **Find Available PDF**.
- `status` — required when `--update-csv` is used.
- `local_pdf` and `sha256` — updated when present.

Use `--key-column`, `--url-column`, `--status-column`, and `--status-value`
only when a project's schema differs. `batch-csv` intentionally has no
`--limit` option: a multi-paper list must be submitted in one invocation, not
split into model-driven one-row runs. For a diagnostic, prepare a separate
one-row CSV explicitly.

The agent/model boundary is strict:

1. The agent prepares or locates the complete input CSV once.
2. The agent invokes one `batch-csv` process for that list.
3. The script performs every native lookup, browser attempt, cleanup, retry,
   Zotero reconciliation, hash, CSV checkpoint, and report write serially.
4. After the process exits, the agent reads the final JSON report once and
   summarizes the result or requests a login handoff when necessary.

Do not have the model loop over rows, call `save` once per paper, poll browser
tabs, or convert results manually. Individual commands are for diagnosis or a
single explicit paper only. Multi-paper work must be one `batch-csv` run.

## Preconditions

- Zotero Desktop and the CLI Bridge must be running.
- The selected browser must have Zotero Connector installed.
- Assign `Ctrl+Shift+S` to Connector's **Save to Zotero** action.
- Configure institutional proxy rules in Connector, including
  `%.ezproxy2.utwente.nl/%p` for University of Twente access.
- Keep an interactive, unlocked Windows session. Browser shortcuts do not work
  in a non-interactive service session.
- The browser may reuse an authenticated session, but an agent must hand login,
  MFA, CAPTCHA, or consent prompts to Breno. Never request, inspect, export, or
  store credentials, cookies, tokens, or profiles.
- Follow the active `zotero:` library `AGENTS.md`, including OneDrive and
  Zotero synchronization checks before and after authorized attachment writes.

## What the runner guarantees

- It first addresses the exact existing Zotero parent key.
- It tries native **Find Available PDF** before browser Connector unless
  `--skip-native` is supplied.
- A Connector-created item must match the canonical DOI or normalized
  title/year.
- Only one verified, unannotated PDF may move to the canonical item.
- The canonical item's collection memberships must remain unchanged.
- Temporary bibliographic duplicates, snapshots, and non-PDF children remain
  recoverable in Zotero Trash; they are not merged into the canonical record.
- CSV successes are checkpointed atomically after every item.
- A named mutex prevents concurrent batches against the same CSV on one
  machine.
- Per-item timeouts and transient failures are isolated and retried.
- Browser work is strictly serial. For each URL, the runner creates a new
  one-page browser window, records its exact Windows handle, attempts the
  Connector save, closes that exact window, verifies that it disappeared, and
  only then advances to the next row. It never guesses which existing user tab
  should be closed.
- Batch retrieval runs in one Python process. It does not spawn another CLI
  process per paper, so cleanup `finally` blocks cannot be bypassed by a parent
  process timeout.

Do not independently merge or delete temporary records after the run. Inspect
the report and Zotero final state first.

## Resume, reports, and exit codes

The runner writes these files beside the source CSV by default:

- `<stem>.zotero-connector-report.json` — atomic latest-run checkpoint.
- `<stem>.zotero-connector-runs.jsonl` — append-only event history.

The standard JSON report declares `executionMode: single-process-serial`.
Interactive-download mode uses the explicitly documented variant below; treat
any other value as an incompatible or older runner.

### Automatic EBSCO full-text route

The standard batch automatically searches the University of Twente EBSCO
collection by exact title. For INFORMS records (`10.1287/*` or a
`pubsonline.informs.org` access URL), it tries EBSCO before the publisher page;
for other records it uses EBSCO after a clean publisher/Connector miss. The
runner opens the generated EBSCO results URL in the authenticated Edge profile,
uses Windows UI Automation to activate only an exact-title `Access now (PDF)`
control, waits for the EBSCO viewer, invokes Connector there, adopts the one
verified PDF into the existing parent, and closes the exact browser window.

This route is local and deterministic. It does not inspect or export cookies,
does not use model clicks or screen coordinates, and retains the existing
duplicate/snapshot cleanup and collection-preservation guarantees. Use
`--skip-ebsco` only for diagnostics. `--ebsco-load-wait`,
`--ebsco-max-tabs`, and `--ebsco-tab-wait` are bounded recovery controls, not
per-paper model-loop controls. If EBSCO requires login, MFA, CAPTCHA, or
consent, stop for Breno's interactive handoff as usual.

### Manual-review download handoff

When publisher metadata is correct but Connector cannot obtain the file, run
the complete manual-review queue once in interactive-download mode:

```powershell
zotero-connector batch-csv `
  --csv "<project-output>\pdf-status.csv" `
  --status-value manual_review `
  --policy-value interactive_download `
  --interactive-downloads `
  --browser edge `
  --update-csv `
  --interactive-wait 900
```

This remains a single-process serial batch. For each row with an `access_url`,
the script opens one isolated window and waits while Breno completes any
login/challenge and uses the publisher's real download control. It watches the
browser download directory, accepts only a stable `%PDF-` file whose DOI or
title matches the CSV row, attaches it to the canonical Zotero parent, updates
the checksum/status checkpoint, closes the exact window, and advances. Invalid
or mismatched downloads are reported and preserved for review, never attached
or deleted. Rows without an access URL are classified `manual-no-url`.

Use a `retrieval_policy` column to keep licensing or edition decisions out of
the browser loop. The command above selects only `interactive_download`; use
`manual_decision` for books, previews, ambiguous editions, or sources where a
single canonical PDF has not been chosen. Override the column name with
`--policy-column` only when the project schema requires it.

Use `--download-dir` when the browser does not download to the current user's
`Downloads` folder. The report declares
`executionMode: single-process-serial-interactive-download`. The user may
interact with publisher pages; the model must not poll, click, or run rows
individually.

After an interruption, reconcile Zotero state without reopening any pages:

```powershell
zotero-connector batch-csv `
  --csv "<project-output>\pdf-status.csv" `
  --reconcile-only `
  --update-csv
```

Interpret exit codes as follows:

- `0` — every selected item has a PDF, or there was nothing left to process.
- `6` — clean completion, but one or more selected items still have no PDF.
- `7` — at least one operational error; retry those rows.
- `2` — startup/configuration failure such as unavailable Zotero or CLI Bridge.

Exit `6` is a retrieval outcome, not a software failure. Report the unresolved
items; do not repeatedly rerun unchanged gated or metadata-only sources.
The report's `interactiveRequired` count identifies anti-bot, sign-in, or
access-denied pages that need a later human browser handoff. Batch mode closes
those temporary windows and continues; it does not poll them with a model.

## Scheduling

The cheapest execution is a local manual run. If recurring execution is
explicitly requested, only the hub scheduler owner (`PARABELLUM`) may configure
it. Windows Task Scheduler must use **Run only when user is logged on**, keep
the session interactive, and prevent a second instance. The CLI mutex provides
an additional overlap guard.

## Development verification

From this repository:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q src tests
zotero-connector doctor --json
```

For live changes, also run a small or `--reconcile-only` project batch and
inspect both its exit code and durable report. Never claim a successful PDF
retrieval based only on a child command; verify the canonical Zotero parent's
final attachment, path, collections, and PDF signature.
