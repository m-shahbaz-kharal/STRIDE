from __future__ import annotations

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/liguard")

# Connection-pool sizing. The defaults (5 pool / 10 overflow) are
# fine for a small deployment; on a busy server bump
# STRIDE_DB_POOL_SIZE / STRIDE_DB_MAX_OVERFLOW. ``pool_pre_ping`` keeps
# stale connections (e.g. after a server-side idle timeout) from
# surfacing as request-time errors.
_POOL_SIZE = int(os.getenv("STRIDE_DB_POOL_SIZE", "10"))
_MAX_OVERFLOW = int(os.getenv("STRIDE_DB_MAX_OVERFLOW", "10"))
_POOL_TIMEOUT = int(os.getenv("STRIDE_DB_POOL_TIMEOUT", "30"))


class Base(DeclarativeBase):
    pass


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=_POOL_SIZE,
    max_overflow=_MAX_OVERFLOW,
    pool_timeout=_POOL_TIMEOUT,
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
