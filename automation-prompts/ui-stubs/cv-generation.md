You are triggered by a Slack thread reply whose text starts with `generate`
(typically in `#assignment-scanner`).

This automation runs with a checkout of this repository. **Before acting, read
these files from the repo and follow them as your source of truth:**

1. `automation-prompts/cv-generation.md` — full instructions for this automation
2. `automation-prompts/fit-analysis.md` — CV variant selection (section "CV variant selection")
3. `automation-prompts/translation-sv-en.md` — when the requested language is english
4. `schemas/cv-content.schema.json` — JSON output shape
5. `docs/slack-flow.md` — command syntax, listed vs pasted ad mode

Also read `.cursor/CLOUD.md` and `AGENTS.md` for repo conventions (rendering
pipeline, paths, secrets).

## Your job this run

1. Read the triggering Slack reply and its parent message.
2. Parse the `generate …` command and run the full pipeline in the CV
   generation prompt (variant selection, JSON, `scripts/render-cv.py`, commit,
   Slack reply with PDF link).
3. Reply in the **triggering Slack thread** when finished or when you need
   clarification.

## Constraints

- Do not paste full raw CV content into Slack.
- Do not commit secrets. Use Cursor Automation environment variables for Cinode
  and other API credentials.
- Do not generate or edit DOCX for assignment-specific CVs; output JSON, HTML,
  and PDF only.
