# BookTidy

A Dockerised web application for managing and renaming EPUB eBook files. BookTidy scans a folder of EPUBs, enriches metadata using Open Library and LLM APIs (via OpenRouter), and produces cleanly renamed and tagged files.

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/jdcb4/BookRenameRobust.git
cd BookRenameRobust
```

Create a `.env` file:

```env
OPENROUTER_API_KEY=sk-or-v1-your-key-here
INPUT_DIR=/path/to/your/epub/folder
OUTPUT_DIR=/path/to/output/folder
```

### 2. Run with Docker Compose

```bash
docker compose up --build
```

Open **http://localhost:8080** in your browser.

### 3. First Run

1. Go to **Settings** and verify your API key is set
2. Click **Test LLM Connection** to verify both models respond
3. Go to **Dashboard** and click **Scan Input Folder**
4. Review books in the **Review Queue**, approve them, then click **Commit All Approved**

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | *(required)* | API key for OpenRouter LLM calls |
| `OPENROUTER_MODEL_PRIMARY` | `google/gemini-flash-1.5` | Primary LLM model for metadata enrichment |
| `OPENROUTER_MODEL_SECONDARY` | `anthropic/claude-sonnet-4-5` | Secondary model (used when primary confidence < 0.75) |
| `LLM_CONCURRENCY` | `5` | Number of parallel LLM calls (1–10) |
| `AUTO_ACCEPT_THRESHOLD` | `0.95` | Confidence threshold for auto-accept (0.85–1.00) |
| `INPUT_DIR` | `./input` | Source folder containing EPUB files |
| `OUTPUT_DIR` | `./output` | Destination folder for renamed files |
| `PORT` | `8080` | Web UI port |

All settings are also configurable via the **Settings** page in the web UI. Settings changed in the UI are persisted to `/data/settings.json` inside the container and survive restarts.

## Example docker-compose.yml

```yaml
version: "3.8"
services:
  booktidy:
    image: jdcb4/BookRenameRobust:latest
    ports:
      - "8080:8080"
    volumes:
      - /home/user/ebooks:/input
      - /home/user/ebooks-sorted:/output
      - ./data:/data
    environment:
      - OPENROUTER_API_KEY=sk-or-v1-your-key
      - LLM_CONCURRENCY=3
```

## How Books Are Routed (Four Queues)

After processing, each book is routed to one of four queues:

### Auto-Processed
Books that meet **all** of these criteria are committed automatically:
- `title_confidence` >= threshold (default 0.95)
- `author_confidence` >= threshold (default 0.95)
- Language is English
- No quality issues
- No flags

These appear in the **Auto-Processed** log panel. Each has an **Undo** button.

### Review Queue
Books that don't meet auto-accept criteria but have no quality issues. You review the suggested metadata, edit if needed, and approve or skip.

### Flagged Quality
Books where the LLM detected quality problems (OCR errors, garbled text, encoding issues, etc.). Quality issues are shown prominently. You can approve anyway, skip, or reject.

### Non-English
Books where the detected language is not English. Default action is "Skip" but you can override and approve.

## Duplicate Detection

Before processing, BookTidy computes MD5 hashes of all EPUB files and identifies duplicates. Duplicate groups are shown in the **Duplicates** tab. You can review and delete duplicates with a confirmation step (type DELETE to confirm).

## Processing Pipeline

For each EPUB file:

1. **Extract metadata** — Read OPF metadata (title, author, series, ISBN, etc.)
2. **Extract text sample** — First ~3,000 words of body text
3. **Open Library lookup** — Search by ISBN or title+author for canonical data
4. **Primary LLM enrichment** — Send all data to the primary model for structured metadata
5. **Secondary LLM check** — If primary confidence < 0.75, a second model independently processes the same data. Agreements are used; disagreements are flagged for user review
6. **ASCII sanitisation** — Convert all non-ASCII characters to safe equivalents
7. **Routing** — Route to the appropriate queue
8. **Filename generation** — Build the output filename from approved metadata

## Output Filename Format

- No series: `Author - Title.epub`
- With series (total known): `Author - Series - Book X of Y - Title.epub`
- With series (total unknown): `Author - Series - Book X - Title.epub`

Author is always in "Last, First" format.

## LLM Token Cost Estimate

Per book: approximately **~4,000 tokens input + ~500 tokens output**. With the default primary model (Gemini Flash 1.5), this costs fractions of a cent per book. The secondary model is only triggered when primary confidence is below 0.75 (typically ~10-20% of books).

## Dual-Model Behaviour

When the primary model returns an overall confidence below **0.75**, BookTidy automatically sends the same prompt to the secondary model for an independent assessment. Where both models agree, the agreed value is used. Where they disagree, both values are shown side-by-side in the Book Detail panel for you to choose.

Books that triggered the secondary model are marked with a **"2nd LLM"** badge.

## Parallelisation and Rate Limits

BookTidy processes books in parallel using an async worker pool. The default concurrency is **5 simultaneous LLM calls**, configurable via `LLM_CONCURRENCY` (1–10).

If you hit rate limits (HTTP 429):
- BookTidy automatically backs off with exponential delay (starting at 10s)
- Up to 3 retries before marking as error
- **Reduce `LLM_CONCURRENCY` to 1–2** if you consistently hit rate limits

Each book gets its own independent LLM call — parallelism has no effect on result quality.

## Running Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

## Project Structure

```
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── backend/
│   ├── main.py              # FastAPI app, routes, WebSocket
│   ├── scanner.py           # Scan, dedup, pipeline orchestration
│   ├── epub_parser.py       # EPUB metadata extraction and write-back
│   ├── text_extractor.py    # Body text sample extraction
│   ├── open_library.py      # Open Library API client
│   ├── llm_client.py        # OpenRouter client and prompt template
│   ├── sanitiser.py         # ASCII sanitisation and filename builder
│   ├── genre.py             # Genre taxonomy constants
│   ├── router.py            # Queue routing logic
│   ├── db.py                # SQLite database
│   └── config.py            # Configuration management
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── styles.css
└── tests/
    ├── test_sanitiser.py
    ├── test_filename_builder.py
    ├── test_subtitle_stripper.py
    ├── test_author_normaliser.py
    ├── test_genre_validator.py
    └── test_queue_router.py
```
