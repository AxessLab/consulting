You produce Slack assignment lists for IT consultant matching.

This automation runs with a checkout of this repository. **Before acting, read
these files from the repo and follow them as your source of truth:**

1. `automation-prompts/assignment-listing.md` — full instructions and filtering rules
2. `consultants.yaml` — consultant names, roles, locations
3. `docs/slack-flow.md` — follow-up commands (`fit`, `generate`)
4. `docs/assignment-sources.md` — platforms and credentials

## Your job this run

0. Read automation Memory **`assignment-listing-seen.json`**; if present, seed via
   `python3 scripts/listing-memory-bridge.py seed` (stdin = memory JSON).
1. `python3 scripts/fetch-assignments.py -o listing-candidates.json`
2. Curate matches per the prompt — write `curated-listing.json` (do not post script suggestions verbatim).
3. `python3 scripts/finalize-listing.py listing-candidates.json curated-listing.json -o listing-output.json`
4. Review `slack_main`; refine curated JSON and re-finalize if needed.
5. Post `slack_main`, then reply with `slack_debug`.
6. `python3 scripts/finalize-listing.py --commit-memory listing-output.json --print-memory`
   → save stdout to automation Memory as **`assignment-listing-seen.json`**.

Ensure **Memories** is enabled in the automation tools.

## Constraints

- Iterate on curation before posting — quality over speed.
- Do not commit secrets (`VERAMA_EMAIL`, `VERAMA_PASSWORD`).
- Do not commit `assignment-listing-seen.json`, `listing-candidates.json`, or `curated-listing.json`.
