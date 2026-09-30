"""Administrative use cases: the identity directory, account status and audit review.

Everything here is reached only through routes guarded by ``Permission``
dependencies (``USER_READ_ALL``, ``ADMIN_USER_MANAGE``, ``AUDIT_READ``), so this
service never re-implements authorisation — it assumes the caller is already
authorised and focuses on the operation itself.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    DuplicateResourceError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.core.logging import get_logger
from app.core.permissions import Permission, permissions_for
from app.core.security import hash_password
from app.models.enums import AuditAction, UserRole, VerificationStatus
from app.models.user import User
from app.repositories.audit_repository import AuditLogRepository
from app.repositories.beekeeper_repository import BeekeeperRepository
from app.repositories.cluster_repository import ClusterRepository
from app.repositories.packaging_repository import PackagingUnitRepository
from app.repositories.token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.admin import AdminUserCreate
from app.schemas.audit import AuditLogEntry
from app.schemas.beekeeper import BeekeeperCreate
from app.schemas.user import UserPublic
from app.services.audit_service import AuditService
from app.services.auth_service import REVOKE_ROLE_CHANGED

logger = get_logger("service")


class AdminService:
    """Administrative operations over users, and audit review."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.beekeepers = BeekeeperRepository(session)
        self.clusters = ClusterRepository(session)
        self.audit_logs = AuditLogRepository(session)
        self.tokens = RefreshTokenRepository(session)
        self.audit = AuditService(session)
        self.units = PackagingUnitRepository(session)

    # ------------------------------------------------------------------ #
    # Dashboard
    # ------------------------------------------------------------------ #
    def platform_summary(self) -> dict:
        """Headline counts for the administrator dashboard.

        Every figure is an aggregate over the database. An empty platform
        reports zeros and the UI renders empty states — no placeholder numbers.
        """
        counts_by_role = self.users.count_by_role()
        total = sum(counts_by_role.values())
        verification_counts = self.beekeepers.count_by_verification_status()

        return {
            "users": {
                "total": total,
                "active": self.users.count_active(),
                "inactive": total - self.users.count_active(),
                # Roles with zero accounts are still reported so the UI can show
                # which parts of the supply chain have not onboarded yet.
                "by_role": {role.value: counts_by_role.get(role.value, 0) for role in UserRole},
            },
            "beekeepers": {
                "total": sum(verification_counts.values()),
                "by_verification_status": {
                    status.value: verification_counts.get(status.value, 0)
                    for status in VerificationStatus
                },
            },
            "clusters": {
                "total": self.clusters.count(),
                "active": self.clusters.count(is_active=True),
            },
            "modules": {
                # Implemented modules report "available"; the rest are honest
                # about their state rather than pretending to be live.
                "user_management": "available",
                "beekeeping": "available",
                "hives": "available",
                "iot": "available",
                "ai": "available",
                "blockchain": "available",
                "supply_chain": "available",
            },
        }

    # ------------------------------------------------------------------ #
    # User directory
    # ------------------------------------------------------------------ #
    def list_users(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        role: UserRole | None = None,
        is_active: bool | None = None,
        is_verified: bool | None = None,
        search: str | None = None,
        order_by: str = "created_at",
        descending: bool = True,
    ) -> tuple[list[UserPublic], int]:
        """Paginated, searchable identity directory.

        Search covers name, email and phone. Filtering and counting share one
        ``WHERE`` clause so the pagination metadata always matches the rows.
        """
        filters: list = []
        if role is not None:
            filters.append(User.role == role)
        if is_active is not None:
            filters.append(User.is_active.is_(is_active))
        if is_verified is not None:
            filters.append(User.is_verified.is_(is_verified))
        if search and search.strip():
            term = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(User.name).like(term),
                    func.lower(User.email).like(term),
                    func.lower(func.coalesce(User.phone, "")).like(term),
                )
            )

        query = select(User)
        count_query = select(func.count()).select_from(User)
        if filters:
            from sqlalchemy import and_

            combined = and_(*filters)
            query = query.where(combined)
            count_query = count_query.where(combined)

        total = int(self.session.execute(count_query).scalar_one())

        column = getattr(User, order_by, User.created_at)
        query = query.order_by(column.desc() if descending else column.asc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        rows = list(self.session.execute(query).scalars().all())
        return [UserPublic.model_validate(row) for row in rows], total

    # ------------------------------------------------------------------ #
    # Creating accounts for operational roles
    # ------------------------------------------------------------------ #
    @staticmethod
    def _require(actor: User, permission: Permission) -> None:
        """Assert the actor holds a capability, in the service layer.

        The route dependency enforces the same thing; this is the second lock on
        the same door. It exists because these two operations (creating an
        account for somebody else, and deciding its role) are the ones where a
        missing dependency would be a privilege-escalation bug rather than a
        cosmetic one, so the check does not live only in the HTTP layer.
        """
        if permission not in permissions_for(actor.role):
            raise ForbiddenError(
                "Your role cannot perform this action",
                details={
                    "required_permission": str(permission),
                    "your_role": str(actor.role),
                },
            )

    def _create_beekeeper_record(self, user: User, details: BeekeeperCreate | None):
        """Create the apiary record an account needs to act as a beekeeper.

        Imported here rather than at module scope because ``BeekeeperService``
        imports this module's neighbours; the same lazy import registration uses.
        """
        from app.services.beekeeper_service import BeekeeperService

        return BeekeeperService(self.session).create_for_user(user, details or BeekeeperCreate())

    def create_user(self, payload: AdminUserCreate, *, actor: User) -> tuple[User, bool]:
        """Provision an account with any of the ten roles.

        This is the same account every other door creates — the same table, the
        same bcrypt hash, the same ``/auth/login``. The difference is only who
        chooses the role: an administrator, not the visitor.

        Returns the user and whether a beekeeper record was created with it.
        """
        self._require(actor, Permission.ADMIN_USER_MANAGE)
        # Choosing the role is a separate capability from creating the account:
        # holding "manage users" must not silently imply "grant any role".
        self._require(actor, Permission.ADMIN_ROLE_ASSIGN)

        if self.users.email_exists(payload.email):
            raise DuplicateResourceError(
                "An account with this email already exists.",
                details={"field": "email"},
            )
        if payload.phone and self.users.phone_exists(payload.phone):
            raise DuplicateResourceError(
                "An account with this phone number already exists.",
                details={"field": "phone"},
            )

        # The facility is resolved *before* the account is written, so a bad id
        # cannot leave an account behind with a dangling reference in it.
        facility = self._resolve_packaging_unit(payload)

        try:
            user = self.users.create_user(
                name=payload.name,
                email=payload.email,
                password_hash=hash_password(payload.password),
                role=payload.role,
                phone=payload.phone,
                state=payload.state,
                district=payload.district,
                organization=payload.organization,
                is_active=payload.is_active,
            )
            if facility is not None:
                user.packaging_unit_id = facility.id

            # A beekeeper account without its beekeeper record would be an
            # account that cannot do its job, so both are created together —
            # exactly as registration does it. The record starts PENDING: an
            # administrator creating the account is not a verification.
            beekeeper = None
            if user.role is UserRole.BEEKEEPER:
                beekeeper = self._create_beekeeper_record(user, payload.beekeeper)
        except IntegrityError as exc:  # race between the checks above and the insert
            self.session.rollback()
            raise DuplicateResourceError(
                "An account with these details already exists."
            ) from exc

        self.audit.user_provisioned(
            user,
            role=str(user.role),
            actor=actor,
            is_active=payload.is_active,
            reason=payload.reason,
            beekeeper_code=getattr(beekeeper, "beekeeper_code", None),
        )
        if facility is not None:
            # Its own entry as well: the account was attached to a facility in the
            # same act, and that is a fact a reviewer looks for by facility.
            self.audit.record(
                AuditAction.PACKAGING_UNIT_MEMBER_CHANGED,
                actor=actor,
                entity_type="packaging_unit",
                entity_id=facility.id,
                description=(
                    f"{user.name} ({user.email}) created as a packaging-unit account at "
                    f"{facility.name} ({facility.unit_code})"
                ),
                metadata={
                    "unit_code": facility.unit_code,
                    "unit_id": str(facility.id),
                    "user_id": str(user.id),
                    "user_email": user.email,
                    "action": "attached",
                    "previous_unit_id": None,
                    "reason": payload.reason,
                },
            )
        self.users.commit()

        logger.info(
            "Account provisioned by an administrator",
            extra={
                "subject_user_id": str(user.id),
                "role": str(user.role),
                "actor_id": str(actor.id),
            },
        )
        return user, beekeeper is not None

    def _resolve_packaging_unit(self, payload: AdminUserCreate):
        """The facility named for a packaging-unit account, checked against the register.

        Named for the role and for no other, active, and existing. An administrator
        creating the account has the register to hand; naming a facility that is
        retired is refused rather than silently accepted, because a retired unit
        takes no new work.
        """
        unit_id = getattr(payload, "packaging_unit_id", None)
        if unit_id is None:
            return None
        unit = self.units.get(unit_id)
        if unit is None:
            raise NotFoundError(
                f"Packaging unit {unit_id} not found",
                details={"resource": "packaging_unit", "field": "packaging_unit_id"},
            )
        if not unit.is_active:
            raise ValidationError(
                f"Packaging unit {unit.unit_code} is {unit.status}; attach the account to an active unit.",
                details={
                    "field": "packaging_unit_id",
                    "unit_code": unit.unit_code,
                    "status": str(unit.status),
                },
            )
        return unit

    def set_user_role(
        self,
        user_id: uuid.UUID,
        *,
        role: UserRole,
        actor: User,
        reason: str | None = None,
    ) -> tuple[User, UserRole, int]:
        """Change which role an account holds.

        Guard rails, in order:

        * the actor must hold ``ADMIN_ROLE_ASSIGN`` (administrators only);
        * an administrator cannot change **their own** role — that is the route
          by which somebody could grant themselves a role they were not given;
        * the last active administrator cannot be moved off ADMIN, for the same
          reason the last one cannot be deactivated;
        * live sessions are revoked, because the account's permissions change the
          moment this commits and the person must not keep acting on a session
          opened under the old role.

        Returns the updated user, its previous role and how many sessions were
        revoked.
        """
        self._require(actor, Permission.ADMIN_ROLE_ASSIGN)
        user = self.get_user(user_id)
        previous_role = UserRole(str(user.role))

        if user.id == actor.id:
            raise ValidationError(
                "You cannot change your own role. Ask another administrator.",
                details={"field": "role"},
            )
        if role is previous_role:
            # Idempotent: nothing changed, so nothing is audited.
            return user, previous_role, 0
        if previous_role is UserRole.ADMIN and self.users.count(
            role=UserRole.ADMIN, is_active=True
        ) <= 1:
            raise ValidationError(
                "The last active administrator cannot be moved to another role. "
                "Promote another administrator first.",
                details={"field": "role"},
            )

        updated = self.users.update(user, role=role)

        # A promoted beekeeper keeps the record they already had (history is
        # never deleted); a new beekeeper gets one, because the account cannot
        # work without it. The record's verification state is untouched either
        # way — a role change is not a verification.
        beekeeper_created = False
        if role is UserRole.BEEKEEPER and self.beekeepers.get_by_user_id(user_id) is None:
            self._create_beekeeper_record(updated, None)
            beekeeper_created = True

        revoked = self.tokens.revoke_all_for_user(user_id, reason=REVOKE_ROLE_CHANGED)

        self.audit.user_role_changed(
            updated,
            previous_role=str(previous_role),
            new_role=str(role),
            actor=actor,
            reason=reason,
            sessions_revoked=revoked,
            beekeeper_created=beekeeper_created,
        )
        self.users.commit()

        logger.info(
            "Account role changed",
            extra={
                "subject_user_id": str(user_id),
                "previous_role": str(previous_role),
                "new_role": str(role),
                "actor_id": str(actor.id),
                "sessions_revoked": revoked,
            },
        )
        return updated, previous_role, revoked

    def get_user(self, user_id: uuid.UUID) -> User:
        user = self.users.get(user_id)
        if user is None:
            raise NotFoundError("User not found")
        return user

    def user_detail(self, user_id: uuid.UUID) -> dict:
        """Account plus the context an administrator needs to make a decision."""
        user = self.get_user(user_id)
        beekeeper = self.beekeepers.get_by_user_id(user_id)

        return {
            "user": UserPublic.model_validate(user),
            "beekeeper": (
                {
                    "id": str(beekeeper.id),
                    "beekeeper_code": beekeeper.beekeeper_code,
                    "verification_status": str(beekeeper.verification_status),
                    "district": beekeeper.district,
                    "state": beekeeper.state,
                    "number_of_hives": beekeeper.number_of_hives,
                    "cluster_name": beekeeper.cluster.cluster_name if beekeeper.cluster else None,
                }
                if beekeeper
                else None
            ),
            # Recent actions on this account, newest first.
            "recent_activity": [
                AuditLogEntry.model_validate(entry)
                for entry in self.audit_logs.for_entity("user", user_id, limit=10)
            ],
        }

    def set_user_active(
        self, user_id: uuid.UUID, *, is_active: bool, actor: User, reason: str | None = None
    ) -> User:
        """Enable or disable an account, with two guard rails.

        An administrator cannot deactivate their own account (it would lock them
        out mid-session), and the last active administrator cannot be
        deactivated (it would leave the platform unadministered).
        """
        user = self.get_user(user_id)

        if not is_active:
            if user.id == actor.id:
                raise ValidationError(
                    "You cannot deactivate your own account",
                    details={"field": "is_active"},
                )
            if user.is_admin and self.users.count(role=UserRole.ADMIN, is_active=True) <= 1:
                raise ValidationError(
                    "The last active administrator cannot be deactivated. "
                    "Promote another administrator first.",
                    details={"field": "is_active"},
                )

        if user.is_active == is_active:
            # Idempotent: nothing changed, so nothing is audited.
            return user

        from datetime import datetime, timezone

        updated = self.users.update(
            user,
            is_active=is_active,
            deactivated_at=None if is_active else datetime.now(timezone.utc),
        )
        self.audit.user_status_changed(
            updated, is_active=is_active, actor=actor, reason=reason
        )
        self.users.commit()

        logger.info(
            "Account status changed",
            extra={
                "subject_user_id": str(user_id),
                "is_active": is_active,
                "actor_id": str(actor.id),
            },
        )
        return updated

    # ------------------------------------------------------------------ #
    # Audit review
    # ------------------------------------------------------------------ #
    def list_audit_logs(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        action: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        user_id: uuid.UUID | None = None,
    ) -> tuple[list[AuditLogEntry], int]:
        rows, total = self.audit_logs.search(
            page=page,
            page_size=page_size,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
        )
        return [AuditLogEntry.model_validate(row) for row in rows], total

    def activity_summary(self, *, hours: int = 24) -> dict:
        return self.audit.activity_summary(hours=hours)
