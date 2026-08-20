"""Import a directory of per-stream .bib files into an existing project.

The parsing, item typing, creator handling, duplicate matching and planning
all live in zotero-core, shared with the other tools that write to the same
library. What is left here is the connector's own contract: the project
collection must already exist, and the result keeps the exact shape
``command_import_bib`` and the recorded run reports expect.
"""

from __future__ import annotations

from pathlib import Path

from zotero_core.backends.desktop import DesktopBridgeBackend
from zotero_core.bib import load_bib_directory as _load_bib_directory
from zotero_core.plan import (
    ADD_EXISTING,
    ALREADY_PRESENT,
    CREATE,
    NEEDS_REVIEW,
    PRESERVE_EXISTING_LEAF,
    apply_plan,
    plan_import,
)
from zotero_core.bib import load_bib_streams

#: Kept as a re-export so the parity harness and any caller keep working.
load_bib_directory = _load_bib_directory

_COUNT_NAMES = {
    CREATE: "create",
    ADD_EXISTING: "addExisting",
    ALREADY_PRESENT: "alreadyPresent",
    PRESERVE_EXISTING_LEAF: "preservedElsewhere",
    NEEDS_REVIEW: "needsReview",
}


def _counts(plan) -> dict[str, int]:
    counts = plan.counts
    return {name: counts.get(action, 0) for action, name in _COUNT_NAMES.items()}


def _result(plan) -> dict:
    payload = plan.to_dict()
    return {
        "ok": plan.ok,
        "applied": plan.applied,
        "parentKey": plan.parent_key,
        "parentName": plan.parent_name,
        "parsed": plan.parsed,
        "counts": _counts(plan),
        "collections": payload["collections"],
        "conflicts": payload["conflicts"],
        "plan": payload["plan"],
    }


def import_bib_directory(
    bib_dir: str | Path,
    parent_name: str,
    *,
    apply: bool = False,
) -> dict:
    works = load_bib_streams(bib_dir)
    backend = DesktopBridgeBackend()
    plan = plan_import(works, parent_name, backend=backend, require_parent=True)
    if plan.ok and apply:
        apply_plan(plan, backend)
    return _result(plan)
