# CV rendering scripts

Python utilities for the HTML/PDF CV generation pipeline.

## Setup

```bash
pip install -r requirements.txt
```

PDF rendering uses a Chromium-based browser (Edge or Chrome) in headless mode.

## Extract portraits and logo

```bash
python scripts/extract-photos.py
```

## Render HTML and PDF from JSON

```bash
python scripts/render-cv.py examples/karin-toft-english.json
```

Outputs under `generated-cvs/<assignment-id> - <assignment title>/`:

- `<consultant-slug>-<language>.json`
- `<consultant-slug>-<language>.html`
- `<consultant-slug>-<language>.pdf`

CV content must validate against `schemas/cv-content.schema.json`.

## Automation flow

The Slack `generate` automation should:

1. Tailor assignment-specific content and write JSON.
2. Run `python scripts/render-cv.py "generated-cvs/<assignment-folder>/<consultant-slug>-<language>.json" --skip-json`.
3. Commit JSON, HTML, and PDF under `generated-cvs/`.

See `automation-prompts/cv-generation.md`.
