from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


def _sqlite_connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


engine = create_engine(
    settings.database_url,
    connect_args=_sqlite_connect_args(settings.database_url),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def migrate_sqlite_schema() -> None:
    """为旧版 SQLite 库补充列（create_all 不会 ALTER）。"""
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        if conn.dialect.name != "sqlite":
            return
        rows = conn.execute(text("PRAGMA table_info(tasks)")).fetchall()
        cols = {row[1] for row in rows}
        if "zip_md5" not in cols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN zip_md5 VARCHAR(32)"))
        if "collection_template_original_filename" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE tasks ADD COLUMN collection_template_original_filename VARCHAR(512)"
                )
            )
        if "run_ocr" not in cols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN run_ocr BOOLEAN DEFAULT 1"))
        if "run_claude" not in cols:
            conn.execute(
                text("ALTER TABLE tasks ADD COLUMN run_claude BOOLEAN DEFAULT 1")
            )
        if "run_agent" not in cols:
            conn.execute(
                text("ALTER TABLE tasks ADD COLUMN run_agent BOOLEAN DEFAULT 1")
            )
            if "run_claude" in cols:
                conn.execute(text("UPDATE tasks SET run_agent = run_claude"))
        if "run_collection_fill" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE tasks ADD COLUMN run_collection_fill BOOLEAN DEFAULT 1"
                )
            )
        if "task_kind" not in cols:
            conn.execute(
                text("ALTER TABLE tasks ADD COLUMN task_kind VARCHAR(32) DEFAULT 'general'")
            )
            conn.execute(
                text("UPDATE tasks SET task_kind = 'general' WHERE task_kind IS NULL")
            )
        if "source_docx_filename" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE tasks ADD COLUMN source_docx_filename VARCHAR(512)"
                )
            )
        if "indicator_judgment_rules" not in cols:
            conn.execute(
                text("ALTER TABLE tasks ADD COLUMN indicator_judgment_rules TEXT")
            )
        if "fill_logic_rules" not in cols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN fill_logic_rules TEXT"))
        conn.execute(
            text(
                "UPDATE tasks SET status = 'AGENT_RUNNING' WHERE status = 'CLAUDE_RUNNING'"
            )
        )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
