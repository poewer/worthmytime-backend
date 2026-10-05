from alembic import command
from alembic.config import Config
from sanic_testing.reusable import ReusableClient
from sqlalchemy import create_engine, inspect

from app.main import create_app
from app.models import Base


def _alembic(url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_upgrade_creates_all_tables_and_downgrade_removes(tmp_path):
    db = tmp_path / "m.db"
    cfg = _alembic(f"sqlite+aiosqlite:///{db}")
    sync = create_engine(f"sqlite:///{db}")

    command.upgrade(cfg, "head")
    assert set(Base.metadata.tables) <= set(inspect(sync).get_table_names())

    command.downgrade(cfg, "base")
    assert set(Base.metadata.tables).isdisjoint(inspect(sync).get_table_names())


def test_models_match_migrations(tmp_path):
    """Autogenerate nie powinien widzieć różnic między modelami a migracjami."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    db = tmp_path / "d.db"
    command.upgrade(_alembic(f"sqlite+aiosqlite:///{db}"), "head")
    with create_engine(f"sqlite:///{db}").connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_app_runs_on_migrated_db(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'a.db'}"
    command.upgrade(_alembic(url), "head")
    with ReusableClient(create_app(url)) as client:  # bez create_schema
        _, res = client.get("/api/v1/health")
        assert res.status == 200
