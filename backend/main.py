"""FastAPI application — routes, WebSocket endpoint, static file serving."""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import db
from backend.config import get_settings_for_api, reload_settings, save_settings, settings
from backend.llm_client import (
    FALLBACK_MODEL_LIST,
    PINNED_MODELS,
    fetch_models,
    test_connection,
)
from backend.scanner import (
    _cleanup_empty_dirs,
    commit_all_approved,
    commit_book,
    progress_queue,
    scan_input_dir,
    undo_book,
)

logger = logging.getLogger("booktidy")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

LOG_FILE = os.path.join(settings.data_dir, "booktidy.log")
try:
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(file_handler)
except Exception:
    pass

# WebSocket connections
active_ws: set[WebSocket] = set()


async def _broadcaster():
    """Read from progress_queue and fan out to all WebSocket clients."""
    while True:
        try:
            msg = await progress_queue.get()
            dead = set()
            for ws in active_ws:
                try:
                    await ws.send_json(msg)
                except Exception:
                    dead.add(ws)
            active_ws -= dead
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(0.1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    task = asyncio.create_task(_broadcaster())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="BookTidy", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Determine frontend directory relative to this file
def _delete_source_file(file_path: str | None) -> None:
    """Delete a source file from the input dir and clean up empty parent dirs."""
    if not file_path:
        return
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            _cleanup_empty_dirs(os.path.dirname(file_path), settings.input_dir)
            logger.info(f"Deleted source file: {file_path}")
    except OSError as e:
        logger.warning(f"Could not delete source file {file_path}: {e}")


FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ---------------------------------------------------------------------------
# Serve frontend
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    return FileResponse(index_path)


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws/progress")
async def ws_progress(websocket: WebSocket):
    await websocket.accept()
    active_ws.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_ws.discard(websocket)
    except Exception:
        active_ws.discard(websocket)


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

@app.post("/api/scan")
async def trigger_scan():
    job_id = await db.create_job()
    asyncio.create_task(scan_input_dir(job_id))
    return {"job_id": job_id, "status": "started"}


@app.get("/api/jobs/latest")
async def get_latest_job():
    job = await db.get_latest_job()
    return job or {}


# ---------------------------------------------------------------------------
# Books
# ---------------------------------------------------------------------------

class MetadataUpdate(BaseModel):
    proposed_title: Optional[str] = None
    proposed_author: Optional[str] = None
    proposed_series: Optional[str] = None
    proposed_series_index: Optional[float] = None
    proposed_series_total: Optional[float] = None
    proposed_year: Optional[int] = None
    proposed_language: Optional[str] = None
    proposed_publisher: Optional[str] = None
    proposed_description: Optional[str] = None
    proposed_genre: Optional[str] = None
    proposed_subgenre: Optional[str] = None
    proposed_subjects: Optional[str] = None


@app.get("/api/books")
async def list_books(state: Optional[str] = None):
    if state:
        states = [s.strip() for s in state.split(",")]
        books = await db.get_books(states=states)
    else:
        books = await db.get_books()
    return {"books": books}


@app.get("/api/books/counts")
async def book_counts():
    return await db.get_book_counts()


@app.get("/api/books/{book_id}")
async def get_book(book_id: int):
    book = await db.get_book(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    return book


@app.put("/api/books/{book_id}/metadata")
async def update_metadata(book_id: int, data: MetadataUpdate):
    book = await db.get_book(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if updates:
        # Rebuild filename if title/author/series changed
        from backend.sanitiser import build_filename, sanitise_string
        title = updates.get("proposed_title", book.get("proposed_title", ""))
        author = updates.get("proposed_author", book.get("proposed_author", ""))
        series = updates.get("proposed_series", book.get("proposed_series"))
        series_idx = updates.get("proposed_series_index", book.get("proposed_series_index"))
        series_total = updates.get("proposed_series_total", book.get("proposed_series_total"))
        filename = build_filename(author, title, series, series_idx, series_total)
        updates["proposed_filename"] = filename
        await db.update_book(book_id, **updates)
    return {"status": "updated"}


@app.post("/api/books/{book_id}/approve")
async def approve_book(book_id: int):
    book = await db.get_book(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    if book["state"] not in ("review", "flagged_quality", "non_english"):
        raise HTTPException(400, f"Cannot approve book in state '{book['state']}'")
    await db.update_book(book_id, state="approved")
    return {"status": "approved"}


@app.post("/api/books/bulk-approve")
async def bulk_approve(book_ids: list[int]):
    results = []
    for bid in book_ids:
        try:
            book = await db.get_book(bid)
            if book and book["state"] in ("review", "flagged_quality", "non_english"):
                await db.update_book(bid, state="approved")
                results.append({"book_id": bid, "status": "approved"})
            else:
                results.append({"book_id": bid, "status": "skipped", "reason": "invalid state"})
        except Exception as e:
            results.append({"book_id": bid, "status": "error", "reason": str(e)})
    return {"results": results}


@app.post("/api/books/{book_id}/reject")
async def reject_book(book_id: int):
    book = await db.get_book(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    # Delete source file from input
    _delete_source_file(book.get("file_path"))
    await db.update_book(book_id, state="rejected")
    return {"status": "rejected"}


@app.post("/api/books/{book_id}/skip")
async def skip_book(book_id: int):
    book = await db.get_book(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    # Delete source file from input
    _delete_source_file(book.get("file_path"))
    await db.update_book(book_id, state="skipped")
    return {"status": "skipped"}


@app.post("/api/books/{book_id}/undo")
async def undo_book_endpoint(book_id: int):
    book = await db.get_book(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    if book["state"] not in ("auto_accepted", "committed"):
        raise HTTPException(400, f"Cannot undo book in state '{book['state']}'")
    try:
        await undo_book(book_id)
        return {"status": "undone"}
    except Exception as e:
        raise HTTPException(500, str(e))


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------

@app.post("/api/commit")
async def commit_all():
    results = await commit_all_approved()
    return {"results": results}


@app.post("/api/commit/{book_id}")
async def commit_single(book_id: int):
    try:
        output_path = await commit_book(book_id)
        return {"status": "committed", "output_path": output_path}
    except Exception as e:
        raise HTTPException(500, str(e))


# ---------------------------------------------------------------------------
# Non-EPUB files
# ---------------------------------------------------------------------------

@app.get("/api/non-epub")
async def list_non_epub():
    files = await db.get_non_epub_files()
    return {"files": files}


class DeleteConfirmation(BaseModel):
    confirmed: bool = False


@app.delete("/api/non-epub")
async def delete_non_epub(data: DeleteConfirmation):
    if not data.confirmed:
        raise HTTPException(400, "Confirmation required")
    deleted = await db.delete_all_non_epub()
    return {"deleted": deleted, "count": len(deleted)}


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------

@app.get("/api/duplicates")
async def list_duplicates():
    dupes = await db.get_duplicates()
    return {"duplicates": dupes}


@app.delete("/api/duplicates")
async def delete_duplicates(data: DeleteConfirmation):
    if not data.confirmed:
        raise HTTPException(400, "Confirmation required")
    deleted = await db.delete_duplicate_files()
    return {"deleted": deleted, "count": len(deleted)}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class SettingsUpdate(BaseModel):
    openrouter_api_key: Optional[str] = None
    openrouter_model_primary: Optional[str] = None
    openrouter_model_secondary: Optional[str] = None
    llm_concurrency: Optional[int] = None
    auto_accept_threshold: Optional[float] = None
    input_dir: Optional[str] = None
    output_dir: Optional[str] = None


@app.get("/api/settings")
async def get_settings():
    return get_settings_for_api()


@app.put("/api/settings")
async def update_settings(data: SettingsUpdate):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    for key, value in updates.items():
        if hasattr(settings, key):
            # Don't overwrite API key with masked value
            if key == "openrouter_api_key" and value == "****":
                continue
            setattr(settings, key, value)
    save_settings()
    return {"status": "saved"}


@app.post("/api/settings/test-llm")
async def test_llm():
    primary_result = await test_connection(settings.openrouter_model_primary)
    secondary_result = await test_connection(settings.openrouter_model_secondary)
    return {"primary": primary_result, "secondary": secondary_result}


@app.post("/api/settings/refresh-models")
async def refresh_models():
    models = await fetch_models()
    return {"models": models, "pinned": PINNED_MODELS}


@app.get("/api/models")
async def get_models():
    return {"models": FALLBACK_MODEL_LIST, "pinned": PINNED_MODELS}


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

@app.get("/api/logs")
async def get_logs(lines: int = 100):
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r") as f:
                all_lines = f.readlines()
                return {"lines": all_lines[-lines:]}
    except Exception:
        pass
    return {"lines": []}
