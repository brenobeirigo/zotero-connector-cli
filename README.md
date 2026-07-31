# Zotero Connector CLI

Windows CLI wrapper around the installed Zotero Connector browser extension.
It activates a supported browser window and invokes the Connector's standard
`Ctrl+Shift+S` command. The browser extension retains responsibility for page
translation, institutional proxy handling, authenticated downloads, and
communication with Zotero Desktop.

The CLI never reads browser cookies, profiles, passwords, or extension storage.

Automated agents should follow [AGENTS.md](AGENTS.md), which documents project
CSV schemas, preconditions, batch/resume commands, exit-code handling, durable
reports, authentication handoffs, and Zotero safety invariants.

## Requirements

- Windows 10 or 11
- Python 3.10+
- Zotero Desktop open
- Zotero Connector installed in Edge, Brave, Chrome, or Firefox
- `Ctrl+Shift+S` assigned to the Connector's **Save to Zotero** action
- Any institutional proxy configured in the Connector

## Install

```powershell
python -m pip install -e C:\dev\repos\app\zotero-connector-cli
```

## Usage

Check the environment:

```powershell
zotero-connector doctor
```

Try Zotero's native **Find Available PDF** on an existing bibliographic item:

```powershell
zotero-connector find-pdf --parent-key 4JZVYAIP
```

Open a URL in Edge and add its PDF to that same existing item:

```powershell
zotero-connector save `
  --browser edge `
  --parent-key 4JZVYAIP `
  --url "https://www-sciencedirect-com.ezproxy2.utwente.nl/science/article/pii/S0038012119304963"
```

The temporary article tab is closed after reconciliation so batch runs do not
accumulate tabs or trigger browser tab-limit extensions. Use `--keep-tab` only
when the page must remain open for a login handoff or inspection.

Invoke the Connector on the active browser tab:

```powershell
zotero-connector save-active --browser edge --parent-key 4JZVYAIP
```

Attach a PDF downloaded through a publisher or database UI directly to its
existing item, without creating a temporary bibliographic record:

```powershell
zotero-connector attach-file `
  --parent-key UZVUC4HT `
  --file "C:\Users\breno\Downloads\EBSCO-FullText-07_31_2026.pdf"
```

Run an entire project status CSV locally, with no model or API service:

```powershell
zotero-connector batch-csv `
  --csv "C:\path\to\pdf-status.csv" `
  --browser edge `
  --update-csv
```

The batch command resumes from rows whose `status` is `missing_pdf`, retries
transient Zotero errors twice, verifies final attachment state directly in
Zotero, and can update `status`, `local_pdf`, and `sha256`. Each successful row
is written through an atomic CSV checkpoint immediately, so a stopped run can
resume without redoing completed items. The runner also:

- prevents overlapping runs against the same CSV with a crash-safe Windows
  named mutex;
- isolates timeouts and transient failures to one row and continues;
- writes an atomic `*.zotero-connector-report.json` checkpoint after every row;
- appends every start, item result, and finish to
  `*.zotero-connector-runs.jsonl`;
- returns exit code `7` for operational errors and `6` for a clean run that
  simply found no PDF for one or more selected items.

The batch is one local process and one serial loop. For every URL it opens an
isolated one-page browser window, targets that exact window handle, completes
the Connector attempt, closes and verifies removal of that exact window, and
only then opens the next URL. Existing user tabs are never selected for batch
cleanup. The report records `executionMode: single-process-serial`.

For multi-paper work, the model or agent should only prepare the CSV, invoke
one `batch-csv` command, and analyze the final report. It must not call `save`
paper by paper or monitor and steer individual browser attempts.

This execution path is deterministic local software. It does not call an LLM,
Codex, or any paid API. It still requires Zotero Desktop, the configured Zotero
Connector, an interactive Windows desktop, and an already authenticated browser
session. Login, MFA, CAPTCHA, and consent prompts require a human.

After an interrupted run, use `--reconcile-only --update-csv` to refresh the
CSV from final Zotero state without reopening publisher pages.

For inexpensive routine operation, launch the command manually or from Windows
Task Scheduler with **Run only when user is logged on**. The Connector shortcut
needs an interactive desktop, so do not use a non-interactive service account.
The production batch intentionally has no `--limit` option. Submit the complete
CSV once; this prevents an agent from turning a project into repeated one-row
model-driven invocations. For an explicit diagnostic, create a separate
one-row CSV. Configure Task Scheduler not to start a second instance if one is
already running; the CLI mutex independently enforces the same rule.

Anti-bot (`Just a moment...`), human-verification, sign-in, login, access-denied,
and similar interstitial titles are reported as `interactive-required`. Their
isolated windows are closed before the batch continues, and the final report's
`interactiveRequired` count tells an agent when Breno needs a later login
handoff.

For that handoff, process the whole review queue with no model monitoring:

```powershell
zotero-connector batch-csv `
  --csv "C:\path\to\pdf-status.csv" `
  --status-value manual_review `
  --policy-value interactive_download `
  --interactive-downloads `
  --browser edge `
  --update-csv `
  --interactive-wait 900
```

The script serially opens each row's URL and watches the browser download
folder while the user completes login/challenge and clicks the publisher's
actual download control. A completed file is attached only after its PDF
signature and DOI/title identity pass. The exact temporary window closes before
the next row. The final report uses
`single-process-serial-interactive-download`; mismatches remain unmodified and
are listed under `rejectedDownloads`. Use `--download-dir` if the browser saves
elsewhere.

The optional `retrieval_policy` column separates feasible download handoffs
(`interactive_download`) from records that still need an edition, licensing,
or format choice (`manual_decision`). `--policy-value` filters the whole queue
before the serial run; `--policy-column` changes the column name when needed.

The default report and JSONL log are written beside the CSV. Override them with
`--report-file` and `--log-file`. Exit codes are:

- `0`: every selected item has a PDF (or there was nothing left to process);
- `6`: the run completed normally, but at least one selected item still lacks a
  retrievable PDF;
- `7`: at least one row had an operational failure and should be retried;
- `2`: startup or configuration failed, such as Zotero or CLI Bridge being
  unavailable.

Use `--json` for machine-readable output. A successful command reports Zotero
items changed after the shortcut was sent.

The default save sequence is:

1. Refuse to continue if the canonical item already has a PDF.
2. Try Zotero's native **Find Available PDF**, which attaches directly to the
   existing item.
3. If that fails, invoke the browser Connector in the authenticated tab.
4. Require exactly one new bibliographic item matching the canonical item's DOI
   or normalized title and year.
5. Validate the new child PDF, move only that PDF to the canonical item, and
   move the temporary bibliographic duplicate to Zotero Trash.
6. Run Zotero data sync and report the final attachment key and linked path.

No active duplicate remains after a successful save. The temporary item stays
recoverable in Zotero Trash.

Connector snapshots, HTML captures, supplementary files, and other non-PDF
children are never moved to the canonical item. They remain under the temporary
duplicate in Zotero Trash. The canonical parent's collection memberships are
captured before adoption and must be exactly unchanged afterward. Since Zotero
child attachments follow their parent item, the adopted PDF therefore appears
in the canonical item's existing project stream rather than the Connector's
currently selected collection.

If the Connector saves only metadata and a snapshot, with no PDF, the CLI
still moves that exact temporary duplicate and all of its children to Zotero
Trash and synchronizes the cleanup.

If a redirected page produces one temporary item whose DOI and title do not
match the requested parent, the CLI also places that item and its children in
Trash and reports the mismatch instead of adopting anything.

## Safety model

- Refuses to send the shortcut unless Zotero's local Connector endpoint answers.
- Targets only an explicit supported browser process.
- Does not inspect or export authentication state.
- Reports Zotero changes through the read-only Local API.
- Requires an exact canonical parent key for every save.
- Reconciles Connector-created duplicates only on an exact DOI or normalized
  title/year match.
- Moves only one verified, unannotated PDF and preserves the original item
  metadata, collections, tags, date added, and item key.
- Never adopts Connector-created snapshots or other non-PDF children.
- Verifies that the canonical parent's collection IDs are unchanged after the
  PDF is adopted.
- Moves the temporary duplicate to Zotero Trash rather than deleting it.

## How it maps to Zotero Connector

The official Connector manifest maps `Ctrl+Shift+S` to its browser action. That
action selects the detected translator, runs it in the authenticated page, and
sends translated items to Zotero Desktop's local `/connector/saveItems`
pipeline. This CLI invokes the same installed extension action instead of
reimplementing publisher translators or handling browser credentials.
