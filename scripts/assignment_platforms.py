"""Normalized assignment records and source scanner registry."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Callable

import requests

ALLAKONSULT_BASE = "https://allakonsultuppdrag.se"
VERAMA_BASE = "https://app.verama.com"
SCAN_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"


@dataclass(frozen=True)
class SourceConfig:
    prefix: str
    active: bool = True


SOURCE_REGISTRY: dict[str, SourceConfig] = {
    "allakonsultuppdrag.se": SourceConfig(prefix="a"),
    "verama.com": SourceConfig(prefix="v"),
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
    skills: list[Any] = field(default_factory=list)

    @property
    def dedupe_key(self) -> str:
        return f"{self.source_key}:{self.source_id}"

    # Backward-compatible aliases used by older helper code.
    @property
    def platform(self) -> str:
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
    source_key: str
    status: str
    count: int
    total_visible: int | None = None
    total_unique_visible: int | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.total_visible is None:
            self.total_visible = self.count
        if self.total_unique_visible is None:
            self.total_unique_visible = self.count

    @property
    def platform(self) -> str:
        return self.source_key


def assignment_record_from_dict(row: dict[str, Any]) -> AssignmentRecord:
    """Load current canonical rows and older snake_case/platform rows."""
    source_key = row.get("source_key") or row.get("platform") or ""
    source_id = str(row.get("source_id") or "")
    prefix = SOURCE_REGISTRY.get(source_key, SourceConfig(prefix="")).prefix
    listing_id = str(row.get("listing_id") or f"{prefix}{source_id}")
    return AssignmentRecord(
        listing_id=listing_id,
        source_key=source_key,
        source_id=source_id,
        title=row.get("title") or "",
        description=row.get("description") or "",
        descriptionSummary=row.get("descriptionSummary") or row.get("description_summary") or "",
        publishedDate=row.get("publishedDate") or row.get("published_date"),
        lastApplicationDate=row.get("lastApplicationDate") or row.get("last_application_date"),
        startDate=row.get("startDate") or row.get("start_date"),
        endDate=row.get("endDate") or row.get("end_date"),
        duration=row.get("duration") or "",
        workMode=row.get("workMode") or row.get("work_mode") or "",
        location=row.get("location") or "",
        sourceUrl=row.get("sourceUrl") or row.get("source_url") or "",
        broker=row.get("broker") or "",
        skills=row.get("skills") or [],
    )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _normalize_text(value: str) -> str:
    return value.lower().replace("ä", "a").replace("å", "a").replace("ö", "o")


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", text).strip()


def _allakonsult_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": SCAN_USER_AGENT, "Accept": "application/json"})
    return session


def scan_allakonsultuppdrag(
    *,
    page_size: int = 100,
    max_pages: int | None = None,
    **_: Any,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    source_key = "allakonsultuppdrag.se"
    session = _allakonsult_session()
    by_id: dict[str, AssignmentRecord] = {}
    page = 1
    total_pages: int | None = None
    total_visible = 0

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
            rows = payload.get("data") or []
            total_visible += len(rows)

            for row in rows:
                source_id = str(row["id"])
                by_id[source_id] = AssignmentRecord(
                    listing_id=f"a{source_id}",
                    source_key=source_key,
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

            if not payload.get("hasNextPage"):
                break
            if total_pages is not None and page >= total_pages:
                break
            page += 1

        records = list(by_id.values())
        return records, PlatformScanResult(
            source_key=source_key,
            status="ok",
            count=len(records),
            total_visible=total_visible,
            total_unique_visible=len(records),
        )
    except Exception as exc:  # noqa: BLE001
        return list(by_id.values()), PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(by_id),
            total_visible=total_visible,
            total_unique_visible=len(by_id),
            message=str(exc),
        )


def _verama_location(city: str | None, country_code: str | None) -> str:
    if city and country_code:
        return f"{city} ({country_code})"
    return city or country_code or ""


def _verama_work_mode(remoteness: Any, *extra_fields: str) -> str:
    explicit = " ".join(extra_fields)
    normalized = _normalize_text(explicit)
    try:
        remote_percent = int(remoteness) if remoteness is not None else None
    except (TypeError, ValueError):
        remote_percent = None

    if remote_percent == 100 or any(term in normalized for term in ("distans", "fjarr", "remote")):
        if remote_percent == 100:
            return "remote"
        return explicit.strip()
    if remote_percent is not None and remote_percent > 0:
        return f"hybrid ({remote_percent}% remote)"
    if remote_percent == 0:
        return "on-site"
    return explicit.strip()


TARGET_TITLE_TERMS = re.compile(
    r"\b(accessibility|tillgänglighet|tillganglighet|wcag|frontend|front-end|"
    r"react|next\.?js|angular|wordpress|java|spring|backend|fullstack|"
    r"full-stack|full stack|ux|ui|designer|product designer|interaktionsdesign|"
    r"projektledare|project manager|scrum master|agile coach|projektkoordinator|"
    r"project coordinator|leveransansvarig|developer|utvecklare|consultant|konsult)\b",
    re.I,
)

OUTSIDE_TITLE_TERMS = re.compile(
    r"\b(sap|network|nätverk|natverk|security operations|soc|hr|payroll|"
    r"automation engineer|factory|plc|embedded|fpga|mobile|ios|android|"
    r"data engineer|data scientist|analyst|business analyst|testare|tester)\b",
    re.I,
)

STRONG_A11Y_TITLE = re.compile(
    r"tillgänglighetsgranskare|tillganglighetsgranskare|"
    r"tillgänglighetsspecialist|tillganglighetsspecialist|"
    r"accessibility specialist|accessibility consultant|wcag specialist|"
    r"document accessibility|dokumenttillgänglighet|dokumenttillganglighet|"
    r"webbtillgänglighetsspecialist|webbtillganglighetsspecialist",
    re.I,
)

NEAR_STOCKHOLM_TERMS = (
    "stockholm",
    "solna",
    "sundbyberg",
    "kista",
    "bromma",
    "sollentuna",
    "danderyd",
    "taby",
    "täby",
    "jarfalla",
    "järfälla",
    "nacka",
    "huddinge",
    "lidingo",
    "lidingö",
    "alvsjo",
    "älvsjö",
    "arsta",
    "årsta",
    "stockholms lan",
    "stockholms län",
    "botkyrka",
    "upplands vasby",
    "upplands väsby",
    "sodertalje",
    "södertälje",
    "haninge",
    "tyreso",
    "tyresö",
    "vallingby",
    "vällingby",
    "farsta",
)


def _verama_location_precheck(record: AssignmentRecord) -> bool:
    location = _normalize_text(record.location)
    work_mode = _normalize_text(record.workMode)
    if "remote" == work_mode or "distans" in work_mode or "fjarr" in work_mode:
        return True
    if any(term in location for term in NEAR_STOCKHOLM_TERMS):
        return True
    if re.search(r"\b(frontend|front-end|react|angular|wordpress)\b", record.title, re.I):
        return "goteborg" in location or "göteborg" in location or "gothenburg" in location
    return False


def _verama_should_fetch_detail(
    record: AssignmentRecord,
    *,
    scan_date: date,
    seen_ids: set[str],
) -> bool:
    if record.source_id in seen_ids:
        return False
    last_app = _parse_date(record.lastApplicationDate)
    if last_app is not None and last_app < scan_date:
        return False
    title = record.title or ""
    if not record.lastApplicationDate:
        return True
    if STRONG_A11Y_TITLE.search(title):
        return True
    if OUTSIDE_TITLE_TERMS.search(title) and not TARGET_TITLE_TERMS.search(title):
        return False
    if not TARGET_TITLE_TERMS.search(title):
        return False
    return _verama_location_precheck(record) or STRONG_A11Y_TITLE.search(title) is not None


def _first_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _verama_skills(payload: dict[str, Any]) -> list[Any]:
    for key in ("skills", "competences", "competencies", "requiredSkills"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _merge_verama_detail(record: AssignmentRecord, payload: dict[str, Any]) -> AssignmentRecord:
    description = _first_text(
        payload,
        (
            "description",
            "jobDescription",
            "assignmentDescription",
            "descriptionText",
            "text",
            "content",
        ),
    )
    summary = _first_text(payload, ("descriptionSummary", "summary", "shortDescription"))
    if not summary and description:
        summary = _strip_html(description)[:300]

    remote_text = _first_text(payload, ("workMode", "workingMode", "remotenessDescription"))
    work_mode = record.workMode
    if remote_text:
        detail_mode = _verama_work_mode(None, remote_text)
        if detail_mode:
            work_mode = f"{work_mode}; {detail_mode}" if work_mode else detail_mode

    start_date = _first_text(payload, ("firstDayOfAssignment", "startDate", "assignmentStartDate"))
    end_date = _first_text(payload, ("lastDayOfAssignment", "endDate", "assignmentEndDate"))
    duration = _first_text(payload, ("duration", "assignmentLength", "period"))
    if not duration and (start_date or end_date):
        duration = f"{start_date} - {end_date}".strip(" -")

    return AssignmentRecord(
        listing_id=record.listing_id,
        source_key=record.source_key,
        source_id=record.source_id,
        title=record.title,
        description=description,
        descriptionSummary=summary,
        publishedDate=record.publishedDate,
        lastApplicationDate=record.lastApplicationDate
        or _first_text(payload, ("lastDayOfApplications", "lastApplicationDate", "applicationDeadline", "deadline")),
        startDate=start_date or record.startDate,
        endDate=end_date or record.endDate,
        duration=duration or record.duration,
        workMode=work_mode,
        location=record.location,
        sourceUrl=record.sourceUrl,
        broker=record.broker,
        skills=_verama_skills(payload),
    )


def scan_verama(
    email: str,
    password: str,
    *,
    page_size: int = 100,
    headless: bool = True,
    seen_ids: set[str] | None = None,
    scan_date: date | None = None,
    **_: Any,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    source_key = "verama.com"
    seen_ids = seen_ids or set()
    scan_date = scan_date or date.today()

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [], PlatformScanResult(
            source_key=source_key,
            status="error",
            count=0,
            message="playwright is not installed; run pip install -r requirements.txt",
        )

    by_id: dict[str, AssignmentRecord] = {}
    total_visible = 0

    def api_headers(auth_headers: dict[str, str]) -> dict[str, str]:
        return {
            **auth_headers,
            "User-Agent": SCAN_USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{VERAMA_BASE}/app/job-requests",
        }

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
                    headers=api_headers(auth_headers),
                    timeout=60000,
                )
                if response.status != 200:
                    raise RuntimeError(
                        f"Verama job API returned {response.status}: {response.text()[:200]}"
                    )

                payload = response.json()
                rows = payload.get("content") or []
                total_visible += len(rows)
                for row in rows:
                    source_id = str(row["id"])
                    record = AssignmentRecord(
                        listing_id=f"v{source_id}",
                        source_key=source_key,
                        source_id=source_id,
                        title=row.get("title") or "",
                        publishedDate=row.get("firstDayOfApplications"),
                        lastApplicationDate=row.get("lastDayOfApplications"),
                        workMode=_verama_work_mode(row.get("remoteness")),
                        location=_verama_location(row.get("city"), row.get("countryCode")),
                        sourceUrl=f"{VERAMA_BASE}/app/job-requests/{source_id}",
                        broker=row.get("originServiceName") or "",
                    )
                    by_id[source_id] = record

                if payload.get("last") or not rows:
                    break
                page_num += 1

            for source_id, record in list(by_id.items()):
                if not _verama_should_fetch_detail(record, scan_date=scan_date, seen_ids=seen_ids):
                    continue
                detail_response = api.get(
                    f"{VERAMA_BASE}/api/job-requests/v2/{source_id}",
                    headers=api_headers(auth_headers),
                    timeout=60000,
                )
                if detail_response.status in {401, 403}:
                    raise RuntimeError(f"Verama detail API returned {detail_response.status}")
                if detail_response.status == 404:
                    detail_response = api.get(
                        f"{VERAMA_BASE}/api/job-requests/{source_id}",
                        headers=api_headers(auth_headers),
                        timeout=60000,
                    )
                if detail_response.status != 200:
                    continue
                by_id[source_id] = _merge_verama_detail(record, detail_response.json())

            browser.close()

        records = list(by_id.values())
        return records, PlatformScanResult(
            source_key=source_key,
            status="ok",
            count=len(records),
            total_visible=total_visible,
            total_unique_visible=len(records),
        )
    except PlaywrightTimeoutError as exc:
        return list(by_id.values()), PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(by_id),
            total_visible=total_visible,
            total_unique_visible=len(by_id),
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return list(by_id.values()), PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(by_id),
            total_visible=total_visible,
            total_unique_visible=len(by_id),
            message=str(exc),
        )


PlatformScanner = Callable[..., tuple[list[AssignmentRecord], PlatformScanResult]]

PLATFORM_SCANNERS: dict[str, PlatformScanner] = {
    "allakonsultuppdrag.se": scan_allakonsultuppdrag,
    "verama.com": scan_verama,
}

DEFAULT_PLATFORMS = [key for key, config in SOURCE_REGISTRY.items() if config.active]
DEFAULT_SOURCES = DEFAULT_PLATFORMS


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
    seen_ids_by_source = seen_ids_by_source or {}
    verama_email = os.environ.get("VERAMA_EMAIL")
    verama_password = os.environ.get("VERAMA_PASSWORD")

    for platform_id in platform_ids:
        scanner = PLATFORM_SCANNERS.get(platform_id)
        if scanner is None:
            results.append(
                PlatformScanResult(
                    source_key=platform_id,
                    status="error",
                    count=0,
                    message=f"Unknown source: {platform_id}",
                )
            )
            continue

        if platform_id == "verama.com":
            if not verama_email or not verama_password:
                results.append(
                    PlatformScanResult(
                        source_key=platform_id,
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
                seen_ids=seen_ids_by_source.get(platform_id, set()),
                scan_date=scan_date,
            )
        else:
            rows, result = scanner(max_pages=max_pages, scan_date=scan_date)

        assignments.extend(rows)
        results.append(result)

    return assignments, results
