"""OpenRouter LLM client, prompt template, dual-model logic, retry/backoff."""

import asyncio
import json
import logging
import re
from typing import Any, Optional

import httpx

from backend.config import settings
from backend.genre import genre_taxonomy_for_prompt

logger = logging.getLogger("booktidy.llm")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ---------------------------------------------------------------------------
# PROMPT TEMPLATE — clearly labelled constant for easy editing
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """You are a book metadata expert. Analyse the following EPUB book information and return accurate, enriched metadata as a JSON object.

## INPUTS

### Folder Path (lower-confidence hint)
The folder path the file was found in is provided below. Downloaded eBooks are frequently organised in Author/Series/Title or Author/Title folder structures. Use the folder name(s) as an additional signal when inferring author name, series, and title — but treat them as lower-confidence hints compared to the EPUB metadata and text sample.

Folder path: {folder_path}
Original filename: {file_name}

### EPUB Metadata (from OPF)
Title: {orig_title}
Subtitle: {orig_subtitle}
Author/Creator: {orig_author}
Series: {orig_series}
Series Index: {orig_series_index}
Series Total: {orig_series_total}
Language: {orig_language}
Publisher: {orig_publisher}
Date: {orig_date}
ISBN: {orig_isbn}
Description: {orig_description}
Subjects: {orig_subjects}

### Extracted Text Sample (first ~1000 words)
{text_sample}

## AUTHOR NAME RULES
- Return the **primary author only** — strip co-authors, editors, translators, illustrators entirely
- Format is always **"Last, First"** — e.g. King, Stephen / Le Carre, John
- Use the **most commonly published form** of the author's name — e.g. Rowling, J.K. not Rowling, Joanne; Asimov, Isaac not Asimov, Isaak
- If the author publishes under a pen name, use the pen name — e.g. Twain, Mark not Clemens, Samuel
- Be consistent across all books by the same author — always resolve to the canonical published form

## SUBTITLE RULES
- Merge title and subtitle into a single title field in most cases
- Strip generic subtitle phrases unconditionally, including but not limited to: "A Novel", "A Thriller", "A Mystery", "An Epic Fantasy", "A Memoir", "A True Story", "The Novel", "A Story", "Book One", "Book 1", "Part One", "Part 1", "A Romance", "A Legal Thriller", "An Unauthorised Biography", "A Short Story Collection"
- Keep the subtitle only if it is genuinely meaningful and distinct from the main title — e.g. "The Lord of the Rings: The Fellowship of the Ring" → keep; "The Hunger Games: A Novel" → strip
- When merging, use a colon and space as separator: Main Title: Meaningful Subtitle

## QUALITY ASSESSMENT
Using the extracted text sample, assess the overall quality of this eBook file. Flag quality issues including but not limited to: excessive OCR errors or garbled text, machine-translated English, missing or truncated content, repeated or scrambled chapters, placeholder or watermark text, obvious encoding corruption, or text that does not match the expected title/author. Return a quality_issues array listing any problems found, and a quality_ok boolean (false if any significant issue is found).

## GENRE TAXONOMY
Assign exactly one genre and one subgenre from the following approved list ONLY. No values outside this taxonomy are permitted. If no subgenre fits precisely, use the closest available match and note it in confidence_notes.

{genre_taxonomy}

## OUTPUT FORMAT
Return ONLY a raw JSON object — no prose, no markdown fences, no preamble. The JSON must contain exactly these fields:

{{
  "title": "string (merged title, generic subtitles stripped)",
  "author": "Last, First",
  "series": "string or null",
  "series_index": 1,
  "series_total": 4,
  "year": 1998,
  "language": "en (ISO 639-1 two-letter code)",
  "publisher": "string or null",
  "description": "string or null",
  "genre": "top-level genre from approved taxonomy",
  "subgenre": "subgenre from approved taxonomy",
  "subjects": ["string"],
  "title_confidence": 0.97,
  "author_confidence": 0.96,
  "confidence": 0.91,
  "confidence_notes": "string explaining any uncertainty",
  "flags": ["string - any issues or warnings"],
  "quality_ok": true,
  "quality_issues": ["string - any quality problems found"]
}}

Important:
- title_confidence and author_confidence are separate per-field scores (0.0 to 1.0)
- confidence is the overall metadata confidence score (0.0 to 1.0)
- series_index and series_total should be integers or null
- If series info is not available, set series to null, series_index to null, series_total to null
- language must be a two-letter ISO 639-1 code (e.g. "en", "fr", "de")
"""

# ---------------------------------------------------------------------------
# Pinned models (always at top of selector) and empty fallback
# ---------------------------------------------------------------------------

FALLBACK_MODEL_LIST: list[dict] = []

PINNED_MODELS = [
    {"id": "google/gemini-3-flash-preview", "name": "Google - Gemini 3 Flash Preview (pinned default)", "provider": "Google"},
    {"id": "anthropic/claude-sonnet-4.6", "name": "Anthropic - Claude Sonnet 4.6 (pinned default)", "provider": "Anthropic"},
]


def _build_prompt(book_data: dict) -> str:
    """Build the LLM prompt from book data."""
    return PROMPT_TEMPLATE.format(
        folder_path=book_data.get("relative_path", ""),
        file_name=book_data.get("file_name", ""),
        orig_title=book_data.get("orig_title", "Unknown"),
        orig_subtitle=book_data.get("orig_subtitle", "None"),
        orig_author=book_data.get("orig_author", "Unknown"),
        orig_series=book_data.get("orig_series", "None"),
        orig_series_index=book_data.get("orig_series_index", "None"),
        orig_series_total=book_data.get("orig_series_total", "None"),
        orig_language=book_data.get("orig_language", "Unknown"),
        orig_publisher=book_data.get("orig_publisher", "Unknown"),
        orig_date=book_data.get("orig_date", "Unknown"),
        orig_isbn=book_data.get("orig_isbn", "None"),
        orig_description=book_data.get("orig_description", "None"),
        orig_subjects=book_data.get("orig_subjects", "None"),
        text_sample=book_data.get("text_sample", "No text sample available."),
        genre_taxonomy=genre_taxonomy_for_prompt(),
    )


def _extract_json(text: str) -> dict:
    """Extract a JSON object from LLM response text.

    Handles: raw JSON, markdown-fenced JSON, JSON embedded in prose.
    """
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip markdown fences
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    # Extract first {...} block (greedy inner match)
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract JSON from LLM response: {text[:200]}")


def _validate_llm_response(data: dict) -> dict:
    """Validate and normalise fields from LLM response."""
    result = {}

    result["title"] = str(data.get("title", "")).strip() or None
    result["author"] = str(data.get("author", "")).strip() or None
    result["series"] = data.get("series") if data.get("series") else None
    result["series_index"] = _safe_float(data.get("series_index"))
    result["series_total"] = _safe_float(data.get("series_total"))
    result["year"] = _safe_int(data.get("year"))
    result["language"] = str(data.get("language", "en")).strip()[:5].lower() or "en"
    result["publisher"] = data.get("publisher") if data.get("publisher") else None
    result["description"] = data.get("description") if data.get("description") else None
    result["genre"] = str(data.get("genre", "")).strip() or None
    result["subgenre"] = str(data.get("subgenre", "")).strip() or None
    result["subjects"] = data.get("subjects", [])
    if isinstance(result["subjects"], list):
        result["subjects"] = [str(s) for s in result["subjects"]]
    else:
        result["subjects"] = []

    result["title_confidence"] = _safe_float(data.get("title_confidence")) or 0.5
    result["author_confidence"] = _safe_float(data.get("author_confidence")) or 0.5
    result["confidence"] = _safe_float(data.get("confidence")) or 0.5
    result["confidence_notes"] = str(data.get("confidence_notes", "")).strip()
    result["flags"] = data.get("flags", [])
    if not isinstance(result["flags"], list):
        result["flags"] = []
    result["quality_ok"] = bool(data.get("quality_ok", True))
    result["quality_issues"] = data.get("quality_issues", [])
    if not isinstance(result["quality_issues"], list):
        result["quality_issues"] = []

    return result


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


async def _call_openrouter(model: str, prompt: str) -> dict:
    """Make a single call to the OpenRouter API.

    Handles retries and rate limiting (429 with exponential backoff).
    """
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://booktidy.local",
        "X-Title": "BookTidy",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 2000,
    }

    max_retries = 5
    backoff = 10.0

    # Rate-limit status codes: 429 (Too Many Requests) and 403 (Forbidden,
    # which OpenRouter also returns for rate-limiting / quota issues)
    RATE_LIMIT_CODES = {429, 403}

    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(OPENROUTER_URL, json=payload, headers=headers)

                if resp.status_code in RATE_LIMIT_CODES:
                    if attempt < max_retries:
                        wait = backoff + (attempt * 5)  # progressive backoff
                        logger.warning(
                            f"Rate limited ({resp.status_code}), backing off {wait:.0f}s "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(wait)
                        backoff *= 1.5
                        continue
                    resp.raise_for_status()

                resp.raise_for_status()
                data = resp.json()

                content = data["choices"][0]["message"]["content"]
                return _extract_json(content)

        except httpx.HTTPStatusError as e:
            if e.response.status_code in RATE_LIMIT_CODES and attempt < max_retries:
                wait = backoff + (attempt * 5)
                logger.warning(
                    f"Rate limited ({e.response.status_code}), backing off {wait:.0f}s "
                    f"(attempt {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(wait)
                backoff *= 1.5
                continue
            if attempt < max_retries:
                wait = 5 + (attempt * 3)
                logger.warning(f"LLM call failed (attempt {attempt + 1}), retrying in {wait}s: {e}")
                await asyncio.sleep(wait)
                continue
            raise
        except Exception as e:
            if attempt < max_retries:
                wait = 5 + (attempt * 3)
                logger.warning(f"LLM call failed (attempt {attempt + 1}), retrying in {wait}s: {e}")
                await asyncio.sleep(wait)
                continue
            raise

    raise RuntimeError(f"LLM call to {model} failed after all retries")


async def enrich_book(book_data: dict) -> dict:
    """Run the primary LLM enrichment, plus secondary if confidence < 0.75.

    Returns a dict with keys:
    - primary: validated primary LLM response
    - secondary: validated secondary LLM response or None
    - primary_model: model used for primary call
    - secondary_model: model used for secondary call or None
    - primary_raw: raw JSON string from primary
    - secondary_raw: raw JSON string from secondary or None
    """
    prompt = _build_prompt(book_data)

    # Primary call
    primary_model = settings.openrouter_model_primary
    primary_raw = await _call_openrouter(primary_model, prompt)
    primary = _validate_llm_response(primary_raw)

    result = {
        "primary": primary,
        "primary_model": primary_model,
        "primary_raw": json.dumps(primary_raw),
        "secondary": None,
        "secondary_model": None,
        "secondary_raw": None,
    }

    # Conditional secondary call — only for genuinely uncertain results
    # (~5-10% of books should trigger this with a 0.5 threshold)
    if primary["confidence"] is not None and primary["confidence"] < 0.5:
        secondary_model = settings.openrouter_model_secondary
        try:
            secondary_raw = await _call_openrouter(secondary_model, prompt)
            secondary = _validate_llm_response(secondary_raw)
            result["secondary"] = secondary
            result["secondary_model"] = secondary_model
            result["secondary_raw"] = json.dumps(secondary_raw)
        except Exception as e:
            logger.error(f"Secondary LLM call failed: {e}")

    return result


async def test_connection(model: str) -> dict:
    """Test LLM connection with a minimal prompt. Returns success/latency info."""
    import time
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://booktidy.local",
        "X-Title": "BookTidy",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": 'Respond with exactly: {"status": "ok"}'}],
        "temperature": 0,
        "max_tokens": 50,
    }
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(OPENROUTER_URL, json=payload, headers=headers)
            resp.raise_for_status()
            elapsed = time.monotonic() - start
            return {"success": True, "latency_ms": int(elapsed * 1000), "model": model}
    except Exception as e:
        elapsed = time.monotonic() - start
        return {"success": False, "error": str(e), "latency_ms": int(elapsed * 1000), "model": model}


def _format_pricing(pricing: dict) -> str:
    """Format pricing dict into a readable string like '$0.10/$0.30 per 1M tokens'."""
    if not pricing:
        return "free"
    prompt_price = pricing.get("prompt", "0")
    completion_price = pricing.get("completion", "0")
    try:
        p = float(prompt_price) * 1_000_000
        c = float(completion_price) * 1_000_000
        if p == 0 and c == 0:
            return "free"
        return f"${p:.2f}/${c:.2f} per 1M tok"
    except (ValueError, TypeError):
        return "N/A"


async def fetch_models() -> list[dict]:
    """Fetch ALL available models from OpenRouter API with pricing info."""
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get("https://openrouter.ai/api/v1/models", headers=headers)
            resp.raise_for_status()
            data = resp.json()
            models = []
            for m in data.get("data", []):
                model_id = m.get("id", "")
                provider = model_id.split("/")[0] if "/" in model_id else ""
                model_name_raw = m.get("name", model_id)
                pricing = _format_pricing(m.get("pricing", {}))
                display_name = f"{provider} - {model_name_raw} - {pricing}"
                models.append({
                    "id": model_id,
                    "name": display_name,
                    "provider": provider,
                    "context_length": m.get("context_length", 0),
                    "pricing": pricing,
                })
            # Sort by provider, then model name
            models.sort(key=lambda x: (x["provider"].lower(), x["name"].lower()))
            return models
    except Exception as e:
        logger.error(f"Failed to fetch models from OpenRouter: {e}")
        return FALLBACK_MODEL_LIST
