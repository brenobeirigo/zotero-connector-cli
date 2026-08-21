"""Gating and scratch-space for the live profile.

Two rules hold everywhere in this package, and they are enforced here rather
than trusted to each test:

1. Nothing runs unless it was asked for. Absent ``ZOTERO_CONNECTOR_LIVE=1``
   every live test skips, so ``pytest`` and ``unittest discover`` stay safe to
   run on any machine, including CI.
2. Nothing touches an item these tests did not create. Every write happens
   inside a scratch collection whose name carries a run token, and teardown
   trashes exactly what it made.
"""

from __future__ import annotations

import os
import unittest
import uuid

LIVE_ENV = "ZOTERO_CONNECTOR_LIVE"

#: Every scratch collection this profile creates starts with this. A stray one
#: left behind by a killed run is identifiable, and safe to delete by hand.
SCRATCH_PREFIX = "zzz-connector-live-test"


def live_enabled() -> bool:
    return os.environ.get(LIVE_ENV, "") == "1"


def requires_live(test):
    return unittest.skipUnless(
        live_enabled(),
        f"live profile is off; set {LIVE_ENV}=1 to run it against real Zotero",
    )(test)


def scratch_name() -> str:
    """A collection name no real project would collide with."""
    return f"{SCRATCH_PREFIX}-{uuid.uuid4().hex[:8]}"


_CREATE_COLLECTION_JS = r"""
const lib = Zotero.Libraries.userLibraryID;
const collection = new Zotero.Collection();
collection.libraryID = lib;
collection.name = name;
await collection.saveTx();
return collection.key;
"""

_CREATE_ITEM_JS = r"""
const lib = Zotero.Libraries.userLibraryID;
const target = Zotero.Collections.getByLibrary(lib, true).find(c => c.key === collectionKey);
if (!target) throw new Error("Scratch collection not found: " + collectionKey);
const item = new Zotero.Item(entry.itemType);
item.libraryID = lib;
for (const [field, value] of Object.entries(entry.fields)) {
    const fieldID = Zotero.ItemFields.getID(field);
    if (fieldID && Zotero.ItemFields.isValidForType(fieldID, item.itemTypeID)) {
        item.setField(field, value);
    }
}
if (entry.creators) item.setCreators(entry.creators);
item.setCollections([target.id]);
await item.saveTx();
return item.key;
"""

# Deliberately narrow: it refuses any collection whose name is not one of
# ours, so a wrong key cannot delete a real project.
_TEARDOWN_JS = r"""
const lib = Zotero.Libraries.userLibraryID;
const removed = {items: [], collections: []};
for (const key of collectionKeys) {
    const collection = Zotero.Collections.getByLibrary(lib, true).find(c => c.key === key);
    if (!collection) continue;
    if (!collection.name.startsWith(prefix)) {
        throw new Error(
            "Refusing to tear down '" + collection.name + "': not a scratch collection"
        );
    }
    for (const item of collection.getChildItems()) {
        item.deleted = true;
        await item.saveTx();
        removed.items.push(item.key);
    }
    await collection.eraseTx();
    removed.collections.push(key);
}
for (const key of itemKeys) {
    const item = Zotero.Items.getByLibraryAndKey(lib, key);
    if (item && !item.deleted) {
        item.deleted = true;
        await item.saveTx();
        removed.items.push(item.key);
    }
}
return removed;
"""


class LiveZoteroTestCase(unittest.TestCase):
    """Base class that owns a scratch collection and always cleans it up."""

    @classmethod
    def setUpClass(cls):
        if not live_enabled():
            raise unittest.SkipTest(
                f"live profile is off; set {LIVE_ENV}=1 to run it against real Zotero"
            )
        from zotero_core.backends.desktop import bridge_info

        cls.bridge = bridge_info()
        if not cls.bridge["endpointRegistered"]:
            raise unittest.SkipTest("the CLI Bridge endpoint is not registered")

    def setUp(self):
        from zotero_core.backends.desktop import _const, evaluate

        self._evaluate = evaluate
        self._const = _const
        self._collections: list[str] = []
        self._items: list[str] = []
        self.collection_name = scratch_name()
        self.collection_key = self._run(
            _CREATE_COLLECTION_JS, name=self.collection_name
        )
        self._collections.append(self.collection_key)
        self.addCleanup(self._teardown)

    def _run(self, script, **params):
        return self._evaluate(self._const(**params) + script, timeout=60)

    def make_item(self, collection_key=None, item_type="journalArticle", creators=(), **fields):
        """Create one scratch item. Tracked, and trashed on teardown."""
        entry = {
            "itemType": item_type,
            "fields": dict(fields),
            "creators": [dict(creator) for creator in creators],
        }
        key = self._run(
            _CREATE_ITEM_JS,
            entry=entry,
            collectionKey=collection_key or self.collection_key,
        )
        self._items.append(key)
        return key

    def make_collection(self, name=None):
        key = self._run(_CREATE_COLLECTION_JS, name=name or scratch_name())
        self._collections.append(key)
        return key

    def _teardown(self):
        self._run(
            _TEARDOWN_JS,
            collectionKeys=list(self._collections),
            itemKeys=list(self._items),
            prefix=SCRATCH_PREFIX,
        )
