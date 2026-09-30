"""Migration hygiene: a single head, and metadata that matches the migrations."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _script_directory() -> ScriptDirectory:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return ScriptDirectory.from_config(config)


class TestMigrationChain:
    def test_there_is_exactly_one_head(self) -> None:
        heads = _script_directory().get_heads()

        assert len(heads) == 1, f"Multiple migration heads found: {heads}"

    def _source_of(self, revision: str) -> str:
        script = _script_directory().get_revision(revision)
        assert script is not None, f"Revision {revision} not found"
        return Path(script.path).read_text()

    def _source_containing(self, marker: str) -> str:
        """The source of whichever revision introduced ``marker``.

        Tests below assert on the revision that *added* a table rather than on
        whatever happens to be the head, so later phases do not break them.
        """
        for script in _script_directory().walk_revisions():
            source = Path(script.path).read_text()
            if marker in source:
                return source
        raise AssertionError(f"No revision contains {marker!r}")

    def _initial_revision(self) -> str:
        """Walk the chain down to its root, whatever the current head is."""
        script = _script_directory().get_revision(_script_directory().get_current_head())
        assert script is not None
        while script.down_revision is not None:
            script = _script_directory().get_revision(script.down_revision)
            assert script is not None
        return script.revision

    def test_initial_revision_creates_auth_tables(self) -> None:
        source = self._source_of(self._initial_revision())

        assert "create_table('users'" in source
        assert "create_table('refresh_tokens'" in source
        assert "name='user_role'" in source
        # The enum type must be dropped explicitly on downgrade.
        assert "sa.Enum(name=\"user_role\").drop" in source

    def test_phase_two_revision_creates_the_management_tables(self) -> None:
        """The Phase 2 migration covers profiles, beekeepers, clusters and audit."""
        source = self._source_containing("create_table('beekeepers'")

        for table in (
            "user_profiles",
            "kvic_clusters",
            "beekeepers",
            "beekeeper_verification_history",
            "audit_logs",
            "document_sequences",
        ):
            assert f"create_table('{table}'" in source, table

        # The shared enum is created once and referenced with create_type=False.
        assert "verification_status_enum.create" in source
        assert "create_type=False" in source
        # …and dropped on downgrade, because drop_table does not remove types.
        assert "verification_status_enum.drop" in source

    def test_phase_three_revision_creates_the_hive_and_iot_tables(self) -> None:
        """Phase 3 adds the hive registry and the smart-hive IoT tables."""
        source = self._source_containing("create_table('hives'")

        for table in ("hives", "iot_devices", "sensor_configs", "sensor_readings"):
            assert f"create_table('{table}'" in source, table

        # Every enum the phase introduces is created once, explicitly, and dropped
        # again on downgrade — the same pattern the Phase 2 migration uses.
        for enum_name in (
            "queen_status",
            "colony_strength",
            "hive_status",
            "device_type",
            "connection_type",
            "device_status",
            "sensor_type",
            "telemetry_source",
        ):
            assert f'name="{enum_name}"' in source, enum_name
        assert "enum_type.create(op.get_bind(), checkfirst=True)" in source
        assert "enum_type.drop(op.get_bind(), checkfirst=True)" in source

        # Telemetry must stay idempotent at the database level.
        assert "uq_sensor_readings_device_timestamp" in source

    def test_phase_four_revision_creates_the_ai_tables(self) -> None:
        """Phase 4 adds the stored analyses and the alerts raised by them."""
        source = self._source_containing("'hive_ai_analyses'")

        assert "op.create_table(" in source
        for table in ("hive_ai_analyses", "ai_alerts"):
            assert f"'{table}'" in source, table

        # Eight enum types, created explicitly and dropped again on downgrade.
        for enum_name in (
            "ai_health_status",
            "ai_risk_level",
            "ai_trend",
            "ai_data_quality",
            "ai_analysis_source",
            "ai_alert_type",
            "ai_alert_severity",
            "ai_alert_status",
        ):
            assert f'name="{enum_name}"' in source, enum_name
        assert "enum_type.create(op.get_bind(), checkfirst=True)" in source
        assert "enum_type.drop(op.get_bind(), checkfirst=True)" in source

        # Alert de-duplication is a service rule, not a database constraint: a
        # partial unique index on ``status`` would not work on the SQLite
        # fallback the test suite uses.
        assert "dedupe_key" in source
        assert "uq_ai" not in source

        # The alert cascade follows the analysis it came from.
        assert "ondelete='CASCADE'" in source

    def test_phase_two_revision_chain_is_linear(self) -> None:
        scripts = list(_script_directory().walk_revisions())
        # alembic_version is not a script; every script except the head has
        # exactly one child.
        assert len(scripts) >= 2
        assert all(script.down_revision is not None for script in scripts[:-1])

    def test_model_metadata_defines_the_expected_tables(self) -> None:
        from app.models import Base

        assert {
            "users",
            "refresh_tokens",
            "user_profiles",
            "kvic_clusters",
            "beekeepers",
            "beekeeper_verification_history",
            "audit_logs",
            "document_sequences",
            # Phase 3
            "hives",
            "iot_devices",
            "sensor_configs",
            "sensor_readings",
            # Phase 4
            "hive_ai_analyses",
            "ai_alerts",
        } <= set(Base.metadata.tables)

    def test_uuid_primary_keys_and_timestamps(self) -> None:
        from app.models import Base

        for table_name in ("users", "refresh_tokens"):
            table = Base.metadata.tables[table_name]
            assert "id" in table.columns
            assert table.columns["id"].primary_key
            assert "created_at" in table.columns
            assert "updated_at" in table.columns

    def test_users_table_has_no_plaintext_password_column(self) -> None:
        from app.models import Base

        users = Base.metadata.tables["users"]
        assert "password_hash" in users.columns
        assert "password" not in users.columns
