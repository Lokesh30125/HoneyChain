"""Initial authentication foundation: users and refresh tokens.

Creates the two tables required by the Phase 1 foundation:

``users``
    Single identity record for all ten HoneyChain roles (one auth system, RBAC
    by role). UUID primary key so identifiers stay non-enumerable in public
    trace URLs and QR payloads added in Phase 3.

``refresh_tokens``
    Server-side session records enabling real logout, token rotation and
    replay detection. Only a SHA-256 fingerprint of the token is stored.

Revision ID: 37a03aa5a040
Revises:
Create Date: 2026-09-22 18:15:04.790910+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '37a03aa5a040'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The ``user_role`` enum type is created implicitly by create_table below.
    op.create_table('users',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('phone', sa.String(length=20), nullable=True),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.Enum('ADMIN', 'BEEKEEPER', 'COLLECTION_CENTER', 'PROCESSOR', 'LAB_TECHNICIAN', 'PACKAGING_UNIT', 'DISTRIBUTOR', 'RETAILER', 'CONSUMER', 'KVIC_OFFICER', name='user_role'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('state', sa.String(length=80), nullable=True),
    sa.Column('district', sa.String(length=80), nullable=True),
    sa.Column('organization', sa.String(length=160), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('length(name) >= 2', name=op.f('ck_users_name_min_length')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('phone', name=op.f('uq_users_phone'))
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_role'), 'users', ['role'], unique=False)
    op.create_index('ix_users_role_active', 'users', ['role', 'is_active'], unique=False)
    op.create_table('refresh_tokens',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('jti', sa.String(length=64), nullable=False),
    sa.Column('replaced_by_jti', sa.String(length=64), nullable=True),
    sa.Column('revoked', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoke_reason', sa.String(length=80), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('device', sa.String(length=64), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_refresh_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens')),
    sa.UniqueConstraint('jti', name=op.f('uq_refresh_tokens_jti'))
    )
    op.create_index('ix_refresh_tokens_expires_at', 'refresh_tokens', ['expires_at'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_token_hash'), 'refresh_tokens', ['token_hash'], unique=True)
    op.create_index('ix_refresh_tokens_user_active', 'refresh_tokens', ['user_id', 'revoked'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_refresh_tokens_user_id'), table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_user_active', table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_token_hash'), table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_expires_at', table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_index('ix_users_role_active', table_name='users')
    op.drop_index(op.f('ix_users_role'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    # ``drop_table`` does not remove the enum type; without this, a later
    # upgrade would fail with "type user_role already exists".
    sa.Enum(name="user_role").drop(op.get_bind(), checkfirst=True)
