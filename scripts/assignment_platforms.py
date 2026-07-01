"""Canonical assignment records and source scanner registry."""

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
    source_key: str


SOURCE_REGISTRY: tuple[SourceConfig, ...] = (
    SourceConfig(prefix="a", source_key="allakonsultuppdrag.se"),
    SourceConfig(prefix="v", source_key="verama.com"),
)
SOURCE_CONFIGS = {source.source_key: source for source in SOURCE_REGISTRY}
SOURCE_PREFIXES = {source.source_key: source.prefix for source in SOURCE_REGISTRY}
SOURCE_KEYS_BY_PREFIX = {source.prefix: source.source_key for source in SOURCE_REGISTRY}


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
        """Backward-compatible alias used by older prompt examples."""
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

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> "AssignmentRecord":
        """Accept current canonical rows and legacy snake_case candidate rows."""
        mapped = dict(row)
        if "source_key" not in mapped and "platform" in mapped:
            mapped["source_key"] = mapped.pop("platform")
        aliases = {
            "description_summary": "descriptionSummary",
            "published_date": "publishedDate",
            "last_application_date": "lastApplicationDate",
            "start_date": "startDate",
            "end_date": "endDate",
            "work_mode": "workMode",
            "source_url": "sourceUrl",
        }
        for old_key, new_key in aliases.items():
            if old_key in mapped and new_key not in mapped:
                mapped[new_key] = mapped.pop(old_key)
        allowed = {field.name for field in cls.__dataclass_fields__.values()}
        return cls(**{key: value for key, value in mapped.items() if key in allowed})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlatformScanResult:
    source_key: str
    status: str
    count: int
    message: str | None = None

    @property
    def platform(self) -> str:
        """Backward-compatible alias."""
        return self.source_key

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "platform": self.source_key,
            "status": self.status,
            "count": self.count,
            "message": self.message,
        }


def _source_prefix(source_key: str) -> str:
    return SOURCE_PREFIXES[source_key]


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
    **_: Any,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    source_key = "allakonsultuppdrag.se"
    prefix = _source_prefix(source_key)
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
                    listing_id=f"{prefix}{source_id}",
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
                by_source_id[source_id] = record

            if not payload.get("hasNextPage"):
                break
            if total_pages is not None and page >= total_pages:
                break
            page += 1

        records = list(by_source_id.values())
        return records, PlatformScanResult(source_key=source_key, status="ok", count=len(records))
    except Exception as exc:  # noqa: BLE001
        return list(by_source_id.values()), PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(by_source_id),
            message=str(exc),
        )


def _verama_location(city: str | None, country_code: str | None) -> str:
    if city and country_code:
        return f"{city} ({country_code})"
    return city or country_code or ""


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _verama_work_mode(row: dict[str, Any]) -> str:
    remoteness = _parse_int(row.get("remoteness"))
    explicit_parts = [
        str(row.get(key) or "")
        for key in ("workMode", "workplaceType", "locationType", "remoteStatus")
    ]
    explicit = " ".join(part for part in explicit_parts if part).strip()
    if remoteness == 100:
        return "remote" if not explicit else f"remote, {explicit}"
    if remoteness is not None and 0 < remoteness < 100:
        return f"hybrid, {remoteness}% remote" if not explicit else f"hybrid, {remoteness}% remote, {explicit}"
    if remoteness == 0:
        return "on-site" if not explicit else explicit
    return explicit


def _first_string(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = _first_string(value, "text", "value", "description", "name")
            if nested:
                return nested
    return ""


def _extract_verama_description(detail: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "description",
        "jobDescription",
        "assignmentDescription",
        "roleDescription",
        "requestDescription",
        "requirements",
        "mustHaves",
        "niceToHaves",
        "scopeDescription",
    ):
        value = detail.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
        elif isinstance(value, dict):
            nested = _first_string(value, "text", "value", "description")
            if nested:
                parts.append(nested)
    return "\n\n".join(dict.fromkeys(parts))


def _normalize_skill_item(item: Any) -> dict[str, str] | None:
    if isinstance(item, str) and item.strip():
        return {"name": item.strip()}
    if isinstance(item, dict):
        for key in ("name", "title", "label", "skill", "competence"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return {"name": value.strip()}
            if isinstance(value, dict):
                nested = _first_string(value, "name", "title", "label")
                if nested:
                    return {"name": nested}
    return None


def _extract_verama_skills(detail: dict[str, Any]) -> list[dict[str, str]]:
    skills: list[dict[str, str]] = []
    for key in ("skills", "competences", "requiredSkills", "wantedSkills", "technologies"):
        value = detail.get(key)
        if isinstance(value, list):
            for item in value:
                normalized = _normalize_skill_item(item)
                if normalized:
                    skills.append(normalized)
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for skill in skills:
        normalized_name = skill["name"].strip().lower()
        if normalized_name not in seen:
            seen.add(normalized_name)
            unique.append(skill)
    return unique


def _date_before_scan(value: str | None, scan_date: date) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return False
    return parsed < scan_date


TARGET_TITLE = re.compile(
    r"\b(accessibility|tillgänglighet|tillganglighet|wcag|frontend|front-end|react|"
    r"next\.?js|angular|wordpress|java|spring|fullstack|full-stack|full stack|ux|ui|"
    r"product designer|interaction design|interaktionsdesign|tjänstedesign|tjanstedesign|"
    r"project manager|projektledare|scrum master|projektkoordinator|project coordinator|"
    r"agile coach|leveransansvarig|developer|utvecklare|consultant|konsult)\b",
    re.I,
)

OUTSIDE_TITLE = re.compile(
    r"\b(sap|network|nätverk|natverk|security operations|soc|cyber|hr|payroll|"
    r"löne|lone|automation engineer|factory|industrial|embedded|fpga|data engineer|"
    r"devops|cloud engineer|mobile developer|ios|android|testare|tester)\b",
    re.I,
)

STRONG_ACCESSIBILITY_TITLE = re.compile(
    r"\b(tillgänglighetsgranskare|tillganglighetsgranskare|"
    r"tillgänglighetsspecialist|tillganglighetsspecialist|accessibility specialist|"
    r"accessibility consultant|wcag specialist|document accessibility|"
    r"dokumenttillgänglighet|dokumenttillganglighet|webbtillgänglighetsspecialist|"
    r"webbtillganglighetsspecialist)\b",
    re.I,
)

NEAR_STOCKHOLM_TEXT = re.compile(
    r"\b(stockholm|solna|sundbyberg|kista|bromma|sollentuna|danderyd|täby|taby|"
    r"järfälla|jarfalla|nacka|huddinge|lidingö|lidingo|älvsjö|alvsjo|årsta|arsta|"
    r"stockholms län|stockholms lan|botkyrka|upplands väsby|upplands vasby|"
    r"södertälje|sodertalje|haninge|tyresö|tyreso|vällingby|vallingby|farsta|"
    r"göteborg|goteborg|gothenburg)\b",
    re.I,
)


def _verama_location_precheck(record: AssignmentRecord) -> bool:
    fields = f"{record.workMode} {record.location}".lower()
    if "remote" in fields or "distans" in fields or "fjärr" in fields or "fjarr" in fields:
        return True
    return bool(NEAR_STOCKHOLM_TEXT.search(record.location))


def _verama_should_fetch_detail(
    record: AssignmentRecord,
    *,
    seen_ids: set[str],
    scan_date: date,
) -> tuple[bool, str | None]:
    if record.source_id in seen_ids:
        return False, "already seen"
    if _date_before_scan(record.lastApplicationDate, scan_date):
        return False, "expired on list row"
    title = record.title or ""
    if OUTSIDE_TITLE.search(title) and not TARGET_TITLE.search(title):
        return False, "title outside target families"
    if not _verama_location_precheck(record) and not STRONG_ACCESSIBILITY_TITLE.search(title):
        return False, "location pre-check failed"
    if not TARGET_TITLE.search(title):
        return False, "title lacks target signal"
    return True, None


def _verama_record_from_list(row: dict[str, Any]) -> AssignmentRecord:
    source_key = "verama.com"
    source_id = str(row["id"])
    return AssignmentRecord(
        listing_id=f"{_source_prefix(source_key)}{source_id}",
        source_key=source_key,
        source_id=source_id,
        title=row.get("title") or "",
        description="",
        descriptionSummary="",
        publishedDate=row.get("firstDayOfApplications"),
        lastApplicationDate=row.get("lastDayOfApplications"),
        workMode=_verama_work_mode(row),
        location=_verama_location(row.get("city"), row.get("countryCode")),
        sourceUrl=f"{VERAMA_BASE}/app/job-requests/{source_id}",
        broker=row.get("originServiceName") or "",
        skills=[],
    )


def _merge_verama_detail(record: AssignmentRecord, detail: dict[str, Any]) -> None:
    description = _extract_verama_description(detail)
    skills = _extract_verama_skills(detail)
    record.description = description
    record.descriptionSummary = _first_string(detail, "descriptionSummary", "summary", "shortDescription") or description[:300]
    record.lastApplicationDate = record.lastApplicationDate or _first_string(
        detail,
        "lastDayOfApplications",
        "applicationDeadline",
        "lastApplicationDate",
        "deadline",
    )
    record.startDate = _first_string(detail, "firstDayOfAssignment", "startDate", "assignmentStartDate")
    record.endDate = _first_string(detail, "lastDayOfAssignment", "endDate", "assignmentEndDate")
    duration = _first_string(detail, "duration", "assignmentPeriod", "period")
    if not duration and (record.startDate or record.endDate):
        duration = " - ".join(part for part in (record.startDate or "", record.endDate or "") if part)
    record.duration = duration
    if skills:
        record.skills = skills
    detail_work_mode = _verama_work_mode(detail)
    if detail_work_mode and detail_work_mode != "on-site":
        record.workMode = ", ".join(dict.fromkeys([record.workMode, detail_work_mode]).keys()).strip(", ")


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

    by_source_id: dict[str, AssignmentRecord] = {}
    detail_fetches = 0
    detail_failures = 0

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context(user_agent=SCAN_USER_AGENT, locale="sv-SE")

            def login_and_capture() -> dict[str, str]:
                page = context.new_page()
                auth_headers: dict[str, str] = {}

                def capture_auth_headers(request) -> None:  # noqa: ANN001
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

            auth_headers = login_and_capture()
            api = context.request

            def api_get(path: str, *, params: dict[str, str] | None = None, relogin: bool = True):  # noqa: ANN202
                nonlocal auth_headers
                response = api.get(
                    f"{VERAMA_BASE}{path}",
                    params=params,
                    headers={
                        **auth_headers,
                        "User-Agent": SCAN_USER_AGENT,
                        "Accept": "application/json, text/plain, */*",
                        "Referer": f"{VERAMA_BASE}/app/job-requests",
                    },
                    timeout=60000,
                )
                if response.status in {401, 403} and relogin:
                    auth_headers = login_and_capture()
                    return api_get(path, params=params, relogin=False)
                return response

            page_num = 0
            while True:
                response = api_get(
                    "/api/job-requests/v2",
                    params={
                        "page": str(page_num),
                        "size": str(page_size),
                        "query": "",
                        "dedicated": "false",
                        "favouritesOnly": "false",
                        "recommendedOnly": "false",
                        "sort": "firstDayOfApplications,DESC",
                    },
                )
                if response.status != 200:
                    raise RuntimeError(
                        f"Verama job API returned {response.status}: {response.text()[:200]}"
                    )

                payload = response.json()
                rows = payload.get("content") or []
                for row in rows:
                    record = _verama_record_from_list(row)
                    should_fetch, _reason = _verama_should_fetch_detail(
                        record,
                        seen_ids=seen_ids,
                        scan_date=scan_date,
                    )
                    if should_fetch:
                        detail_response = api_get(f"/api/job-requests/v2/{record.source_id}")
                        if detail_response.status == 404:
                            detail_response = api_get(f"/api/job-requests/{record.source_id}")
                        if detail_response.status == 200:
                            detail_fetches += 1
                            _merge_verama_detail(record, detail_response.json())
                        else:
                            detail_failures += 1
                    by_source_id[record.source_id] = record

                if payload.get("last") or not rows:
                    break
                page_num += 1

            browser.close()

        message = None
        if detail_failures:
            message = f"{detail_fetches} detail fetches, {detail_failures} detail failures"
        elif detail_fetches:
            message = f"{detail_fetches} conditional detail fetches"
        return list(by_source_id.values()), PlatformScanResult(
            source_key=source_key,
            status="ok",
            count=len(by_source_id),
            message=message,
        )
    except PlaywrightTimeoutError as exc:
        return list(by_source_id.values()), PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(by_source_id),
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return list(by_source_id.values()), PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(by_source_id),
            message=str(exc),
        )


PlatformScanner = Callable[..., tuple[list[AssignmentRecord], PlatformScanResult]]

PLATFORM_SCANNERS: dict[str, PlatformScanner] = {
    "allakonsultuppdrag.se": scan_allakonsultuppdrag,
    "verama.com": scan_verama,
}

DEFAULT_PLATFORMS = [source.source_key for source in SOURCE_REGISTRY]


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
    seen_ids_by_source = seen_ids_by_source or {}

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
            rows, result = scanner(
                max_pages=max_pages,
                seen_ids=seen_ids_by_source.get(platform_id, set()),
                scan_date=scan_date,
            )

        assignments.extend(rows)
        results.append(result)

    return assignments, results
