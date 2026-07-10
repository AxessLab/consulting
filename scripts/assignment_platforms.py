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
SOURCE_REGISTRY: dict[str, dict[str, str]] = {
    "allakonsultuppdrag.se": {"prefix": "a"},
    "verama.com": {"prefix": "v"},
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlatformScanResult:
    platform: str
    status: str
    count: int
    message: str | None = None


def source_prefix(source_key: str) -> str:
    return SOURCE_REGISTRY.get(source_key, {}).get("prefix", "")


def prefixed_listing_id(source_key: str, source_id: str) -> str:
    return f"{source_prefix(source_key)}{source_id}"


def parse_api_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def normalize_text(value: str) -> str:
    return value.casefold()


def _normalize_work_mode(work_mode: str, description: str = "") -> str:
    description_text = normalize_text(description)
    remote_percent = re.search(r"distansarbete\s*(\d{1,3})\s*%", description_text)
    if remote_percent:
        percent = int(remote_percent.group(1))
        if percent == 100:
            return "remote"
        if percent == 0:
            return "on-site"
        return f"{percent}% remote"
    return work_mode


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
                    listing_id=prefixed_listing_id(platform, source_id),
                    title=row.get("title") or "",
                    description=row.get("description") or "",
                    description_summary=row.get("descriptionSummary") or "",
                    published_date=row.get("publishedDate"),
                    last_application_date=row.get("lastApplicationDate"),
                    start_date=row.get("startDate"),
                    end_date=row.get("endDate"),
                    duration=row.get("duration") or "",
                    work_mode=_normalize_work_mode(
                        row.get("workMode") or "",
                        row.get("description") or "",
                    ),
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


def _verama_work_mode(remoteness: Any, *extra_fields: str) -> str:
    extras = " ".join(field for field in extra_fields if field)
    normalized_extras = normalize_text(extras)
    if remoteness == 100 or re.search(r"\b(remote|distans|fjärrarbete|fjarrarbete)\b", normalized_extras):
        return "remote" if remoteness in (None, 100) else f"{remoteness}% remote"
    if isinstance(remoteness, int) and 0 < remoteness < 100:
        return f"{remoteness}% remote"
    if remoteness == 0:
        return "on-site"
    return ""


def _work_mode_is_fully_remote(work_mode: str) -> bool:
    normalized = normalize_text(work_mode)
    percentage_remote = re.search(r"\b(\d{1,3})\s*%\s*remote\b", normalized)
    if percentage_remote:
        return int(percentage_remote.group(1)) >= 100
    return bool(re.search(r"\b(remote|distans|fjärrarbete|fjarrarbete)\b", normalized))


def _first_string(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            return str(value)
    return ""


def _description_from_detail(detail: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "description",
        "jobDescription",
        "assignmentDescription",
        "requirements",
        "requiredCompetence",
        "competenceRequirements",
        "roleDescription",
    ):
        value = detail.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n\n".join(dict.fromkeys(parts))


def _skills_from_detail(detail: dict[str, Any]) -> list[dict[str, Any]]:
    raw_skills = detail.get("skills") or detail.get("skillRequirements") or detail.get("competences") or []
    skills: list[dict[str, Any]] = []
    if not isinstance(raw_skills, list):
        return skills
    for item in raw_skills:
        if isinstance(item, dict):
            name = item.get("name") or item.get("skillName") or item.get("competenceName") or item.get("title")
            if name:
                skills.append({"name": str(name)})
        elif isinstance(item, str):
            skills.append({"name": item})
    return skills


def _verama_list_record(row: dict[str, Any]) -> AssignmentRecord:
    source_id = str(row["id"])
    remoteness = row.get("remoteness")
    if isinstance(remoteness, str) and remoteness.isdigit():
        remoteness = int(remoteness)
    return AssignmentRecord(
        platform="verama.com",
        source_id=source_id,
        listing_id=prefixed_listing_id("verama.com", source_id),
        title=row.get("title") or "",
        description_summary=row.get("summary") or row.get("systemId") or "",
        published_date=row.get("firstDayOfApplications"),
        last_application_date=row.get("lastDayOfApplications"),
        work_mode=_verama_work_mode(remoteness, str(row.get("workMode") or "")),
        location=_verama_location(row.get("city"), row.get("countryCode")),
        source_url=f"{VERAMA_BASE}/app/job-requests/{source_id}",
        broker=row.get("originServiceName") or "",
    )


def _title_clearly_outside_target(title: str) -> bool:
    text = normalize_text(title)
    outside = re.search(
        r"\b(sap|network|nätverk|security operations|soc|hr|payroll|lön|"
        r"automation engineer|factory|produktion|analyst|analytiker|"
        r"embedded|fpga|test engineer|cloud engineer|devops|mobile|ios|android)\b",
        text,
    )
    target = re.search(
        r"\b(accessibility|tillgänglighet|tillganglighet|wcag|frontend|front-end|"
        r"react|next\.?js|angular|wordpress|java|spring|fullstack|full-stack|"
        r"ux|ui|product designer|interaction design|interaktionsdesign|"
        r"project manager|projektledare|scrum master|agile coach|"
        r"projektkoordinator|project coordinator|developer|utvecklare|consultant|konsult)\b",
        text,
    )
    return bool(outside and not target)


def _verama_location_precheck_fails(record: AssignmentRecord) -> bool:
    location = normalize_text(record.location)
    work_mode = normalize_text(record.work_mode)
    if _work_mode_is_fully_remote(work_mode):
        return False
    if any(
        place in location
        for place in (
            "stockholm",
            "solna",
            "sundbyberg",
            "kista",
            "bromma",
            "sollentuna",
            "danderyd",
            "täby",
            "jarfalla",
            "järfälla",
            "nacka",
            "huddinge",
            "lidingö",
            "älvsjö",
            "årsta",
            "stockholms län",
            "göteborg",
            "goteborg",
            "gothenburg",
        )
    ):
        return False
    return True


def _strong_accessibility_title(title: str) -> bool:
    text = normalize_text(title)
    return bool(
        re.search(
            r"\b(tillgänglighetsgranskare|tillganglighetsgranskare|"
            r"tillgänglighetsspecialist|tillganglighetsspecialist|"
            r"accessibility specialist|accessibility consultant|wcag specialist|"
            r"document accessibility|dokumenttillgänglighet|dokumenttillganglighet)\b",
            text,
        )
    )


def _should_fetch_verama_detail(
    record: AssignmentRecord,
    *,
    seen_source_ids: set[str],
    scan_date: date,
) -> bool:
    if record.source_id in seen_source_ids:
        return False
    last_application = parse_api_date(record.last_application_date)
    if last_application is not None and last_application < scan_date:
        return False
    if _title_clearly_outside_target(record.title):
        return False
    if _verama_location_precheck_fails(record) and not _strong_accessibility_title(record.title):
        return False
    return True


def _merge_verama_detail(record: AssignmentRecord, detail: dict[str, Any]) -> AssignmentRecord:
    description = _description_from_detail(detail)
    summary = _first_string(detail, ("descriptionSummary", "summary", "shortDescription"))
    if not summary and description:
        summary = description[:300]
    start_date = _first_string(
        detail,
        ("firstDayOfAssignment", "assignmentStartDate", "startDate", "startsAt"),
    )
    end_date = _first_string(
        detail,
        ("lastDayOfAssignment", "assignmentEndDate", "endDate", "endsAt"),
    )
    last_application = record.last_application_date or _first_string(
        detail,
        ("lastDayOfApplications", "lastApplicationDate", "applicationDeadline", "deadline"),
    )
    explicit_work_mode = _first_string(detail, ("workMode", "remotePolicy", "locationDescription"))
    work_mode = record.work_mode
    if explicit_work_mode and re.search(
        r"\b(remote|distans|fjärrarbete|fjarrarbete|hybrid)\b",
        normalize_text(explicit_work_mode),
    ):
        work_mode = f"{record.work_mode} {explicit_work_mode}".strip()
    duration = _first_string(detail, ("duration", "assignmentPeriod", "period"))

    record.description = description
    record.description_summary = summary or record.description_summary
    record.last_application_date = last_application
    record.start_date = start_date or record.start_date
    record.end_date = end_date or record.end_date
    record.duration = duration or record.duration
    record.work_mode = work_mode
    record.skills = _skills_from_detail(detail)
    return record


def scan_verama(
    email: str,
    password: str,
    *,
    page_size: int = 100,
    headless: bool = True,
    seen_source_ids: set[str] | None = None,
    scan_date: date | None = None,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    platform = "verama.com"
    seen_source_ids = seen_source_ids or set()
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

    by_source_id: dict[str, AssignmentRecord] = {}

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

            def login_and_capture_headers() -> None:
                auth_headers.clear()
                page.goto(f"{VERAMA_BASE}/sv/login", wait_until="domcontentloaded", timeout=60000)
                page.locator('input[type="email"], input[name="email"]').first.fill(email)
                page.locator('input[type="password"]').first.fill(password)
                page.locator(
                    'button[type="submit"], button:has-text("Logga in"), button:has-text("Log in")'
                ).first.click()
                page.wait_for_timeout(8000)
                page.goto(f"{VERAMA_BASE}/app/job-requests", wait_until="networkidle", timeout=90000)
                page.wait_for_timeout(3000)

            def api_headers() -> dict[str, str]:
                return {
                    **auth_headers,
                    "accept": "application/json, text/plain, */*",
                    "referer": f"{VERAMA_BASE}/app/job-requests",
                }

            login_and_capture_headers()

            if not auth_headers:
                raise RuntimeError("Could not capture Verama auth headers after login")

            api = context.request
            page_num = 0
            relogin_used = False
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
                    headers=api_headers(),
                    timeout=60000,
                )
                if response.status in (401, 403) and not relogin_used:
                    relogin_used = True
                    login_and_capture_headers()
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
                        headers=api_headers(),
                        timeout=60000,
                    )
                if response.status != 200:
                    raise RuntimeError(
                        f"Verama job API returned {response.status}: {response.text()[:200]}"
                    )

                payload = response.json()
                rows = payload.get("content") or []
                for row in rows:
                    record = _verama_list_record(row)
                    if _should_fetch_verama_detail(
                        record,
                        seen_source_ids=seen_source_ids,
                        scan_date=scan_date,
                    ):
                        detail = None
                        for path in (
                            f"{VERAMA_BASE}/api/job-requests/v2/{record.source_id}",
                            f"{VERAMA_BASE}/api/job-requests/{record.source_id}",
                        ):
                            detail_response = api.get(
                                path,
                                headers=api_headers(),
                                timeout=60000,
                            )
                            if detail_response.status in (401, 403) and not relogin_used:
                                relogin_used = True
                                login_and_capture_headers()
                                detail_response = api.get(
                                    path,
                                    headers=api_headers(),
                                    timeout=60000,
                                )
                            if detail_response.status == 200:
                                detail = detail_response.json()
                                break
                        if isinstance(detail, dict):
                            record = _merge_verama_detail(record, detail)
                    by_source_id[record.source_id] = record

                if payload.get("last") or not rows:
                    break
                page_num += 1

            browser.close()

        records = list(by_source_id.values())
        return records, PlatformScanResult(platform=platform, status="ok", count=len(records))
    except PlaywrightTimeoutError as exc:
        records = list(by_source_id.values())
        return records, PlatformScanResult(
            platform=platform,
            status="error",
            count=len(records),
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        records = list(by_source_id.values())
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
    seen_keys: set[str] | None = None,
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
                seen_source_ids={
                    key.split(":", 1)[1]
                    for key in (seen_keys or set())
                    if key.startswith(f"{platform_id}:")
                },
                scan_date=scan_date,
            )
        else:
            rows, result = scanner(max_pages=max_pages)

        assignments.extend(rows)
        results.append(result)

    return assignments, results
