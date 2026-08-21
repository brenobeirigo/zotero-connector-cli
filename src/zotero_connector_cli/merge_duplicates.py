"""Repair works the library already holds more than once.

The grouping, the choice of which copy survives, and the safety checks all
live in zotero-core, shared with the importer that refuses to create these
duplicates in the first place. What is left here is the connector's own
contract: the repair runs through Zotero Desktop and the CLI Bridge, because
merging moves child items and records a replacement relation, and no other
route can do that.

A plan is written before anything is touched and can be edited by hand. That
is the point: title matches are never merged on the tool's own authority, and
an artifact that is not a work at all -- a saved database landing page, say --
is something only a person can recognise.
"""

from __future__ import annotations

import json
from pathlib import Path

from zotero_core.backends.desktop import DesktopBridgeBackend
from zotero_core.dedup import (
    MERGE,
    REVIEW,
    SKIP,
    TRASH,
    MergePlan,
    apply_merge_plan,
    find_duplicates,
    review_backlog,
)

__all__ = [
    "MERGE",
    "REVIEW",
    "SKIP",
    "TRASH",
    "apply_duplicates_plan",
    "load_plan",
    "save_plan",
    "scan_duplicates",
    "summarize",
]


def scan_duplicates(*, backend=None) -> MergePlan:
    """Snapshot the library and group it into duplicate sets."""
    backend = backend or DesktopBridgeBackend()
    return find_duplicates(backend.snapshot_library())


def load_plan(path: str | Path) -> MergePlan:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    plan = MergePlan.from_dict(payload)
    if plan.applied:
        raise ValueError(
            f"{path} records a plan that was already applied; re-scan instead of "
            "replaying it, or the merged-away keys will no longer resolve"
        )
    plan.validate()
    return plan


def save_plan(plan: MergePlan, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def apply_duplicates_plan(plan: MergePlan, *, backend=None) -> MergePlan:
    """Write the plan. Refuses a plan that does not pass its own checks."""
    backend = backend or DesktopBridgeBackend()
    return apply_merge_plan(plan, backend)


def summarize(plan: MergePlan) -> dict:
    """The shape the CLI prints and the recorded reports keep."""
    counts = plan.counts
    return {
        "ok": True,
        "applied": plan.applied,
        "librarySize": plan.library_size,
        "groups": len(plan.groups),
        "counts": {
            "merge": counts[MERGE],
            "trash": counts[TRASH],
            "review": counts[REVIEW],
            "skip": counts[SKIP],
        },
        "itemsRemoved": plan.items_removed,
        "reviewGroups": [
            {
                "rule": group.rule,
                "title": group.title,
                "keys": group.keys,
                "reason": group.reason,
            }
            for group in review_backlog(plan)
        ],
    }
