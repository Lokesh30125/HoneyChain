"""Beekeeper business logic: code generation, registration, updates, verification.

Codes such as ``BKR-GNT-00001`` are produced here through
:class:`~app.models.document_sequence.DocumentSequence`, never supplied by a
client and never derived from ``COUNT(*)`` (which would collide under concurrent
registration and reuse codes after a deletion).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.beekeeper import Beekeeper
from app.models.document_sequence import DocumentSequence, district_code
from app.models.enums import VerificationStatus
from app.models.user import User
from app.repositories.beekeeper_repository import BeekeeperRepository
from app.repositories.cluster_repository import ClusterRepository
from app.repositories.user_repository import UserRepository
from app.schemas.beekeeper import BeekeeperCreate, BeekeeperSelfUpdate, BeekeeperUpdate
from app.services.audit_service import AuditService

logger = get_logger("service")

#: Width of the numeric part of a generated code (BKR-GNT-00001).
SEQUENCE_WIDTH = 5

#: Bee species commonly kept in India, offered as suggestions in the UI.
#: Stored as free text so a species outside this list is still accepted.
BEE_SPECIES_OPTIONS = [
    "Apis cerana indica",
    "Apis mellifera",
    "Apis dorsata",
    "Apis florea",
    "Trigona (stingless)",
    "Mixed / multiple species",
]


class BeekeeperService:
    """All beekeeper use cases, including the verification workflow."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.beekeepers = BeekeeperRepository(session)
        self.users = UserRepository(session)
        self.clusters = ClusterRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ #
    # Code generation
    # ------------------------------------------------------------------ #
    @staticmethod
    def build_beekeeper_code(district: str | None, sequence: str) -> str:
        """Compose a code from the district abbreviation and a sequence value."""
        return f"BKR-{district_code(district)}-{sequence}"

    def generate_beekeeper_code(self, district: str | None) -> str:
        """Reserve the next unique beekeeper code for a district.

        The counter is scoped per district (``BEEKEEPER:BKR-GNT``) so numbering
        stays readable locally. A collision with an existing row falls back to a
        wider number rather than failing the registration.
        """
        prefix = f"BKR-{district_code(district)}"
        for attempt in range(5):
            sequence = DocumentSequence.next_value(
                self.session, f"BEEKEEPER:{prefix}", width=SEQUENCE_WIDTH + attempt
            )
            candidate = f"{prefix}-{sequence}"
            if not self.beekeepers.code_exists(candidate):
                return candidate
            logger.warning(
                "Beekeeper code collision, retrying", extra={"candidate": candidate}
            )
        raise ValidationError(
            "Could not allocate a unique beekeeper code. Please retry."
        )

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #
    def create_for_user(self, user: User, payload: BeekeeperCreate) -> Beekeeper:
        """Create the beekeeper record for a newly registered user.

        Called by :class:`~app.services.auth_service.AuthService` inside the
        registration transaction, so a user is never left without their beekeeper
        record if anything fails midway.
        """
        if self.beekeepers.get_by_user_id(user.id) is not None:
            raise ValidationError("This user already has a beekeeper record")

        district = payload.district or user.district

        beekeeper = self.beekeepers.create(
            user_id=user.id,
            beekeeper_code=self.generate_beekeeper_code(district),
            experience_years=payload.experience_years,
            bee_species=payload.bee_species,
            number_of_hives=payload.number_of_hives,
            # Only what the person actually supplied: the district is not a
            # stand-in for a village, and inventing one would corrupt the map.
            village=payload.village,
            mandal=payload.mandal,
            district=district,
            state=payload.state or user.state,
            pincode=payload.pincode,
            # Unassigned until an officer places the beekeeper in a cluster:
            # membership is granted by the organisation, never claimed.
            kvic_cluster_id=None,
            registration_date=date.today(),
            # Always PENDING: the platform never self-certifies a beekeeper.
            verification_status=VerificationStatus.PENDING,
        )

        self._record_initial_verification(beekeeper, actor=user)
        self.audit.beekeeper_created(beekeeper, actor=user)

        logger.info(
            "Beekeeper record created",
            extra={
                "beekeeper_code": beekeeper.beekeeper_code,
                "district": beekeeper.district,
            },
        )
        return beekeeper

    def _record_initial_verification(self, beekeeper: Beekeeper, *, actor: User | None) -> None:
        """Open the audit trail with the ``None → PENDING`` entry."""
        from app.models.beekeeper_verification_history import BeekeeperVerificationHistory

        entry = BeekeeperVerificationHistory(
            beekeeper_id=beekeeper.id,
            previous_status=None,
            new_status=VerificationStatus.PENDING,
            remarks="Registration received; awaiting review.",
            changed_by_id=actor.id if actor else None,
            changed_by_name=actor.name if actor else "system",
            changed_by_role=str(actor.role) if actor else "SYSTEM",
        )
        self.session.add(entry)
        self.session.flush()

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get_by_user(self, user: User) -> Beekeeper:
        """The authenticated beekeeper's own record (``/beekeepers/me``)."""
        beekeeper = self.beekeepers.get_by_user_id(user.id)
        if beekeeper is None:
            raise NotFoundError(
                "No beekeeper record is linked to this account",
                details={"hint": "Only users with the BEEKEEPER role have one."},
            )
        return beekeeper

    def get(self, beekeeper_id: uuid.UUID) -> Beekeeper:
        beekeeper = self.beekeepers.get_with_user(beekeeper_id)
        if beekeeper is None:
            raise NotFoundError("Beekeeper not found")
        return beekeeper

    def list_beekeepers(self, **filters) -> tuple[list[Beekeeper], int]:
        return self.beekeepers.search(**filters)

    def verification_history(self, beekeeper_id: uuid.UUID) -> list:
        beekeeper = self.get(beekeeper_id)
        return beekeeper.verification_history

    def filter_options(self) -> dict[str, list]:
        """Values for the UI filter dropdowns, derived from stored data."""
        return {
            "districts": self.beekeepers.distinct_districts(),
            "states": self.beekeepers.distinct_states(),
            "bee_species": BEE_SPECIES_OPTIONS,
            "verification_statuses": [status.value for status in VerificationStatus],
        }

    # ------------------------------------------------------------------ #
    # Updates
    # ------------------------------------------------------------------ #
    def update_own(self, user: User, payload: BeekeeperSelfUpdate) -> Beekeeper:
        """Beekeepers edit their own apiary details.

        ``BeekeeperSelfUpdate`` cannot express a cluster, verification status or
        beekeeper code, so those are structurally impossible to change here — the
        schema rejects them before the service is reached. Location changes are
        mirrored into the user's profile so the two views never disagree.
        """
        beekeeper = self.get_by_user(user)
        changes = payload.model_dump(exclude_unset=True)

        if not changes:
            return beekeeper

        updated = self.beekeepers.update(beekeeper, **changes)
        self._sync_profile_location(user, changes)
        self.audit.beekeeper_updated(updated, actor=user, changed_fields=sorted(changes))
        self.beekeepers.commit()
        return updated

    def update_by_officer(self, beekeeper_id: uuid.UUID, payload: BeekeeperUpdate, *, actor: User) -> Beekeeper:
        """Officer/administrator edit, including cluster assignment."""
        beekeeper = self.get(beekeeper_id)
        changes = payload.model_dump(exclude_unset=True)

        # ``exclude_unset`` tells us whether the client sent the field at all,
        # which matters here: omitting it leaves the assignment alone, while
        # sending an explicit null removes the beekeeper from their cluster.
        cluster = None
        cluster_changed = "kvic_cluster_id" in payload.model_fields_set
        if cluster_changed:
            cluster = self._resolve_cluster(changes.pop("kvic_cluster_id"))
            changes["kvic_cluster_id"] = cluster.id if cluster else None

        if not changes:
            return beekeeper

        updated = self.beekeepers.update(beekeeper, **changes)

        if cluster_changed:
            # Assign through the relationship too. Updating only the foreign key
            # leaves the already-loaded ``updated.cluster`` serving the previous
            # value from the identity map, so the response would show the old
            # cluster (or ``None``) until the session is re-read.
            updated.cluster = cluster
            self.session.flush()
            self.audit.cluster_member_assigned(updated, actor=actor, cluster=cluster)

        self.audit.beekeeper_updated(updated, actor=actor, changed_fields=sorted(changes))
        self.beekeepers.commit()
        return updated

    def assign_cluster(self, beekeeper_id: uuid.UUID, cluster_id: uuid.UUID | None, *, actor: User) -> Beekeeper:
        beekeeper = self.get(beekeeper_id)
        cluster = self._resolve_cluster(cluster_id)

        # Set the relationship rather than the raw column so ``beekeeper.cluster``
        # and the foreign key cannot disagree within the same session.
        beekeeper.cluster = cluster
        self.session.flush()
        updated = beekeeper
        self.audit.cluster_member_assigned(updated, actor=actor, cluster=cluster)
        self.beekeepers.commit()
        return updated

    # ------------------------------------------------------------------ #
    # Verification workflow
    # ------------------------------------------------------------------ #
    def change_verification(
        self,
        beekeeper_id: uuid.UUID,
        *,
        status: VerificationStatus,
        remarks: str | None,
        actor: User,
    ) -> Beekeeper:
        """Move a beekeeper through the verification lifecycle.

        Enforces :meth:`VerificationStatus.can_transition_to`, so an officer
        cannot jump ``PENDING → SUSPENDED`` or re-verify an already-verified
        record without an intervening review step. Every accepted change appends
        to the history table.
        """
        from app.models.beekeeper_verification_history import BeekeeperVerificationHistory

        beekeeper = self.get(beekeeper_id)
        previous = beekeeper.verification_status

        if previous == status:
            raise ValidationError(
                f"This beekeeper is already {status.label}",
                details={"field": "status", "current_status": str(previous)},
            )

        if not previous.can_transition_to(status):
            raise ValidationError(
                f"Cannot move from {previous.label} to {status.label}",
                details={
                    "field": "status",
                    "current_status": str(previous),
                    "allowed_next": [str(s) for s in VerificationStatus.allowed_transitions(previous)],
                },
            )

        now = datetime.now(timezone.utc)

        beekeeper.verification_status = status
        beekeeper.verification_remarks = remarks
        beekeeper.verified_by_id = actor.id
        beekeeper.verified_at = now if status == VerificationStatus.VERIFIED else None

        self.session.add(beekeeper)

        entry = BeekeeperVerificationHistory(
            beekeeper_id=beekeeper.id,
            previous_status=previous,
            new_status=status,
            remarks=remarks,
            changed_by_id=actor.id,
            changed_by_name=actor.name,
            changed_by_role=str(actor.role),
        )
        self.session.add(entry)

        self.audit.beekeeper_verification_changed(
            beekeeper,
            actor=actor,
            previous_status=str(previous),
            new_status=str(status),
            remarks=remarks,
        )

        self.beekeepers.commit()
        logger.info(
            "Beekeeper verification changed",
            extra={
                "beekeeper_code": beekeeper.beekeeper_code,
                "previous_status": str(previous),
                "new_status": str(status),
                "actor_role": str(actor.role),
            },
        )
        return beekeeper

    # ------------------------------------------------------------------ #
    # Summary (database-backed; no invented figures)
    # ------------------------------------------------------------------ #
    def summary(self) -> dict:
        """Counts for the beekeeper management screens.

        Every number comes from an aggregate query. When the database is empty
        the values are genuinely zero and the UI shows an empty state rather than
        placeholder figures.
        """
        by_status = self.beekeepers.count_by_verification_status()
        total = sum(by_status.values())
        return {
            "total": total,
            "by_verification_status": {
                status.value: by_status.get(status.value, 0) for status in VerificationStatus
            },
            "by_district": [
                {"district": district or "Unspecified", "count": count}
                for district, count in self.beekeepers.count_by_district(limit=10)
            ],
            "assigned_to_cluster": sum(self.beekeepers.count_by_cluster().values()),
        }

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _resolve_cluster(self, cluster_id: uuid.UUID | None):
        if cluster_id is None:
            return None
        cluster = self.clusters.get(cluster_id)
        if cluster is None:
            raise NotFoundError("KVIC cluster not found", details={"field": "kvic_cluster_id"})
        if not cluster.is_active:
            raise ValidationError(
                "That cluster is inactive and cannot accept members",
                details={"field": "kvic_cluster_id"},
            )
        return cluster

    def _sync_profile_location(self, user: User, changes: dict) -> None:
        """Mirror apiary location edits into the user's profile.

        The profile row is created on demand: the beekeeper has just told us
        where they are, so the profile page should show the same thing rather
        than an empty Location section.
        """
        location_fields = {"village", "mandal", "district", "state", "pincode"} & set(changes)
        if not location_fields:
            return

        from app.repositories.profile_repository import UserProfileRepository

        profile = UserProfileRepository(self.session).get_or_create(user.id)
        for field in location_fields:
            setattr(profile, field, changes[field])
        self.session.add(profile)
        self.session.flush()

__all__ = ["BeekeeperService", "BEE_SPECIES_OPTIONS", "SEQUENCE_WIDTH"]
