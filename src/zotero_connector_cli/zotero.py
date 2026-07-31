from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


CONNECTOR_BASE = "http://127.0.0.1:23119"


class ZoteroUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ApiState:
    version: int
    keys: frozenset[str]


def _request(path: str, timeout: float = 5.0) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(
        CONNECTOR_BASE + path,
        headers={
            "User-Agent": "zotero-connector-cli/0.1",
            "Zotero-API-Version": "3",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(), dict(response.headers.items())
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ZoteroUnavailable(
            "Zotero Desktop is not reachable at 127.0.0.1:23119"
        ) from exc


def ping() -> str:
    body, _headers = _request("/connector/ping")
    return body.decode("utf-8", errors="replace").strip()


def state(limit: int = 200) -> ApiState:
    body, headers = _request(
        "/api/users/0/items?"
        + urllib.parse.urlencode(
            {
                "sort": "dateModified",
                "direction": "desc",
                "limit": limit,
                "include": "data",
            }
        )
    )
    items = json.loads(body)
    version = int(headers.get("Last-Modified-Version", "0"))
    return ApiState(version=version, keys=frozenset(item["key"] for item in items))


def changed_items(since_version: int, limit: int = 100) -> list[dict]:
    body, _headers = _request(
        "/api/users/0/items?"
        + urllib.parse.urlencode(
            {
                "since": since_version,
                "sort": "dateModified",
                "direction": "desc",
                "limit": limit,
                "include": "data",
            }
        )
    )
    return json.loads(body)


def wait_for_changes(
    before: ApiState,
    timeout: float,
    settle_seconds: float,
    poll_seconds: float = 0.75,
) -> tuple[ApiState, list[dict]]:
    deadline = time.monotonic() + timeout
    last_version = before.version
    last_change_at: float | None = None
    latest = before

    while time.monotonic() < deadline:
        latest = state()
        if latest.version != last_version:
            last_version = latest.version
            last_change_at = time.monotonic()
        if last_change_at is not None and time.monotonic() - last_change_at >= settle_seconds:
            return latest, changed_items(before.version)
        time.sleep(poll_seconds)

    return latest, changed_items(before.version) if latest.version > before.version else []
