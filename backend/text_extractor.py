"""Extract plain text sample (~3000 words) from EPUB body content."""

import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib")
warnings.filterwarnings("ignore", category=FutureWarning, module="ebooklib")

from bs4 import BeautifulSoup
from ebooklib import epub

TARGET_WORDS = 3000


def extract_text_sample(epub_path: str) -> str:
    """Extract the first ~3000 words of readable body text from an EPUB.

    Walks the spine items, strips HTML, and concatenates text until the
    word target is reached.
    """
    book = epub.read_epub(epub_path, options={"ignore_ncx": True})
    words_collected: list[str] = []
    word_count = 0

    for item in book.get_items_of_type(9):  # ITEM_DOCUMENT = 9
        if word_count >= TARGET_WORDS:
            break

        try:
            content = item.get_content()
            if not content:
                continue
            soup = BeautifulSoup(content, "lxml")

            # Remove script and style elements
            for tag in soup(["script", "style", "head"]):
                tag.decompose()

            text = soup.get_text(separator=" ")
            # Normalise whitespace
            text = " ".join(text.split())

            if not text:
                continue

            words = text.split()
            remaining = TARGET_WORDS - word_count
            words_collected.extend(words[:remaining])
            word_count += min(len(words), remaining)
        except Exception:
            continue

    return " ".join(words_collected)
