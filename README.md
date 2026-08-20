# Zotero Connector CLI

Windows CLI wrapper around the installed Zotero Connector browser extension.
It activates a supported browser window and invokes the Connector's standard
`Ctrl+Shift+S` command. The browser extension retains responsibility for page
translation, institutional proxy handling, authenticated downloads, and
communication with Zotero Desktop.

The CLI never reads browser cookies, profiles, passwords, or extension storage.

> [!IMPORTANT]
> This is an experimental Windows tool. Write-capable commands currently
> require a companion Zotero CLI Bridge that exposes a local-only evaluation
> endpoint. The bridge is installed in the author's environment but is not yet
> distributed from this repository. See [TODO.md](TODO.md) before treating the
> package as a turnkey installation.

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
- Companion Zotero CLI Bridge for commands that modify the library

## Install

```powershell
git clone https://github.com/brenobeirigo/zotero-core.git
git clone https://github.com/brenobeirigo/zotero-connector-cli.git
python -m pip install -e .\zotero-core
python -m pip install -e .\zotero-connector-cli
```

BibTeX parsing, item typing, duplicate matching and import planning come from
[zotero-core](https://github.com/brenobeirigo/zotero-core), which this package
shares with the other tools that write to the same library. What lives here is
the Windows side: browser Connector automation, PDF retrieval and its route
cascade, and the resumable batch runner.

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
  --url "https://publisher.example.edu/article/10.0000/example"
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
  --file "C:\path\to\downloaded-paper.pdf"
```

When Zotero has a relative linked-attachment base directory configured, place
the verified PDF inside that directory before calling `attach-file`. The CLI
creates a linked attachment and refuses to import the file into Zotero's
internal storage. If the parent has exactly one broken, unannotated linked-PDF
record, the command relinks that record in place and preserves its attachment
key. Annotated broken records are never selected automatically.

Import BibTeX stream files into one existing project collection without a
Zotero Web API key:

```powershell
zotero-connector import-bib `
  --bib-dir "C:\path\to\bib-streams" `
  --parent-name "2026_paper_example"

zotero-connector import-bib `
  --bib-dir "C:\path\to\bib-streams" `
  --parent-name "2026_paper_example" `
  --apply
```

The first command is a dry run. The second creates any missing one-level
subcollections named after the `.bib` files, matches existing items globally
by DOI or normalized title/year, adds canonical records instead of importing
duplicates, and creates only genuinely absent records. If a canonical item is
already in another leaf of the same project, its existing placement is
preserved and reported instead of giving it two project-stream memberships.
The command uses the local Zotero CLI Bridge and therefore needs neither a
model nor `ZOTERO_API_KEY`.

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
- reconciles an exact DOI/title Connector save after a transient Zotero bridge
  outage before retrying, preventing hidden successful saves from becoming
  active duplicates;
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
`interactiveRequired` count tells an agent when the user needs a later login
handoff.

The standard batch also includes an automatic University of Twente EBSCO
full-text route. INFORMS items (`10.1287/*` or a Pubsonline access URL) go to
EBSCO before the publisher page; other clean publisher misses receive EBSCO as
a fallback. The CLI generates an exact-title EBSCO search, activates only the
matching `Access now (PDF)` accessibility control, waits for the EBSCO viewer,
and invokes Zotero Connector there. It uses the signed-in Edge session without
reading cookies, uses no model or screen coordinates, attaches only to the
canonical parent, preserves collections, and closes the exact browser window.
Use `--skip-ebsco` only when diagnosing this route.

For a lawful source that is reachable from another Tailscale machine, add an
explicit `remote_url` column and enable the serial SSH fallback:

```powershell
zotero-connector batch-csv `
  --csv "C:\path\to\pdf-status.csv" `
  --browser edge `
  --remote-host "user@remote-host" `
  --update-csv
```

The local/native, publisher, and EBSCO routes remain first. After a clean miss,
the runner asks the configured remote host to download that row's HTTPS
`remote_url` into a
random `/tmp` file, copies it back over SCP, removes the remote temporary file,
and verifies the local PDF signature, SHA-256, page readability, and DOI/title
identity before attaching it to the existing Zotero parent. Transfers are
serial and use OpenSSH batch mode, so the command remains standalone and needs
no model monitoring. Successful staging copies are removed only after their
hash matches the canonical attachment; mismatches remain staged beside the CSV
for review. The report records the host, source URL, checksum, validation, and
attachment result.

`remote_url` must be an explicit lawful open-access, institutional, publisher,
repository, or user-authorized direct PDF URL. The fallback does not search
remote catalogues, reuse browser credentials, or automate unauthorized-copy
services; known piracy domains are rejected. SSH keys and Tailscale access stay
machine-local and are never written to the project CSV or report.

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

1. Refuse to continue if the canonical item already has a physically existing
   PDF; broken attachment records do not count as available files.
2. Try Zotero's native **Find Available PDF**, which attaches directly to the
   existing item.
3. If that fails, invoke the browser Connector in the authenticated tab.
4. Require exactly one new bibliographic item matching the canonical item's DOI
   or normalized title and year.
5. Validate the new child PDF, move only that PDF to the canonical item,
   externalize a new unannotated stored PDF into Zotero's configured linked
   base directory, remove the verified internal stored copy, discard newly
   created unannotated non-PDF file attachments, and move the temporary
   bibliographic duplicate to Zotero Trash.
6. Run Zotero data sync and report the final attachment key and linked path.

No active duplicate remains after a successful save. The temporary item stays
recoverable in Zotero Trash.

Connector snapshots, HTML captures, and other non-PDF file children are never
moved to the canonical item. After an exact PDF adoption, newly created,
unannotated non-PDF file children of that exact temporary duplicate are
permanently discarded. This makes the successful Connector path PDF-only.
Non-file metadata remains on the temporary duplicate in Zotero Trash. The
canonical parent's collection memberships are captured before adoption and
must be exactly unchanged afterward. Since Zotero child attachments follow
their parent item, the adopted PDF therefore appears in the canonical item's
existing project stream rather than the Connector's currently selected
collection.

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
- Never adopts Connector-created snapshots or other non-PDF children; after a
  successful PDF adoption it erases only unannotated non-PDF file children of
  the exact temporary duplicate.
- When linked attachments are configured, verifies the linked copy and removes
  the Connector's internal stored PDF instead of leaving it in Zotero Trash.
- Verifies that the canonical parent's collection IDs are unchanged after the
  PDF is adopted.
- Moves the temporary duplicate to Zotero Trash rather than deleting it.

## How it maps to Zotero Connector

The official Connector manifest maps `Ctrl+Shift+S` to its browser action. That
action selects the detected translator, runs it in the authenticated page, and
sends translated items to Zotero Desktop's local `/connector/saveItems`
pipeline. This CLI invokes the same installed extension action instead of
reimplementing publisher translators or handling browser credentials.
