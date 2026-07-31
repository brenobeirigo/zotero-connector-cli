# Zotero Connector CLI

Windows CLI wrapper around the installed Zotero Connector browser extension.
It activates a supported browser window and invokes the Connector's standard
`Ctrl+Shift+S` command. The browser extension retains responsibility for page
translation, institutional proxy handling, authenticated downloads, and
communication with Zotero Desktop.

The CLI never reads browser cookies, profiles, passwords, or extension storage.

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

Invoke the Connector on the active browser tab:

```powershell
zotero-connector save-active --browser edge --parent-key 4JZVYAIP
```

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
