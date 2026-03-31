from sqlmodel import SQLModel, Session, create_engine

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, echo=False, connect_args=connect_args)


def init_db() -> None:
    # Ensure models are imported so SQLModel registers tables.
    import app.models  # noqa: F401

    # When sqlite files are deleted/recreated during local development,
    # stale pooled connections can point at the old file handle and fail writes.
    engine.dispose()
    if settings.reset_db_on_start:
        SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session

