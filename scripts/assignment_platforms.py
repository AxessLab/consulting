"""Canonical assignment records and source scanner registry."""

from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Callable

import requests

ALLAKONSULT_BASE = "https://allakonsultuppdrag.se"
VERAMA_BASE = "https://app.verama.com"
SCAN_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"

ALLAKONSULT_KEY = "allakonsultuppdrag.se"
VERAMA_KEY = "verama.com"

NEAR_STOCKHOLM = {
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
}

GOTHENBURG_ALIASES = {"gothenburg", "goteborg", "göteborg"}

A11Y_STRONG_TITLE = re.compile(
    r"\b(tillgänglighetsgranskare|tillganglighetsgranskare|"
    r"tillgänglighetsspecialist|tillganglighetsspecialist|"
    r"accessibility specialist|accessibility consultant|wcag specialist|"
    r"document accessibility|dokumenttillgänglighet|dokumenttillganglighet|"
    r"webbtillgänglighetsspecialist|webbtillganglighetsspecialist)\b",
    re.I,
)

VERAMA_CLEARLY_OUTSIDE_TITLE = re.compile(
    r"\b(sap|network|nätverk|natverk|security operations|soc\b|"
    r"hr\b|payroll|lönespecialist|lonespecialist|automation engineer|"
    r"factory|manufacturing|embedded|fpga|data engineer|data scientist|"
    r"testledare|test lead|qa engineer|devops|cloud engineer|"
    r"platform engineer|solution architect|mobile developer|ios\b|android\b|"
    r"\.net|c#|python|php|vue)\b",
    re.I,
)

VERAMA_TARGET_OR_AMBIGUOUS_TITLE = re.compile(
    r"\b(accessibility|tillgänglighet|tillganglighet|wcag|frontend|front-end|"
    r"react|next\.?js|angular|wordpress|java|spring|backend|fullstack|"
    r"full-stack|ux|ui|product designer|interaction designer|"
    r"interaktionsdesigner|tjänstedesign|tjanstedesign|project manager|"
    r"projektledare|scrum master|agile coach|projektkoordinator|"
    r"project coordinator|leveransansvarig|developer|utvecklare|"
    r"konsult|consultant|project lead)\b",
    re.I,
)


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

    @property
    def platform(self) -> str:
        """Backward-compatible alias for older scripts."""
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


def assignment_from_dict(row: Mapping[str, Any]) -> AssignmentRecord:
    """Load either canonical records or the previous snake_case/platform shape."""

    source_key = str(row.get("source_key") or row.get("platform") or "")
    source_id = str(row.get("source_id") or "")
    listing_id = str(row.get("listing_id") or f"{source_prefix(source_key)}{source_id}")
    return AssignmentRecord(
        listing_id=listing_id,
        source_key=source_key,
        source_id=source_id,
        title=str(row.get("title") or ""),
        description=str(row.get("description") or ""),
        descriptionSummary=str(row.get("descriptionSummary") or row.get("description_summary") or ""),
        publishedDate=row.get("publishedDate") or row.get("published_date"),
        lastApplicationDate=row.get("lastApplicationDate") or row.get("last_application_date"),
        startDate=row.get("startDate") or row.get("start_date"),
        endDate=row.get("endDate") or row.get("end_date"),
        duration=str(row.get("duration") or ""),
        workMode=str(row.get("workMode") or row.get("work_mode") or ""),
        location=str(row.get("location") or ""),
        sourceUrl=str(row.get("sourceUrl") or row.get("source_url") or ""),
        broker=str(row.get("broker") or ""),
        skills=list(row.get("skills") or []),
    )


@dataclass
class PlatformScanResult:
    source_key: str
    status: str
    count: int
    message: str | None = None

    @property
    def platform(self) -> str:
        """Backward-compatible alias for older scripts."""
        return self.source_key


@dataclass(frozen=True)
class SourceConfig:
    key: str
    prefix: str
    active: bool = True


SOURCE_REGISTRY: tuple[SourceConfig, ...] = (
    SourceConfig(ALLAKONSULT_KEY, "a"),
    SourceConfig(VERAMA_KEY, "v"),
)
SOURCE_CONFIG_BY_KEY = {source.key: source for source in SOURCE_REGISTRY}


def source_prefix(source_key: str) -> str:
    config = SOURCE_CONFIG_BY_KEY.get(source_key)
    return config.prefix if config else ""


def _normalize_text(value: str) -> str:
    lowered = value.lower()
    normalized = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _date_before_scan(value: str | None, scan_date: date | None) -> bool:
    parsed = _parse_iso_date(value)
    return parsed is not None and scan_date is not None and parsed < scan_date


def _near_stockholm(location: str) -> bool:
    normalized = _normalize_text(location)
    return any(place in normalized for place in NEAR_STOCKHOLM)


def _in_gothenburg(location: str) -> bool:
    normalized = _normalize_text(location)
    return any(alias in normalized for alias in GOTHENBURG_ALIASES)


def _title_is_frontend(title: str) -> bool:
    return re.search(r"\b(frontend|front-end|react|next\.?js|angular|wordpress)\b", title, re.I) is not None


def _field_has_explicit_remote(work_mode: str, location: str) -> bool:
    fields = _normalize_text(f"{work_mode} {location}")
    if re.search(r"\b100\s*%\s*remote\b", fields):
        return True
    if re.search(r"\b([1-9]\d?)\s*%\s*remote\b", fields):
        return False
    return any(term in fields for term in ("remote", "distans", "fjarrarbete"))


def _allakonsult_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": SCAN_USER_AGENT,
            "Accept": "application/json",
        }
    )
    return session


def scan_allakonsultuppdrag(
    *,
    page_size: int = 100,
    max_pages: int | None = None,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    source_key = ALLAKONSULT_KEY
    session = _allakonsult_session()
    by_id: dict[str, AssignmentRecord] = {}
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
        return records, PlatformScanResult(source_key=source_key, status="ok", count=len(records))
    except Exception as exc:  # noqa: BLE001
        return list(by_id.values()), PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(by_id),
            message=str(exc),
        )


def _verama_location(city: str | None, country_code: str | None) -> str:
    if city and country_code:
        return f"{city} ({country_code})"
    return city or country_code or ""


def _verama_work_mode(remoteness: Any, explicit_text: str = "") -> str:
    try:
        remote_percent = int(remoteness) if remoteness is not None else None
    except (TypeError, ValueError):
        remote_percent = None

    explicit = _normalize_text(explicit_text)
    if remote_percent == 100:
        return "remote"
    if remote_percent is not None and 0 < remote_percent < 100:
        return f"{remote_percent}% remote"
    if any(term in explicit for term in ("remote", "distans", "fjarrarbete")):
        return "remote"
    if remote_percent == 0:
        return "on-site"
    return ""


def _first_scalar(payload: Any, keys: tuple[str, ...]) -> str:
    if isinstance(payload, dict):
        lowered_keys = {key.lower(): key for key in payload}
        for key in keys:
            actual = lowered_keys.get(key.lower())
            if actual is None:
                continue
            value = payload.get(actual)
            if isinstance(value, (str, int, float)) and str(value).strip():
                return str(value)
        for value in payload.values():
            found = _first_scalar(value, keys)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _first_scalar(item, keys)
            if found:
                return found
    return ""


def _extract_verama_skills(payload: Any) -> list[Any]:
    skills: list[Any] = []

    def visit(value: Any, parent_key: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_lower = key.lower()
                if key_lower in {"skills", "competences", "competencies", "requiredskills"}:
                    visit(child, key_lower)
                elif parent_key in {"skills", "competences", "competencies", "requiredskills"}:
                    visit(child, parent_key)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("title") or item.get("label")
                    if name:
                        skills.append({"name": str(name)})
                    else:
                        visit(item, parent_key)
                elif isinstance(item, str) and item.strip():
                    skills.append(item.strip())

    visit(payload)
    deduped: list[Any] = []
    seen: set[str] = set()
    for item in skills:
        key = str(item.get("name") if isinstance(item, dict) else item)
        normalized = _normalize_text(key)
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(item)
    return deduped


def _verama_detail_needed(
    record: AssignmentRecord,
    *,
    seen_ids: set[str],
    scan_date: date | None,
) -> bool:
    if record.source_id in seen_ids:
        return False
    if _date_before_scan(record.lastApplicationDate, scan_date):
        return False

    title = record.title
    strong_a11y = A11Y_STRONG_TITLE.search(title) is not None
    if VERAMA_CLEARLY_OUTSIDE_TITLE.search(title) and not strong_a11y:
        return False

    location_ok = (
        _field_has_explicit_remote(record.workMode, record.location)
        or _near_stockholm(record.location)
        or (_title_is_frontend(title) and _in_gothenburg(record.location))
    )
    if not location_ok and not strong_a11y:
        return False

    if not record.lastApplicationDate:
        return True
    return VERAMA_TARGET_OR_AMBIGUOUS_TITLE.search(title) is not None


def _merge_verama_detail(record: AssignmentRecord, detail: dict[str, Any]) -> AssignmentRecord:
    description = _first_scalar(
        detail,
        (
            "description",
            "jobDescription",
            "assignmentDescription",
            "roleDescription",
            "descriptionText",
            "publicDescription",
        ),
    )
    summary = _first_scalar(detail, ("descriptionSummary", "summary", "shortDescription"))
    last_application = _first_scalar(
        detail,
        (
            "lastDayOfApplications",
            "lastApplicationDate",
            "applicationDeadline",
            "deadline",
            "applyBy",
        ),
    )
    start_date = _first_scalar(
        detail,
        ("firstDayOfAssignment", "assignmentStartDate", "startDate", "start"),
    )
    end_date = _first_scalar(
        detail,
        ("lastDayOfAssignment", "assignmentEndDate", "endDate", "end"),
    )
    duration = _first_scalar(detail, ("duration", "assignmentPeriod", "period", "extent"))
    explicit_work_mode = _first_scalar(detail, ("workMode", "remoteWork", "remotenessDescription"))

    if not duration and start_date and end_date:
        duration = f"{start_date} - {end_date}"

    return AssignmentRecord(
        listing_id=record.listing_id,
        source_key=record.source_key,
        source_id=record.source_id,
        title=record.title,
        description=description or record.description,
        descriptionSummary=summary or (description[:300] if description else record.descriptionSummary),
        publishedDate=record.publishedDate,
        lastApplicationDate=record.lastApplicationDate or last_application or None,
        startDate=record.startDate or start_date or None,
        endDate=record.endDate or end_date or None,
        duration=record.duration or duration,
        workMode=record.workMode or _verama_work_mode(None, explicit_work_mode),
        location=record.location,
        sourceUrl=record.sourceUrl,
        broker=record.broker,
        skills=_extract_verama_skills(detail) or record.skills,
    )


def scan_verama(
    email: str,
    password: str,
    *,
    page_size: int = 100,
    headless: bool = True,
    seen_ids: set[str] | None = None,
    scan_date: date | None = None,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    source_key = VERAMA_KEY
    seen_ids = seen_ids or set()

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

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context(user_agent=SCAN_USER_AGENT, locale="sv-SE")

            def login_and_capture_headers() -> dict[str, str]:
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
                page.close()

                if not auth_headers:
                    raise RuntimeError("Could not capture Verama auth headers after login")
                return auth_headers

            auth_headers = login_and_capture_headers()
            api = context.request
            page_num = 0
            relogin_used = False
            request_headers = {
                "User-Agent": SCAN_USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Referer": f"{VERAMA_BASE}/app/job-requests",
            }

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
                    headers={**auth_headers, **request_headers},
                    timeout=60000,
                )
                if response.status in {401, 403} and not relogin_used:
                    relogin_used = True
                    auth_headers = login_and_capture_headers()
                    continue
                if response.status != 200:
                    raise RuntimeError(
                        f"Verama job API returned {response.status}: {response.text()[:200]}"
                    )

                payload = response.json()
                rows = payload.get("content") or []
                for row in rows:
                    source_id = str(row["id"])
                    by_id[source_id] = AssignmentRecord(
                        listing_id=f"v{source_id}",
                        source_key=source_key,
                        source_id=source_id,
                        title=row.get("title") or "",
                        descriptionSummary="",
                        publishedDate=row.get("firstDayOfApplications"),
                        lastApplicationDate=row.get("lastDayOfApplications"),
                        workMode=_verama_work_mode(row.get("remoteness")),
                        location=_verama_location(row.get("city"), row.get("countryCode")),
                        sourceUrl=f"{VERAMA_BASE}/app/job-requests/{source_id}",
                        broker=row.get("originServiceName") or "",
                    )

                if payload.get("last") or not rows:
                    break
                page_num += 1

            for source_id, record in list(by_id.items()):
                if not _verama_detail_needed(record, seen_ids=seen_ids, scan_date=scan_date):
                    continue

                detail_payload: dict[str, Any] | None = None
                for detail_url in (
                    f"{VERAMA_BASE}/api/job-requests/v2/{source_id}",
                    f"{VERAMA_BASE}/api/job-requests/{source_id}",
                ):
                    detail_response = api.get(
                        detail_url,
                        headers={**auth_headers, **request_headers},
                        timeout=60000,
                    )
                    if detail_response.status == 200:
                        detail_payload = detail_response.json()
                        break
                    if detail_response.status in {401, 403}:
                        auth_headers = login_and_capture_headers()
                        continue

                if detail_payload:
                    by_id[source_id] = _merge_verama_detail(record, detail_payload)

            browser.close()

        records = list(by_id.values())
        return records, PlatformScanResult(source_key=source_key, status="ok", count=len(records))
    except PlaywrightTimeoutError as exc:
        return list(by_id.values()), PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(by_id),
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return list(by_id.values()), PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(by_id),
            message=str(exc),
        )


PlatformScanner = Callable[..., tuple[list[AssignmentRecord], PlatformScanResult]]

PLATFORM_SCANNERS: dict[str, PlatformScanner] = {
    ALLAKONSULT_KEY: scan_allakonsultuppdrag,
    VERAMA_KEY: scan_verama,
}

DEFAULT_PLATFORMS = [source.key for source in SOURCE_REGISTRY if source.active]
DEFAULT_SOURCES = DEFAULT_PLATFORMS


def scan_platforms(
    platform_ids: list[str],
    *,
    max_pages: int | None = None,
    headless: bool = True,
    seen_by_source: dict[str, set[str]] | None = None,
    scan_date: date | None = None,
) -> tuple[list[AssignmentRecord], list[PlatformScanResult]]:
    assignments: list[AssignmentRecord] = []
    results: list[PlatformScanResult] = []
    seen_by_source = seen_by_source or {}
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

        if platform_id == VERAMA_KEY:
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
                seen_ids=seen_by_source.get(platform_id, set()),
                scan_date=scan_date,
            )
        else:
            rows, result = scanner(max_pages=max_pages)

        if result.status == "ok":
            assignments.extend(rows)
        results.append(result)

    return assignments, results
