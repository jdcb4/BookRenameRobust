"""Open Library API async client."""

import json
from typing import Any, Optional

import httpx

TIMEOUT = 10.0
BASE_URL = "https://openlibrary.org"


async def search_by_isbn(isbn: str) -> Optional[dict[str, Any]]:
    """Search Open Library by ISBN. Returns parsed data or None."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                f"{BASE_URL}/api/books",
                params={
                    "bibkeys": f"ISBN:{isbn}",
                    "format": "json",
                    "jscmd": "data",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            key = f"ISBN:{isbn}"
            if key in data:
                return _parse_response(data[key])
    except Exception:
        pass
    return None


async def search_by_title_author(title: str, author: str) -> Optional[dict[str, Any]]:
    """Search Open Library by title and author. Returns parsed data or None."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            params = {"q": f"{title} {author}", "limit": 1}
            resp = await client.get(f"{BASE_URL}/search.json", params=params)
            resp.raise_for_status()
            data = resp.json()
            docs = data.get("docs", [])
            if docs:
                return _parse_search_result(docs[0])
    except Exception:
        pass
    return None


async def lookup(isbn: Optional[str], title: Optional[str], author: Optional[str]) -> Optional[dict[str, Any]]:
    """Try ISBN lookup first, fall back to title+author search.

    Returns a dict with parsed fields and the raw response, or None.
    """
    result = None
    if isbn:
        result = await search_by_isbn(isbn)
    if result is None and title and author:
        result = await search_by_title_author(title, author)
    elif result is None and title:
        result = await search_by_title_author(title, "")
    return result


def _parse_response(data: dict) -> dict[str, Any]:
    """Parse an Open Library book data response."""
    authors = data.get("authors", [])
    author_name = authors[0].get("name", "") if authors else ""
    subjects = [s.get("name", "") for s in data.get("subjects", [])[:10]]
    publishers = data.get("publishers", [])
    publisher = publishers[0].get("name", "") if publishers else ""
    publish_date = data.get("publish_date", "")

    return {
        "title": data.get("title", ""),
        "author": author_name,
        "subjects": subjects,
        "publisher": publisher,
        "publish_date": publish_date,
        "language": "",
        "series": "",
        "raw": json.dumps(data),
    }


def _parse_search_result(doc: dict) -> dict[str, Any]:
    """Parse an Open Library search result document."""
    authors = doc.get("author_name", [])
    author_name = authors[0] if authors else ""
    subjects = doc.get("subject", [])[:10]
    publishers = doc.get("publisher", [])
    publisher = publishers[0] if publishers else ""
    year = doc.get("first_publish_year", "")
    languages = doc.get("language", [])
    language = languages[0] if languages else ""

    return {
        "title": doc.get("title", ""),
        "author": author_name,
        "subjects": subjects,
        "publisher": publisher,
        "publish_date": str(year) if year else "",
        "language": language,
        "series": "",
        "raw": json.dumps(doc),
    }
