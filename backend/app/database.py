from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine_options = {
    "pool_pre_ping": True,
    "pool_size": settings.db_pool_size,
    "max_overflow": settings.db_max_overflow,
    "pool_timeout": settings.db_pool_timeout_seconds,
    "pool_recycle": settings.db_pool_recycle_seconds,
}
if settings.database_url.startswith("postgresql"):
    engine_options["connect_args"] = {
        "options": (
            f"-c statement_timeout={settings.db_statement_timeout_ms} "
            f"-c idle_in_transaction_session_timeout={settings.db_idle_transaction_timeout_ms}"
        )
    }
else:
    for option in ("pool_size", "max_overflow", "pool_timeout", "pool_recycle"):
        engine_options.pop(option)

engine = create_engine(settings.database_url, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
