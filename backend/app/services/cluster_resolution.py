"""Which cluster a record belongs to — derived once, used everywhere.

A batch's cluster is not chosen; it follows from the records that produced it. The
collection names a cluster (copied from the beekeeper who made the harvest), the
beekeeper's own record names theirs, and a hive may name its own. Three places
need the same answer: creating a batch, creating a collection, and the repair
script that fills in rows written before the rule existed.

Putting the rule here rather than in each of them is what keeps them from
disagreeing — and what keeps a "which cluster is this?" bug from having three
different fixes in three files.

The rule refuses to guess. A beekeeper with no cluster recorded derives nothing; a
beekeeper whose hives disagree derives nothing. A record with no cluster is a real
state on this platform — an apiary nobody has placed yet — and is rendered as
"not in a cluster" rather than being attached to somebody else's.
"""

from __future__ import annotations

import uuid
from typing import Any


def cluster_for(
    *,
    collection: Any = None,
    beekeeper: Any = None,
    hives: list[Any] | None = None,
) -> tuple[uuid.UUID | None, str | None]:
    """Return ``(cluster_id, source)``, or ``(None, None)`` when it cannot be told.

    ``source`` names where the value came from, so a caller can record it in an
    audit entry instead of leaving a backfilled foreign key unexplained.
    """
    if collection is not None and getattr(collection, "cluster_id", None) is not None:
        return collection.cluster_id, "collection"

    if beekeeper is not None:
        direct = getattr(beekeeper, "kvic_cluster_id", None)
        if direct is not None:
            return direct, "beekeeper"

    candidates = {
        getattr(hive, "cluster_id", None)
        for hive in (hives or [])
        if getattr(hive, "cluster_id", None) is not None
    }
    if len(candidates) == 1:
        return candidates.pop(), "source hives"

    if beekeeper is not None:
        owned = {
            getattr(hive, "cluster_id", None)
            for hive in list(getattr(beekeeper, "hives", []) or [])
            if getattr(hive, "cluster_id", None) is not None
        }
        if len(owned) == 1:
            return owned.pop(), "the beekeeper's hives"

    return None, None
