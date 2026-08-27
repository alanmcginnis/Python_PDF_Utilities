# PDF Page Sorter

Local tools for splitting 2-up scanned PDFs and reordering pages in a browser.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if you don't have it, then from this directory:

```bash
uv sync
```

That creates `.venv` and installs Python dependencies.

## Run the UI

**`reorder_ui.py` is the main file.** Put your PDF in `pdfs/`, then:

```bash
uv run python reorder_ui.py your_scan.pdf
```

It opens [http://127.0.0.1:8765](http://127.0.0.1:8765). Type printed page numbers or drag thumbnails, then save. Output is written next to the input as `*_reordered.pdf`.

```bash
# optional flags
uv run python reorder_ui.py your_scan.pdf -o custom_name.pdf
uv run python reorder_ui.py your_scan.pdf --port 9000
uv run python reorder_ui.py your_scan.pdf --skip-thumbs   # reuse existing thumbs/
```

## Typical workflow

1. Drop the source PDF into `pdfs/`
2. If each sheet is two pages side by side:

   ```bash
   uv run python split_halves.py your_scan.pdf
   ```

   That writes `pdfs/your_scan_halves.pdf` (left half, then right half, per sheet).
3. Reorder in the UI:

   ```bash
   uv run python reorder_ui.py your_scan_halves.pdf
   ```

Bare filenames are looked up in `pdfs/` first, then the project root.

## Other scripts

| Script | What it does |
|---|---|
| `split_halves.py` | Split each page into left then right halves |
| `reorder_by_page_number.py` | OCR footer `~N~` numbers and rewrite in numeric order |
| `cleanup.py` | Remove `thumbs/`, logs, and intermediate `*_halves` / `*_reordered` PDFs |

OCR reorder needs Tesseract on your PATH:

```bash
brew install tesseract
uv run python reorder_by_page_number.py
```

That script currently hardcodes its input/output filenames near the top of the file.

Cleanup examples:

```bash
uv run python cleanup.py --thumbs
uv run python cleanup.py --all --dry-run
uv run python cleanup.py --stem your_scan
```
