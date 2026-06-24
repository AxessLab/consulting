# AGENTS.md

## Cursor Cloud specific instructions

This repository holds consultant metadata, curated text summaries, source CV
files, generated CV drafts, HTML/PDF templates, and small Python scripts used by
Cursor Automations.

Practical implications for agents working here:

- **CV generation** uses a two-step pipeline: automations produce structured JSON;
  `scripts/render-cv.py` renders HTML and PDF from `templates/cv.html.j2`.
- Install dependencies before rendering:
  `pip install -r requirements.txt`
- PDF rendering needs a Chromium-based browser (Edge, Chrome, or Chromium).
- Do **not** generate or edit DOCX files for assignment-specific CVs. Source
  DOCX files under `cvs/` are factual content sources only.
- Portrait images live under `photos/`. Refresh with `python scripts/extract-photos.py`.
- Generated assignment CVs are stored under
  `generated-cvs/<assignment-id> - <assignment title>/` as JSON, HTML, and PDF.
- There is no application server, build step, or test suite. Validate changes by
  running `python scripts/render-cv.py` on example or generated JSON and
  reviewing the HTML/PDF output.
- If scripts or dependencies change, update this file and automation prompt
  guidance in `automation-prompts/cv-generation.md`.
