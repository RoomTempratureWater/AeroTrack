import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.config import settings

# Ensure data directory exists for SQLite
db_url = settings.DATABASE_URL
if db_url.startswith("sqlite+aiosqlite:///"):
    # Strip the scheme — handles both relative (///) and absolute (////) paths
    db_path = db_url.replace("sqlite+aiosqlite:///", "", 1)
    if not db_path.startswith("/"):
        # relative path: resolve against CWD
        db_path = os.path.abspath(db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with async_session() as session:
        yield session
