"""Queue routing logic — determines where each book goes after pipeline processing."""

from backend.config import settings


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
            import json
            quality_issues = json.loads(quality_issues)
        except (json.JSONDecodeError, TypeError):
            quality_issues = [quality_issues] if quality_issues else []

    flags = book_data.get("flags", [])
    if isinstance(flags, str):
        try:
            import json
            flags = json.loads(flags)
        except (json.JSONDecodeError, TypeError):
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

    # Auto-accept: both confidences above threshold, no flags, English, quality OK
    if (
        title_conf >= threshold
        and author_conf >= threshold
        and quality_ok
        and (not flags or len(flags) == 0)
    ):
        return "auto_accepted"

    # Everything else goes to review
    return "review"
