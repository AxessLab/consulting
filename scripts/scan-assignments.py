#!/usr/bin/env python3
"""Scan assignment platforms and emit normalized JSON for the listing automation."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import requests

ALLAKONSULT_BASE = "https://allakonsultuppdrag.se"
VERAMA_BASE = "https://app.verama.com"
USER_AGENT = "Mozilla/5.0 (compatible; AxessLabAssignmentScanner/1.0)"


@dataclass
class Assignment:
    id: str
    platform: str
    source_id: str
    title: str
    location: str | None
    url: str
    published_date: str | None = None
    broker: str | None = None
    work_mode: str | None = None
    description_summary: str | None = None


@dataclass
class PlatformScan:
    platform: str
    status: str
    count: int
    message: str | None = None


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def scan_allakonsultuppdrag(
    *,
    page_size: int = 100,
    max_pages: int | None = None,
) -> tuple[list[Assignment], PlatformScan]:
    platform = "allakonsultuppdrag.se"
    session = _session()
    assignments: list[Assignment] = []
    page = 1

    try:
        while True:
            if max_pages is not None and page > max_pages:
                break

            response = session.get(
                f"{ALLAKONSULT_BASE}/api/assignments",
                params={"page": page, "pageSize": page_size},
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("data") or []

            for row in rows:
                source_id = str(row["id"])
                assignments.append(
                    Assignment(
                        id=source_id,
                        platform=platform,
                        source_id=source_id,
                        title=row.get("title") or "",
                        location=row.get("location"),
                        url=row.get("sourceUrl") or f"{ALLAKONSULT_BASE}/",
                        published_date=row.get("publishedDate"),
                        broker=row.get("broker"),
                        work_mode=row.get("workMode"),
                        description_summary=row.get("descriptionSummary"),
                    )
                )

            if not payload.get("hasNextPage"):
                break
            page += 1

        return assignments, PlatformScan(platform=platform, status="ok", count=len(assignments))
    except Exception as exc:  # noqa: BLE001 - surface scan failures in JSON output
        return assignments, PlatformScan(
            platform=platform,
            status="error",
            count=len(assignments),
            message=str(exc),
        )


def _verama_location(city: str | None, country_code: str | None) -> str | None:
    if city and country_code:
        return f"{city} ({country_code})"
    return city or country_code


def scan_verama(
    email: str,
    password: str,
    *,
    page_size: int = 100,
    headless: bool = True,
) -> tuple[list[Assignment], PlatformScan]:
    platform = "verama.com"

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [], PlatformScan(
            platform=platform,
            status="error",
            count=0,
            message="playwright is not installed; run pip install -r requirements.txt",
        )

    assignments: list[Assignment] = []

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context(user_agent=USER_AGENT, locale="sv-SE")
            page = context.new_page()
            auth_headers: dict[str, str] = {}

            def capture_auth_headers(request) -> None:
                if "job-requests/v2" not in request.url or auth_headers:
                    return
                for key in (
                    "authorization",
                    "x-session",
                    "x-context-id",
                    "x-frontend-version",
                    "accept-language",
                ):
                    value = request.headers.get(key)
                    if value:
                        auth_headers[key] = value

            page.on("request", capture_auth_headers)

            page.goto(f"{VERAMA_BASE}/sv/login", wait_until="domcontentloaded", timeout=60000)
            page.locator('input[type="email"], input[name="email"]').first.fill(email)
            page.locator('input[type="password"]').first.fill(password)
            page.locator(
                'button[type="submit"], button:has-text("Logga in"), button:has-text("Log in")'
            ).first.click()
            page.wait_for_timeout(8000)
            page.goto(f"{VERAMA_BASE}/app/job-requests", wait_until="networkidle", timeout=90000)
            page.wait_for_timeout(3000)

            if not auth_headers:
                raise RuntimeError("Could not capture Verama auth headers after login")

            api = context.request
            page_num = 0
            while True:
                response = api.get(
                    f"{VERAMA_BASE}/api/job-requests/v2",
                    params={
                        "page": str(page_num),
                        "size": str(page_size),
                        "query": "",
                        "dedicated": "false",
                        "favouritesOnly": "false",
                        "recommendedOnly": "false",
                        "sort": "firstDayOfApplications,DESC",
                    },
                    headers={
                        **auth_headers,
                        "accept": "application/json, text/plain, */*",
                        "referer": f"{VERAMA_BASE}/app/job-requests",
                    },
                    timeout=60000,
                )
                if response.status != 200:
                    raise RuntimeError(
                        f"Verama job API returned {response.status}: {response.text()[:200]}"
                    )

                payload = response.json()
                rows = payload.get("content") or []
                for row in rows:
                    source_id = str(row["id"])
                    assignments.append(
                        Assignment(
                            id=f"v{source_id}",
                            platform=platform,
                            source_id=source_id,
                            title=row.get("title") or "",
                            location=_verama_location(row.get("city"), row.get("countryCode")),
                            url=f"{VERAMA_BASE}/app/job-requests/{source_id}",
                            published_date=row.get("firstDayOfApplications"),
                            broker=row.get("originServiceName"),
                            work_mode=(
                                f"{row.get('remoteness')}% remote"
                                if row.get("remoteness") is not None
                                else None
                            ),
                            description_summary=row.get("systemId"),
                        )
                    )

                if payload.get("last") or not rows:
                    break
                page_num += 1

            browser.close()

        return assignments, PlatformScan(platform=platform, status="ok", count=len(assignments))
    except PlaywrightTimeoutError as exc:
        return assignments, PlatformScan(
            platform=platform,
            status="error",
            count=len(assignments),
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 - surface scan failures in JSON output
        return assignments, PlatformScan(
            platform=platform,
            status="error",
            count=len(assignments),
            message=str(exc),
        )


def scan_assignments(
    *,
    platforms: list[str],
    verama_email: str | None,
    verama_password: str | None,
    max_pages: int | None = None,
    headless: bool = True,
) -> dict[str, Any]:
    assignments: list[Assignment] = []
    platform_results: list[PlatformScan] = []

    if "allakonsultuppdrag.se" in platforms:
        aka_assignments, aka_result = scan_allakonsultuppdrag(max_pages=max_pages)
        assignments.extend(aka_assignments)
        platform_results.append(aka_result)

    if "verama.com" in platforms:
        if not verama_email or not verama_password:
            platform_results.append(
                PlatformScan(
                    platform="verama.com",
                    status="skipped",
                    count=0,
                    message="VERAMA_EMAIL and VERAMA_PASSWORD are not set",
                )
            )
        else:
            verama_assignments, verama_result = scan_verama(
                verama_email,
                verama_password,
                headless=headless,
            )
            assignments.extend(verama_assignments)
            platform_results.append(verama_result)

    return {
        "scannedAt": datetime.now(UTC).isoformat(),
        "platforms": [asdict(result) for result in platform_results],
        "assignments": [asdict(assignment) for assignment in assignments],
    }


def build_slack_debug_summary(platform_results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for result in platform_results:
        label = result["platform"]
        if result["status"] == "ok":
            parts.append(f"{label} ({result['count']})")
        elif result["status"] == "skipped":
            parts.append(f"{label} (skipped)")
        else:
            parts.append(f"{label} (error)")
    return "Scanned platforms: " + ", ".join(parts)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platform",
        action="append",
        dest="platforms",
        choices=["allakonsultuppdrag.se", "verama.com"],
        help="Platform to scan (default: both)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Limit allakonsultuppdrag.se pagination (testing)",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run Verama browser login with a visible window",
    )
    parser.add_argument(
        "--debug-summary",
        action="store_true",
        help="Print a Slack-ready platform summary line to stderr",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    import os

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    args = parse_args(argv)
    platforms = args.platforms or ["allakonsultuppdrag.se", "verama.com"]

    payload = scan_assignments(
        platforms=platforms,
        verama_email=os.environ.get("VERAMA_EMAIL"),
        verama_password=os.environ.get("VERAMA_PASSWORD"),
        max_pages=args.max_pages,
        headless=not args.headed,
    )

    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")

    if args.debug_summary:
        summary = build_slack_debug_summary(payload["platforms"])
        print(summary, file=sys.stderr)

    failed = [p for p in payload["platforms"] if p["status"] == "error"]
    return 1 if failed and not payload["assignments"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
