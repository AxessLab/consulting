# Data governance

This repository supports consultant fit analysis for IT assignments. Keep the
data factual, minimal, reviewed, and appropriate for AI-assisted automation.

## Privacy rules

- Do not store API tokens, Slack credentials, private keys, passwords, or other
  secrets in this repo.
- Do not store unnecessary personal data.
- Do not store sensitive internal details unless they are required for the
  automation and approved for this use.
- Use placeholders and templates when documenting examples.
- Keep curated summaries factual and reviewed.
- Update summaries when consultant profiles, CVs, skills, availability, or
  constraints change.

## Curated CV summaries

Each consultant may have multiple CV variants. Each variant has its own curated
summary file and optional raw CV files under `cvs/`. Create a new variant when a
consultant needs a materially different positioning (for example fullstack versus
backend-only), not for minor wording tweaks.

Curated summaries should help the automation make better assignment-specific
recommendations. They should contain concise evidence and notes that are safe to
use in application planning.

Good summary content:

- verified roles and responsibilities
- relevant assignment evidence
- skills and tools with supporting context
- domains and industries
- language capability when relevant
- known availability or constraints, if approved for this use
- CV improvement notes

Avoid:

- private opinions
- unsupported claims
- health, family, or other sensitive personal data
- raw secrets or credentials
- details that should not appear in Slack

## Source, template, and generated CVs

Source CV files may be stored under `cvs/` when they have an operational purpose
for assignment-specific CV generation.

Shared CV template files may be stored under `templates/`. The primary template
is `cv.html.j2` for HTML/PDF rendering. Templates should avoid unnecessary
personal data beyond what generated CVs require.

Generated CV files may be stored under `generated-cvs/` when created for a
specific assignment. They should:

- be JSON, HTML, and PDF files produced from curated content, Cinode profile
  data, source CV facts, and the assignment ad via `scripts/render-cv.py`
- use portrait images from `photos/` where appropriate
- contain only factual, reviewed, and assignment-relevant personal data
- avoid internal notes, uncertainty, prompt reasoning, API responses, or secrets
- be reviewed by a human before being sent to a client
- be replaced by a newer generated file rather than edited manually in place when
  the automation is rerun

Generated CV Slack replies should link to the PDF (and optionally HTML) in the
repository for authorized reviewers. Do not publish generated CVs through
unauthenticated public file shares unless that has been explicitly approved for
the consultant and assignment.

## Slack output rules

Slack assignment lists should stay compact and avoid sensitive consultant
details. Detailed fit replies should include only information needed to explain
which CV variant was used, fit, gaps, CV updates, suggested application angle,
and confidence. CV generation replies should include the generated file link,
selected language, selected CV variant, source CV, template source, short
positioning summary, and a review reminder. Link to the generated PDF in Slack.
Do not paste full raw CV content into Slack.

## Ambiguous data

When the automation cannot confidently match a consultant name or assignment id,
it should ask for clarification instead of guessing.

When evidence is weak, stale, or missing, the fit reply should say so clearly.
