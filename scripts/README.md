# CV rendering scripts

Python utilities for the HTML/PDF CV generation pipeline and assignment scanning.

## Setup

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

PDF rendering uses a Chromium-based browser (Edge or Chrome) in headless mode.
Verama raw scanning also uses Playwright when enabled.

## List assignments (Slack listing)

```bash
python scripts/fetch-assignments.py -o listing-candidates.json
python scripts/finalize-listing.py listing-candidates.json curated-listing.json -o listing-output.json
python scripts/finalize-listing.py --commit-memory listing-output.json --print-memory
```

Cloud automations must also sync via automation Memory — see
`automation-prompts/assignment-listing.md` steps 0 and 5.

Fetches from all registered platforms; the automation agent curates matches before
finalize formats three-tier Slack text. See `automation-prompts/assignment-listing.md`.

Heuristic-only testing:

```bash
python scripts/list-assignments.py --deterministic -o listing-output.json
```

## Raw multi-platform fetch (optional)

```bash
export VERAMA_EMAIL=...
export VERAMA_PASSWORD=...
python scripts/scan-assignments.py --debug-summary
```

See `docs/assignment-sources.md`.

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

1. Tailor assignment-specific content and write JSON (from a listed assignment ad
   URL or pasted parent message text).
2. Run `python scripts/render-cv.py "generated-cvs/<assignment-folder>/<consultant-slug>-<language>.json" --skip-json`.
3. Commit JSON, HTML, and PDF under `generated-cvs/`.

See `automation-prompts/cv-generation.md`.
