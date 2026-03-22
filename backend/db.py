"""SQLite database schema, connection helper, and queries."""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from backend.config import settings

DB_PATH = os.path.join(settings.data_dir, "booktidy.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS processing_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL DEFAULT 'running',
    total_files INTEGER DEFAULT 0,
    epub_count INTEGER DEFAULT 0,
    non_epub_count INTEGER DEFAULT 0,
    duplicate_count INTEGER DEFAULT 0,
    processed_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,
    relative_path TEXT NOT NULL DEFAULT '',
    file_name TEXT NOT NULL,
    file_size_bytes INTEGER,
    md5_hash TEXT,
    state TEXT NOT NULL DEFAULT 'pending',
    scan_job_id INTEGER REFERENCES processing_jobs(id),

    -- Original metadata from EPUB OPF
    orig_title TEXT,
    orig_subtitle TEXT,
    orig_author TEXT,
    orig_series TEXT,
    orig_series_index REAL,
    orig_series_total REAL,
    orig_language TEXT,
    orig_publisher TEXT,
    orig_date TEXT,
    orig_isbn TEXT,
    orig_description TEXT,
    orig_subjects TEXT,

    -- Text sample
    text_sample TEXT,

    -- Open Library response
    open_library_data TEXT,

    -- LLM primary response
    llm_primary_model TEXT,
    llm_primary_raw TEXT,
    llm_primary_title TEXT,
    llm_primary_author TEXT,
    llm_primary_series TEXT,
    llm_primary_series_index REAL,
    llm_primary_series_total REAL,
    llm_primary_year INTEGER,
    llm_primary_language TEXT,
    llm_primary_publisher TEXT,
    llm_primary_description TEXT,
    llm_primary_genre TEXT,
    llm_primary_subgenre TEXT,
    llm_primary_subjects TEXT,
    llm_primary_title_confidence REAL,
    llm_primary_author_confidence REAL,
    llm_primary_confidence REAL,
    llm_primary_confidence_notes TEXT,
    llm_primary_quality_ok INTEGER,
    llm_primary_quality_issues TEXT,
    llm_primary_flags TEXT,

    -- LLM secondary response (nullable)
    llm_secondary_used INTEGER DEFAULT 0,
    llm_secondary_model TEXT,
    llm_secondary_raw TEXT,
    llm_secondary_title TEXT,
    llm_secondary_author TEXT,
    llm_secondary_series TEXT,
    llm_secondary_series_index REAL,
    llm_secondary_series_total REAL,
    llm_secondary_year INTEGER,
    llm_secondary_language TEXT,
    llm_secondary_publisher TEXT,
    llm_secondary_description TEXT,
    llm_secondary_genre TEXT,
    llm_secondary_subgenre TEXT,
    llm_secondary_subjects TEXT,
    llm_secondary_title_confidence REAL,
    llm_secondary_author_confidence REAL,
    llm_secondary_confidence REAL,
    llm_secondary_confidence_notes TEXT,
    llm_secondary_quality_ok INTEGER,
    llm_secondary_quality_issues TEXT,
    llm_secondary_flags TEXT,

    -- Final proposed metadata (editable by user)
    proposed_title TEXT,
    proposed_author TEXT,
    proposed_series TEXT,
    proposed_series_index REAL,
    proposed_series_total REAL,
    proposed_year INTEGER,
    proposed_language TEXT,
    proposed_publisher TEXT,
    proposed_description TEXT,
    proposed_genre TEXT,
    proposed_subgenre TEXT,
    proposed_subjects TEXT,
    proposed_filename TEXT,

    -- Confidence scores (from winning LLM result)
    title_confidence REAL,
    author_confidence REAL,
    overall_confidence REAL,
    confidence_notes TEXT,
    quality_ok INTEGER DEFAULT 1,
    quality_issues TEXT,
    flags TEXT,

    -- Sanitisation
    sanitisation_diff TEXT,

    -- Outcome
    output_path TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_books_state ON books(state);
CREATE INDEX IF NOT EXISTS idx_books_md5 ON books(md5_hash);
CREATE INDEX IF NOT EXISTS idx_books_scan_job ON books(scan_job_id);

CREATE TABLE IF NOT EXISTS non_epub_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,
    file_name TEXT NOT NULL,
    file_size_bytes INTEGER,
    file_extension TEXT,
    scan_job_id INTEGER REFERENCES processing_jobs(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS duplicate_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    original_file_path TEXT NOT NULL,
    md5_hash TEXT NOT NULL,
    file_size_bytes INTEGER,
    scan_job_id INTEGER REFERENCES processing_jobs(id),
    action TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_duplicate_md5 ON duplicate_files(md5_hash);
"""


async def init_db() -> None:
    """Create database and tables if they don't exist."""
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript(SCHEMA_SQL)
        await db.commit()


@asynccontextmanager
async def get_db():
    """Yield a fresh aiosqlite connection. Always use inside `async with`."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

async def create_job() -> int:
    async with get_db() as db:
        cursor = await db.execute("INSERT INTO processing_jobs DEFAULT VALUES")
        await db.commit()
        return cursor.lastrowid


async def update_job(job_id: int, **kwargs) -> None:
    if not kwargs:
        return
    cols = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values())
    vals.append(job_id)
    async with get_db() as db:
        await db.execute(f"UPDATE processing_jobs SET {cols} WHERE id = ?", vals)
        await db.commit()


async def get_job(job_id: int) -> Optional[dict]:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM processing_jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def insert_book(data: dict) -> int:
    cols = ", ".join(data.keys())
    placeholders = ", ".join("?" for _ in data)
    async with get_db() as db:
        cursor = await db.execute(
            f"INSERT OR IGNORE INTO books ({cols}) VALUES ({placeholders})",
            list(data.values()),
        )
        await db.commit()
        return cursor.lastrowid


async def update_book(book_id: int, **kwargs) -> None:
    if not kwargs:
        return
    kwargs["updated_at"] = "datetime('now')"
    sets = []
    vals = []
    for k, v in kwargs.items():
        if v == "datetime('now')":
            sets.append(f"{k} = datetime('now')")
        else:
            sets.append(f"{k} = ?")
            vals.append(v)
    vals.append(book_id)
    async with get_db() as db:
        await db.execute(f"UPDATE books SET {', '.join(sets)} WHERE id = ?", vals)
        await db.commit()


async def get_book(book_id: int) -> Optional[dict]:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM books WHERE id = ?", (book_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_books(state: Optional[str] = None, states: Optional[list[str]] = None) -> list[dict]:
    async with get_db() as db:
        if states:
            placeholders = ", ".join("?" for _ in states)
            cursor = await db.execute(
                f"SELECT * FROM books WHERE state IN ({placeholders}) ORDER BY id", states,
            )
        elif state:
            cursor = await db.execute(
                "SELECT * FROM books WHERE state = ? ORDER BY id", (state,),
            )
        else:
            cursor = await db.execute("SELECT * FROM books ORDER BY id")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_book_counts() -> dict:
    async with get_db() as db:
        counts = {}
        for s in [
            "pending", "processing", "review", "flagged_quality",
            "non_english", "auto_accepted", "approved", "committed",
            "error", "skipped", "rejected",
        ]:
            cursor = await db.execute("SELECT COUNT(*) FROM books WHERE state = ?", (s,))
            row = await cursor.fetchone()
            counts[s] = row[0]
        cursor = await db.execute("SELECT COUNT(*) FROM books")
        row = await cursor.fetchone()
        counts["total"] = row[0]
        return counts


async def insert_non_epub(data: dict) -> int:
    cols = ", ".join(data.keys())
    placeholders = ", ".join("?" for _ in data)
    async with get_db() as db:
        cursor = await db.execute(
            f"INSERT OR IGNORE INTO non_epub_files ({cols}) VALUES ({placeholders})",
            list(data.values()),
        )
        await db.commit()
        return cursor.lastrowid


async def get_non_epub_files() -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM non_epub_files ORDER BY file_path")
        return [dict(r) for r in await cursor.fetchall()]


async def delete_all_non_epub() -> list[str]:
    """Delete all non-epub files from disk and DB. Returns list of deleted paths."""
    files = await get_non_epub_files()
    deleted = []
    for f in files:
        path = f["file_path"]
        try:
            if os.path.exists(path):
                os.remove(path)
                deleted.append(path)
        except OSError:
            pass
    async with get_db() as db:
        await db.execute("DELETE FROM non_epub_files")
        await db.commit()
    return deleted


async def insert_duplicate(data: dict) -> int:
    cols = ", ".join(data.keys())
    placeholders = ", ".join("?" for _ in data)
    async with get_db() as db:
        cursor = await db.execute(
            f"INSERT INTO duplicate_files ({cols}) VALUES ({placeholders})",
            list(data.values()),
        )
        await db.commit()
        return cursor.lastrowid


async def get_duplicates() -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM duplicate_files WHERE action = 'pending' ORDER BY md5_hash, file_path"
        )
        return [dict(r) for r in await cursor.fetchall()]


async def delete_duplicate_files() -> list[str]:
    """Delete pending duplicate files from disk and mark as deleted in DB."""
    dupes = await get_duplicates()
    deleted = []
    for d in dupes:
        path = d["file_path"]
        try:
            if os.path.exists(path):
                os.remove(path)
                deleted.append(path)
        except OSError:
            pass
    async with get_db() as db:
        await db.execute("UPDATE duplicate_files SET action = 'deleted' WHERE action = 'pending'")
        await db.commit()
    return deleted


async def get_latest_job() -> Optional[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM processing_jobs ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
