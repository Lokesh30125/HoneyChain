"""Data access for ``user_profiles``."""

from __future__ import annotations

import uuid

from app.models.user_profile import UserProfile
from app.repositories.base import BaseRepository


class UserProfileRepository(BaseRepository[UserProfile]):
    model = UserProfile

    def get_by_user(self, user_id: uuid.UUID) -> UserProfile | None:
        return self.get_by(user_id=user_id)

    def get_or_create(self, user_id: uuid.UUID) -> UserProfile:
        """Return the profile, creating an empty one on first access.

        Lazy creation keeps registration minimal: a user who supplies only the
        mandatory fields gets a profile row the first time they open the profile
        page (or the first time a location needs to be stored).
        """
        profile = self.get_by_user(user_id)
        if profile is None:
            profile = self.create(user_id=user_id)
        return profile

    def update_location(self, profile: UserProfile, **fields: object) -> UserProfile:
        allowed = {"village", "mandal", "district", "state", "pincode"}
        return self.update(profile, **{k: v for k, v in fields.items() if k in allowed})
