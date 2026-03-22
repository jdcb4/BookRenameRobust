"""INPUT_DIR scan, deduplication, pipeline orchestration, and async worker pool."""

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from backend import db
from backend.config import settings
from backend.epub_parser import extract_metadata, write_metadata_and_move
from backend.llm_client import enrich_book
from backend.open_library import lookup as ol_lookup
from backend.router import route_book
from backend.sanitiser import (
    build_filename,
    normalise_author,
    sanitise_all_fields,
    sanitise_string,
    strip_generic_subtitle,
)
from backend.text_extractor import extract_text_sample

logger = logging.getLogger("booktidy.scanner")

# Module-level progress queue — main.py reads from this via WebSocket broadcaster
progress_queue: asyncio.Queue = asyncio.Queue()


async def _notify(msg: dict) -> None:
    """Push a progress message for WebSocket broadcast."""
    await progress_queue.put(msg)


def _md5_sync(path: str) -> str:
    """Compute MD5 hash of a file (synchronous, run in executor)."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


async def compute_md5(path: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _md5_sync, path)


async def scan_input_dir(job_id: int) -> None:
    """Full scan pipeline: discover files → dedup → process each EPUB."""
    input_dir = settings.input_dir

    await _notify({"type": "scan_started", "job_id": job_id})

    # --- Step 0a: Walk and classify files ---
    epub_files: list[str] = []
    non_epub_files: list[str] = []

    for root, _dirs, files in os.walk(input_dir):
        for fname in files:
            fpath = os.path.join(root, fname)
            if fname.lower().endswith(".epub"):
                epub_files.append(fpath)
            else:
                non_epub_files.append(fpath)

    # Insert non-epub files
    for fpath in non_epub_files:
        fname = os.path.basename(fpath)
        ext = os.path.splitext(fname)[1].lower()
        try:
            size = os.path.getsize(fpath)
        except OSError:
            size = 0
        await db.insert_non_epub({
            "file_path": fpath,
            "file_name": fname,
            "file_size_bytes": size,
            "file_extension": ext,
            "scan_job_id": job_id,
        })

    await db.update_job(
        job_id,
        total_files=len(epub_files) + len(non_epub_files),
        epub_count=len(epub_files),
        non_epub_count=len(non_epub_files),
    )

    # --- Step 0b: Deduplication ---
    hash_map: dict[str, list[str]] = {}
    for fpath in epub_files:
        try:
            h = await compute_md5(fpath)
            hash_map.setdefault(h, []).append(fpath)
        except Exception as e:
            logger.error(f"Failed to hash {fpath}: {e}")

    duplicate_count = 0
    unique_epub_files: list[tuple[str, str]] = []  # (path, md5)

    for md5_hash, paths in hash_map.items():
        paths.sort()  # deterministic: keep first alphabetically
        unique_epub_files.append((paths[0], md5_hash))
        for dup_path in paths[1:]:
            duplicate_count += 1
            try:
                size = os.path.getsize(dup_path)
            except OSError:
                size = 0
            await db.insert_duplicate({
                "file_path": dup_path,
                "original_file_path": paths[0],
                "md5_hash": md5_hash,
                "file_size_bytes": size,
                "scan_job_id": job_id,
            })

    await db.update_job(job_id, duplicate_count=duplicate_count)

    await _notify({
        "type": "scan_classified",
        "job_id": job_id,
        "epub_count": len(unique_epub_files),
        "non_epub_count": len(non_epub_files),
        "duplicate_count": duplicate_count,
    })

    # --- Step 1+: Process each unique EPUB through the pipeline ---
    total = len(unique_epub_files)
    processed = 0
    errors = 0

    sem = asyncio.Semaphore(settings.llm_concurrency)

    async def process_one(fpath: str, md5_hash: str) -> None:
        nonlocal processed, errors
        try:
            await _process_book(fpath, md5_hash, job_id, sem)
        except Exception as e:
            errors += 1
            logger.error(f"Pipeline failed for {fpath}: {e}")
            # Try to insert/update as error
            try:
                fname = os.path.basename(fpath)
                rel = os.path.relpath(fpath, input_dir)
                book_id = await db.insert_book({
                    "file_path": fpath,
                    "relative_path": os.path.dirname(rel),
                    "file_name": fname,
                    "md5_hash": md5_hash,
                    "state": "error",
                    "error_message": str(e)[:500],
                    "scan_job_id": job_id,
                })
                await _notify({
                    "type": "book_update",
                    "book_id": book_id,
                    "state": "error",
                    "file_name": fname,
                    "error": str(e)[:200],
                })
            except Exception:
                pass
        finally:
            processed += 1
            await db.update_job(job_id, processed_count=processed, error_count=errors)
            await _notify({
                "type": "progress",
                "job_id": job_id,
                "done": processed,
                "total": total,
                "errors": errors,
            })

    tasks = [process_one(fpath, md5) for fpath, md5 in unique_epub_files]
    await asyncio.gather(*tasks)

    await db.update_job(job_id, status="completed", completed_at="datetime('now')")
    await _notify({"type": "scan_completed", "job_id": job_id})


async def _process_book(fpath: str, md5_hash: str, job_id: int, sem: asyncio.Semaphore) -> None:
    """Run the full pipeline for a single book."""
    input_dir = settings.input_dir
    fname = os.path.basename(fpath)
    rel = os.path.relpath(fpath, input_dir)
    relative_dir = os.path.dirname(rel)

    try:
        file_size = os.path.getsize(fpath)
    except OSError:
        file_size = 0

    # Insert book record as pending
    book_id = await db.insert_book({
        "file_path": fpath,
        "relative_path": relative_dir,
        "file_name": fname,
        "file_size_bytes": file_size,
        "md5_hash": md5_hash,
        "state": "processing",
        "scan_job_id": job_id,
    })

    if not book_id:
        # Already exists (UNIQUE constraint), update state
        existing = None
        async with db.get_db() as conn:
            cursor = await conn.execute("SELECT id, state FROM books WHERE file_path = ?", (fpath,))
            row = await cursor.fetchone()
            if row:
                book_id = row[0]
                if row[1] in ("committed", "approved", "auto_accepted"):
                    return  # Already processed
                await conn.execute(
                    "UPDATE books SET state = 'processing', scan_job_id = ? WHERE id = ?",
                    (job_id, book_id),
                )
                await conn.commit()

    await _notify({"type": "book_update", "book_id": book_id, "state": "processing", "file_name": fname})

    # --- Step 1: Extract EPUB metadata ---
    loop = asyncio.get_event_loop()
    try:
        epub_meta = await loop.run_in_executor(None, extract_metadata, fpath)
    except Exception as e:
        await db.update_book(book_id, state="error", error_message=f"EPUB parse error: {e}")
        await _notify({"type": "book_update", "book_id": book_id, "state": "error", "file_name": fname, "error": str(e)[:200]})
        return

    await db.update_book(book_id, **epub_meta)

    # --- Step 2: Extract text sample ---
    try:
        text_sample = await loop.run_in_executor(None, extract_text_sample, fpath)
    except Exception:
        text_sample = ""
    await db.update_book(book_id, text_sample=text_sample[:50000])  # cap storage

    # --- Step 3: Open Library lookup ---
    try:
        ol_data = await ol_lookup(
            isbn=epub_meta.get("orig_isbn"),
            title=epub_meta.get("orig_title"),
            author=epub_meta.get("orig_author"),
        )
    except Exception:
        ol_data = None

    if ol_data:
        await db.update_book(book_id, open_library_data=ol_data.get("raw", ""))

    # --- Step 4: Primary LLM enrichment (uses semaphore for concurrency control) ---
    book_data = {
        "relative_path": relative_dir,
        "file_name": fname,
        "text_sample": text_sample[:15000],  # cap prompt size
        "open_library_data": ol_data.get("raw") if ol_data else None,
        **epub_meta,
    }

    async with sem:
        try:
            llm_result = await enrich_book(book_data)
        except Exception as e:
            await db.update_book(book_id, state="error", error_message=f"LLM error: {e}")
            await _notify({"type": "book_update", "book_id": book_id, "state": "error", "file_name": fname, "error": str(e)[:200]})
            return

    # Store primary LLM result
    primary = llm_result["primary"]
    primary_update = {
        "llm_primary_model": llm_result["primary_model"],
        "llm_primary_raw": llm_result["primary_raw"],
        "llm_primary_title": primary.get("title"),
        "llm_primary_author": primary.get("author"),
        "llm_primary_series": primary.get("series"),
        "llm_primary_series_index": primary.get("series_index"),
        "llm_primary_series_total": primary.get("series_total"),
        "llm_primary_year": primary.get("year"),
        "llm_primary_language": primary.get("language"),
        "llm_primary_publisher": primary.get("publisher"),
        "llm_primary_description": primary.get("description"),
        "llm_primary_genre": primary.get("genre"),
        "llm_primary_subgenre": primary.get("subgenre"),
        "llm_primary_subjects": json.dumps(primary.get("subjects", [])),
        "llm_primary_title_confidence": primary.get("title_confidence"),
        "llm_primary_author_confidence": primary.get("author_confidence"),
        "llm_primary_confidence": primary.get("confidence"),
        "llm_primary_confidence_notes": primary.get("confidence_notes"),
        "llm_primary_quality_ok": 1 if primary.get("quality_ok") else 0,
        "llm_primary_quality_issues": json.dumps(primary.get("quality_issues", [])),
        "llm_primary_flags": json.dumps(primary.get("flags", [])),
    }
    await db.update_book(book_id, **primary_update)

    # Store secondary LLM result if used
    if llm_result["secondary"]:
        sec = llm_result["secondary"]
        sec_update = {
            "llm_secondary_used": 1,
            "llm_secondary_model": llm_result["secondary_model"],
            "llm_secondary_raw": llm_result["secondary_raw"],
            "llm_secondary_title": sec.get("title"),
            "llm_secondary_author": sec.get("author"),
            "llm_secondary_series": sec.get("series"),
            "llm_secondary_series_index": sec.get("series_index"),
            "llm_secondary_series_total": sec.get("series_total"),
            "llm_secondary_year": sec.get("year"),
            "llm_secondary_language": sec.get("language"),
            "llm_secondary_publisher": sec.get("publisher"),
            "llm_secondary_description": sec.get("description"),
            "llm_secondary_genre": sec.get("genre"),
            "llm_secondary_subgenre": sec.get("subgenre"),
            "llm_secondary_subjects": json.dumps(sec.get("subjects", [])),
            "llm_secondary_title_confidence": sec.get("title_confidence"),
            "llm_secondary_author_confidence": sec.get("author_confidence"),
            "llm_secondary_confidence": sec.get("confidence"),
            "llm_secondary_confidence_notes": sec.get("confidence_notes"),
            "llm_secondary_quality_ok": 1 if sec.get("quality_ok") else 0,
            "llm_secondary_quality_issues": json.dumps(sec.get("quality_issues", [])),
            "llm_secondary_flags": json.dumps(sec.get("flags", [])),
        }
        await db.update_book(book_id, **sec_update)

    # --- Determine winning result ---
    # If secondary was used, merge (prefer agreed values, flag disagreements)
    winning = primary
    if llm_result["secondary"]:
        winning = _merge_llm_results(primary, llm_result["secondary"])

    # --- Step 6: ASCII sanitisation ---
    proposed = {
        "proposed_title": winning.get("title", ""),
        "proposed_author": winning.get("author", ""),
        "proposed_series": winning.get("series"),
        "proposed_series_index": winning.get("series_index"),
        "proposed_series_total": winning.get("series_total"),
        "proposed_year": winning.get("year"),
        "proposed_language": winning.get("language", "en"),
        "proposed_publisher": winning.get("publisher"),
        "proposed_description": winning.get("description"),
        "proposed_genre": winning.get("genre"),
        "proposed_subgenre": winning.get("subgenre"),
        "proposed_subjects": json.dumps(winning.get("subjects", [])),
    }

    # Strip generic subtitles from title
    if proposed["proposed_title"]:
        proposed["proposed_title"] = strip_generic_subtitle(proposed["proposed_title"])

    # Sanitise string fields
    sanitised, diffs = sanitise_all_fields(proposed)

    # Build filename
    author_for_file = sanitised.get("proposed_author", "")
    title_for_file = sanitised.get("proposed_title", "")
    series_for_file = sanitised.get("proposed_series")
    series_idx = sanitised.get("proposed_series_index")
    series_total = sanitised.get("proposed_series_total")

    proposed_filename = build_filename(
        author=author_for_file,
        title=title_for_file,
        series=series_for_file,
        series_index=series_idx,
        series_total=series_total,
    )

    # Confidence and quality
    title_conf = winning.get("title_confidence", 0.5)
    author_conf = winning.get("author_confidence", 0.5)
    overall_conf = winning.get("confidence", 0.5)
    quality_ok = winning.get("quality_ok", True)
    quality_issues = winning.get("quality_issues", [])
    flags = winning.get("flags", [])

    update_data = {
        **sanitised,
        "proposed_filename": proposed_filename,
        "title_confidence": title_conf,
        "author_confidence": author_conf,
        "overall_confidence": overall_conf,
        "confidence_notes": winning.get("confidence_notes", ""),
        "quality_ok": 1 if quality_ok else 0,
        "quality_issues": json.dumps(quality_issues),
        "flags": json.dumps(flags),
        "sanitisation_diff": json.dumps(diffs) if diffs else None,
    }

    # --- Step 7: Routing ---
    route_data = {
        "title_confidence": title_conf,
        "author_confidence": author_conf,
        "overall_confidence": overall_conf,
        "quality_ok": quality_ok,
        "quality_issues": quality_issues,
        "flags": flags,
        "proposed_language": sanitised.get("proposed_language", "en"),
    }
    state = route_book(route_data)
    update_data["state"] = state

    await db.update_book(book_id, **update_data)

    # If auto-accepted, commit immediately
    if state == "auto_accepted":
        try:
            await commit_book(book_id)
        except Exception as e:
            logger.error(f"Auto-commit failed for book {book_id}: {e}")
            await db.update_book(book_id, state="auto_accepted", error_message=str(e)[:500])

    await _notify({
        "type": "book_update",
        "book_id": book_id,
        "state": state,
        "file_name": fname,
        "proposed_filename": proposed_filename,
    })


def _merge_llm_results(primary: dict, secondary: dict) -> dict:
    """Merge primary and secondary LLM results, preferring agreed values."""
    merged = dict(primary)  # Start with primary

    # Fields to compare
    compare_fields = ["title", "author", "series", "series_index", "genre", "subgenre", "language", "year"]
    disagreements = []

    for field in compare_fields:
        p_val = primary.get(field)
        s_val = secondary.get(field)
        if p_val and s_val and str(p_val).strip().lower() != str(s_val).strip().lower():
            disagreements.append(f"{field}: primary='{p_val}' vs secondary='{s_val}'")
            # Use the one with higher overall confidence
            if (secondary.get("confidence", 0) or 0) > (primary.get("confidence", 0) or 0):
                merged[field] = s_val

    # Average confidence scores
    for conf_field in ["title_confidence", "author_confidence", "confidence"]:
        p = primary.get(conf_field, 0) or 0
        s = secondary.get(conf_field, 0) or 0
        merged[conf_field] = (p + s) / 2

    # Merge quality assessments (conservative — flag if either flags it)
    merged["quality_ok"] = primary.get("quality_ok", True) and secondary.get("quality_ok", True)
    p_issues = primary.get("quality_issues", [])
    s_issues = secondary.get("quality_issues", [])
    merged["quality_issues"] = list(set(p_issues + s_issues))

    p_flags = primary.get("flags", [])
    s_flags = secondary.get("flags", [])
    merged["flags"] = list(set(p_flags + s_flags))

    if disagreements:
        notes = merged.get("confidence_notes", "")
        notes += f" LLM disagreements: {'; '.join(disagreements)}"
        merged["confidence_notes"] = notes.strip()

    return merged


async def commit_book(book_id: int) -> str:
    """Commit a single book: write metadata, move to OUTPUT_DIR.

    Returns the output path on success.
    Raises on failure.
    """
    book = await db.get_book(book_id)
    if not book:
        raise ValueError(f"Book {book_id} not found")

    source_path = book["file_path"]
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Source file not found: {source_path}")

    proposed_filename = book.get("proposed_filename")
    if not proposed_filename:
        raise ValueError(f"No proposed filename for book {book_id}")

    metadata = {
        "title": book.get("proposed_title", ""),
        "author": book.get("proposed_author", ""),
        "series": book.get("proposed_series"),
        "series_index": book.get("proposed_series_index"),
        "language": book.get("proposed_language", "en"),
        "publisher": book.get("proposed_publisher"),
        "date": str(book.get("proposed_year", "")) if book.get("proposed_year") else None,
        "description": book.get("proposed_description"),
        "subjects": book.get("proposed_subjects"),
        "genre": book.get("proposed_genre"),
        "subgenre": book.get("proposed_subgenre"),
    }

    output_dir = settings.output_dir
    loop = asyncio.get_event_loop()
    output_path = await loop.run_in_executor(
        None, write_metadata_and_move, source_path, output_dir, proposed_filename, metadata
    )

    # Remove original from input dir
    try:
        if os.path.exists(source_path):
            os.remove(source_path)
    except OSError as e:
        logger.warning(f"Could not remove original {source_path}: {e}")

    await db.update_book(book_id, state="committed", output_path=output_path)
    return output_path


async def commit_all_approved() -> list[dict]:
    """Commit all approved books. Returns list of results."""
    books = await db.get_books(states=["approved", "auto_accepted"])
    results = []
    for book in books:
        try:
            output_path = await commit_book(book["id"])
            results.append({"book_id": book["id"], "success": True, "output_path": output_path})
        except Exception as e:
            await db.update_book(book["id"], error_message=str(e)[:500])
            results.append({"book_id": book["id"], "success": False, "error": str(e)[:200]})
    return results


async def undo_book(book_id: int) -> None:
    """Undo an auto-accepted book: move back from OUTPUT_DIR to INPUT_DIR."""
    book = await db.get_book(book_id)
    if not book:
        raise ValueError(f"Book {book_id} not found")

    if book["state"] == "committed" and book.get("output_path"):
        output_path = book["output_path"]
        source_path = book["file_path"]
        if os.path.exists(output_path):
            import shutil
            # Move back to original location
            os.makedirs(os.path.dirname(source_path), exist_ok=True)
            shutil.move(output_path, source_path)

    await db.update_book(book_id, state="review", output_path=None)
