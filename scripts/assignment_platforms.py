"""Normalized assignment records and platform scanner registry."""

from __future__ import annotations

import html
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Callable

import requests

ALLAKONSULT_BASE = "https://allakonsultuppdrag.se"
VERAMA_BASE = "https://app.verama.com"
ALLAKONSULT_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"
SCAN_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"

SOURCE_REGISTRY: dict[str, dict[str, Any]] = {
    "allakonsultuppdrag.se": {"prefix": "a", "active": True},
    "verama.com": {"prefix": "v", "active": True},
}


@dataclass
class AssignmentRecord:
    listing_id: str
    source_key: str
    source_id: str
    title: str
    description: str = ""
    descriptionSummary: str = ""
    publishedDate: str | None = None
    lastApplicationDate: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    duration: str = ""
    workMode: str = ""
    location: str = ""
    sourceUrl: str = ""
    broker: str = ""
    skills: list[dict[str, Any] | str] = field(default_factory=list)

    @property
    def dedupe_key(self) -> str:
        return f"{self.source_key}:{self.source_id}"

    @property
    def platform(self) -> str:
        """Backward-compatible alias for older curation files."""
        return self.source_key

    @property
    def description_summary(self) -> str:
        return self.descriptionSummary

    @property
    def published_date(self) -> str | None:
        return self.publishedDate

    @property
    def last_application_date(self) -> str | None:
        return self.lastApplicationDate

    @property
    def start_date(self) -> str | None:
        return self.startDate

    @property
    def end_date(self) -> str | None:
        return self.endDate

    @property
    def work_mode(self) -> str:
        return self.workMode

    @property
    def source_url(self) -> str:
        return self.sourceUrl

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
                    listing_id=f"{SOURCE_REGISTRY[platform]['prefix']}{source_id}",
                    source_key=platform,
                    source_id=source_id,
                    title=row.get("title") or "",
                    description=row.get("description") or "",
                    descriptionSummary=row.get("descriptionSummary") or "",
                    publishedDate=row.get("publishedDate"),
                    lastApplicationDate=row.get("lastApplicationDate"),
                    startDate=row.get("startDate"),
                    endDate=row.get("endDate"),
                    duration=row.get("duration") or "",
                    workMode=row.get("workMode") or "",
                    location=row.get("location") or "",
                    sourceUrl=row.get("sourceUrl") or f"{ALLAKONSULT_BASE}/",
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


def _strip_html(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.I)
    text = re.sub(r"</\s*(p|div|li|h\d)\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _coalesce_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _strip_html(value)
    return ""


def _verama_work_mode(remoteness: Any, *extra_values: Any) -> str:
    parts: list[str] = []
    try:
        remote_percent = int(remoteness) if remoteness is not None else None
    except (TypeError, ValueError):
        remote_percent = None

    if remote_percent == 100:
        parts.append("remote")
    elif remote_percent is not None and 0 < remote_percent < 100:
        parts.append(f"hybrid, {remote_percent}% remote")
    elif remote_percent == 0:
        parts.append("on-site")

    for value in extra_values:
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())

    return " | ".join(dict.fromkeys(parts))


def _parse_verama_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


NEAR_STOCKHOLM_LOCATIONS = (
    "stockholm",
    "solna",
    "sundbyberg",
    "kista",
    "bromma",
    "sollentuna",
    "danderyd",
    "täby",
    "taby",
    "järfälla",
    "jarfalla",
    "nacka",
    "huddinge",
    "lidingö",
    "lidingo",
    "älvsjö",
    "alvsjo",
    "årsta",
    "arsta",
    "stockholms län",
    "stockholms lan",
    "botkyrka",
    "upplands väsby",
    "upplands vasby",
    "södertälje",
    "sodertalje",
    "haninge",
    "tyresö",
    "tyreso",
    "vällingby",
    "vallingby",
    "farsta",
)


STRONG_A11Y_TITLE = re.compile(
    r"(tillgänglighetsgranskare|tillganglighetsgranskare|"
    r"tillgänglighetsspecialist|tillganglighetsspecialist|"
    r"accessibility specialist|accessibility consultant|wcag specialist|"
    r"document accessibility|dokumenttillgänglighet|dokumenttillganglighet|"
    r"webbtillgänglighetsspecialist|webbtillganglighetsspecialist)",
    re.I,
)


TARGET_TITLE_SIGNAL = re.compile(
    r"\b(accessibility|tillgänglighet|tillganglighet|wcag|frontend|front-end|"
    r"react|next\.?js|angular|wordpress|java|spring|backend|fullstack|full-stack|"
    r"ux|ui|designer|product designer|interaction design|interaktionsdesign|"
    r"tjänstedesign|tjanstedesign|projektledare|project manager|scrum master|"
    r"projektkoordinator|project coordinator|agile coach|developer|utvecklare|"
    r"systemutvecklare|consultant|konsult|project lead|leveransansvarig)\b",
    re.I,
)


OUTSIDE_TITLE_SIGNAL = re.compile(
    r"\b(sap|network|nätverk|natverk|security operations|soc|hr|payroll|"
    r"automation engineer|factory|produktion|embedded|fpga|data engineer|"
    r"cloud engineer|devops|mobile|ios|android|test engineer|qa engineer|"
    r"business analyst|analytiker|inköpare|buyer|mechanical|mekanik)\b",
    re.I,
)


def _verama_title_clearly_outside(title: str) -> bool:
    if STRONG_A11Y_TITLE.search(title):
        return False
    if TARGET_TITLE_SIGNAL.search(title):
        return False
    return OUTSIDE_TITLE_SIGNAL.search(title) is not None


def _verama_location_precheck(record: AssignmentRecord) -> bool:
    title = record.title.lower()
    location = record.location.lower()
    work_mode = record.workMode.lower()
    if "remote" in re.sub(r"\b([1-9]\d?)\s*%\s*remote\b", "", work_mode):
        return True
    if any(term in f"{work_mode} {location}" for term in ("distans", "fjärrarbete", "fjarrarbete")):
        return True
    if any(place in location for place in NEAR_STOCKHOLM_LOCATIONS):
        return True
    if re.search(r"\b(frontend|front-end|react|angular|wordpress)\b", title) and any(
        city in location for city in ("gothenburg", "goteborg", "göteborg")
    ):
        return True
    return STRONG_A11Y_TITLE.search(record.title) is not None


def _should_fetch_verama_detail(
    record: AssignmentRecord,
    *,
    seen_keys: set[str],
    scan_date: date | None,
) -> bool:
    if record.dedupe_key in seen_keys:
        return False
    last_application_date = _parse_verama_date(record.lastApplicationDate)
    if scan_date is not None and last_application_date is not None and last_application_date < scan_date:
        return False
    if _verama_title_clearly_outside(record.title):
        return False
    if not _verama_location_precheck(record):
        return False
    return True


def _verama_skills(detail: dict[str, Any]) -> list[dict[str, str] | str]:
    values: list[Any] = []
    for key in (
        "skills",
        "competences",
        "competencies",
        "requiredCompetences",
        "requiredSkills",
        "technologies",
    ):
        value = detail.get(key)
        if isinstance(value, list):
            values.extend(value)

    skills: list[dict[str, str] | str] = []
    seen: set[str] = set()
    for item in values:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = str(
                item.get("name")
                or item.get("title")
                or item.get("label")
                or item.get("competenceName")
                or ""
            ).strip()
        else:
            name = ""
        if name and name.lower() not in seen:
            skills.append({"name": name})
            seen.add(name.lower())
    return skills


def _merge_verama_detail(record: AssignmentRecord, detail: dict[str, Any]) -> AssignmentRecord:
    description = _coalesce_text(
        detail,
        (
            "description",
            "jobDescription",
            "assignmentDescription",
            "roleDescription",
            "requirements",
            "content",
        ),
    )
    summary = _coalesce_text(detail, ("descriptionSummary", "summary", "shortDescription"))
    if not summary and description:
        summary = description[:300]

    start_date = detail.get("firstDayOfAssignment") or detail.get("startDate") or detail.get("assignmentStartDate")
    end_date = detail.get("lastDayOfAssignment") or detail.get("endDate") or detail.get("assignmentEndDate")
    duration = (
        detail.get("duration")
        or detail.get("assignmentDuration")
        or detail.get("period")
        or (f"{start_date} - {end_date}" if start_date and end_date else "")
    )
    deadline = (
        record.lastApplicationDate
        or detail.get("lastDayOfApplications")
        or detail.get("lastApplicationDate")
        or detail.get("applicationDeadline")
        or detail.get("deadline")
    )
    city = detail.get("city")
    country_code = detail.get("countryCode")
    location = record.location or _verama_location(city, country_code)
    work_mode = _verama_work_mode(
        detail.get("remoteness"),
        detail.get("workMode"),
        detail.get("workplaceType"),
        detail.get("remoteStatus"),
    ) or record.workMode

    record.description = description or record.description
    record.descriptionSummary = summary or record.descriptionSummary
    record.lastApplicationDate = deadline
    record.startDate = start_date or record.startDate
    record.endDate = end_date or record.endDate
    record.duration = str(duration or record.duration or "")
    record.workMode = work_mode
    record.location = location
    record.skills = _verama_skills(detail) or record.skills
    return record


def scan_verama(
    email: str,
    password: str,
    *,
    page_size: int = 100,
    headless: bool = True,
    seen_keys: set[str] | None = None,
    scan_date: date | None = None,
    _retrying_auth: bool = False,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    platform = "verama.com"
    seen_keys = seen_keys or set()

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
                if response.status in (401, 403):
                    raise PermissionError(f"Verama job API returned {response.status}")
                if response.status != 200:
                    raise RuntimeError(
                        f"Verama job API returned {response.status}: {response.text()[:200]}"
                    )

                payload = response.json()
                rows = payload.get("content") or []
                for row in rows:
                    source_id = str(row["id"])
                    remoteness = row.get("remoteness")
                    work_mode = _verama_work_mode(remoteness)
                    records.append(
                        AssignmentRecord(
                            listing_id=f"v{source_id}",
                            source_key=platform,
                            source_id=source_id,
                            title=row.get("title") or "",
                            descriptionSummary="",
                            publishedDate=row.get("firstDayOfApplications"),
                            lastApplicationDate=row.get("lastDayOfApplications"),
                            workMode=work_mode,
                            location=_verama_location(row.get("city"), row.get("countryCode")),
                            sourceUrl=f"{VERAMA_BASE}/app/job-requests/{source_id}",
                            broker=row.get("originServiceName") or "",
                        )
                    )

                if payload.get("last") or not rows:
                    break
                page_num += 1

            by_key = {record.dedupe_key: record for record in records}
            records = list(by_key.values())

            for record in records:
                if not _should_fetch_verama_detail(
                    record,
                    seen_keys=seen_keys,
                    scan_date=scan_date,
                ):
                    continue

                detail_response = api.get(
                    f"{VERAMA_BASE}/api/job-requests/v2/{record.source_id}",
                    headers={
                        **auth_headers,
                        "accept": "application/json, text/plain, */*",
                        "referer": f"{VERAMA_BASE}/app/job-requests/{record.source_id}",
                    },
                    timeout=60000,
                )
                if detail_response.status == 404:
                    detail_response = api.get(
                        f"{VERAMA_BASE}/api/job-requests/{record.source_id}",
                        headers={
                            **auth_headers,
                            "accept": "application/json, text/plain, */*",
                            "referer": f"{VERAMA_BASE}/app/job-requests/{record.source_id}",
                        },
                        timeout=60000,
                    )
                if detail_response.status in (401, 403):
                    raise PermissionError(
                        f"Verama detail API returned {detail_response.status}"
                    )
                if detail_response.status != 200:
                    continue
                _merge_verama_detail(record, detail_response.json())

            browser.close()

        return records, PlatformScanResult(platform=platform, status="ok", count=len(records))
    except PermissionError as exc:
        if not _retrying_auth:
            return scan_verama(
                email,
                password,
                page_size=page_size,
                headless=headless,
                seen_keys=seen_keys,
                scan_date=scan_date,
                _retrying_auth=True,
            )
        return records, PlatformScanResult(
            platform=platform,
            status="error",
            count=len(records),
            message=str(exc),
        )
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

DEFAULT_PLATFORMS = [
    source_key
    for source_key, config in SOURCE_REGISTRY.items()
    if config.get("active") and source_key in PLATFORM_SCANNERS
]


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
                seen_keys=seen_keys or set(),
                scan_date=scan_date,
            )
        else:
            rows, result = scanner(max_pages=max_pages)

        assignments.extend(rows)
        results.append(result)

    return assignments, results
