from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from . import __version__
from .privileged import (
    ZoteroBridgeError,
    adopt_connector_pdf,
    attach_pdf_file,
    bridge_ping,
    find_available_pdf,
    parent_info,
    sync_library,
)
from .windows import (
    Window,
    activate_window,
    close_window,
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


def _open_url(browser: str, url: str, timeout: float = 15.0) -> Window:
    executable = find_browser_executable(browser)
    if not executable:
        raise RuntimeError(f"{browser.title()} executable was not found")
    process_names = BROWSER_PROCESSES[browser]
    original_hwnds = {
        window.hwnd
        for window in list_windows()
        if window.process_name in process_names
    }
    args = [str(executable)]
    if browser == "firefox":
        args.extend(["-new-window", url])
    else:
        args.extend(["--new-window", url])
    subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + timeout
    observed_new_windows: dict[int, Window] = {}
    try:
        while time.monotonic() < deadline:
            current = [
                window
                for window in list_windows()
                if window.process_name in process_names
                and window.hwnd not in original_hwnds
            ]
            for window in current:
                observed_new_windows[window.hwnd] = window
            limiter_windows = [
                window
                for window in current
                if window.title == "The extension Tab Limiter says"
            ]
            for limiter_window in limiter_windows:
                close_window(limiter_window)
            candidates = [
                window
                for window in current
                if window.title != "The extension Tab Limiter says"
            ]
            if candidates:
                foreground = foreground_window()
                if foreground:
                    for candidate in candidates:
                        if candidate.hwnd == foreground.hwnd:
                            return candidate
                return candidates[0]
            time.sleep(0.2)
        raise RuntimeError(
            f"{browser.title()} did not create an isolated temporary browser window"
        )
    except Exception:
        for window in observed_new_windows.values():
            try:
                close_window(window)
            except OSError:
                pass
        raise


def _close_temporary_browser_window(window: Window, timeout: float = 10.0) -> None:
    try:
        close_window(window)
    except OSError as exc:
        raise RuntimeError(
            f"Failed to close temporary browser window {window.hwnd}: {exc}"
        ) from exc
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(current.hwnd != window.hwnd for current in list_windows()):
            return
        time.sleep(0.2)
    raise RuntimeError(
        f"Temporary browser window {window.hwnd} did not close within {timeout} seconds"
    )


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


def command_attach_file(args: argparse.Namespace) -> int:
    ping()
    source = Path(args.file).expanduser().resolve()
    if not source.is_file():
        raise RuntimeError(f"PDF file not found: {source}")
    with source.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise RuntimeError(f"File does not have a PDF signature: {source}")
    result = attach_pdf_file(
        args.parent_key,
        str(source),
        wait_seconds=args.wait,
    )
    if result["ok"] and result["route"] != "already-present":
        result["sync"] = sync_library()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["ok"]:
        collections = ", ".join(
            collection["name"] for collection in result.get("collections", [])
        ) or "(existing collection)"
        print(
            f"PDF attached to canonical Zotero item {result['parentKey']} "
            f"in: {collections}."
        )
    else:
        print(
            f"Zotero did not finish attaching the PDF to {result['parentKey']}.",
            file=sys.stderr,
        )
    return 0 if result["ok"] else 5


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def _write_csv_atomic(path: Path, rows: list[dict]) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(
                stream,
                fieldnames=rows[0].keys(),
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def _append_json_line(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def _single_batch_instance(csv_path: Path):
    """Hold a crash-safe, machine-local named mutex for one project CSV."""
    if sys.platform != "win32":
        yield
        return

    mutex_name = (
        "Local\\ZoteroConnectorCLI-"
        + hashlib.sha256(str(csv_path).casefold().encode("utf-8")).hexdigest()
    )
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    handle = kernel32.CreateMutexW(None, False, mutex_name)
    if not handle:
        raise RuntimeError(
            f"Unable to create the batch lock (Windows error {ctypes.get_last_error()})"
        )
    if ctypes.get_last_error() == 183:
        kernel32.CloseHandle(handle)
        raise RuntimeError(f"Another batch is already running for {csv_path}")
    try:
        yield
    finally:
        kernel32.CloseHandle(handle)


def _final_parent_state(parent_key: str, retries: int, retry_delay: float) -> dict:
    last_error = None
    for attempt in range(retries + 1):
        try:
            return parent_info(parent_key)
        except (ZoteroUnavailable, ZoteroBridgeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(retry_delay)
    raise RuntimeError(
        f"Unable to read final Zotero state for {parent_key}: {last_error}"
    )


def _child_failed_operationally(
    child_result: dict,
    attempts: list[dict],
    reconcile_only: bool,
) -> bool:
    if reconcile_only:
        return False
    if child_result.get("route") in {"command-error", "command-timeout"}:
        return True
    return bool(attempts and attempts[-1]["exitCode"] not in (0, 3, 4, 9))


def _child_route(child_result: dict) -> str:
    return (
        child_result.get("route")
        or child_result.get("adoption", {}).get("route")
        or "unknown"
    )


def _interactive_block_reason(title: str) -> str | None:
    normalized = " ".join(title.casefold().split())
    indicators = {
        "just a moment": "anti-bot challenge",
        "verify you are human": "human-verification challenge",
        "checking your browser": "anti-bot challenge",
        "access denied": "access-denied page",
        "sign in": "sign-in page",
        "log in": "login page",
    }
    return next(
        (reason for marker, reason in indicators.items() if marker in normalized),
        None,
    )


def _batch_retrieval_attempt(
    parent_key: str,
    url: str,
    args: argparse.Namespace,
) -> tuple[int, dict]:
    if url:
        save_args = argparse.Namespace(
            parent_key=parent_key,
            browser=args.browser,
            url=url,
            keep_tab=False,
            load_wait=args.load_wait,
            title_contains=None,
            timeout=args.timeout,
            settle=args.settle,
            skip_native=args.skip_native,
            native_wait=args.native_wait,
            json=True,
        )
        return _execute_save(save_args, open_url=True)
    if args.skip_native:
        return 4, {"ok": False, "route": "no-url", "parentKey": parent_key}

    result = find_available_pdf(parent_key, wait_seconds=args.native_wait)
    if result["ok"]:
        result["sync"] = sync_library()
        return 0, result
    return 4, result


def command_batch_csv(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv).expanduser().resolve()
    if not csv_path.is_file():
        raise RuntimeError(f"CSV file not found: {csv_path}")
    if args.retries < 0:
        raise RuntimeError("--retries must be zero or greater")
    if min(
        args.retry_delay,
        args.pause,
        args.load_wait,
        args.timeout,
        args.settle,
        args.native_wait,
    ) < 0:
        raise RuntimeError("batch timing options must be zero or greater")
    report_path = (
        Path(args.report_file).expanduser().resolve()
        if args.report_file
        else csv_path.with_name(f"{csv_path.stem}.zotero-connector-report.json")
    )
    log_path = (
        Path(args.log_file).expanduser().resolve()
        if args.log_file
        else csv_path.with_name(f"{csv_path.stem}.zotero-connector-runs.jsonl")
    )
    run_id = (
        f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-"
        f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    )

    with _single_batch_instance(csv_path):
        ping()
        bridge_ping()
        with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fieldnames = reader.fieldnames or []
            rows = list(reader)
        if not rows:
            raise RuntimeError(f"CSV has no records: {csv_path}")
        if args.key_column not in fieldnames:
            raise RuntimeError(f"CSV has no {args.key_column!r} column")
        if args.update_csv and args.status_column not in fieldnames:
            raise RuntimeError(
                f"CSV has no {args.status_column!r} column required by --update-csv"
            )

        selected = [
            row
            for row in rows
            if not args.status_value
            or row.get(args.status_column, "") == args.status_value
        ]
        results = []
        started_at = _timestamp()

        def checkpoint(finished: bool = False) -> dict:
            operational_errors = sum(
                bool(result.get("operationalError")) for result in results
            )
            report = {
                "ok": all(result["ok"] for result in results)
                and not operational_errors,
                "finished": finished,
                "runId": run_id,
                "startedAt": started_at,
                "updatedAt": _timestamp(),
                "executionMode": "single-process-serial",
                "csv": str(csv_path),
                "reportFile": str(report_path),
                "logFile": str(log_path),
                "selected": len(selected),
                "processed": len(results),
                "withPDF": sum(result["ok"] for result in results),
                "withoutPDF": sum(
                    not result["ok"] and not result.get("operationalError")
                    for result in results
                ),
                "interactiveRequired": sum(
                    result.get("route") == "interactive-required"
                    for result in results
                ),
                "operationalErrors": operational_errors,
                "results": results,
            }
            _write_json_atomic(report_path, report)
            return report

        _append_json_line(
            log_path,
            {
                "event": "run-start",
                "runId": run_id,
                "at": started_at,
                "csv": str(csv_path),
                "selected": len(selected),
            },
        )
        checkpoint()

        for index, row in enumerate(selected, start=1):
            parent_key = row.get(args.key_column, "").strip()
            url = row.get(args.url_column, "").strip()
            if not parent_key:
                result = {
                    "index": index,
                    "ok": False,
                    "route": "invalid-row",
                    "error": f"missing {args.key_column}",
                    "operationalError": True,
                    "attachments": [],
                    "collections": [],
                    "attempts": [],
                }
                results.append(result)
                _append_json_line(
                    log_path,
                    {"event": "item", "runId": run_id, "at": _timestamp(), **result},
                )
                checkpoint()
                continue

            child_result = {
                "ok": False,
                "route": "reconcile-only" if args.reconcile_only else "not-run",
                "parentKey": parent_key,
            }
            attempts = []
            max_attempts = 1 if args.reconcile_only else args.retries + 1
            for attempt in range(1, max_attempts + 1):
                if args.reconcile_only:
                    break
                try:
                    exit_code, child_result = _batch_retrieval_attempt(
                        parent_key,
                        url,
                        args,
                    )
                    attempts.append(
                        {
                            "attempt": attempt,
                            "exitCode": exit_code,
                            "result": child_result,
                        }
                    )
                    if exit_code in (0, 3, 4, 8, 9):
                        break
                except (RuntimeError, ZoteroUnavailable, ZoteroBridgeError) as exc:
                    child_result = {
                        "ok": False,
                        "route": "command-error",
                        "error": str(exc),
                    }
                    attempts.append(
                        {
                            "attempt": attempt,
                            "exitCode": None,
                            "result": child_result,
                        }
                    )
                if attempt < max_attempts:
                    time.sleep(args.retry_delay)

            try:
                final = _final_parent_state(
                    parent_key,
                    retries=args.retries,
                    retry_delay=args.retry_delay,
                )
            except RuntimeError as exc:
                result = {
                    "index": index,
                    "ok": False,
                    "parentKey": parent_key,
                    "title": row.get("title", ""),
                    "route": "final-state-error",
                    "error": str(exc),
                    "operationalError": True,
                    "attachments": [],
                    "collections": [],
                    "attempts": attempts,
                }
                results.append(result)
                _append_json_line(
                    log_path,
                    {"event": "item", "runId": run_id, "at": _timestamp(), **result},
                )
                checkpoint()
                continue

            final_pdfs = [
                attachment
                for attachment in final["attachments"]
                if attachment["isPDF"]
                and not attachment["deleted"]
                and attachment["exists"]
            ]
            result = {
                "index": index,
                "ok": bool(final_pdfs),
                "parentKey": parent_key,
                "title": final["title"],
                "route": (
                    "final-state-pdf" if final_pdfs else _child_route(child_result)
                ),
                "attachments": final_pdfs,
                "collections": final["collections"],
                "attempts": attempts,
            }
            if child_result.get("cleanupOk") is False:
                result["operationalError"] = True
                result["error"] = child_result.get(
                    "tabCloseError", "temporary browser window cleanup failed"
                )
            elif (
                not final_pdfs
                and _child_failed_operationally(
                    child_result,
                    attempts,
                    reconcile_only=args.reconcile_only,
                )
            ):
                result["operationalError"] = True
                result["error"] = child_result.get(
                    "error", "child command failed before a conclusive result"
                )

            if final_pdfs and args.update_csv:
                attachment = final_pdfs[0]
                path = Path(attachment["path"])
                try:
                    sha256 = _file_sha256(path)
                except OSError as exc:
                    result["ok"] = False
                    result["route"] = "attachment-read-error"
                    result["error"] = str(exc)
                    result["operationalError"] = True
                else:
                    if args.status_column in row:
                        row[args.status_column] = args.success_status
                    if "local_pdf" in row:
                        row["local_pdf"] = str(path)
                    if "sha256" in row:
                        row["sha256"] = sha256
                    _write_csv_atomic(csv_path, rows)

            results.append(result)
            _append_json_line(
                log_path,
                {"event": "item", "runId": run_id, "at": _timestamp(), **result},
            )
            checkpoint()
            if args.pause and index < len(selected):
                time.sleep(args.pause)

        report = checkpoint(finished=True)
        _append_json_line(
            log_path,
            {
                "event": "run-finish",
                "runId": run_id,
                "at": _timestamp(),
                "processed": report["processed"],
                "withPDF": report["withPDF"],
                "withoutPDF": report["withoutPDF"],
                "interactiveRequired": report["interactiveRequired"],
                "operationalErrors": report["operationalErrors"],
            },
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"Processed {report['processed']} items: "
            f"{report['withPDF']} with PDFs, "
            f"{report['withoutPDF']} without PDFs, "
            f"{report['operationalErrors']} operational errors."
        )
        print(f"Report: {report_path}")
        print(f"Run log: {log_path}")
        for result in results:
            if result.get("operationalError"):
                state_label = "ERROR"
            elif result.get("route") == "interactive-required":
                state_label = "LOGIN"
            else:
                state_label = "PDF" if result["ok"] else "NO PDF"
            collections = ", ".join(
                collection["name"] for collection in result["collections"]
            )
            print(
                f"- {state_label} {result.get('parentKey', '(missing key)')}: "
                f"{result.get('title', '')} [{collections or 'no collection'}]"
            )
    if report["operationalErrors"]:
        return 7
    return 0 if report["withoutPDF"] == 0 else 6


def _execute_save(args: argparse.Namespace, open_url: bool) -> tuple[int, dict]:
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
        return 0, result

    if not args.skip_native:
        native = find_available_pdf(args.parent_key, wait_seconds=args.native_wait)
        if native["ok"]:
            native["sync"] = sync_library()
            return 0, native

    browser = _choose_browser(args.browser)
    before = state()
    temporary_window = None
    result = None
    tab_close_error = None
    try:
        if open_url:
            temporary_window = _open_url(browser, args.url)
            time.sleep(args.load_wait)
            window = next(
                (
                    candidate
                    for candidate in list_windows()
                    if candidate.hwnd == temporary_window.hwnd
                ),
                temporary_window,
            )
            if (
                args.title_contains
                and args.title_contains.casefold() not in window.title.casefold()
            ):
                raise RuntimeError(
                    "Temporary browser window title does not contain "
                    f"{args.title_contains!r}: {window.title}"
                )
        else:
            window = find_browser_window(
                BROWSER_PROCESSES[browser], title_contains=args.title_contains
            )

        block_reason = _interactive_block_reason(window.title) if open_url else None
        if block_reason:
            result = {
                "ok": False,
                "route": "interactive-required",
                "interactiveRequired": True,
                "reason": block_reason,
                "browser": browser,
                "windowTitle": window.title,
                "parentKey": args.parent_key,
                "url": args.url,
            }
        else:
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
            if not changed:
                result["route"] = "connector-no-changes"
            changed_parent_keys = [
                item["key"]
                for item in changed
                if not item.get("data", {}).get("parentItem")
                and item.get("data", {}).get("itemType") != "attachment"
            ]
            candidate_keys = list(
                dict.fromkeys(
                    [
                        *changed_parent_keys,
                        *sorted(after.keys.difference(before.keys)),
                    ]
                )
            )
            if changed:
                result["adoption"] = adopt_connector_pdf(
                    args.parent_key, candidate_keys
                )
                result["ok"] = bool(result["adoption"]["ok"])
                if result["ok"] or result["adoption"].get("duplicateTrashed"):
                    result["sync"] = sync_library()
    finally:
        if open_url and temporary_window and not args.keep_tab:
            try:
                _close_temporary_browser_window(temporary_window)
            except (RuntimeError, OSError) as exc:
                tab_close_error = str(exc)

    result["tabClosed"] = bool(
        open_url and temporary_window and not args.keep_tab and not tab_close_error
    )
    result["browserWindowClosed"] = result["tabClosed"]
    result["cleanupOk"] = not tab_close_error
    if tab_close_error:
        result["tabCloseError"] = tab_close_error
        return 8, result
    if result.get("interactiveRequired"):
        return 9, result
    return (0 if result["ok"] else 3), result


def _run_save(args: argparse.Namespace, open_url: bool) -> int:
    exit_code, result = _execute_save(args, open_url=open_url)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result.get("route") == "already-present":
        print(
            f"Canonical Zotero item {result['parentKey']} already has a PDF."
        )
    elif result.get("route") == "native-find-pdf" and result.get("ok"):
        print(
            f"PDF attached directly to canonical Zotero item "
            f"{result['parentKey']} via native Find Available PDF."
        )
    elif result.get("interactiveRequired"):
        print(
            f"Interactive access is required for {result['parentKey']}: "
            f"{result['reason']} ({result['windowTitle']}).",
            file=sys.stderr,
        )
    elif result.get("adoption", {}).get("ok"):
        adoption = result["adoption"]
        print(
            f"PDF attached to canonical Zotero item {adoption['parentKey']}; "
            f"temporary duplicate {adoption['duplicateKey']} moved to Zotero Trash."
        )
        print(
            f"- attachment: {adoption['attachment']['path']} "
            f"[{adoption['attachment']['key']}]"
        )
    elif result.get("adoption", {}).get("duplicateTrashed"):
        adoption = result["adoption"]
        print(
            f"The Connector produced no usable matching PDF for canonical item "
            f"{adoption['parentKey']}; temporary item {adoption['duplicateKey']} "
            "and its snapshots were moved to Zotero Trash.",
            file=sys.stderr,
        )
    else:
        print(
            "No Zotero changes detected. Confirm that the target browser has the "
            "Connector installed and Ctrl+Shift+S is assigned to Save to Zotero.",
            file=sys.stderr,
        )
    return exit_code


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
            "--keep-tab",
            action="store_true",
            help="leave the isolated temporary browser window open after the save",
        )
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

    attach_file = subparsers.add_parser(
        "attach-file",
        help="attach a downloaded PDF directly to an existing Zotero item",
    )
    attach_file.add_argument(
        "--parent-key", required=True, help="canonical Zotero item key"
    )
    attach_file.add_argument("--file", required=True, help="local PDF path")
    attach_file.add_argument(
        "--wait",
        type=float,
        default=8.0,
        help="seconds to wait for attachment post-processing",
    )
    attach_file.add_argument("--json", action="store_true", help="emit JSON")
    attach_file.set_defaults(func=command_attach_file)

    batch_csv = subparsers.add_parser(
        "batch-csv",
        help="process Zotero parent keys and access URLs from a CSV without a model",
    )
    batch_csv.add_argument("--csv", required=True, help="input CSV path")
    batch_csv.add_argument("--browser", choices=list(BROWSER_PROCESSES), default="edge")
    batch_csv.add_argument("--key-column", default="zotero_key")
    batch_csv.add_argument("--url-column", default="access_url")
    batch_csv.add_argument("--status-column", default="status")
    batch_csv.add_argument("--status-value", default="missing_pdf")
    batch_csv.add_argument("--success-status", default="in_zotero")
    batch_csv.add_argument("--update-csv", action="store_true")
    batch_csv.add_argument(
        "--reconcile-only",
        action="store_true",
        help="skip retrieval and update/report from current Zotero state",
    )
    batch_csv.add_argument("--skip-native", action="store_true")
    batch_csv.add_argument("--retries", type=int, default=2)
    batch_csv.add_argument("--retry-delay", type=float, default=5.0)
    batch_csv.add_argument("--pause", type=float, default=2.0)
    batch_csv.add_argument("--load-wait", type=float, default=12.0)
    batch_csv.add_argument("--timeout", type=float, default=100.0)
    batch_csv.add_argument("--settle", type=float, default=10.0)
    batch_csv.add_argument("--native-wait", type=float, default=8.0)
    batch_csv.add_argument(
        "--report-file",
        help="durable atomic JSON checkpoint (default: beside the CSV)",
    )
    batch_csv.add_argument(
        "--log-file",
        help="append-only JSONL run log (default: beside the CSV)",
    )
    batch_csv.add_argument("--json", action="store_true")
    batch_csv.set_defaults(func=command_batch_csv)

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
