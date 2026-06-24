# Cloud agent instructions

Read only by Cursor Cloud / Background Agents and Automations — not local IDE chat.

## Slack automations

Route each run to the matching prompt file. Treat that file as the source of
truth; read cross-references inside it as needed.

| Trigger | Follow |
|---------|--------|
| Slack reply starting with `generate` | `automation-prompts/cv-generation.md` |
| Slack reply starting with `fit` | `automation-prompts/fit-analysis.md` |
| Assignment listing job | `automation-prompts/assignment-listing.md` |

Shared context:

- `docs/slack-flow.md` — command syntax, listed vs pasted ad mode, privacy rules
- `consultants.yaml` — consultant lookup, CV variants, Cinode ids
- `AGENTS.md` — rendering pipeline, paths, and repo conventions

When `language` is `english` for CV generation, also follow
`automation-prompts/translation-sv-en.md`.

CV variant selection for both `fit` and `generate` is defined in
`automation-prompts/fit-analysis.md` (section "CV variant selection").
