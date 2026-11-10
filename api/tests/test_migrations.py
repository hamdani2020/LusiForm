"""Migration round trip: upgrade head, downgrade base, upgrade again, all clean."""

from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.data.models import Base
from tests.dbutil import alembic_config

EXPECTED_TABLES = {
    "partners",
    "users",
    "user_roles",
    "projects",
    "project_versions",
    "intake_drafts",
    "template_versions",
    "assumption_sets",
    "estimates",
    "generation_jobs",
    "artifacts",
    "validation_runs",
    "audit_events",
    "sandbox_accounts",
    "architecture_graphs",
    "diagram_artifacts",
    "deployment_plans",
    "plan_approvals",
    "deployments",
}


def _user_tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def _db_objects(url: str) -> tuple[int, int]:
    """(# of lusiform_* functions, # of non-internal triggers)."""
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            funcs = conn.execute(
                text("SELECT count(*) FROM pg_proc WHERE proname LIKE 'lusiform\\_%'")
            ).scalar_one()
            triggers = conn.execute(
                text("SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal")
            ).scalar_one()
        return funcs, triggers
    finally:
        engine.dispose()


def test_models_cover_exactly_the_nineteen_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES
    assert len(EXPECTED_TABLES) == 19


def test_upgrade_downgrade_round_trip_is_clean(scratch_db_url: str) -> None:
    cfg = alembic_config()
    assert _user_tables(scratch_db_url) == set()

    command.upgrade(cfg, "head")
    assert _user_tables(scratch_db_url) == EXPECTED_TABLES
    funcs, triggers = _db_objects(scratch_db_url)
    assert funcs == 3
    assert triggers > 0

    command.downgrade(cfg, "base")
    assert _user_tables(scratch_db_url) == set()
    assert _db_objects(scratch_db_url) == (0, 0)

    # And forward again, proving the downgrade left nothing behind.
    command.upgrade(cfg, "head")
    assert _user_tables(scratch_db_url) == EXPECTED_TABLES


def test_models_match_migration(scratch_db_url: str) -> None:
    """Autogenerate finds no drift between the models and the migrated schema."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    command.upgrade(alembic_config(), "head")
    engine = create_engine(scratch_db_url)
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"compare_type": True})
            assert compare_metadata(ctx, Base.metadata) == []
    finally:
        engine.dispose()
