# Swedish–English translation glossary

Use this glossary whenever automations translate consultant CV content, summaries,
or Slack replies from Swedish to English (or write English output from Swedish
source material).

Axesslab consultants work in **digital accessibility** (WCAG, audits, inclusive
design, assistive technology). A common AI mistake is translating
**tillgänglighet** as **availability**. That is usually wrong.

## Default rule

When **tillgänglighet** or **tillgänglig** appears in roles, skills, project
descriptions, certifications, audits, standards, or product/system context,
translate to **accessibility** / **accessible** — not **availability** /
**available**.

Only use **availability** / **available** when the Swedish text clearly refers to
**when a consultant can start**, **schedule**, **capacity**, or **whether a
person is free for an assignment** — not their professional domain.

## Term mapping

| Swedish | English (default) | Use availability/available only when |
|---------|-------------------|--------------------------------------|
| tillgänglighet | accessibility | Start date, schedule, capacity, “ledig”, assignment timing |
| tillgänglig | accessible | Consultant is free to start; calendar/schedule context |
| tillgänglighets… (compound) | accessibility… | Same as tillgänglighet |
| tillgänglighetsspecialist | accessibility specialist | — |
| tillgänglighetsexpert | accessibility expert | — |
| tillgänglighetsaudit / granskning | accessibility audit / review | — |
| tillgänglig kod | accessible code | — |
| tillgängliga dokument | accessible documents | — |
| tillgänglighetsanpassning | accessibility adaptation / remediation | — |
| tillgänglighetskrav | accessibility requirements | — |
| arbeta med tillgänglighet | work on accessibility | — |
| tillgänglig från [datum] | available from [date] | ✓ scheduling sense |
| tillgänglighet att börja | availability to start | ✓ scheduling sense |
| omgående tillgänglig | immediately available | ✓ scheduling sense |

## Quick disambiguation

**Accessibility (correct for most CV text):**

- WCAG, EN 301 549, CPWA, CPACC, WAS, audits, screen readers, keyboard navigation
- Roles like tillgänglighetsspecialist, tillgänglighetsarbete
- Project work on websites, apps, documents, forms, design systems
- “förbättra tillgängligheten”, “tillgänglighetsfokus”, “tillgänglighetsnivå”

**Availability (rare, scheduling only):**

- “Konsulten är tillgänglig från 1 september”
- “Tillgänglighet: heltid from Q2”
- Assignment ads asking when someone can start
- `Availability or constraints` sections in curated summaries

If unsure, prefer **accessibility** in CV and skills content. Use
**availability** only when the source explicitly discusses timing or capacity.

## English output checks

Before committing English CV JSON or posting English Slack text, scan for:

- **availability** / **available** near WCAG, audit, specialist, CPWA, design
  system, or project delivery → likely wrong; change to **accessibility** /
  **accessible**
- **accessibility specialist** translated back from tillgänglighetsspecialist —
  correct
- Role titles and skill chips must not say “availability specialist” or
  “availability audit” unless the Swedish source is explicitly about scheduling

## Swedish output

When generating Swedish CVs, keep standard Axesslab terminology:
**tillgänglighet**, **tillgänglighetsspecialist**, **tillgänglighetsaudit**, etc.
Do not substitute **tillgänglighet** with scheduling language unless the facts
are about start date or capacity.
