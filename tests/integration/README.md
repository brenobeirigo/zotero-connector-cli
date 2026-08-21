# The live Windows profile

Unit tests mock the bridge. These do not: they drive a real Zotero Desktop,
the real CLI Bridge plugin, and a real browser, on Windows. They exist because
the write paths in this package — the bridge scripts especially — have no
other coverage, and the only defect that has actually reached a real library
was in one of them.

## Running it

```powershell
$env:ZOTERO_CONNECTOR_LIVE = "1"
python -m pytest tests/integration -v
```

Without that variable every test here skips, so `pytest tests/` and
`python -m unittest discover -s tests` stay safe to run anywhere, CI included.
CI never sets it: there is no Zotero on a GitHub runner.

## What it needs

| | |
|---|---|
| Zotero Desktop | running, 7.0 – 9.0.x |
| CLI Bridge plugin | installed and active — see `zotero-core/docs/cli-bridge.md` |
| A browser | Edge or Chrome, with the Zotero Connector extension |
| Platform | Windows, for the batch lock and the UI-automation paths |

`zotero-connector doctor` reports all of these before you start.

## What it will do to your library

It writes. That is the point of it, and it is why the profile is opt-in.

Every write happens inside a scratch collection named
`zzz-connector-live-test-<random>`. Teardown trashes the items it created and
erases the collections it created, and it **refuses** to erase any collection
whose name does not start with that prefix — so a bug in the harness cannot
take a real project with it. That refusal is itself asserted, in
`test_teardown_refuses_a_collection_it_did_not_create`.

Items go to Zotero's trash rather than being erased, so anything left behind
by a killed run is recoverable. If a run is interrupted, look for collections
matching `zzz-connector-live-test-*` and delete them by hand; they are always
safe to remove.

The profile never touches an item it did not create, and never empties the
trash.

## What it covers

| Area | Tests |
|---|---|
| Bridge identity and version | `BridgeTests` |
| Temporary-item cleanup | `ScratchLifecycleTests` |
| Collection preservation on import | `ImportTests` |
| Merge, attachment moves, collection union | `MergeTests` |
| Interrupted-run recovery, atomic checkpoints, the batch lock | `RecoveryTests` |
| Browser and Connector availability | `BrowserTests` |

Still uncovered, and honest about it: the EBSCO UI-automation walk itself. It
needs an authenticated institutional session and a specific publisher page,
and asserting against a third party's live HTML would make this suite fail for
reasons that have nothing to do with this package.
