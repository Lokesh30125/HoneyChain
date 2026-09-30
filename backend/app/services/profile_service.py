"""Profile business logic — ``GET/PUT/PATCH /api/v1/profile``.

A user may only ever read or modify **their own** profile: every method takes the
authenticated :class:`~app.models.user.User` and derives the subject from it, so
there is no parameter a caller could tamper with to reach another account.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.enums import VerificationStatus
from app.models.user import User
from app.repositories.beekeeper_repository import BeekeeperRepository
from app.repositories.profile_repository import UserProfileRepository
from app.repositories.user_repository import UserRepository
from app.schemas.profile import (
    BeekeeperSummaryForProfile,
    FullProfileResponse,
    ProfilePatch,
    ProfilePublic,
    ProfileUpdate,
    UserAccountSummary,
)
from app.services.audit_service import AuditService

logger = get_logger("service")


class ProfileService:
    """Reads and updates the authenticated user's profile."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.profiles = UserProfileRepository(session)
        self.users = UserRepository(session)
        self.beekeepers = BeekeeperRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get_full_profile(self, user: User) -> FullProfileResponse:
        """Assemble the whole profile page payload in one call."""
        profile = self.profiles.get_by_user(user.id)
        beekeeper = self.beekeepers.get_by_user_id(user.id) if user.is_beekeeper else None

        return FullProfileResponse(
            account=self._account_summary(user),
            profile=self._profile_payload(user, profile),
            beekeeper=self._beekeeper_summary(beekeeper),
        )

    @staticmethod
    def _account_summary(user: User) -> UserAccountSummary:
        return UserAccountSummary(
            id=user.id,
            email=user.email,
            role=user.role,
            role_label=user.role.label,
            is_active=user.is_active,
            is_verified=user.is_verified,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )

    @staticmethod
    def _profile_payload(user: User, profile) -> ProfilePublic:
        """Return the profile, falling back to the user row for legacy fields.

        ``users`` still carries ``state``/``district`` from Phase 1, so values
        entered at registration are shown even before a profile row exists.
        """
        if profile is None:
            return ProfilePublic(
                id=None,
                user_id=user.id,
                state=user.state,
                district=user.district,
            )
        return ProfilePublic.model_validate(profile)

    @staticmethod
    def _beekeeper_summary(beekeeper) -> BeekeeperSummaryForProfile | None:
        if beekeeper is None:
            return None
        cluster = beekeeper.cluster
        return BeekeeperSummaryForProfile(
            id=beekeeper.id,
            beekeeper_code=beekeeper.beekeeper_code,
            verification_status=str(beekeeper.verification_status),
            verification_label=VerificationStatus(beekeeper.verification_status).label,
            experience_years=beekeeper.experience_years,
            bee_species=beekeeper.bee_species,
            number_of_hives=beekeeper.number_of_hives,
            village=beekeeper.village,
            mandal=beekeeper.mandal,
            district=beekeeper.district,
            state=beekeeper.state,
            pincode=beekeeper.pincode,
            registration_date=beekeeper.registration_date,
            cluster_id=beekeeper.kvic_cluster_id,
            cluster_code=cluster.cluster_code if cluster else None,
            cluster_name=cluster.cluster_name if cluster else None,
        )

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def replace_profile(self, user: User, payload: ProfileUpdate) -> FullProfileResponse:
        """``PUT`` — apply the submitted values, clearing omitted optional fields."""
        return self._apply(user, payload.model_dump(exclude_unset=False), mode="replace")

    def patch_profile(self, user: User, payload: ProfilePatch) -> FullProfileResponse:
        """``PATCH`` — change only the fields present in the request body."""
        return self._apply(user, payload.model_dump(exclude_unset=True), mode="patch")

    def update_location(self, user: User, **location: object) -> None:
        """Internal helper used when another module records a location."""
        profile = self.profiles.get_or_create(user.id)
        self.profiles.update_location(profile, **location)
        self.profiles.flush()

    def _apply(self, user: User, changes: dict, *, mode: str) -> FullProfileResponse:
        profile = self.profiles.get_or_create(user.id)

        if not changes:
            return self.get_full_profile(user)

        # Only the schema's own fields may be written; anything else (role,
        # email, is_active) is not part of the payload type at all.
        editable = set(ProfileUpdate.model_fields.keys())
        applied = {key: value for key, value in changes.items() if key in editable}

        for field, value in applied.items():
            setattr(profile, field, value)

        # Keep the denormalised copy on ``users`` in step with the profile so
        # existing district/state filters and dashboards stay correct.
        user_updates = {}
        if "district" in applied:
            user_updates["district"] = applied["district"] or None
        if "state" in applied:
            user_updates["state"] = applied["state"] or None
        if user_updates:
            for field, value in user_updates.items():
                setattr(user, field, value)
            self.session.add(user)

        if mode == "replace":
            # A PUT is a full representation: clear fields the caller omitted,
            # so "delete my phone number" is expressible.
            for field in editable - set(applied.keys()):
                setattr(profile, field, None)

        self.session.add(profile)
        self.audit.profile_updated(user, changed_fields=sorted(applied.keys()))
        self.profiles.commit()

        logger.info(
            "Profile updated",
            extra={"user_id": str(user.id), "fields": sorted(applied.keys()), "mode": mode},
        )
        return self.get_full_profile(user)

    # ------------------------------------------------------------------ #
    # Officer-facing read (returns a different user's public profile)
    # ------------------------------------------------------------------ #
    def get_public_profile(self, user_id) -> FullProfileResponse:
        """Profile of an arbitrary user, for administrative review.

        Callers must already hold ``USER_READ_ALL``; the route enforces that, so
        this method never decides authorisation itself.
        """
        from app.core.exceptions import NotFoundError

        user = self.users.get(user_id)
        if user is None:
            raise NotFoundError("User not found")
        return self.get_full_profile(user)
