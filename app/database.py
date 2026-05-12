import os
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

_raw_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./team_task_manager.db")

# Railway sets DATABASE_URL as postgresql:// — upgrade it to the asyncpg dialect.
if _raw_url.startswith("postgresql://"):
    DATABASE_URL = _raw_url.replace(
        "postgresql://",
        "postgresql+asyncpg://",
        1,
    )
elif _raw_url.startswith("postgres://"):
    DATABASE_URL = _raw_url.replace(
        "postgres://",
        "postgresql+asyncpg://",
        1,
    )
else:
    DATABASE_URL = _raw_url

print(f"Using the database : {DATABASE_URL}")

# echo defaults to off; set DB_ECHO=1 locally to see SQL queries.
engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=os.getenv("DB_ECHO", "0") == "1",
)

# Enable SQLite foreign key constraints
if DATABASE_URL.startswith("sqlite"):
    
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session
