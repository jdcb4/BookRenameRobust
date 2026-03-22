"""ASCII sanitisation, subtitle stripping, author normalisation, and filename builder."""

import re
import unicodedata
from typing import Optional

# ---------------------------------------------------------------------------
# Substitution map: Unicode → ASCII replacements
# ---------------------------------------------------------------------------

SUBSTITUTION_MAP: dict[str, str] = {
    # Smart quotes
    "\u2018": "'",   # '
    "\u2019": "'",   # '
    "\u201C": '"',   # "
    "\u201D": '"',   # "
    "\u201A": "'",   # ‚
    "\u201E": '"',   # „
    # Dashes
    "\u2013": "-",   # en dash
    "\u2014": "-",   # em dash
    # Ellipsis
    "\u2026": "...",
    # Common accented characters
    "\u00E9": "e", "\u00E8": "e", "\u00EA": "e", "\u00EB": "e",
    "\u00C9": "E", "\u00C8": "E", "\u00CA": "E", "\u00CB": "E",
    "\u00E0": "a", "\u00E1": "a", "\u00E2": "a", "\u00E3": "a", "\u00E4": "a", "\u00E5": "a",
    "\u00C0": "A", "\u00C1": "A", "\u00C2": "A", "\u00C3": "A", "\u00C4": "A", "\u00C5": "A",
    "\u00EC": "i", "\u00ED": "i", "\u00EE": "i", "\u00EF": "i",
    "\u00CC": "I", "\u00CD": "I", "\u00CE": "I", "\u00CF": "I",
    "\u00F2": "o", "\u00F3": "o", "\u00F4": "o", "\u00F5": "o", "\u00F6": "o", "\u00F8": "o",
    "\u00D2": "O", "\u00D3": "O", "\u00D4": "O", "\u00D5": "O", "\u00D6": "O", "\u00D8": "O",
    "\u00F9": "u", "\u00FA": "u", "\u00FB": "u", "\u00FC": "u",
    "\u00D9": "U", "\u00DA": "U", "\u00DB": "U", "\u00DC": "U",
    "\u00F1": "n", "\u00D1": "N",
    "\u00E7": "c", "\u00C7": "C",
    "\u00FF": "y", "\u00FD": "y", "\u00DD": "Y",
    "\u00DF": "ss",  # ß
    "\u00F0": "d",   # ð
    "\u00FE": "th",  # þ
    "\u00DE": "Th",  # Þ
    # Ligatures
    "\u00E6": "ae", "\u00C6": "AE",
    "\u0153": "oe", "\u0152": "OE",
    "\uFB01": "fi", "\uFB02": "fl",
}

# ---------------------------------------------------------------------------
# Generic subtitle phrases to strip
# ---------------------------------------------------------------------------

GENERIC_SUBTITLE_PHRASES = [
    "A Novel", "A Thriller", "A Mystery", "An Epic Fantasy", "A Memoir",
    "A True Story", "The Novel", "A Story", "Book One", "Book 1",
    "Part One", "Part 1", "A Romance", "A Legal Thriller",
    "An Unauthorised Biography", "A Short Story Collection",
    "An Unauthorized Biography", "A Novella", "A Short Novel",
    "A Tale", "A Fable", "A Novel of Suspense",
]

# Pre-compile patterns for subtitle stripping (case-insensitive)
_SUBTITLE_PATTERNS = [
    re.compile(r"[:\-]\s*" + re.escape(phrase) + r"\s*$", re.IGNORECASE)
    for phrase in GENERIC_SUBTITLE_PHRASES
]


def sanitise_string(text: str) -> tuple[str, list[tuple[str, str, str]]]:
    """Apply ASCII sanitisation to a string.

    Returns (sanitised_string, list_of_substitutions).
    Each substitution is (original_char, replacement, description).
    """
    if not text:
        return "", []

    substitutions = []
    result = []

    for char in text:
        if char in SUBSTITUTION_MAP:
            replacement = SUBSTITUTION_MAP[char]
            substitutions.append((char, replacement, f"U+{ord(char):04X}"))
            result.append(replacement)
        elif ord(char) > 127:
            # Try unicode decomposition for remaining non-ASCII
            decomposed = unicodedata.normalize("NFD", char)
            ascii_part = "".join(c for c in decomposed if ord(c) < 128)
            if ascii_part:
                substitutions.append((char, ascii_part, f"U+{ord(char):04X} decomposed"))
                result.append(ascii_part)
            else:
                substitutions.append((char, "", f"U+{ord(char):04X} stripped"))
                # stripped entirely
        else:
            result.append(char)

    sanitised = "".join(result)
    # Normalise whitespace
    sanitised = re.sub(r"\s+", " ", sanitised).strip()
    return sanitised, substitutions


def strip_generic_subtitle(title: str) -> str:
    """Remove generic subtitle phrases from the end of a title."""
    result = title
    for pattern in _SUBTITLE_PATTERNS:
        result = pattern.sub("", result)
    # Also strip standalone trailing colon or dash left behind
    result = re.sub(r"\s*[:\-]\s*$", "", result).strip()
    return result


def normalise_author(author_str: str) -> str:
    """Normalise an author string to 'Last, First' format.

    Handles:
    - 'First Last' → 'Last, First'
    - 'Last, First' → 'Last, First' (already correct)
    - Multiple authors → keep only the first
    - Prefixes like 'by' stripped
    """
    if not author_str:
        return ""

    # Strip 'by ' prefix
    author = re.sub(r"^(?:by|written by)\s+", "", author_str, flags=re.IGNORECASE).strip()

    # Take only the first author if multiple (separated by ;, &, and, with, et al)
    author = re.split(r"\s*(?:;|&|\band\b|\bwith\b|\bet al\.?)", author, flags=re.IGNORECASE)[0].strip()

    # Remove roles in parentheses: "Name (Editor)" → "Name"
    author = re.sub(r"\s*\(.*?\)\s*", " ", author).strip()

    # If already in "Last, First" format, return as-is
    if "," in author:
        parts = [p.strip() for p in author.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            return f"{parts[0]}, {parts[1]}"

    # Convert "First Middle Last" → "Last, First Middle"
    parts = author.split()
    if len(parts) == 0:
        return ""
    if len(parts) == 1:
        return parts[0]

    last = parts[-1]
    first = " ".join(parts[:-1])
    return f"{last}, {first}"


def build_filename(
    author: str,
    title: str,
    series: Optional[str] = None,
    series_index: Optional[float] = None,
    series_total: Optional[float] = None,
) -> str:
    """Build the output filename from metadata components.

    Formats:
    - No series:              Author - Title.epub
    - Series, total known:    Author - Series - Book X of Y - Title.epub
    - Series, total unknown:  Author - Series - Book X - Title.epub
    """
    # Sanitise all components
    author_s, _ = sanitise_string(author)
    title_s, _ = sanitise_string(title)

    # Clean up whitespace and separators
    author_s = author_s.strip()
    title_s = title_s.strip()

    if not author_s:
        author_s = "Unknown Author"
    if not title_s:
        title_s = "Unknown Title"

    if series and series_index is not None:
        series_s, _ = sanitise_string(series)
        series_s = series_s.strip()
        idx = int(series_index) if series_index == int(series_index) else series_index

        if series_total is not None and series_total > 0:
            total = int(series_total) if series_total == int(series_total) else series_total
            filename = f"{author_s} - {series_s} - Book {idx} of {total} - {title_s}.epub"
        else:
            filename = f"{author_s} - {series_s} - Book {idx} - {title_s}.epub"
    else:
        filename = f"{author_s} - {title_s}.epub"

    # Remove any double spaces
    filename = re.sub(r"  +", " ", filename)
    return filename


def sanitise_all_fields(data: dict) -> tuple[dict, dict]:
    """Sanitise all string fields in a metadata dict.

    Returns (sanitised_data, diff_dict) where diff_dict maps field names
    to their substitution lists.
    """
    sanitised = {}
    diffs = {}

    string_fields = [
        "proposed_title", "proposed_author", "proposed_series",
        "proposed_publisher", "proposed_description",
    ]

    for key, value in data.items():
        if key in string_fields and isinstance(value, str):
            clean, subs = sanitise_string(value)
            sanitised[key] = clean
            if subs:
                diffs[key] = [(orig, repl, desc) for orig, repl, desc in subs]
        else:
            sanitised[key] = value

    return sanitised, diffs
