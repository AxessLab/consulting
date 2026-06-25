# Assignment sources

The assignment-listing automation scans these platforms on each run:

| Platform | Scanner | Credentials |
|----------|---------|-------------|
| [allakonsultuppdrag.se](https://allakonsultuppdrag.se/) | Public REST API | None |
| [Verama](https://app.verama.com/) (Ework) | Playwright login + authenticated REST API | `VERAMA_EMAIL`, `VERAMA_PASSWORD` |

Run the scanner locally or from Cursor Automations:

```bash
pip install -r requirements.txt
python -m playwright install chromium
export VERAMA_EMAIL=consulting@axesslab.com
export VERAMA_PASSWORD=veramaAxs!
python scripts/scan-assignments.py --debug-summary
```

## Output

`scripts/scan-assignments.py` prints JSON to stdout:

- `scannedAt` — UTC timestamp
- `platforms` — per-platform status, count, and optional error message
- `assignments` — normalized assignment rows for Slack listing

Assignment ids in Slack:

- allakonsultuppdrag.se — numeric id, e.g. `[6236]`
- verama.com — `v` prefix, e.g. `[v81392]`

Verama ad links use `https://app.verama.com/app/job-requests/<id>`.

## Secrets

Store `VERAMA_EMAIL` and `VERAMA_PASSWORD` in Cursor Automation environment
variables. Do not commit credentials to this repository. Copy `.env.example` to
`.env` for local runs only.

## Deduping

Some Ework/Verama assignments also appear on allakonsultuppdrag.se via brokers.
When posting Slack list items, skip duplicates that match the same buyer, title,
and location across platforms.
