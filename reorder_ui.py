#!/usr/bin/env python3
"""Local PDF page reorderer: type page numbers or drag thumbnails."""

from __future__ import annotations

import argparse
import shutil
import webbrowser
from pathlib import Path
from threading import Timer

import fitz
from flask import Flask, jsonify, request, send_from_directory
from pypdf import PdfReader, PdfWriter

from paths import PDFS, ROOT, ensure_pdfs_dir, resolve_pdf

PDF = PDFS / "Document_20260804_001_halves.pdf"
OUT = PDFS / "Document_20260804_001_reordered.pdf"
THUMBS = ROOT / "thumbs"
THUMB_SCALE = 1.1

app = Flask(__name__)

HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Reorder PDF pages</title>
<style>
  :root {
    --bg: #1c1b19;
    --panel: #2a2825;
    --ink: #f3efe6;
    --muted: #a39e93;
    --accent: #d97757;
    --warn: #c9a227;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
    background: radial-gradient(1200px 600px at 20% -10%, #3a342c, var(--bg));
    color: var(--ink);
    min-height: 100vh;
  }
  header {
    position: sticky; top: 0; z-index: 10;
    display: flex; gap: 1rem; align-items: center; justify-content: space-between;
    padding: 0.9rem 1.25rem;
    background: rgba(28,27,25,0.92);
    border-bottom: 1px solid #3d3933;
    backdrop-filter: blur(8px);
  }
  h1 { font-size: 1.15rem; margin: 0; font-weight: 600; letter-spacing: 0.02em; }
  .meta { color: var(--muted); font-size: 0.9rem; }
  .actions { display: flex; gap: 0.6rem; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
  button {
    font: inherit; border: 0; border-radius: 8px; padding: 0.55rem 0.95rem;
    cursor: pointer; background: var(--panel); color: var(--ink);
  }
  button.primary { background: var(--accent); color: #1c120e; font-weight: 700; }
  button:disabled { opacity: 0.5; cursor: wait; }
  #status { min-width: 14rem; color: var(--muted); font-size: 0.9rem; text-align: right; }
  #grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
    gap: 1.25rem;
    padding: 1.25rem;
  }
  .card {
    background: var(--panel);
    border: 1px solid #423e37;
    border-radius: 12px;
    padding: 0.7rem;
    cursor: grab;
    user-select: none;
    transition: transform .12s ease, border-color .12s ease, box-shadow .12s ease;
  }
  .card:hover { border-color: #6b6357; transform: translateY(-2px); }
  .card.dragging { opacity: 0.45; cursor: grabbing; }
  .card.over { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(217,119,87,.35); }
  .card.dupe { border-color: var(--warn); }
  .card img {
    width: 100%; height: auto; display: block;
    border-radius: 8px; background: #111; cursor: zoom-in;
  }
  .label {
    display: flex; align-items: center; justify-content: space-between;
    gap: 0.6rem; margin-top: 0.55rem; font-size: 1rem; color: var(--muted);
  }
  .label strong { color: var(--ink); font-weight: 600; }
  .page-input {
    width: 5.5rem;
    font: inherit;
    font-size: 1.15rem;
    font-weight: 700;
    text-align: center;
    padding: 0.35rem 0.4rem;
    border-radius: 8px;
    border: 1px solid #5a5348;
    background: #171513;
    color: var(--ink);
  }
  .page-input:focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 2px rgba(217,119,87,.35);
  }
  .page-input.filled { border-color: #6f9f7a; }
  #lightbox {
    display: none; position: fixed; inset: 0; z-index: 20;
    background: rgba(0,0,0,.82); align-items: center; justify-content: center;
    padding: 2rem;
  }
  #lightbox.open { display: flex; }
  #lightbox img {
    max-width: min(1100px, 94vw); max-height: 92vh;
    border-radius: 10px; box-shadow: 0 20px 60px rgba(0,0,0,.5);
  }
</style>
</head>
<body>
<header>
  <div>
    <h1>Reorder pages</h1>
    <div class="meta">Type the printed page # on each card · Enter sorts & jumps to next · blank = unnumbered (kept first)</div>
  </div>
  <div class="actions">
    <div id="status">Ready</div>
    <button type="button" id="sort">Sort now</button>
    <button type="button" id="reset">Reset</button>
    <button type="button" class="primary" id="save">Save PDF</button>
  </div>
</header>
<main id="grid"></main>
<div id="lightbox"><img alt="page preview"></div>
<script>
const PAGE_COUNT = __PAGE_COUNT__;
const STORAGE_KEY = 'pdf-reorder-v1';
let order = Array.from({length: PAGE_COUNT}, (_, i) => i);
const original = [...order];
/** printed page number keyed by source index; '' if unknown/unnumbered */
let pageNums = Object.fromEntries(order.map(i => [i, '']));
let focusSrc = null;

const grid = document.getElementById('grid');
const status = document.getElementById('status');
const lightbox = document.getElementById('lightbox');
const lightImg = lightbox.querySelector('img');

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    if (Array.isArray(data.order) && data.order.length === PAGE_COUNT) order = data.order.map(Number);
    if (data.pageNums && typeof data.pageNums === 'object') {
      for (const [k, v] of Object.entries(data.pageNums)) pageNums[k] = String(v ?? '');
    }
  } catch (_) {}
}

function saveState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ order, pageNums }));
}

function parseNum(v) {
  const s = String(v ?? '').trim();
  if (!s) return null;
  const n = Number(s);
  return Number.isInteger(n) && n > 0 ? n : null;
}

function countFilled() {
  return Object.values(pageNums).filter(v => parseNum(v) !== null).length;
}

function duplicateSet() {
  const seen = new Map();
  const dupes = new Set();
  for (const src of order) {
    const n = parseNum(pageNums[src]);
    if (n === null) continue;
    if (seen.has(n)) { dupes.add(n); }
    else seen.set(n, src);
  }
  return dupes;
}

function sortByPageNumbers() {
  const numbered = [];
  const blank = [];
  for (const src of order) {
    const n = parseNum(pageNums[src]);
    if (n === null) blank.push(src);
    else numbered.push([n, src]);
  }
  numbered.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  order = [...blank, ...numbered.map(x => x[1])];
  const dupes = duplicateSet();
  let msg = `Sorted · ${countFilled()}/${PAGE_COUNT} numbered`;
  if (dupes.size) msg += ` · duplicates: ${[...dupes].sort((a,b)=>a-b).join(', ')}`;
  status.textContent = msg;
  saveState();
}

function nextUnnumberedAfter(srcIndex) {
  const start = order.indexOf(srcIndex);
  for (let i = 1; i <= order.length; i++) {
    const src = order[(start + i) % order.length];
    if (parseNum(pageNums[src]) === null) return src;
  }
  return null;
}

function render() {
  const dupes = duplicateSet();
  grid.innerHTML = '';
  order.forEach((srcIndex, pos) => {
    const n = parseNum(pageNums[srcIndex]);
    const card = document.createElement('div');
    card.className = 'card' + (n !== null && dupes.has(n) ? ' dupe' : '');
    card.draggable = true;
    card.dataset.pos = String(pos);
    card.dataset.src = String(srcIndex);

    const img = document.createElement('img');
    img.src = `/thumbs/${String(srcIndex).padStart(3,'0')}.jpg`;
    img.alt = `page ${pos + 1}`;
    img.loading = 'lazy';
    img.addEventListener('click', () => {
      if (card.dataset.dragged === '1') return;
      lightImg.src = img.src;
      lightbox.classList.add('open');
    });

    const label = document.createElement('div');
    label.className = 'label';

    const left = document.createElement('strong');
    left.textContent = `#${pos + 1}`;

    const input = document.createElement('input');
    input.className = 'page-input' + (n !== null ? ' filled' : '');
    input.type = 'text';
    input.inputMode = 'numeric';
    input.placeholder = '#';
    input.value = pageNums[srcIndex] ?? '';
    input.title = 'Printed page number';
    input.addEventListener('click', e => e.stopPropagation());
    input.addEventListener('mousedown', e => e.stopPropagation());
    input.addEventListener('dragstart', e => e.preventDefault());
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        pageNums[srcIndex] = input.value.trim();
        const next = nextUnnumberedAfter(srcIndex);
        focusSrc = next;
        sortByPageNumbers();
        render();
      } else if (e.key === 'Escape') {
        input.blur();
      }
    });
    input.addEventListener('change', () => {
      pageNums[srcIndex] = input.value.trim();
      saveState();
      input.classList.toggle('filled', parseNum(pageNums[srcIndex]) !== null);
      status.textContent = `${countFilled()}/${PAGE_COUNT} numbered · press Enter or Sort`;
    });

    const right = document.createElement('span');
    right.textContent = `scan ${srcIndex + 1}`;

    label.append(left, input, right);
    card.append(img, label);

    card.addEventListener('dragstart', (e) => {
      if (e.target === input) { e.preventDefault(); return; }
      card.classList.add('dragging');
      card.dataset.dragged = '1';
      e.dataTransfer.setData('text/plain', String(pos));
      e.dataTransfer.effectAllowed = 'move';
    });
    card.addEventListener('dragend', () => {
      card.classList.remove('dragging');
      setTimeout(() => { card.dataset.dragged = '0'; }, 50);
      [...grid.children].forEach(c => c.classList.remove('over'));
    });
    card.addEventListener('dragover', (e) => {
      e.preventDefault();
      card.classList.add('over');
    });
    card.addEventListener('dragleave', () => card.classList.remove('over'));
    card.addEventListener('drop', (e) => {
      e.preventDefault();
      const from = Number(e.dataTransfer.getData('text/plain'));
      const to = Number(card.dataset.pos);
      if (Number.isNaN(from) || from === to) return;
      const [item] = order.splice(from, 1);
      order.splice(to, 0, item);
      status.textContent = `Moved · ${countFilled()}/${PAGE_COUNT} numbered`;
      saveState();
      render();
    });

    grid.appendChild(card);
  });

  if (focusSrc !== null) {
    const el = grid.querySelector(`.card[data-src="${focusSrc}"] .page-input`);
    if (el) { el.focus(); el.select(); }
    focusSrc = null;
  }
}

document.getElementById('sort').onclick = () => {
  // pull current input values first
  [...grid.querySelectorAll('.card')].forEach(card => {
    const src = Number(card.dataset.src);
    const input = card.querySelector('.page-input');
    if (input) pageNums[src] = input.value.trim();
  });
  sortByPageNumbers();
  render();
};

document.getElementById('reset').onclick = () => {
  if (!confirm('Clear all typed page numbers and reset order?')) return;
  order = [...original];
  pageNums = Object.fromEntries(order.map(i => [i, '']));
  localStorage.removeItem(STORAGE_KEY);
  status.textContent = 'Reset';
  render();
};

document.getElementById('save').onclick = async () => {
  [...grid.querySelectorAll('.card')].forEach(card => {
    const src = Number(card.dataset.src);
    const input = card.querySelector('.page-input');
    if (input) pageNums[src] = input.value.trim();
  });
  sortByPageNumbers();
  render();

  const btn = document.getElementById('save');
  btn.disabled = true;
  status.textContent = 'Saving…';
  try {
    const res = await fetch('/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ order }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Save failed');
    status.textContent = `Saved ${data.pages} pages → ${data.file}`;
  } catch (err) {
    status.textContent = String(err.message || err);
  } finally {
    btn.disabled = false;
  }
};

lightbox.onclick = () => lightbox.classList.remove('open');
loadState();
status.textContent = `${countFilled()}/${PAGE_COUNT} numbered`;
render();
</script>
</body>
</html>
"""


@app.get("/")
def index():
    reader = PdfReader(str(PDF))
    return HTML.replace("__PAGE_COUNT__", str(len(reader.pages)))


@app.get("/thumbs/<path:name>")
def thumbs(name: str):
    return send_from_directory(THUMBS, name)


@app.post("/save")
def save():
    data = request.get_json(force=True) or {}
    order = data.get("order")
    reader = PdfReader(str(PDF))
    n = len(reader.pages)
    if not isinstance(order, list) or sorted(order) != list(range(n)):
        return jsonify(error="Invalid page order"), 400
    writer = PdfWriter()
    for i in order:
        writer.add_page(reader.pages[int(i)])
    with open(OUT, "wb") as f:
        writer.write(f)
    return jsonify(ok=True, pages=n, file=OUT.name)


def default_out(src: Path) -> Path:
    stem = src.stem.removesuffix("_halves")
    return src.with_name(f"{stem}_reordered.pdf")


def render_thumbs(src: Path, outdir: Path, scale: float = THUMB_SCALE) -> int:
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)
    doc = fitz.open(src)
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        pix.save(str(outdir / f"{i:03d}.jpg"))
    n = len(doc)
    doc.close()
    return n


def main():
    global PDF, OUT

    ensure_pdfs_dir()
    parser = argparse.ArgumentParser(
        description="Drag-and-drop / type-to-reorder PDF pages in a browser. "
        f"PDFs are read from / written to {PDFS.name}/ by default."
    )
    parser.add_argument(
        "pdf",
        help=f"Input PDF (usually *_halves.pdf in {PDFS.name}/)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output PDF (default: pdfs/<stem>_reordered.pdf)",
    )
    parser.add_argument(
        "--skip-thumbs",
        action="store_true",
        help="Reuse existing thumbs/ (skip regenerate)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Local port (default: 8765)",
    )
    args = parser.parse_args()

    PDF = resolve_pdf(args.pdf)
    OUT = resolve_pdf(args.output, must_exist=False) if args.output else default_out(PDF)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    if not args.skip_thumbs:
        print(f"Rendering thumbs for {PDF.name}…")
        n = render_thumbs(PDF, THUMBS)
        print(f"Wrote {n} thumbnails → {THUMBS}/")
    elif not THUMBS.exists() or not any(THUMBS.glob("*.jpg")):
        raise SystemExit("No thumbs/ found — omit --skip-thumbs to generate them")

    port = args.port
    Timer(0.6, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    print(f"Open http://127.0.0.1:{port}")
    print(f"Source: {PDF}")
    print(f"Output: {OUT}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
