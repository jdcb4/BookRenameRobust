"""Queue routing logic — determines where each book goes after pipeline processing."""

import json as _json
import re

from backend.config import settings

# Flags that are informational and should NOT prevent auto-accept.
# These are common LLM flags that don't indicate a problem with identification.
BENIGN_FLAG_PATTERNS = [
    re.compile(r"co.?author", re.IGNORECASE),
    re.compile(r"secondary.*author", re.IGNORECASE),
    re.compile(r"multiple.*author", re.IGNORECASE),
    re.compile(r"author.*stripped", re.IGNORECASE),
    re.compile(r"author.*removed", re.IGNORECASE),
    re.compile(r"editor.*removed", re.IGNORECASE),
    re.compile(r"translator.*removed", re.IGNORECASE),
    re.compile(r"illustrator.*removed", re.IGNORECASE),
    re.compile(r"only.*primary.*author", re.IGNORECASE),
    re.compile(r"additional.*author", re.IGNORECASE),
]


def _is_benign_flag(flag: str) -> bool:
    """Check if a flag is informational only and shouldn't block auto-accept."""
    return any(p.search(flag) for p in BENIGN_FLAG_PATTERNS)


def route_book(book_data: dict) -> str:
    """Determine the queue for a processed book.

    Args:
        book_data: Dict containing at minimum:
            - title_confidence (float)
            - author_confidence (float)
            - overall_confidence (float)
            - quality_ok (bool)
            - quality_issues (list)
            - flags (list)
            - proposed_language (str)

    Returns:
        One of: 'auto_accepted', 'flagged_quality', 'non_english', 'review'
    """
    quality_ok = book_data.get("quality_ok", True)
    quality_issues = book_data.get("quality_issues", [])
    if isinstance(quality_issues, str):
        try:
            quality_issues = _json.loads(quality_issues)
        except (_json.JSONDecodeError, TypeError):
            quality_issues = [quality_issues] if quality_issues else []

    flags = book_data.get("flags", [])
    if isinstance(flags, str):
        try:
            flags = _json.loads(flags)
        except (_json.JSONDecodeError, TypeError):
            flags = [flags] if flags else []

    language = (book_data.get("proposed_language") or "en").strip().lower()
    title_conf = book_data.get("title_confidence", 0) or 0
    author_conf = book_data.get("author_confidence", 0) or 0
    threshold = settings.auto_accept_threshold

    # Flagged quality — takes priority
    if not quality_ok or (quality_issues and len(quality_issues) > 0):
        return "flagged_quality"

    # Non-English
    if language != "en":
        return "non_english"

    # Filter out benign flags — only meaningful flags should block auto-accept
    meaningful_flags = [f for f in flags if not _is_benign_flag(f)]

    # Auto-accept: both confidences above threshold, no meaningful flags, English, quality OK
    if (
        title_conf >= threshold
        and author_conf >= threshold
        and quality_ok
        and len(meaningful_flags) == 0
    ):
        return "auto_accepted"

    # Everything else goes to review
    return "review"
