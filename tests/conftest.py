import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.database as app_database
import app.main as app_main
from app.models import Base


async def _noop_seed_database():
    return None


def _sync_run(coro):
    return asyncio.run(coro)


@pytest.fixture
def test_db_engine(tmp_path):
    db_path = tmp_path / "test.db"
    database_url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(
        database_url,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    async_session = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def initialize_database():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    _sync_run(initialize_database())
    try:
        yield engine, async_session
    finally:
        _sync_run(engine.dispose())


@pytest.fixture
def client(test_db_engine):
    engine, async_session = test_db_engine

    async def override_get_db():
        async with async_session() as session:
            yield session

    # Patch the application to use the test database and avoid production seeding.
    app_main.engine = engine
    app_main.seed_database = _noop_seed_database
    app_database.engine = engine
    app_database.async_session = async_session

    app_main.app.dependency_overrides[app_database.get_db] = override_get_db
    app_main.app.dependency_overrides[app_main.get_db] = override_get_db

    with TestClient(app_main.app) as test_client:
        yield test_client

    app_main.app.dependency_overrides.clear()
