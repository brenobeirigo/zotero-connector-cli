from __future__ import annotations

import json
import urllib.error
import urllib.request

from .zotero import CONNECTOR_BASE, ZoteroUnavailable


class ZoteroBridgeError(RuntimeError):
    pass


def evaluate(script: str, timeout: float = 120.0):
    request = urllib.request.Request(
        CONNECTOR_BASE + "/cli-bridge/eval",
        data=script.encode("utf-8"),
        headers={
            "Content-Type": "text/plain",
            "User-Agent": "zotero-connector-cli/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            error = json.loads(body)
        except json.JSONDecodeError:
            error = {"error": body or str(exc)}
        raise ZoteroBridgeError(error.get("error", str(exc))) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ZoteroUnavailable(
            "Zotero CLI Bridge is not reachable at 127.0.0.1:23119"
        ) from exc

    if isinstance(payload, dict) and payload.get("error"):
        raise ZoteroBridgeError(payload["error"])
    return payload


def bridge_ping() -> dict:
    return evaluate(
        'return {version: Zotero.version, libraryID: Zotero.Libraries.userLibraryID};',
        timeout=10,
    )


def sync_library() -> dict:
    return evaluate(
        """
const started = Date.now();
await Zotero.Sync.Runner.sync({background: true});
return {ok: true, elapsedMs: Date.now() - started};
""",
        timeout=120,
    )


def parent_info(parent_key: str) -> dict:
    key = json.dumps(parent_key)
    return evaluate(
        f"""
const item = Zotero.Items.getByLibraryAndKey(Zotero.Libraries.userLibraryID, {key});
if (!item) throw new Error("Parent item not found: " + {key});
const attachments = [];
for (const id of item.getAttachments()) {{
    const attachment = Zotero.Items.get(id);
    attachments.push({{
        key: attachment.key,
        title: attachment.getField("title"),
        isPDF: attachment.isPDFAttachment(),
        linkMode: attachment.attachmentLinkMode,
        path: await attachment.getFilePathAsync(),
        exists: await attachment.fileExists(),
        deleted: attachment.deleted,
        annotations: attachment.getAnnotations().length
    }});
}}
const collections = item.getCollections().map(id => {{
    const collection = Zotero.Collections.get(id);
    return {{key: collection.key, name: collection.name}};
}});
return {{
    key: item.key,
    title: item.getField("title"),
    DOI: Zotero.Utilities.cleanDOI(item.getField("DOI") || item.getExtraField("DOI")),
    date: item.getField("date"),
    deleted: item.deleted,
    itemType: item.itemType,
    attachments,
    collections
}};
""",
        timeout=20,
    )


def find_available_pdf(parent_key: str, wait_seconds: float = 8.0) -> dict:
    key = json.dumps(parent_key)
    wait_ms = max(0, int(wait_seconds * 1000))
    return evaluate(
        f"""
const item = Zotero.Items.getByLibraryAndKey(Zotero.Libraries.userLibraryID, {key});
if (!item) throw new Error("Parent item not found: " + {key});
if (item.deleted) throw new Error("Parent item is in Zotero Trash");
if (!item.isRegularItem()) throw new Error("Target is not a regular bibliographic item");
const existingPDFs = item.getAttachments()
    .map(id => Zotero.Items.get(id))
    .filter(attachment => attachment.isPDFAttachment() && !attachment.deleted);
if (existingPDFs.length) {{
    return {{
        ok: true,
        route: "already-present",
        parentKey: item.key,
        attachmentKeys: existingPDFs.map(attachment => attachment.key)
    }};
}}
if (!Zotero.Attachments.canFindPDFForItem(item)) {{
    return {{ok: false, route: "native-find-pdf", eligible: false, parentKey: item.key}};
}}
const attachment = await Zotero.Attachments.addAvailablePDF(item);
if (!attachment) {{
    return {{ok: false, route: "native-find-pdf", eligible: true, parentKey: item.key}};
}}
await Zotero.Promise.delay({wait_ms});
const refreshed = Zotero.Items.getByLibraryAndKey(Zotero.Libraries.userLibraryID, {key});
const attachments = [];
for (const id of refreshed.getAttachments()) {{
    const current = Zotero.Items.get(id);
    if (!current.isPDFAttachment() || current.deleted) continue;
    attachments.push({{
        key: current.key,
        linkMode: current.attachmentLinkMode,
        path: await current.getFilePathAsync(),
        exists: await current.fileExists(),
        annotations: current.getAnnotations().length
    }});
}}
return {{
    ok: attachments.some(current => current.exists),
    route: "native-find-pdf",
    eligible: true,
    parentKey: item.key,
    attachments
}};
""",
        timeout=150,
    )


def adopt_connector_pdf(parent_key: str, candidate_keys: list[str]) -> dict:
    parent = json.dumps(parent_key)
    candidates = json.dumps(candidate_keys)
    return evaluate(
        f"""
const parent = Zotero.Items.getByLibraryAndKey(Zotero.Libraries.userLibraryID, {parent});
if (!parent) throw new Error("Canonical parent item not found: " + {parent});
if (parent.deleted) throw new Error("Canonical parent item is in Zotero Trash");
if (!parent.isRegularItem()) throw new Error("Canonical parent is not a regular item");

const cleanDOI = item => Zotero.Utilities.cleanDOI(
    item.getField("DOI") || item.getExtraField("DOI") || ""
).toLowerCase();
const normalizeTitle = value => value
    .normalize("NFKD")
    .replace(/[\\u0300-\\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
const year = item => {{
    const parsed = Zotero.Date.strToDate(item.getField("date") || "");
    return parsed && parsed.year ? String(parsed.year) : "";
}};

const parentDOI = cleanDOI(parent);
const parentTitle = normalizeTitle(parent.getField("title"));
const parentYear = year(parent);
const originalCollectionIDs = [...parent.getCollections()].sort((a, b) => a - b);
const currentPDFs = parent.getAttachments()
    .map(id => Zotero.Items.get(id))
    .filter(attachment => attachment.isPDFAttachment() && !attachment.deleted);
if (currentPDFs.length) {{
    throw new Error("Canonical parent already has a PDF attachment");
}}

const matches = [];
for (const key of {candidates}) {{
    const candidate = Zotero.Items.getByLibraryAndKey(parent.libraryID, key);
    if (!candidate || candidate.deleted || !candidate.isRegularItem() || candidate.id === parent.id) {{
        continue;
    }}
    const candidateDOI = cleanDOI(candidate);
    const doiMatch = parentDOI && candidateDOI && parentDOI === candidateDOI;
    const titleMatch = parentTitle
        && parentTitle === normalizeTitle(candidate.getField("title"))
        && (!parentYear || !year(candidate) || parentYear === year(candidate));
    if (!doiMatch && !titleMatch) continue;
    const pdfs = candidate.getAttachments()
        .map(id => Zotero.Items.get(id))
        .filter(attachment => attachment.isPDFAttachment() && !attachment.deleted);
    if (pdfs.length) matches.push({{candidate, pdfs, doiMatch, titleMatch}});
}}

if (matches.length !== 1) {{
    throw new Error("Expected exactly one exact duplicate with a PDF; found " + matches.length);
}}
if (matches[0].pdfs.length !== 1) {{
    throw new Error("Expected exactly one PDF on the temporary duplicate; found " + matches[0].pdfs.length);
}}

const duplicate = matches[0].candidate;
const attachment = matches[0].pdfs[0];
const path = await attachment.getFilePathAsync();
if (!path || !(await attachment.fileExists())) {{
    throw new Error("Temporary duplicate PDF does not resolve to a local file");
}}
const header = await IOUtils.read(path, {{maxBytes: 5}});
const signature = String.fromCharCode(...header);
if (signature !== "%PDF-") {{
    throw new Error("Temporary duplicate attachment is not a valid PDF");
}}
if (attachment.getAnnotations().length) {{
    throw new Error("Refusing to move an unexpectedly annotated temporary attachment");
}}

await Zotero.DB.executeTransaction(async () => {{
    attachment.parentID = parent.id;
    await attachment.save();
    duplicate.deleted = true;
    await duplicate.save();
}});

const refreshedParent = Zotero.Items.getByLibraryAndKey(parent.libraryID, parent.key);
const moved = Zotero.Items.getByLibraryAndKey(parent.libraryID, attachment.key);
const refreshedDuplicate = Zotero.Items.getByLibraryAndKey(parent.libraryID, duplicate.key);
const finalCollectionIDs = [...refreshedParent.getCollections()].sort((a, b) => a - b);
if (JSON.stringify(originalCollectionIDs) !== JSON.stringify(finalCollectionIDs)) {{
    throw new Error("Canonical parent collection memberships changed unexpectedly");
}}
const collections = finalCollectionIDs.map(id => {{
    const collection = Zotero.Collections.get(id);
    return {{key: collection.key, name: collection.name}};
}});
const temporaryChildrenLeftInTrash = [];
for (const id of refreshedDuplicate.getAttachments(true)) {{
    const child = Zotero.Items.get(id);
    temporaryChildrenLeftInTrash.push({{
        key: child.key,
        title: child.getField("title"),
        contentType: child.attachmentContentType,
        linkMode: child.attachmentLinkMode,
        deleted: child.deleted
    }});
}}
return {{
    ok: moved.parentID === refreshedParent.id
        && refreshedDuplicate.deleted
        && await moved.fileExists(),
    route: "connector-adopt",
    parentKey: refreshedParent.key,
    duplicateKey: refreshedDuplicate.key,
    duplicateTrashed: refreshedDuplicate.deleted,
    collections,
    collectionMembershipsPreserved:
        JSON.stringify(originalCollectionIDs) === JSON.stringify(finalCollectionIDs),
    temporaryChildrenLeftInTrash,
    attachment: {{
        key: moved.key,
        linkMode: moved.attachmentLinkMode,
        path: await moved.getFilePathAsync(),
        exists: await moved.fileExists(),
        annotations: moved.getAnnotations().length
    }},
    match: {{
        DOI: matches[0].doiMatch,
        title: matches[0].titleMatch
    }}
}};
""",
        timeout=60,
    )
