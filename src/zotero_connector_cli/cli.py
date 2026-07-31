from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from .privileged import (
    ZoteroBridgeError,
    adopt_connector_pdf,
    bridge_ping,
    find_available_pdf,
    parent_info,
    sync_library,
)
from .windows import (
    activate_window,
    find_browser_executable,
    find_browser_window,
    foreground_window,
    list_windows,
    send_ctrl_shift_s,
)
from .zotero import ZoteroUnavailable, ping, state, wait_for_changes


BROWSER_PROCESSES = {
    "edge": {"msedge"},
    "brave": {"brave"},
    "chrome": {"chrome"},
    "firefox": {"firefox"},
}


def _choose_browser(requested: str) -> str:
    if requested != "auto":
        return requested

    foreground = foreground_window()
    if foreground:
        for browser, process_names in BROWSER_PROCESSES.items():
            if foreground.process_name in process_names:
                return browser

    for browser in ("edge", "brave", "chrome", "firefox"):
        if find_browser_executable(browser):
            return browser
    raise RuntimeError("No supported browser executable found")


def _open_url(browser: str, url: str) -> Path:
    executable = find_browser_executable(browser)
    if not executable:
        raise RuntimeError(f"{browser.title()} executable was not found")
    args = [str(executable)]
    if browser == "firefox":
        args.extend(["-new-tab", url])
    else:
        args.extend(["--new-tab", url])
    subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return executable


def _summarize_item(item: dict) -> dict:
    data = item.get("data", {})
    return {
        "key": item.get("key"),
        "itemType": data.get("itemType"),
        "title": data.get("title"),
        "parentItem": data.get("parentItem"),
        "contentType": data.get("contentType"),
        "linkMode": data.get("linkMode"),
        "path": data.get("path"),
    }


def _result_payload(
    browser: str,
    window_title: str,
    before_version: int,
    after_version: int,
    changed: list[dict],
) -> dict:
    return {
        "ok": bool(changed),
        "browser": browser,
        "windowTitle": window_title,
        "beforeVersion": before_version,
        "afterVersion": after_version,
        "changedItems": [_summarize_item(item) for item in changed],
    }


def command_doctor(args: argparse.Namespace) -> int:
    result: dict = {
        "version": __version__,
        "zotero": {"reachable": False, "message": ""},
        "cliBridge": {"reachable": False, "message": ""},
        "browsers": {},
        "visibleBrowserWindows": [],
    }
    try:
        result["zotero"] = {"reachable": True, "message": ping()}
    except ZoteroUnavailable as exc:
        result["zotero"]["message"] = str(exc)
    try:
        bridge = bridge_ping()
        result["cliBridge"] = {
            "reachable": True,
            "message": f"Zotero {bridge['version']}",
        }
    except (ZoteroUnavailable, ZoteroBridgeError) as exc:
        result["cliBridge"]["message"] = str(exc)

    for browser in BROWSER_PROCESSES:
        executable = find_browser_executable(browser)
        result["browsers"][browser] = str(executable) if executable else None

    browser_processes = set().union(*BROWSER_PROCESSES.values())
    result["visibleBrowserWindows"] = [
        {
            "process": window.process_name,
            "pid": window.pid,
            "title": window.title,
        }
        for window in list_windows()
        if window.process_name in browser_processes
    ]

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "available" if result["zotero"]["reachable"] else "unavailable"
        print(f"Zotero: {status} — {result['zotero']['message']}")
        bridge_status = "available" if result["cliBridge"]["reachable"] else "unavailable"
        print(f"Bridge: {bridge_status} — {result['cliBridge']['message']}")
        for browser, executable in result["browsers"].items():
            print(f"{browser:7}: {executable or 'not found'}")
        for window in result["visibleBrowserWindows"]:
            print(f"window : {window['process']} ({window['pid']}) — {window['title']}")
        print("Shortcut: Ctrl+Shift+S must be assigned to Save to Zotero")
    return 0 if result["zotero"]["reachable"] and result["cliBridge"]["reachable"] else 2


def command_find_pdf(args: argparse.Namespace) -> int:
    result = find_available_pdf(args.parent_key, wait_seconds=args.wait)
    if result["ok"]:
        result["sync"] = sync_library()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["ok"]:
        print(
            f"PDF available on canonical Zotero item {result['parentKey']} "
            f"via {result['route']}."
        )
    else:
        print(
            f"Zotero Find Available PDF found no PDF for {result['parentKey']}.",
            file=sys.stderr,
        )
    return 0 if result["ok"] else 4


def _run_save(args: argparse.Namespace, open_url: bool) -> int:
    ping()
    canonical = parent_info(args.parent_key)
    existing_pdfs = [
        attachment
        for attachment in canonical["attachments"]
        if attachment["isPDF"] and not attachment["deleted"]
    ]
    if existing_pdfs:
        result = {
            "ok": True,
            "route": "already-present",
            "parentKey": canonical["key"],
            "attachments": existing_pdfs,
            "collections": canonical["collections"],
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            collections = ", ".join(
                collection["name"] for collection in canonical["collections"]
            ) or "(no collection)"
            print(
                f"Canonical Zotero item {canonical['key']} already has a PDF "
                f"in: {collections}."
            )
        return 0

    if not args.skip_native:
        native = find_available_pdf(args.parent_key, wait_seconds=args.native_wait)
        if native["ok"]:
            native["sync"] = sync_library()
            if args.json:
                print(json.dumps(native, ensure_ascii=False, indent=2))
            else:
                print(
                    f"PDF attached directly to canonical Zotero item "
                    f"{native['parentKey']} via native Find Available PDF."
                )
            return 0

    browser = _choose_browser(args.browser)
    before = state()

    if open_url:
        _open_url(browser, args.url)
        time.sleep(args.load_wait)

    window = find_browser_window(
        BROWSER_PROCESSES[browser],
        title_contains=args.title_contains,
    )
    activate_window(window)
    send_ctrl_shift_s()

    after, changed = wait_for_changes(
        before,
        timeout=args.timeout,
        settle_seconds=args.settle,
    )
    result = _result_payload(
        browser=browser,
        window_title=window.title,
        before_version=before.version,
        after_version=after.version,
        changed=changed,
    )
    candidate_keys = [
        item["key"]
        for item in changed
        if not item.get("data", {}).get("parentItem")
        and item.get("data", {}).get("itemType") != "attachment"
    ]
    if changed:
        result["adoption"] = adopt_connector_pdf(args.parent_key, candidate_keys)
        result["ok"] = bool(result["adoption"]["ok"])
        if result["ok"]:
            result["sync"] = sync_library()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif changed and result.get("adoption", {}).get("ok"):
        adoption = result["adoption"]
        print(
            f"PDF attached to canonical Zotero item {adoption['parentKey']}; "
            f"temporary duplicate {adoption['duplicateKey']} moved to Zotero Trash."
        )
        print(
            f"- attachment: {adoption['attachment']['path']} "
            f"[{adoption['attachment']['key']}]"
        )
    else:
        print(
            "No Zotero changes detected. Confirm that the target browser has the "
            "Connector installed and Ctrl+Shift+S is assigned to Save to Zotero.",
            file=sys.stderr,
        )
    return 0 if result["ok"] else 3


def _add_save_options(parser: argparse.ArgumentParser, include_url: bool) -> None:
    parser.add_argument(
        "--parent-key",
        required=True,
        help="existing canonical Zotero item key that must receive the PDF",
    )
    parser.add_argument(
        "--browser",
        choices=["auto", *BROWSER_PROCESSES],
        default="auto",
        help="browser whose Connector should be invoked",
    )
    if include_url:
        parser.add_argument("--url", required=True, help="article URL to open")
        parser.add_argument(
            "--load-wait",
            type=float,
            default=8.0,
            help="seconds to wait after opening the URL",
        )
    parser.add_argument(
        "--title-contains",
        help="refuse to target a browser window unless its title contains this text",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="maximum seconds to wait for Zotero changes",
    )
    parser.add_argument(
        "--settle",
        type=float,
        default=8.0,
        help="seconds without further Zotero changes before returning",
    )
    parser.add_argument(
        "--skip-native",
        action="store_true",
        help="skip Zotero's native Find Available PDF attempt",
    )
    parser.add_argument(
        "--native-wait",
        type=float,
        default=8.0,
        help="seconds to wait for ZotMoov after a native PDF find",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zotero-connector",
        description="Invoke the installed Zotero Connector from a Windows CLI",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="check Zotero and browser availability")
    doctor.add_argument("--json", action="store_true", help="emit JSON")
    doctor.set_defaults(func=command_doctor)

    find_pdf = subparsers.add_parser(
        "find-pdf",
        help="run Zotero's native Find Available PDF on an existing item",
    )
    find_pdf.add_argument("--parent-key", required=True, help="canonical Zotero item key")
    find_pdf.add_argument(
        "--wait",
        type=float,
        default=8.0,
        help="seconds to wait for attachment post-processing",
    )
    find_pdf.add_argument("--json", action="store_true", help="emit JSON")
    find_pdf.set_defaults(func=command_find_pdf)

    save = subparsers.add_parser("save", help="open a URL and invoke Save to Zotero")
    _add_save_options(save, include_url=True)
    save.set_defaults(func=lambda args: _run_save(args, open_url=True))

    save_active = subparsers.add_parser(
        "save-active",
        help="invoke Save to Zotero in an existing browser window",
    )
    _add_save_options(save_active, include_url=False)
    save_active.set_defaults(func=lambda args: _run_save(args, open_url=False))
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, ZoteroUnavailable, ZoteroBridgeError) as exc:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2
