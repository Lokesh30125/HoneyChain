"""Reading a person's or a place's name out of a stored record.

These three functions exist because "who is this" has one right answer per entity
and several wrong ones. A beekeeper row has no name of its own — the human is the
``User`` it points at — and a cluster's column is ``cluster_name``, not ``name``.
A payload built with ``getattr(record, "name", None)`` therefore comes back with
``None`` for both and a screen quietly renders a blank where a person belongs.

Keeping the lookups here means every module spells a name the same way, and a
schema change is a one-line fix rather than a hunt through services.
"""

from __future__ import annotations

from typing import Any


def person_name(user: Any | None) -> str | None:
    """A user's display name, falling back to their email, then to nothing.

    ``None`` (rather than an empty string) is deliberate: "we do not know who this
    was" and "this person is called ''" are different facts, and a client can only
    tell them apart if the absent one stays absent.
    """
    if user is None:
        return None
    return getattr(user, "name", None) or getattr(user, "email", None)


def beekeeper_name(beekeeper: Any | None) -> str | None:
    """The beekeeper's account holder — the name their own profile shows."""
    if beekeeper is None:
        return None
    return person_name(getattr(beekeeper, "user", None))


def cluster_name(cluster: Any | None) -> str | None:
    """The KVIC cluster's name, as written on the cluster record."""
    if cluster is None:
        return None
    return getattr(cluster, "cluster_name", None) or getattr(cluster, "name", None)


__all__ = ["person_name", "beekeeper_name", "cluster_name"]
