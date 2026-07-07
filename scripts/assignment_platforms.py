"""Canonical assignment records and source scanner registry."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable

import requests

ALLAKONSULT_BASE = "https://allakonsultuppdrag.se"
VERAMA_BASE = "https://app.verama.com"
SCAN_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"


@dataclass(frozen=True)
class SourceConfig:
    key: str
    prefix: str
    status: str = "active"


SOURCE_REGISTRY: dict[str, SourceConfig] = {
    "allakonsultuppdrag.se": SourceConfig(key="allakonsultuppdrag.se", prefix="a"),
    "verama.com": SourceConfig(key="verama.com", prefix="v"),
}

DEFAULT_SOURCES = [
    source.key for source in SOURCE_REGISTRY.values() if source.status == "active"
]
DEFAULT_PLATFORMS = DEFAULT_SOURCES


@dataclass
class AssignmentRecord:
    source_key: str
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
    skills: list[Any] = field(default_factory=list)
    detail_fetched: bool = False

    @property
    def platform(self) -> str:
        """Backward-compatible alias for older scripts."""
        return self.source_key

    @property
    def dedupe_key(self) -> str:
        return f"{self.source_key}:{self.source_id}"

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "AssignmentRecord":
        """Accept both canonical JSON field names and legacy snake_case rows."""
        source_key = row.get("source_key") or row.get("platform") or row.get("sourceKey")
        if not source_key:
            raise ValueError(f"Assignment row is missing source_key: {row!r}")
        return cls(
            source_key=str(source_key),
            source_id=str(row.get("source_id") or row.get("sourceId") or ""),
            listing_id=str(row.get("listing_id") or row.get("listingId") or ""),
            title=row.get("title") or "",
            description=row.get("description") or "",
            description_summary=row.get("descriptionSummary")
            or row.get("description_summary")
            or "",
            published_date=row.get("publishedDate") or row.get("published_date"),
            last_application_date=row.get("lastApplicationDate")
            or row.get("last_application_date"),
            start_date=row.get("startDate") or row.get("start_date"),
            end_date=row.get("endDate") or row.get("end_date"),
            duration=row.get("duration") or "",
            work_mode=row.get("workMode") or row.get("work_mode") or "",
            location=row.get("location") or "",
            source_url=row.get("sourceUrl") or row.get("source_url") or "",
            broker=row.get("broker") or "",
            skills=row.get("skills") or [],
            detail_fetched=bool(row.get("detailFetched") or row.get("detail_fetched")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Emit the canonical assignment record shape consumed downstream."""
        return {
            "listing_id": self.listing_id,
            "source_key": self.source_key,
            "source_id": self.source_id,
            "title": self.title,
            "description": self.description,
            "descriptionSummary": self.description_summary,
            "publishedDate": self.published_date,
            "lastApplicationDate": self.last_application_date,
            "startDate": self.start_date,
            "endDate": self.end_date,
            "duration": self.duration,
            "workMode": self.work_mode,
            "location": self.location,
            "sourceUrl": self.source_url,
            "broker": self.broker,
            "skills": self.skills,
            "detailFetched": self.detail_fetched,
        }


@dataclass
class PlatformScanResult:
    platform: str
    status: str
    count: int
    message: str | None = None
    total_unique_visible: int | None = None

    @property
    def source_key(self) -> str:
        return self.platform


def source_prefix(source_key: str) -> str:
    return SOURCE_REGISTRY[source_key].prefix


def listing_id_for(source_key: str, source_id: str) -> str:
    return f"{source_prefix(source_key)}{source_id}"


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _first_text(payload: dict[str, Any], names: tuple[str, ...]) -> str:
    for name in names:
        value = payload.get(name)
        text = _as_text(value).strip()
        if text:
            return text
    return ""


def _first_value(payload: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = payload.get(name)
        if value not in (None, ""):
            return value
    return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _normalize_text(value: str) -> str:
    return value.casefold()


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
    by_source_id: dict[str, AssignmentRecord] = {}
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
                    source_key=source_key,
                    source_id=source_id,
                    listing_id=listing_id_for(source_key, source_id),
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
                    detail_fetched=True,
                )
                by_source_id[source_id] = record

            if not payload.get("hasNextPage"):
                break
            if total_pages is not None and page >= total_pages:
                break
            page += 1

        records = list(by_source_id.values())
        return records, PlatformScanResult(
            platform=source_key,
            status="ok",
            count=len(records),
            total_unique_visible=len(records),
        )
    except Exception as exc:  # noqa: BLE001
        return list(by_source_id.values()), PlatformScanResult(
            platform=source_key,
            status="error",
            count=len(by_source_id),
            message=str(exc),
            total_unique_visible=len(by_source_id),
        )


def _verama_location(city: str | None, country_code: str | None) -> str:
    if city and country_code:
        return f"{city} ({country_code})"
    return city or country_code or ""


def _verama_work_mode(remoteness: Any, *extra_fields: str) -> str:
    parts: list[str] = []
    if remoteness is not None:
        try:
            remote_percentage = int(remoteness)
        except (TypeError, ValueError):
            remote_percentage = None
        if remote_percentage == 100:
            parts.append("remote")
        elif remote_percentage is not None:
            parts.append(f"{remote_percentage}% remote")
    for field_value in extra_fields:
        value = field_value.strip()
        if value and value not in parts:
            parts.append(value)
    return " | ".join(parts)


TARGET_TITLE_TERMS = re.compile(
    r"\b(accessibility|tillgänglighet|tillganglighet|wcag|frontend|front-end|"
    r"react|next\.?js|angular|wordpress|java|javautvecklare|spring|backend|"
    r"systemutvecklare|"
    r"fullstack|full-stack|ux|ui|product designer|produktdesigner|"
    r"interaction designer|interaktionsdesigner|tjänstedesign|tjanstedesign|"
    r"projektledare|project manager|scrum master|agile coach|"
    r"project coordinator|projektkoordinator|developer|utvecklare|consultant|konsult)\b",
    re.I,
)

OUTSIDE_TITLE_TERMS = re.compile(
    r"\b(sap|network|nätverk|natverk|soc|security operations|payroll|hr\b|"
    r"automation engineer|factory|plc|testare|tester|embedded|fpga|"
    r"data engineer|data analyst|business analyst|analytiker)\b",
    re.I,
)

A11Y_STRONG_TITLE_TERMS = re.compile(
    r"\b(tillgänglighetsgranskare|tillganglighetsgranskare|"
    r"tilgjengelighetsgranskning|tilgjengelighetsgranskere|"
    r"tillgänglighetsspecialist|tillganglighetsspecialist|"
    r"accessibility specialist|accessibility consultant|wcag specialist|"
    r"document accessibility|dokumenttillgänglighet|dokumenttillganglighet|"
    r"webbtillgänglighetsspecialist|webbtillganglighetsspecialist)\b",
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


def _verama_title_needs_detail(title: str) -> bool:
    normalized = _normalize_text(title)
    if A11Y_STRONG_TITLE_TERMS.search(normalized):
        return True
    if OUTSIDE_TITLE_TERMS.search(normalized) and not TARGET_TITLE_TERMS.search(normalized):
        return False
    return TARGET_TITLE_TERMS.search(normalized) is not None


def _location_prefilter_passes(record: AssignmentRecord) -> bool:
    fields = _normalize_text(f"{record.work_mode} {record.location}")
    title = _normalize_text(record.title)
    if A11Y_STRONG_TITLE_TERMS.search(title):
        return True
    if any(term in fields for term in ("remote", "distans", "fjärrarbete", "fjarrarbete")):
        if not re.search(r"\b(0|25|50|75)% remote\b", fields):
            return True
    if any(term in fields for term in NEAR_STOCKHOLM_TERMS):
        return True
    if re.search(r"\b(frontend|front-end|react|angular|wordpress)\b", title):
        return any(term in fields for term in ("gothenburg", "göteborg", "goteborg"))
    return False


def _should_fetch_verama_detail(
    record: AssignmentRecord,
    *,
    seen_ids: set[str],
    scan_date: date,
) -> bool:
    if record.source_id in seen_ids:
        return False
    deadline = _parse_date(record.last_application_date)
    if deadline is not None and deadline < scan_date:
        return False
    plausible_title = _verama_title_needs_detail(record.title)
    if not plausible_title:
        return False
    if not _location_prefilter_passes(record):
        return False
    if deadline is None:
        return True
    return True


def _normalize_skills(value: Any) -> list[Any]:
    if not value:
        return []
    if isinstance(value, list):
        normalized: list[Any] = []
        for item in value:
            if isinstance(item, dict):
                nested_skill = item.get("skill") if isinstance(item.get("skill"), dict) else {}
                name = (
                    item.get("name")
                    or item.get("label")
                    or item.get("title")
                    or nested_skill.get("name")
                )
                normalized.append({"name": str(name)} if name else item)
            elif isinstance(item, str):
                normalized.append(item)
        return normalized
    return []


def _merge_verama_detail(record: AssignmentRecord, detail: dict[str, Any]) -> AssignmentRecord:
    description = _first_text(
        detail,
        (
            "description",
            "jobDescription",
            "assignmentDescription",
            "requestDescription",
            "projectDescription",
            "workDescription",
        ),
    )
    summary = _first_text(
        detail,
        ("descriptionSummary", "summary", "shortDescription", "ingress"),
    )
    deadline = _first_value(
        detail,
        (
            "lastDayOfApplications",
            "lastApplicationDate",
            "applicationDeadline",
            "deadline",
            "applyBefore",
        ),
    )
    start_date = _first_value(
        detail,
        ("firstDayOfAssignment", "startDate", "assignmentStartDate", "startsAt"),
    )
    end_date = _first_value(
        detail,
        ("lastDayOfAssignment", "endDate", "assignmentEndDate", "endsAt"),
    )
    duration = _first_text(detail, ("duration", "assignmentPeriod", "period"))
    if not duration and start_date and end_date:
        duration = f"{start_date} - {end_date}"
    skills = _normalize_skills(
        _first_value(detail, ("skills", "competences", "competencies", "requirements"))
    )
    extra_work_mode = _first_text(detail, ("workMode", "locationType", "remotePolicy"))
    detail_remoteness = _first_value(detail, ("remoteness", "remotePercentage"))
    work_mode = record.work_mode
    if detail_remoteness is not None or extra_work_mode:
        work_mode = _verama_work_mode(detail_remoteness, extra_work_mode) or record.work_mode

    return AssignmentRecord(
        source_key=record.source_key,
        source_id=record.source_id,
        listing_id=record.listing_id,
        title=record.title,
        description=description or record.description,
        description_summary=summary or record.description_summary,
        published_date=record.published_date,
        last_application_date=str(deadline) if deadline else record.last_application_date,
        start_date=str(start_date) if start_date else record.start_date,
        end_date=str(end_date) if end_date else record.end_date,
        duration=duration or record.duration,
        work_mode=work_mode,
        location=record.location,
        source_url=record.source_url,
        broker=record.broker,
        skills=skills or record.skills,
        detail_fetched=True,
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
            platform=source_key,
            status="error",
            count=0,
            message="playwright is not installed; run pip install -r requirements.txt",
            total_unique_visible=0,
        )

    records_by_id: dict[str, AssignmentRecord] = {}

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

            def login_and_capture_headers() -> None:
                auth_headers.clear()
                page.on("request", capture_auth_headers)
                page.goto(f"{VERAMA_BASE}/sv/login", wait_until="domcontentloaded", timeout=60000)
                page.locator('input[type="email"], input[name="email"]').first.fill(email)
                page.locator('input[type="password"]').first.fill(password)
                page.locator(
                    'button[type="submit"], button:has-text("Logga in"), '
                    'button:has-text("Log in")'
                ).first.click()
                page.wait_for_timeout(8000)
                page.goto(f"{VERAMA_BASE}/app/job-requests", wait_until="networkidle", timeout=90000)
                page.wait_for_timeout(3000)
                if not auth_headers:
                    raise RuntimeError("Could not capture Verama auth headers after login")

            def api_headers() -> dict[str, str]:
                return {
                    **auth_headers,
                    "User-Agent": SCAN_USER_AGENT,
                    "accept": "application/json, text/plain, */*",
                    "referer": f"{VERAMA_BASE}/app/job-requests",
                }

            login_and_capture_headers()
            api = context.request
            page_num = 0
            retried_auth = False

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
                if response.status in (401, 403) and not retried_auth:
                    retried_auth = True
                    login_and_capture_headers()
                    continue
                if response.status != 200:
                    raise RuntimeError(
                        f"Verama job API returned {response.status}: {response.text()[:200]}"
                    )

                payload = response.json()
                rows = payload.get("content") or []
                for row in rows:
                    source_id = str(row["id"])
                    remoteness = row.get("remoteness")
                    record = AssignmentRecord(
                        source_key=source_key,
                        source_id=source_id,
                        listing_id=listing_id_for(source_key, source_id),
                        title=row.get("title") or "",
                        description="",
                        description_summary="",
                        published_date=row.get("firstDayOfApplications"),
                        last_application_date=row.get("lastDayOfApplications"),
                        work_mode=_verama_work_mode(remoteness),
                        location=_verama_location(row.get("city"), row.get("countryCode")),
                        source_url=f"{VERAMA_BASE}/app/job-requests/{source_id}",
                        broker=row.get("originServiceName") or "",
                        skills=[],
                    )

                    if _should_fetch_verama_detail(
                        record,
                        seen_ids=seen_ids,
                        scan_date=scan_date,
                    ):
                        detail_response = api.get(
                            f"{VERAMA_BASE}/api/job-requests/v2/{source_id}",
                            headers=api_headers(),
                            timeout=60000,
                        )
                        if detail_response.status == 404:
                            detail_response = api.get(
                                f"{VERAMA_BASE}/api/job-requests/{source_id}",
                                headers=api_headers(),
                                timeout=60000,
                            )
                        if detail_response.status == 200:
                            record = _merge_verama_detail(record, detail_response.json())

                    records_by_id[source_id] = record

                if payload.get("last") or not rows:
                    break
                page_num += 1

            browser.close()

        records = list(records_by_id.values())
        return records, PlatformScanResult(
            platform=source_key,
            status="ok",
            count=len(records),
            total_unique_visible=len(records),
        )
    except PlaywrightTimeoutError as exc:
        return list(records_by_id.values()), PlatformScanResult(
            platform=source_key,
            status="error",
            count=len(records_by_id),
            message=f"Verama login or listing timed out: {exc}",
            total_unique_visible=len(records_by_id),
        )
    except Exception as exc:  # noqa: BLE001
        return list(records_by_id.values()), PlatformScanResult(
            platform=source_key,
            status="error",
            count=len(records_by_id),
            message=str(exc),
            total_unique_visible=len(records_by_id),
        )


PlatformScanner = Callable[..., tuple[list[AssignmentRecord], PlatformScanResult]]

PLATFORM_SCANNERS: dict[str, PlatformScanner] = {
    "allakonsultuppdrag.se": scan_allakonsultuppdrag,
    "verama.com": scan_verama,
}


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
    verama_email = os.environ.get("VERAMA_EMAIL")
    verama_password = os.environ.get("VERAMA_PASSWORD")
    seen_by_source = seen_by_source or {}
    scan_date = scan_date or date.today()

    for platform_id in platform_ids:
        scanner = PLATFORM_SCANNERS.get(platform_id)
        if scanner is None:
            results.append(
                PlatformScanResult(
                    platform=platform_id,
                    status="error",
                    count=0,
                    message=f"Unknown source: {platform_id}",
                    total_unique_visible=0,
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
                        total_unique_visible=0,
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

        assignments.extend(rows)
        results.append(result)

    return assignments, results
