import pathlib
import sqlite3
from datetime import datetime, timezone


DOC_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".gif",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".tif",
    ".tiff",
    ".txt",
    ".webp",
    ".xls",
    ".xlsx",
}


def init_docs_db(db_path):
    path = pathlib.Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(path))
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS docs_files (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                size_bytes INTEGER NOT NULL,
                modified_at TEXT,
                indexed_at TEXT NOT NULL
            )
            """
        )
        connection.commit()
    finally:
        connection.close()


def index_docs(local_root, db_path, extensions=None):
    root = pathlib.Path(local_root)
    init_docs_db(db_path)

    allowed = set(extensions or DOC_EXTENSIONS)
    indexed_at = datetime.now(timezone.utc).isoformat()
    rows = []

    if root.exists():
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if allowed and path.suffix.lower() not in allowed:
                continue

            stat = path.stat()
            rows.append(
                (
                    path.name,
                    str(path),
                    stat.st_size,
                    datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    indexed_at,
                )
            )

    connection = sqlite3.connect(str(db_path))
    try:
        connection.execute("DELETE FROM docs_files")
        connection.executemany(
            """
            INSERT INTO docs_files (
                name,
                path,
                size_bytes,
                modified_at,
                indexed_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()
    finally:
        connection.close()

    return len(rows)
