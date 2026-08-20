from __future__ import annotations

import json
import re
import subprocess
import uuid
from pathlib import Path

from zotero_core.hashing import file_sha256
from urllib.parse import urlsplit


class RemoteFetchError(RuntimeError):
    """Raised when the SSH retrieval host cannot return a usable PDF."""


_SSH_HOST = re.compile(
    r"^(?:[A-Za-z0-9_.-]+@)?(?:[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)$"
)
_BLOCKED_SOURCE_MARKERS = (
    "annas-archive",
    "libgen",
    "library-genesis",
    "sci-hub",
    "z-lib",
    "zlibrary",
)


def validate_remote_host(host: str) -> str:
    normalized = host.strip()
    if not normalized or not _SSH_HOST.fullmatch(normalized):
        raise RemoteFetchError(
            "remote host must be a plain OpenSSH target such as user@hostname"
        )
    return normalized


def validate_remote_url(url: str) -> str:
    normalized = url.strip()
    parsed = urlsplit(normalized)
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        raise RemoteFetchError("remote_url must be an absolute HTTPS URL")
    if parsed.username or parsed.password:
        raise RemoteFetchError("remote_url must not contain embedded credentials")
    hostname = parsed.hostname.casefold().rstrip(".")
    if any(marker in hostname for marker in _BLOCKED_SOURCE_MARKERS):
        raise RemoteFetchError(
            "remote_url points to a blocked unauthorized-copy source"
        )
    return normalized


def public_remote_url(url: str) -> str:
    parsed = urlsplit(validate_remote_url(url))
    return parsed._replace(query="", fragment="").geturl()


def _ssh_command(host: str, connect_timeout: float) -> list[str]:
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={max(1, int(connect_timeout))}",
        host,
    ]


def probe_remote_host(host: str, connect_timeout: float = 10.0) -> dict:
    target = validate_remote_host(host)
    completed = subprocess.run(
        [*_ssh_command(target, connect_timeout), "python3", "-"],
        input="print('ok')\n",
        capture_output=True,
        text=True,
        timeout=max(5.0, connect_timeout + 5.0),
        check=False,
    )
    if completed.returncode != 0 or completed.stdout.strip() != "ok":
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RemoteFetchError(
            f"SSH retrieval host {target!r} is unavailable: {detail or 'probe failed'}"
        )
    return {"ok": True, "host": target}


def _remote_download_script(url: str, remote_path: str, timeout: float) -> str:
    return f"""
import hashlib
import json
import pathlib
import subprocess

url = {json.dumps(url)}
path = pathlib.Path({json.dumps(remote_path)})
command = [
    "curl", "--fail", "--location", "--silent", "--show-error",
    "--proto", "=https", "--max-time", {json.dumps(str(max(1, int(timeout))))},
    "--output", str(path), url,
]
completed = subprocess.run(command, capture_output=True, text=True, check=False)
if completed.returncode != 0:
    path.unlink(missing_ok=True)
    print(json.dumps({{"ok": False, "error": completed.stderr.strip() or "curl failed"}}))
    raise SystemExit(completed.returncode)
with path.open("rb") as stream:
    header = stream.read(5)
if header != b"%PDF-":
    path.unlink(missing_ok=True)
    print(json.dumps({{"ok": False, "error": "remote response is not a PDF"}}))
    raise SystemExit(4)
digest = hashlib.sha256()
with path.open("rb") as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
print(json.dumps({{"ok": True, "path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest().upper()}}))
""".strip()


def _remote_cleanup_script(remote_path: str) -> str:
    return (
        "import pathlib\n"
        f"pathlib.Path({json.dumps(remote_path)}).unlink(missing_ok=True)\n"
    )


def fetch_pdf_over_ssh(
    host: str,
    url: str,
    destination: Path,
    *,
    timeout: float = 180.0,
    connect_timeout: float = 10.0,
) -> dict:
    target = validate_remote_host(host)
    source_url = validate_remote_url(url)
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise RemoteFetchError(f"refusing to overwrite staging file: {destination}")

    remote_path = f"/tmp/zotero-connector-{uuid.uuid4().hex}.pdf"
    remote_result = None
    try:
        completed = subprocess.run(
            [*_ssh_command(target, connect_timeout), "python3", "-"],
            input=_remote_download_script(source_url, remote_path, timeout),
            capture_output=True,
            text=True,
            timeout=max(15.0, timeout + connect_timeout + 15.0),
            check=False,
        )
        output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if output_lines:
            try:
                remote_result = json.loads(output_lines[-1])
            except json.JSONDecodeError:
                remote_result = None
        if completed.returncode != 0 or not remote_result or not remote_result.get("ok"):
            detail = (
                (remote_result or {}).get("error")
                or completed.stderr.strip()
                or "remote download failed"
            )
            raise RemoteFetchError(detail)

        copied = subprocess.run(
            [
                "scp",
                "-q",
                "-o",
                "BatchMode=yes",
                "-o",
                f"ConnectTimeout={max(1, int(connect_timeout))}",
                f"{target}:{remote_path}",
                str(destination),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=max(15.0, timeout + connect_timeout),
            check=False,
        )
        if copied.returncode != 0:
            raise RemoteFetchError(copied.stderr.strip() or "SCP transfer failed")
        if not destination.is_file() or destination.read_bytes()[:5] != b"%PDF-":
            raise RemoteFetchError("transferred file is not a PDF")
        local_sha = file_sha256(destination, uppercase=True)
        if local_sha != remote_result["sha256"]:
            raise RemoteFetchError("remote/local SHA-256 mismatch")
        return {
            "ok": True,
            "host": target,
            "sourceUrl": public_remote_url(source_url),
            "remotePath": remote_path,
            "localPath": str(destination),
            "bytes": destination.stat().st_size,
            "sha256": local_sha,
        }
    except Exception:
        if destination.exists():
            destination.unlink()
        raise
    finally:
        try:
            subprocess.run(
                [*_ssh_command(target, connect_timeout), "python3", "-"],
                input=_remote_cleanup_script(remote_path),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=max(5.0, connect_timeout + 5.0),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
