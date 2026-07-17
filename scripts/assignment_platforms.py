"""Normalized assignment records and platform scanner registry."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Callable

import requests

ALLAKONSULT_BASE = "https://allakonsultuppdrag.se"
VERAMA_BASE = "https://app.verama.com"
ALLAKONSULT_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"
SCAN_USER_AGENT = "Mozilla/5.0 (compatible; AxessLabAssignmentScanner/1.0)"

SOURCE_PREFIXES = {
    "allakonsultuppdrag.se": "a",
    "verama.com": "v",
}


@dataclass
class AssignmentRecord:
    platform: str
    source_id: str
    listing_id: str
    title: str
    description: str = ""
    description_summary: str = ""
    published_date: str | None = None
    last_application_date: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    duration: str = ""
    work_mode: str = ""
    location: str = ""
    source_url: str = ""
    broker: str = ""
    skills: list[dict[str, Any]] = field(default_factory=list)

    @property
    def dedupe_key(self) -> str:
        return f"{self.platform}:{self.source_id}"

    @property
    def source_key(self) -> str:
        return self.platform

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlatformScanResult:
    platform: str
    status: str
    count: int
    message: str | None = None


def _allakonsult_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": ALLAKONSULT_USER_AGENT,
            "Accept": "application/json",
        }
    )
    return session


def scan_allakonsultuppdrag(
    *,
    page_size: int = 100,
    max_pages: int | None = None,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    platform = "allakonsultuppdrag.se"
    session = _allakonsult_session()
    by_key: dict[str, AssignmentRecord] = {}
    page = 1
    total_pages: int | None = None

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
            total_pages = payload.get("totalPages", total_pages)

            for row in payload.get("data") or []:
                source_id = str(row["id"])
                record = AssignmentRecord(
                    platform=platform,
                    source_id=source_id,
                    listing_id=f"{SOURCE_PREFIXES[platform]}{source_id}",
                    title=row.get("title") or "",
                    description=row.get("description") or "",
                    description_summary=row.get("descriptionSummary") or "",
                    published_date=row.get("publishedDate"),
                    last_application_date=row.get("lastApplicationDate"),
                    start_date=row.get("startDate"),
                    end_date=row.get("endDate"),
                    duration=row.get("duration") or "",
                    work_mode=row.get("workMode") or "",
                    location=row.get("location") or "",
                    source_url=row.get("sourceUrl") or f"{ALLAKONSULT_BASE}/",
                    broker=row.get("broker") or "",
                    skills=row.get("skills") or [],
                )
                by_key[record.dedupe_key] = record

            if not payload.get("hasNextPage"):
                break
            if total_pages is not None and page >= total_pages:
                break
            page += 1

        records = list(by_key.values())
        return records, PlatformScanResult(platform=platform, status="ok", count=len(records))
    except Exception as exc:  # noqa: BLE001
        return list(by_key.values()), PlatformScanResult(
            platform=platform,
            status="error",
            count=len(by_key),
            message=str(exc),
        )


def _verama_location(city: str | None, country_code: str | None) -> str:
    if city and country_code:
        return f"{city} ({country_code})"
    return city or country_code or ""


def _normalize_text(value: str) -> str:
    replacements = str.maketrans({"å": "a", "ä": "a", "ö": "o"})
    return value.lower().translate(replacements)


def _strip_html(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _first_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return _strip_html(str(value))
    return ""


def _first_date(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


VERAMA_OUTSIDE_TITLE = re.compile(
    r"\b(sap|network|nätverk|natverk|security operations|soc|hr|payroll|"
    r"automation engineer|factory|manufacturing|embedded|fpga|test engineer|"
    r"data engineer|data scientist|business analyst|analyst)\b",
    re.I,
)

VERAMA_PLAUSIBLE_TITLE = re.compile(
    r"\b(accessibility|tillgänglighet|tillganglighet|wcag|frontend|front-end|"
    r"react|next\.?js|angular|wordpress|java|spring|backend|fullstack|"
    r"full-stack|ux|ui|product designer|interaction design|interaktionsdesign|"
    r"project manager|projektledare|scrum master|agile coach|"
    r"projektkoordinator|project coordinator|developer|utvecklare|consultant|"
    r"konsult|lead)\b",
    re.I,
)

STOCKHOLM_LOCATION_TERMS = {
    "stockholm",
    "solna",
    "sundbyberg",
    "kista",
    "bromma",
    "sollentuna",
    "danderyd",
    "taby",
    "jarfalla",
    "nacka",
    "huddinge",
    "lidingo",
    "alvsjo",
    "arsta",
    "stockholms lan",
    "botkyrka",
    "upplands vasby",
    "sodertalje",
    "haninge",
    "tyreso",
    "vallingby",
    "farsta",
}


def _verama_is_remote(record: AssignmentRecord) -> bool:
    fields = _normalize_text(f"{record.work_mode} {record.location}")
    return any(term in fields for term in ("remote", "distans", "fjarrarbete"))


def _verama_near_stockholm(record: AssignmentRecord) -> bool:
    location = _normalize_text(record.location)
    return any(term in location for term in STOCKHOLM_LOCATION_TERMS)


def _verama_frontend_gothenburg(record: AssignmentRecord) -> bool:
    fields = _normalize_text(f"{record.title} {record.location}")
    return (
        any(term in fields for term in ("frontend", "front-end", "react", "angular", "wordpress"))
        and ("goteborg" in fields or "gothenburg" in fields)
    )


def _verama_strong_a11y_title(record: AssignmentRecord) -> bool:
    title = _normalize_text(record.title)
    return any(
        term in title
        for term in (
            "tillganglighetsgranskare",
            "tillganglighetsspecialist",
            "accessibility specialist",
            "accessibility consultant",
            "wcag specialist",
            "webbtillganglighetsspecialist",
        )
    )


def _verama_should_fetch_detail(
    record: AssignmentRecord,
    *,
    seen_ids: set[str],
    scan_date: date,
) -> bool:
    """Keep Verama detail calls to new, plausible rows that need full context."""
    if record.source_id in seen_ids:
        return False

    last_application = _parse_date(record.last_application_date)
    if last_application is not None and last_application < scan_date:
        return False

    title = _normalize_text(record.title)
    if VERAMA_OUTSIDE_TITLE.search(title) and not VERAMA_PLAUSIBLE_TITLE.search(title):
        return False
    if not VERAMA_PLAUSIBLE_TITLE.search(title):
        return False

    if _verama_strong_a11y_title(record):
        return True
    if _verama_is_remote(record) or _verama_near_stockholm(record):
        return True
    if _verama_frontend_gothenburg(record):
        return True
    return False


def _verama_skills(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_skills = payload.get("skills") or payload.get("competences") or []
    skills: list[dict[str, Any]] = []
    if isinstance(raw_skills, list):
        for item in raw_skills:
            if isinstance(item, dict):
                name = item.get("name") or item.get("label") or item.get("skillName")
                if name:
                    skills.append({"name": str(name)})
            elif item:
                skills.append({"name": str(item)})
    return skills


def _merge_verama_detail(record: AssignmentRecord, detail: dict[str, Any]) -> AssignmentRecord:
    description = _first_text(
        detail,
        (
            "description",
            "jobDescription",
            "assignmentDescription",
            "detailedDescription",
            "scopeDescription",
        ),
    )
    summary = _first_text(detail, ("descriptionSummary", "summary", "shortDescription"))
    if not summary and description:
        summary = description[:300]

    start_date = _first_date(detail, ("firstDayOfAssignment", "startDate", "assignmentStartDate"))
    end_date = _first_date(detail, ("lastDayOfAssignment", "endDate", "assignmentEndDate"))
    duration = _first_text(detail, ("duration", "assignmentPeriod", "period"))
    if not duration and (start_date or end_date):
        duration = " - ".join(part for part in (start_date, end_date) if part)

    detail_work_mode = _first_text(detail, ("workMode", "remoteDescription", "remotenessDescription"))
    if detail_work_mode and any(
        term in _normalize_text(detail_work_mode)
        for term in ("remote", "distans", "fjarrarbete", "hybrid")
    ):
        record.work_mode = f"{record.work_mode} {detail_work_mode}".strip()

    record.description = description or record.description
    record.description_summary = summary or record.description_summary
    record.last_application_date = record.last_application_date or _first_date(
        detail,
        ("lastDayOfApplications", "lastApplicationDate", "applicationDeadline", "deadlineDate"),
    )
    record.start_date = start_date
    record.end_date = end_date
    record.duration = duration
    record.skills = _verama_skills(detail)
    return record


def scan_verama(
    email: str,
    password: str,
    *,
    page_size: int = 100,
    headless: bool = True,
    seen_ids: set[str] | None = None,
    scan_date: date | None = None,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    platform = "verama.com"
    seen_ids = seen_ids or set()
    scan_date = scan_date or date.today()

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [], PlatformScanResult(
            platform=platform,
            status="error",
            count=0,
            message="playwright is not installed; run pip install -r requirements.txt",
        )

    records: list[AssignmentRecord] = []

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context(user_agent=SCAN_USER_AGENT, locale="sv-SE")
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
                    remoteness = row.get("remoteness")
                    work_mode = (
                        f"{remoteness}% remote" if remoteness is not None else ""
                    )
                    record = AssignmentRecord(
                        platform=platform,
                        source_id=source_id,
                        listing_id=f"{SOURCE_PREFIXES[platform]}{source_id}",
                        title=row.get("title") or "",
                        description_summary=row.get("systemId") or "",
                        published_date=row.get("firstDayOfApplications"),
                        last_application_date=row.get("lastDayOfApplications"),
                        work_mode=work_mode,
                        location=_verama_location(row.get("city"), row.get("countryCode")),
                        source_url=f"{VERAMA_BASE}/app/job-requests/{source_id}",
                        broker=row.get("originServiceName") or "",
                    )
                    if _verama_should_fetch_detail(
                        record,
                        seen_ids=seen_ids,
                        scan_date=scan_date,
                    ):
                        detail_payload: dict[str, Any] | None = None
                        for detail_path in (
                            f"{VERAMA_BASE}/api/job-requests/v2/{source_id}",
                            f"{VERAMA_BASE}/api/job-requests/{source_id}",
                        ):
                            detail_response = api.get(
                                detail_path,
                                headers={
                                    **auth_headers,
                                    "accept": "application/json, text/plain, */*",
                                    "referer": f"{VERAMA_BASE}/app/job-requests/{source_id}",
                                },
                                timeout=60000,
                            )
                            if detail_response.status == 200:
                                detail_payload = detail_response.json()
                                break
                            if detail_response.status not in (404, 405):
                                raise RuntimeError(
                                    "Verama detail API returned "
                                    f"{detail_response.status} for {source_id}: "
                                    f"{detail_response.text()[:200]}"
                                )
                        if isinstance(detail_payload, dict):
                            record = _merge_verama_detail(record, detail_payload)
                    records.append(record)

                if payload.get("last") or not rows:
                    break
                page_num += 1

            browser.close()

        return records, PlatformScanResult(platform=platform, status="ok", count=len(records))
    except PlaywrightTimeoutError as exc:
        return records, PlatformScanResult(
            platform=platform,
            status="error",
            count=len(records),
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return records, PlatformScanResult(
            platform=platform,
            status="error",
            count=len(records),
            message=str(exc),
        )


PlatformScanner = Callable[..., tuple[list[AssignmentRecord], PlatformScanResult]]

PLATFORM_SCANNERS: dict[str, PlatformScanner] = {
    "allakonsultuppdrag.se": scan_allakonsultuppdrag,
    "verama.com": scan_verama,
}

DEFAULT_PLATFORMS = list(PLATFORM_SCANNERS.keys())


def scan_platforms(
    platform_ids: list[str],
    *,
    max_pages: int | None = None,
    headless: bool = True,
    seen_ids_by_source: dict[str, set[str]] | None = None,
    scan_date: date | None = None,
) -> tuple[list[AssignmentRecord], list[PlatformScanResult]]:
    assignments: list[AssignmentRecord] = []
    results: list[PlatformScanResult] = []
    verama_email = os.environ.get("VERAMA_EMAIL")
    verama_password = os.environ.get("VERAMA_PASSWORD")

    for platform_id in platform_ids:
        scanner = PLATFORM_SCANNERS.get(platform_id)
        if scanner is None:
            results.append(
                PlatformScanResult(
                    platform=platform_id,
                    status="error",
                    count=0,
                    message=f"Unknown platform: {platform_id}",
                )
            )
            continue

        if platform_id == "verama.com":
            if not verama_email or not verama_password:
                results.append(
                    PlatformScanResult(
                        platform=platform_id,
                        status="skipped",
                        count=0,
                        message="VERAMA_EMAIL and VERAMA_PASSWORD are not set",
                    )
                )
                continue
            rows, result = scanner(
                verama_email,
                verama_password,
                headless=headless,
                seen_ids=(seen_ids_by_source or {}).get(platform_id, set()),
                scan_date=scan_date,
            )
        else:
            rows, result = scanner(max_pages=max_pages)

        assignments.extend(rows)
        results.append(result)

    return assignments, results
