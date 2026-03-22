"""EPUB metadata extraction and write-back using ebooklib."""

import os
import shutil
import uuid
import warnings
from pathlib import Path
from typing import Any, Optional

# Suppress ebooklib deprecation warnings
warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib")
warnings.filterwarnings("ignore", category=FutureWarning, module="ebooklib")

from ebooklib import epub


DC_NS = "http://purl.org/dc/elements/1.1/"
OPF_NS = "http://www.idpf.org/2007/opf"


def extract_metadata(epub_path: str) -> dict[str, Any]:
    """Extract all relevant metadata from an EPUB file.

    Returns a dict with keys matching the orig_* fields in the DB.
    """
    book = epub.read_epub(epub_path, options={"ignore_ncx": True})

    def _first(namespace: str, tag: str) -> Optional[str]:
        items = book.get_metadata(namespace, tag)
        if items:
            val = items[0][0] if isinstance(items[0], tuple) else items[0]
            return str(val).strip() if val else None
        return None

    def _all(namespace: str, tag: str) -> list[str]:
        items = book.get_metadata(namespace, tag)
        result = []
        for item in items:
            val = item[0] if isinstance(item, tuple) else item
            if val:
                result.append(str(val).strip())
        return result

    # Extract calibre-specific metadata from OPF meta tags
    series = None
    series_index = None
    series_total = None
    try:
        meta_items = book.get_metadata(OPF_NS, "meta")
        if meta_items is None:
            meta_items = []
    except Exception:
        meta_items = []

    for item in meta_items:
        if isinstance(item, tuple) and len(item) >= 2:
            attrs = item[1] if isinstance(item[1], dict) else {}
            name = attrs.get("name", "")
            content = attrs.get("content", "")
            if name == "calibre:series":
                series = content
            elif name == "calibre:series_index":
                try:
                    series_index = float(content)
                except (ValueError, TypeError):
                    pass
            elif name == "calibre:series_total":
                try:
                    series_total = float(content)
                except (ValueError, TypeError):
                    pass

    # Extract ISBN from identifiers
    isbn = None
    identifiers = book.get_metadata(DC_NS, "identifier")
    for ident in identifiers:
        val = ident[0] if isinstance(ident, tuple) else ident
        if val:
            val_str = str(val).strip()
            # Check for ISBN format
            clean = val_str.replace("-", "").replace(" ", "")
            if len(clean) == 13 and clean.isdigit():
                isbn = clean
                break
            elif len(clean) == 10 and (clean[:-1].isdigit() and (clean[-1].isdigit() or clean[-1].upper() == "X")):
                isbn = clean
                break
            # Check for urn:isbn: prefix
            if val_str.lower().startswith("urn:isbn:"):
                isbn = val_str[9:].strip()
                break
            # Check attrs for isbn scheme
            if isinstance(ident, tuple) and len(ident) >= 2:
                attrs = ident[1] if isinstance(ident[1], dict) else {}
                scheme = attrs.get("opf:scheme", "").lower()
                if scheme == "isbn":
                    isbn = val_str
                    break

    # Extract subtitle — sometimes stored as second dc:title or in meta
    titles = _all(DC_NS, "title")
    title = titles[0] if titles else None
    subtitle = titles[1] if len(titles) > 1 else None

    # Check for subtitle in meta tags if not found
    if not subtitle:
        for item in meta_items:
            if isinstance(item, tuple) and len(item) >= 2:
                attrs = item[1] if isinstance(item[1], dict) else {}
                name = attrs.get("name", "")
                content = attrs.get("content", "")
                if name in ("calibre:title_sort", "subtitle"):
                    if name == "subtitle":
                        subtitle = content

    subjects = _all(DC_NS, "subject")

    return {
        "orig_title": title,
        "orig_subtitle": subtitle,
        "orig_author": _first(DC_NS, "creator"),
        "orig_series": series,
        "orig_series_index": series_index,
        "orig_series_total": series_total,
        "orig_language": _first(DC_NS, "language"),
        "orig_publisher": _first(DC_NS, "publisher"),
        "orig_date": _first(DC_NS, "date"),
        "orig_isbn": isbn,
        "orig_description": _first(DC_NS, "description"),
        "orig_subjects": ",".join(subjects) if subjects else None,
    }


def write_metadata_and_move(
    source_path: str,
    output_dir: str,
    new_filename: str,
    metadata: dict[str, Any],
) -> str:
    """Write metadata to EPUB, validate, and move to output_dir.

    Args:
        source_path: Path to the original EPUB in INPUT_DIR.
        output_dir: OUTPUT_DIR base path.
        new_filename: The new filename (e.g. 'Author - Title.epub').
        metadata: Dict with keys: title, author, series, series_index,
                  language, publisher, date, description, subjects, genre, subgenre.

    Returns:
        The final output path on success.

    Raises:
        RuntimeError: If validation fails after write.
        Exception: On any other failure.
    """
    # Read the EPUB
    book = epub.read_epub(source_path, options={"ignore_ncx": True})

    # --- Clear and set dc:title ---
    if DC_NS in book.metadata:
        book.metadata[DC_NS].pop("title", None)
    title = metadata.get("title", "")
    if title:
        book.add_metadata(DC_NS, "title", title)

    # --- Clear and set dc:creator ---
    if DC_NS in book.metadata:
        book.metadata[DC_NS].pop("creator", None)
    author = metadata.get("author", "")
    if author:
        book.add_metadata(DC_NS, "creator", author)

    # --- Set language ---
    if DC_NS in book.metadata:
        book.metadata[DC_NS].pop("language", None)
    lang = metadata.get("language", "en")
    book.add_metadata(DC_NS, "language", lang)

    # --- Set publisher ---
    if metadata.get("publisher"):
        if DC_NS in book.metadata:
            book.metadata[DC_NS].pop("publisher", None)
        book.add_metadata(DC_NS, "publisher", metadata["publisher"])

    # --- Set date ---
    if metadata.get("date"):
        if DC_NS in book.metadata:
            book.metadata[DC_NS].pop("date", None)
        book.add_metadata(DC_NS, "date", str(metadata["date"]))

    # --- Set description ---
    if metadata.get("description"):
        if DC_NS in book.metadata:
            book.metadata[DC_NS].pop("description", None)
        book.add_metadata(DC_NS, "description", metadata["description"])

    # --- Set subjects (genre, subgenre, and original subjects) ---
    if DC_NS in book.metadata:
        book.metadata[DC_NS].pop("subject", None)
    subjects = []
    if metadata.get("genre"):
        subjects.append(metadata["genre"])
    if metadata.get("subgenre"):
        subjects.append(metadata["subgenre"])
    if metadata.get("subjects"):
        if isinstance(metadata["subjects"], str):
            subjects.extend(s.strip() for s in metadata["subjects"].split(",") if s.strip())
        elif isinstance(metadata["subjects"], list):
            subjects.extend(metadata["subjects"])
    for subj in subjects:
        book.add_metadata(DC_NS, "subject", subj)

    # --- Set calibre series metadata ---
    # Remove existing calibre meta entries
    if OPF_NS in book.metadata and "meta" in book.metadata[OPF_NS]:
        book.metadata[OPF_NS]["meta"] = [
            m for m in book.metadata[OPF_NS]["meta"]
            if not (isinstance(m, tuple) and len(m) >= 2 and
                    isinstance(m[1], dict) and
                    m[1].get("name", "") in (
                        "calibre:series", "calibre:series_index", "calibre:series_total"
                    ))
        ]

    if metadata.get("series"):
        book.add_metadata(OPF_NS, "meta", "", {
            "name": "calibre:series",
            "content": metadata["series"],
        })
        if metadata.get("series_index") is not None:
            book.add_metadata(OPF_NS, "meta", "", {
                "name": "calibre:series_index",
                "content": str(metadata["series_index"]),
            })

    # --- Write to temp file ---
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    temp_filename = f".tmp_{uuid.uuid4().hex}.epub"
    temp_path = os.path.join(output_dir, temp_filename)

    try:
        epub.write_epub(temp_path, book)
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise RuntimeError(f"Failed to write EPUB: {e}") from e

    # --- Validate the output ---
    try:
        validation_book = epub.read_epub(temp_path, options={"ignore_ncx": True})
        # Verify key fields round-trip
        v_titles = validation_book.get_metadata(DC_NS, "title")
        v_title = v_titles[0][0] if v_titles else ""
        if title and str(v_title).strip() != title.strip():
            raise RuntimeError(
                f"Title validation failed: wrote '{title}', read back '{v_title}'"
            )
        # Verify items can be iterated
        list(validation_book.get_items())

        # Check file size sanity
        orig_size = os.path.getsize(source_path)
        new_size = os.path.getsize(temp_path)
        if orig_size > 0 and new_size == 0:
            raise RuntimeError("Output file is empty")
    except RuntimeError:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise RuntimeError(f"EPUB validation failed: {e}") from e

    # --- Move to final destination ---
    final_path = os.path.join(output_dir, new_filename)
    # Handle collision
    if os.path.exists(final_path):
        base, ext = os.path.splitext(new_filename)
        counter = 2
        while os.path.exists(os.path.join(output_dir, f"{base}_{counter}{ext}")):
            counter += 1
        final_path = os.path.join(output_dir, f"{base}_{counter}{ext}")

    shutil.move(temp_path, final_path)
    return final_path
