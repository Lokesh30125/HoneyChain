"""Repair missing cluster links — only where the records already say what they are.

Why a script rather than a migration
------------------------------------
The batch→cluster relationship is derived: a batch copies its cluster from the
collection it was created by, which copied it from the beekeeper who harvested the
honey. A row written before that was true can be missing the value, and a KVIC
officer then sees a batch that is not under any cluster — which is exactly the
report this phase exists to answer.

Most such rows can be filled in from the records that already exist, and a
migration is the wrong tool for the rest: a migration must decide in advance, while
this decision depends on whether the answer is *unambiguous*. So the script works
in three passes and refuses to guess at any of them:

1. **Derive it.** A batch with no cluster whose collection names one is corrected
   from the collection. A batch whose collection has none is corrected from its
   beekeeper, if the beekeeper is in exactly one cluster. A collection or hive can
   be corrected the same way from its beekeeper. Each corrected row is written to
   the audit log as ``DATA_CORRECTION``, naming the source the value came from —
   a backfilled cluster is never an unexplained number in the database.
2. **Report what it could not derive.** Anything left over is listed with the
   reason: no collection, a beekeeper in no cluster, or a beekeeper whose hive
   clusters disagree. Nothing is invented, no cluster is picked at random, and no
   valid record is deleted.
3. **Accept a repair from a person.** ``--assign <record> <cluster>`` is how an
   administrator settles a case the records cannot settle. It is audited like
   everything else, and it is deliberately the *only* way a cluster is ever set by
   hand.

Usage::

    python -m app.scripts.repair_cluster_links --dry-run      # report only (default)
    python -m app.scripts.repair_cluster_links --apply        # write the derivable ones
    python -m app.scripts.repair_cluster_links --assign HC-BATCH-2026-000007 KVIC-GNT-002
"""

from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.logging import configure_logging
from app.models.enums import AuditAction
from app.models.honey_batch import HoneyBatch
from app.models.honey_collection import HoneyCollection
from app.models.hive import Hive
from app.services.audit_service import AuditService
from app.services.cluster_resolution import cluster_for as _cluster_for

#: The provenance string written into the audit metadata, so a reader can see the
#: value was derived rather than typed.
SOURCES = {
    "collection": "the batch's own collection",
    "beekeeper": "the beekeeper who owns the record",
    "source hives": "the source hives of the record",
    "the beekeeper's hives": "the beekeeper's own hives",
    "hive": "the source hives of the record",
    "operator": "an operator naming the cluster explicitly",
}


class Repair:
    """One record that was examined, and what happened to it."""

    def __init__(self, kind: str, code: str, record_id: uuid.UUID, target, source: str, note: str):
        self.kind = kind
        self.code = code
        self.record_id = record_id
        self.target = target  # the cluster id, or None when nothing could be derived
        self.source = source
        self.note = note

    @property
    def resolved(self) -> bool:
        return self.target is not None


def _cluster_from_collection(collection: HoneyCollection | None):
    if collection is None:
        return None
    return collection.cluster_id


def _cluster_with_source(batch) -> tuple[uuid.UUID | None, str, str]:
    """The cluster a batch belongs to, and where the answer came from.

    Delegates to the shared rule so the script, the API and any future backfill
    cannot drift apart.
    """
    target, source = _cluster_for(
        collection=batch.collection,
        beekeeper=batch.beekeeper,
        hives=list(getattr(batch, "source_hives", []) or []),
    )
    if target is None:
        return None, "none", (
            "the batch has no cluster recorded on its collection or its beekeeper, and its "
            "source hives do not agree — the cluster cannot be determined from the records"
        )
    return target, source, f"derived from {SOURCES.get(source, source)}"


def _cluster_from_beekeeper(beekeeper) -> uuid.UUID | None:
    """A beekeeper's cluster — but only when it is the only one in play.

    A beekeeper holds one cluster on their own record (``kvic_cluster_id``), and
    their hives may carry their own. The record's own value is authoritative; if it
    is missing and the hives disagree with each other, the answer is ambiguous and
    this returns nothing rather than picking one.
    """
    if beekeeper is None:
        return None
    direct = getattr(beekeeper, "kvic_cluster_id", None)
    if direct is not None:
        return direct
    clusters = {
        hive.cluster_id
        for hive in list(getattr(beekeeper, "hives", []) or [])
        if getattr(hive, "cluster_id", None) is not None
    }
    if len(clusters) == 1:
        return clusters.pop()
    return None


def _audit(session: Session, record: Repair, *, entity_type: str, description: str) -> None:
    AuditService(session).record(
        action=AuditAction.DATA_CORRECTION,
        entity_type=entity_type,
        entity_id=record.record_id,
        actor=None,
        description=description,
        metadata={
            "record": record.code,
            "field": "cluster_id",
            "cluster_id": str(record.target),
            "source": SOURCES.get(record.source, record.source),
            "reason": record.note,
            "performed_by": "app.scripts.repair_cluster_links",
        },
    )


def survey(session: Session) -> list[Repair]:
    """Examine every record with no cluster and work out whether it can be filled."""
    repairs: list[Repair] = []

    batches = list(
        session.execute(
            select(HoneyBatch)
            .options(
                joinedload(HoneyBatch.collection),
                joinedload(HoneyBatch.beekeeper),
            )
            .where(HoneyBatch.cluster_id.is_(None))
        )
        .scalars()
        .unique()
    )
    for batch in batches:
        derived, source, note = _cluster_with_source(batch)
        repairs.append(Repair("batch", batch.batch_code, batch.id, derived, source, note))

    collections = list(
        session.execute(
            select(HoneyCollection)
            .options(joinedload(HoneyCollection.beekeeper))
            .where(HoneyCollection.cluster_id.is_(None))
        )
        .scalars()
        .unique()
    )
    for collection in collections:
        derived, _source = _cluster_for(beekeeper=collection.beekeeper)
        repairs.append(
            Repair(
                "collection",
                collection.collection_code,
                collection.id,
                derived,
                "beekeeper",
                "derived from the beekeeper who harvested the honey"
                if derived is not None
                else "the harvesting beekeeper's cluster is not recorded, so it cannot be determined",
            )
        )

    hives = list(
        session.execute(
            select(Hive)
            .options(joinedload(Hive.beekeeper))
            .where(Hive.cluster_id.is_(None))
        )
        .scalars()
        .unique()
    )
    for hive in hives:
        derived, _source = _cluster_for(beekeeper=hive.beekeeper)
        repairs.append(
            Repair(
                "hive",
                hive.hive_code,
                hive.id,
                derived,
                "beekeeper",
                "derived from the hive's owner, whose record names one cluster"
                if derived is not None
                else "the owner's cluster is not recorded, so it cannot be determined",
            )
        )
    return repairs


def apply_repairs(session: Session, repairs: list[Repair]) -> int:
    """Write the ones that could be derived, each with an audit entry."""
    applied = 0
    for repair in repairs:
        if not repair.resolved:
            continue
        if repair.kind == "batch":
            record = session.get(HoneyBatch, repair.record_id)
        elif repair.kind == "collection":
            record = session.get(HoneyCollection, repair.record_id)
        else:
            record = session.get(Hive, repair.record_id)
        if record is None or record.cluster_id is not None:
            continue
        record.cluster_id = repair.target
        _audit(
            session,
            repair,
            entity_type=repair.kind,
            description=(
                f"Cluster recorded for {repair.code} from {SOURCES.get(repair.source, repair.source)}"
            ),
        )
        applied += 1
    session.commit()
    return applied


def assign(session: Session, code: str, cluster_code: str) -> int:
    """Attach one record to one cluster, on an operator's instruction."""
    from app.models.cluster import KvicCluster

    cluster = session.execute(
        select(KvicCluster).where(KvicCluster.cluster_code == cluster_code)
    ).scalars().first()
    if cluster is None:
        raise SystemExit(f"No cluster with code {cluster_code}")

    record = None
    kind = ""
    for model, field, name in (
        (HoneyBatch, HoneyBatch.batch_code, "batch"),
        (HoneyCollection, HoneyCollection.collection_code, "collection"),
        (Hive, Hive.hive_code, "hive"),
    ):
        record = session.execute(select(model).where(field == code)).scalars().first()
        if record is not None:
            kind = name
            break
    if record is None:
        raise SystemExit(f"No batch, collection or hive with code {code}")

    previous = record.cluster_id
    record.cluster_id = cluster.id
    repair = Repair(kind, code, record.id, cluster.id, "operator", f"assigned by an operator to {cluster_code}")
    _audit(
        session,
        repair,
        entity_type=kind,
        description=(
            f"Cluster set to {cluster_code} for {code} by an operator "
            f"(was {'unset' if previous is None else previous})"
        ),
    )
    session.commit()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--apply", action="store_true", help="write the derivable corrections")
    parser.add_argument("--dry-run", action="store_true", help="report only (the default)")
    parser.add_argument("--assign", nargs=2, metavar=("RECORD_CODE", "CLUSTER_CODE"))
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings)
    # Never the password: the host and database are enough to know where this ran.
    target = settings.DATABASE_URL.split("@")[-1]
    print(f"Cluster-link repair against ...@{target}")
    print("Nothing is guessed: a value is filled only when the records already imply it.\n")

    with SessionLocal() as session:
        if args.assign:
            code, cluster_code = args.assign
            assign(session, code, cluster_code)
            print(f"{code} attached to {cluster_code} (audited as a data correction).")
            return 0

        repairs = survey(session)
        resolved = [repair for repair in repairs if repair.resolved]
        unresolved = [repair for repair in repairs if not repair.resolved]

        print(f"Records with no cluster: {len(repairs)}")
        for repair in resolved:
            print(f"  DERIVABLE  {repair.kind:10} {repair.code:26} ← {SOURCES[repair.source]}")
        for repair in unresolved:
            print(f"  UNRESOLVED {repair.kind:10} {repair.code:26} — {repair.note}")
        if not repairs:
            print("  (none — every relationship is already recorded)")

        if args.apply and resolved:
            applied = apply_repairs(session, repairs)
            print(f"\nCorrected {applied} record(s), each with a DATA_CORRECTION audit entry.")
        elif resolved:
            print(
                f"\n{len(resolved)} record(s) can be corrected from what is already stored. "
                "Re-run with --apply to write them."
            )
        if unresolved:
            print(
                f"{len(unresolved)} record(s) cannot be determined from the records. Use "
                "--assign <record> <cluster> to settle one, or leave it unresolved: the platform "
                "shows it as not in a cluster rather than inventing one."
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
