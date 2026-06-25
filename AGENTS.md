# AGENTS.md

## Cursor Cloud specific instructions

This repository holds consultant metadata, curated text summaries, source CV
files, generated CV drafts, HTML/PDF templates, and small Python scripts used by
Cursor Automations.

Practical implications for agents working here:

- **CV generation** uses a two-step pipeline: automations produce structured JSON;
  `scripts/render-cv.py` renders HTML and PDF from `templates/cv.html.j2`.
- Install dependencies before rendering or listing:
  `pip install -r requirements.txt` (or `python3 -m pip install -r requirements.txt`
  on Linux cloud agents). Cloud setup runs `.cursor/install.sh`.
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
  guidance in `automation-prompts/cv-generation.md` and
  `automation-prompts/assignment-listing.md`.
- **Assignment listing** runs `python scripts/fetch-assignments.py` to scan all
  platforms in `scripts/assignment_platforms.py`, then the automation agent
  curates matches and runs `scripts/finalize-listing.py` for three-tier Slack
  output. Heuristic hints live in `scripts/assignment_matching.py`; matching
  uses `consultants.yaml`. Dedupe memory: `assignment-listing-seen.json`.

## Cursor Automations

Automations for this repo should use **thin UI stubs** that tell the agent which
prompt files to read from the repo checkout (plain paths — the Automations `@`
picker is for tools, not files). Copy stubs from `automation-prompts/ui-stubs/`
into the Automations editor; see that folder's README for setup.

| Automation | Full prompt |
|------------|-------------|
| Assignment listing | `automation-prompts/assignment-listing.md` |
| Slack `fit …` | `automation-prompts/fit-analysis.md` |
| Slack `generate …` | `automation-prompts/cv-generation.md` |

Cloud-only routing lives in `.cursor/CLOUD.md`. Slack flow and command syntax
are documented in `docs/slack-flow.md`.
