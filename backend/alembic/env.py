from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.config import settings
from app.models import Base

config = context.config
# ConfigParser treats percent signs as interpolation markers. Keep the URL
# unchanged for SQLAlchemy while escaping encoded query parameters in Alembic's
# config representation.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
_LEGACY_ENUM_CONSTRAINTS = {
    "tms_type",
    "load_status",
    "equipment_type",
    "stop_type",
    "rate_side",
    "ingestion_status",
    "ingestion_job_status",
}


def include_object(object_, name, type_, reflected, compare_to):
    """Keep legacy portable-enum checks out of schema drift detection."""
    return not (type_ == "check_constraint" and name in _LEGACY_ENUM_CONSTRAINTS)


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
