# AGENTS.md

## Cursor Cloud specific instructions

This repository is **data/content-only**. It holds consultant metadata, curated
text summaries, source CV files, and generated CV drafts intended for AI
consumption, not a software application.

Practical implications for agents working here:

- There is **no application to run**, **no build step**, **no test suite**, and
  **no lint configuration**. There are no services, ports, databases, or
  external integrations in this repo.
- There are **no dependencies to install**. The environment update script is a
  no-op; do not add package-install commands unless real code/dependencies are
  introduced.
- Most content is plain text/Markdown. Source CVs may be PDF or DOCX files under
  `cvs/`, and generated assignment-specific CVs may be DOCX files under
  `generated-cvs/`. For documentation and metadata changes, "testing" means
  reviewing the content for correctness.
- If application code is later added, update this file and the environment update
  script accordingly (e.g. add the relevant package manager install command and
  document how to run/lint/test the new services).
