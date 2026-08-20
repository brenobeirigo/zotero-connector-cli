from __future__ import annotations

import json
import re
from pathlib import Path

import bibtexparser
from bibtexparser.bparser import BibTexParser

from .privileged import evaluate


TYPE_MAP = {
    "article": "journalArticle",
    "incollection": "bookSection",
    "inbook": "bookSection",
    "inproceedings": "conferencePaper",
    "conference": "conferencePaper",
    "book": "book",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "bachelorthesis": "thesis",
    "thesis": "thesis",
    "techreport": "report",
    "report": "report",
    "online": "webpage",
    "misc": "webpage",
}


def _clean(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[{}]", "", value).strip()


def _authors(value: str | None) -> list[dict[str, str]]:
    creators: list[dict[str, str]] = []
    for raw in re.split(r"\s+and\s+", value or "", flags=re.IGNORECASE):
        name = raw.strip()
        if not name:
            continue
        if name.startswith("{") and name.endswith("}"):
            creators.append(
                {
                    "creatorType": "author",
                    "firstName": "",
                    "lastName": _clean(name),
                    "fieldMode": 1,
                }
            )
            continue
        name = _clean(name)
        if "," in name:
            last, first = (part.strip() for part in name.split(",", 1))
        else:
            parts = name.split()
            first, last = (" ".join(parts[:-1]), parts[-1]) if len(parts) > 1 else ("", parts[0])
        creators.append({"creatorType": "author", "firstName": first, "lastName": last})
    return creators


def _first_creator_match(value: str | None) -> str:
    first = re.split(r"\s+and\s+", value or "", maxsplit=1, flags=re.IGNORECASE)[0].strip()
    if not first:
        return ""
    if first.startswith("{") and first.endswith("}"):
        return _clean(first)
    first = _clean(first)
    if "," in first:
        return first.split(",", 1)[0].strip()
    return first.split()[-1] if first.split() else ""


def _entry_payload(entry: dict[str, str], stream: str) -> dict:
    entry_type = entry.get("ENTRYTYPE", "").casefold()
    item_type = TYPE_MAP.get(entry_type)
    if not item_type:
        raise ValueError(f"unsupported BibTeX type {entry_type!r} for {entry.get('ID')!r}")
    title = _clean(entry.get("title"))
    year = _clean(entry.get("year"))
    if not title or (not year and item_type != "webpage"):
        requirement = "title" if item_type == "webpage" else "title and year"
        raise ValueError(f"BibTeX entry {entry.get('ID')!r} requires {requirement}")

    fields: dict[str, str] = {
        "title": title,
        "date": year,
        "DOI": _clean(entry.get("doi")),
        "url": _clean(entry.get("url")),
        "volume": _clean(entry.get("volume")),
        "pages": _clean(entry.get("pages")).replace("--", "-"),
        "publisher": _clean(entry.get("publisher")),
        "place": _clean(entry.get("address")),
        "series": _clean(entry.get("series")),
        "extra": f"Citation Key: {_clean(entry.get('ID'))}",
    }
    if item_type == "journalArticle":
        fields.update(
            {
                "publicationTitle": _clean(entry.get("journal")),
                "issue": _clean(entry.get("number")),
            }
        )
    elif item_type == "bookSection":
        fields["bookTitle"] = _clean(entry.get("booktitle"))
    elif item_type == "conferencePaper":
        fields["proceedingsTitle"] = _clean(entry.get("booktitle"))
    elif item_type == "thesis":
        fields["university"] = _clean(entry.get("school"))
        if entry_type == "phdthesis":
            thesis_type = "PhD thesis"
        elif entry_type == "mastersthesis":
            thesis_type = "Master's thesis"
        elif entry_type == "bachelorthesis":
            thesis_type = "Bachelor's thesis"
        else:
            thesis_type = _clean(entry.get("type")) or "Thesis"
        fields["thesisType"] = thesis_type
    elif item_type == "report":
        fields["institution"] = _clean(entry.get("institution"))
        fields["reportNumber"] = _clean(entry.get("number"))
    elif item_type == "webpage":
        fields["websiteTitle"] = (
            _clean(entry.get("organization"))
            or _clean(entry.get("publisher"))
            or _clean(entry.get("howpublished"))
        )
        fields["accessDate"] = _clean(entry.get("urldate"))

    return {
        "citationKey": _clean(entry.get("ID")),
        "stream": stream,
        "itemType": item_type,
        "title": title,
        "year": year,
        "doi": _clean(entry.get("doi")),
        "matchCreator": _first_creator_match(entry.get("author")),
        "fields": {key: value for key, value in fields.items() if value},
        "creators": _authors(entry.get("author")),
    }


def load_bib_directory(bib_dir: str | Path) -> list[dict]:
    directory = Path(bib_dir).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f"BibTeX directory does not exist: {directory}")
    payload: list[dict] = []
    seen: set[tuple[str, str]] = set()
    files = sorted(directory.glob("*.bib"), key=lambda path: path.name.casefold())
    if not files:
        raise ValueError(f"No .bib files found in {directory}")
    for path in files:
        parser = BibTexParser(common_strings=True)
        parser.ignore_nonstandard_types = False
        database = bibtexparser.loads(path.read_text(encoding="utf-8"), parser=parser)
        for entry in database.entries:
            item = _entry_payload(entry, path.stem)
            if item["doi"]:
                identity = ("doi", item["doi"].casefold())
            else:
                identity = (
                    "title-year-creator",
                    re.sub(r"\W+", "", item["title"].casefold()),
                    item["year"],
                    re.sub(r"\W+", "", item["matchCreator"].casefold()),
                )
            if identity in seen:
                raise ValueError(f"duplicate staged work in {path.name}: {item['title']}")
            seen.add(identity)
            payload.append(item)
    return payload


def import_bib_directory(
    bib_dir: str | Path,
    parent_name: str,
    *,
    apply: bool = False,
) -> dict:
    entries = load_bib_directory(bib_dir)
    encoded_entries = json.dumps(entries, ensure_ascii=False)
    encoded_parent = json.dumps(parent_name, ensure_ascii=False)
    apply_js = "true" if apply else "false"
    return evaluate(
        f"""
const entries = {encoded_entries};
const parentName = {encoded_parent};
const shouldApply = {apply_js};
const lib = Zotero.Libraries.userLibraryID;
const normalize = value => (value || "")
    .normalize("NFKD")
    .replace(/[\\u0300-\\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
const cleanDOI = value => (Zotero.Utilities.cleanDOI(value || "") || "").toLowerCase();
const yearOf = item => {{
    const parsed = Zotero.Date.strToDate(item.getField("date") || "");
    if (parsed && parsed.year) return String(parsed.year);
    const match = (item.getField("date") || "").match(/\\b(19|20)\\d{{2}}\\b/);
    return match ? match[0] : "";
}};

const parent = Zotero.Collections.getByLibrary(lib, true).find(c => c.name === parentName);
if (!parent) throw new Error("Parent collection not found: " + parentName);
const allCollections = Zotero.Collections.getByLibrary(lib, true);
const descendants = new Set();
let frontier = [parent.id];
while (frontier.length) {{
    const parentID = frontier.shift();
    for (const collection of allCollections.filter(c => c.parentID === parentID)) {{
        if (!descendants.has(collection.id)) {{
            descendants.add(collection.id);
            frontier.push(collection.id);
        }}
    }}
}}

const items = (await Zotero.Items.getAll(lib, true)).filter(
    item => item && typeof item.isRegularItem === "function" && item.isRegularItem() && !item.deleted
);
const byDOI = new Map();
const byTitleYear = new Map();
const byTitleYearCreator = new Map();
for (const item of items) {{
    const doi = cleanDOI(item.getField("DOI") || item.getExtraField("DOI"));
    if (doi) byDOI.set(doi, [...(byDOI.get(doi) || []), item]);
    const key = normalize(item.getField("title")) + "|" + yearOf(item);
    if (key !== "|") byTitleYear.set(key, [...(byTitleYear.get(key) || []), item]);
    const creatorKey = key + "|" + normalize(item.getField("firstCreator"));
    if (key !== "|") byTitleYearCreator.set(creatorKey, [...(byTitleYearCreator.get(creatorKey) || []), item]);
}}

const streamNames = [...new Set(entries.map(entry => entry.stream))].sort();
const streams = new Map();
for (const name of streamNames) {{
    const matches = allCollections.filter(c => c.parentID === parent.id && c.name === name);
    if (matches.length > 1) throw new Error("Duplicate child collections under project: " + name);
    streams.set(name, matches[0] || null);
}}

const plan = [];
const conflicts = [];
for (const entry of entries) {{
    let matches = [];
    const doi = cleanDOI(entry.doi);
    if (doi) matches = byDOI.get(doi) || [];
    if (!matches.length && !doi) {{
        const titleYear = normalize(entry.title) + "|" + entry.year;
        const creator = normalize(entry.matchCreator);
        matches = creator
            ? (byTitleYearCreator.get(titleYear + "|" + creator) || [])
            : (byTitleYear.get(titleYear) || []);
    }}
    if (matches.length > 1) {{
        conflicts.push({{citationKey: entry.citationKey, title: entry.title, reason: "ambiguous-global-match", itemKeys: matches.map(item => item.key)}});
        continue;
    }}
    const existing = matches[0] || null;
    const projectCollections = existing
        ? existing.getCollections().filter(id => id === parent.id || descendants.has(id))
        : [];
    const target = streams.get(entry.stream);
    const inTarget = target && projectCollections.includes(target.id);
    const otherLeaves = projectCollections.filter(id => !target || id !== target.id);
    const otherLeafNames = otherLeaves.map(id => Zotero.Collections.get(id)?.name).filter(Boolean);
    let action = existing ? "add-existing" : "create";
    if (inTarget) action = "already-present";
    else if (otherLeaves.some(id => id !== parent.id)) action = "preserve-existing-project-leaf";
    plan.push({{
        citationKey: entry.citationKey,
        title: entry.title,
        stream: entry.stream,
        action,
        itemKey: existing ? existing.key : null,
        existingProjectCollections: otherLeafNames,
        entry,
    }});
}}
if (conflicts.length) return {{ok: false, applied: false, parentKey: parent.key, parentName, parsed: entries.length, conflicts, plan}};

if (shouldApply) {{
    await Zotero.DB.executeTransaction(async () => {{
        for (const name of streamNames) {{
            if (streams.get(name)) continue;
            const collection = new Zotero.Collection();
            collection.libraryID = lib;
            collection.name = name;
            collection.parentID = parent.id;
            await collection.save();
            streams.set(name, collection);
            descendants.add(collection.id);
        }}
        for (const row of plan) {{
            if (row.action === "already-present" || row.action === "preserve-existing-project-leaf") continue;
            const target = streams.get(row.stream);
            if (row.action === "add-existing") {{
                const item = Zotero.Items.getByLibraryAndKey(lib, row.itemKey);
                const collections = item.getCollections().filter(id => id !== parent.id);
                if (!collections.includes(target.id)) collections.push(target.id);
                item.setCollections(collections);
                await item.save();
                continue;
            }}
            const item = new Zotero.Item(row.entry.itemType);
            item.libraryID = lib;
            for (const [field, value] of Object.entries(row.entry.fields)) {{
                const fieldID = Zotero.ItemFields.getID(field);
                if (fieldID && Zotero.ItemFields.isValidForType(fieldID, item.itemTypeID)) item.setField(field, value);
            }}
            item.setCreators(row.entry.creators);
            item.setCollections([target.id]);
            await item.save();
            row.itemKey = item.key;
        }}
    }});
    await Zotero.Sync.Runner.sync({{background: true}});
}}

const collections = [...streams.entries()].map(([name, collection]) => ({{
    name,
    key: collection ? collection.key : null,
    existed: Boolean(collection),
}}));
const counts = {{create: 0, addExisting: 0, alreadyPresent: 0, preservedElsewhere: 0}};
for (const row of plan) {{
    if (row.action === "create") counts.create++;
    else if (row.action === "add-existing") counts.addExisting++;
    else if (row.action === "already-present") counts.alreadyPresent++;
    else if (row.action === "preserve-existing-project-leaf") counts.preservedElsewhere++;
    delete row.entry;
}}
return {{ok: true, applied: shouldApply, parentKey: parent.key, parentName, parsed: entries.length, counts, collections, conflicts: [], plan}};
""",
        timeout=180,
    )
