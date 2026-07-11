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
ALLAKONSULT_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"
SCAN_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"


@dataclass(frozen=True)
class SourceDefinition:
    prefix: str
    source_key: str


SOURCE_REGISTRY: dict[str, SourceDefinition] = {
    "allakonsultuppdrag.se": SourceDefinition(
        prefix="a",
        source_key="allakonsultuppdrag.se",
    ),
    "verama.com": SourceDefinition(prefix="v", source_key="verama.com"),
}

SOURCE_ORDER = list(SOURCE_REGISTRY.keys())


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
    skills: list[dict[str, Any] | str] = field(default_factory=list)

    @property
    def dedupe_key(self) -> str:
        return f"{self.source_key}:{self.source_id}"

    @property
    def platform(self) -> str:
        """Backward-compatible alias used by older scripts and curated JSON."""
        return self.source_key

    def to_dict(self) -> dict[str, Any]:
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
        }

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "AssignmentRecord":
        """Accept canonical JSON plus the previous snake_case helper shape."""
        return cls(
            source_key=row.get("source_key") or row.get("platform") or "",
            source_id=str(row.get("source_id") or ""),
            listing_id=str(row.get("listing_id") or ""),
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
        )


@dataclass
class PlatformScanResult:
    source_key: str
    status: str
    count: int
    message: str | None = None

    @property
    def platform(self) -> str:
        """Backward-compatible alias for older debug output."""
        return self.source_key

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "status": self.status,
            "count": self.count,
            "message": self.message,
        }


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
    source_key = "allakonsultuppdrag.se"
    prefix = SOURCE_REGISTRY[source_key].prefix
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
                    source_key=source_key,
                    source_id=source_id,
                    listing_id=f"{prefix}{source_id}",
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
                by_key[source_id] = record

            if not payload.get("hasNextPage"):
                break
            if total_pages is not None and page >= total_pages:
                break
            page += 1

        records = list(by_key.values())
        return records, PlatformScanResult(source_key=source_key, status="ok", count=len(records))
    except Exception as exc:  # noqa: BLE001
        return list(by_key.values()), PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(by_key),
            message=str(exc),
        )


def _verama_location(city: str | None, country_code: str | None) -> str:
    if city and country_code:
        return f"{city} ({country_code})"
    return city or country_code or ""


class VeramaAuthExpired(RuntimeError):
    """Raised when captured browser session headers stop authorizing API calls."""


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _plain_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return re.sub(r"<[^>]+>", " ", value)
    if isinstance(value, dict):
        parts: list[str] = []
        for key in (
            "text",
            "value",
            "description",
            "jobDescription",
            "requirements",
            "content",
            "html",
        ):
            if key in value:
                parts.append(_plain_text(value[key]))
        return " ".join(part for part in parts if part)
    if isinstance(value, list):
        return " ".join(_plain_text(item) for item in value)
    return str(value)


def _first_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        text = _plain_text(value).strip()
        if text:
            return re.sub(r"\s+", " ", text)
    return ""


def _first_value(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value:
            return str(value)
    return None


def _verama_work_mode(remoteness: Any, detail: dict[str, Any] | None = None) -> str:
    try:
        remote_percent = int(remoteness)
    except (TypeError, ValueError):
        remote_percent = None

    explicit = ""
    if detail:
        explicit = _first_text(
            detail,
            "workMode",
            "workingMode",
            "remoteWork",
            "locationDescription",
        )
    normalized_explicit = explicit.lower()
    if remote_percent == 100 or re.search(
        r"\b(remote|distans|fjärrarbete|fjarrarbete)\b",
        normalized_explicit,
    ):
        if remote_percent and remote_percent not in (0, 100):
            return f"hybrid ({remote_percent}% remote)"
        return "remote"
    if remote_percent is not None and 0 < remote_percent < 100:
        return f"hybrid ({remote_percent}% remote)"
    if remote_percent == 0:
        return "on-site"
    return explicit


def _verama_skills(detail: dict[str, Any]) -> list[dict[str, str] | str]:
    raw_skills = (
        detail.get("skills")
        or detail.get("competences")
        or detail.get("requiredSkills")
        or detail.get("technologies")
        or []
    )
    if not isinstance(raw_skills, list):
        return []

    skills: list[dict[str, str] | str] = []
    for item in raw_skills:
        if isinstance(item, str):
            skills.append(item)
            continue
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("label") or item.get("title")
        if isinstance(name, dict):
            name = name.get("sv") or name.get("en") or next(iter(name.values()), "")
        if name:
            skills.append({"name": str(name)})
    return skills


def _verama_title_clearly_outside(title: str) -> bool:
    lowered = title.lower()
    outside = re.compile(
        r"\b(sap|network|nätverk|security operations|soc|hr|payroll|lön|"
        r"automation engineer|factory|produktion|embedded|fpga|android|ios|"
        r"data engineer|data scientist|devops|cloud architect|infrastructure)\b",
        re.I,
    )
    target_signal = re.compile(
        r"\b(accessibility|tillgänglighet|tillganglighet|react|next|frontend|"
        r"front-end|angular|wordpress|java|spring|fullstack|full-stack|ux|ui|"
        r"designer|projektledare|project manager|scrum master|koordinator)\b",
        re.I,
    )
    return bool(outside.search(lowered)) and not bool(target_signal.search(lowered))


def _verama_strong_accessibility_title(title: str) -> bool:
    return bool(
        re.search(
            r"tillgänglighetsgransk|tillganglighetsgransk|"
            r"tillgänglighetsspecialist|tillganglighetsspecialist|"
            r"accessibility specialist|accessibility consultant|wcag specialist",
            title,
            re.I,
        )
    )


def _verama_location_precheck(record: AssignmentRecord) -> bool:
    text = f"{record.work_mode} {record.location}".lower()
    if re.search(r"\b100\s*%\s*remote\b", text):
        return True
    text_without_partial_remote = re.sub(r"\b[1-9]\d?\s*%\s*remote\b", "", text)
    if re.search(r"\b(remote|distans|fjärrarbete|fjarrarbete)\b", text_without_partial_remote):
        return True
    return bool(
        re.search(
            r"stockholm|solna|sundbyberg|kista|bromma|sollentuna|danderyd|"
            r"täby|taby|järfälla|jarfalla|nacka|huddinge|lidingö|lidingo|"
            r"älvsjö|alvsjo|årsta|arsta|stockholms län|stockholms lan|"
            r"botkyrka|upplands väsby|upplands vasby|södertälje|sodertalje|"
            r"haninge|tyresö|tyreso|vällingby|vallingby|farsta|göteborg|goteborg|gothenburg",
            text,
            re.I,
        )
    )


def _verama_should_fetch_detail(
    record: AssignmentRecord,
    *,
    seen_ids: set[str],
    scan_date: date,
) -> bool:
    if record.source_id in seen_ids:
        return False

    deadline = _parse_date(record.last_application_date)
    if deadline and deadline < scan_date:
        return False

    if _verama_title_clearly_outside(record.title):
        return False

    if not _verama_location_precheck(record) and not _verama_strong_accessibility_title(
        record.title
    ):
        return False

    return True


def _verama_record_from_row(row: dict[str, Any]) -> AssignmentRecord:
    source_key = "verama.com"
    source_id = str(row["id"])
    remoteness = row.get("remoteness")
    return AssignmentRecord(
        source_key=source_key,
        source_id=source_id,
        listing_id=f"{SOURCE_REGISTRY[source_key].prefix}{source_id}",
        title=row.get("title") or "",
        published_date=row.get("firstDayOfApplications"),
        last_application_date=row.get("lastDayOfApplications")
        or row.get("lastApplicationDate"),
        work_mode=_verama_work_mode(remoteness),
        location=_verama_location(row.get("city"), row.get("countryCode")),
        source_url=f"{VERAMA_BASE}/app/job-requests/{source_id}",
        broker=row.get("originServiceName") or "",
    )


def _merge_verama_detail(
    record: AssignmentRecord,
    detail: dict[str, Any],
    *,
    remoteness: Any,
) -> AssignmentRecord:
    description = _first_text(
        detail,
        "description",
        "jobDescription",
        "assignmentDescription",
        "descriptionHtml",
        "requirements",
    )
    summary = _first_text(detail, "descriptionSummary", "summary", "shortDescription")
    start_date = _first_value(
        detail,
        "firstDayOfAssignment",
        "assignmentStartDate",
        "startDate",
    )
    end_date = _first_value(
        detail,
        "lastDayOfAssignment",
        "assignmentEndDate",
        "endDate",
    )
    duration = _first_text(detail, "duration", "assignmentDuration", "period")
    if not duration and (start_date or end_date):
        duration = " - ".join(part for part in (start_date, end_date) if part)

    return AssignmentRecord(
        source_key=record.source_key,
        source_id=record.source_id,
        listing_id=record.listing_id,
        title=record.title,
        description=description,
        description_summary=summary or description[:300],
        published_date=record.published_date
        or _first_value(detail, "firstDayOfApplications", "publishedDate"),
        last_application_date=record.last_application_date
        or _first_value(
            detail,
            "lastDayOfApplications",
            "lastApplicationDate",
            "applicationDeadline",
            "applicationDueDate",
            "lastDateOfApplication",
        ),
        start_date=start_date,
        end_date=end_date,
        duration=duration,
        work_mode=_verama_work_mode(remoteness, detail) or record.work_mode,
        location=record.location,
        source_url=record.source_url,
        broker=record.broker,
        skills=_verama_skills(detail),
    )


def scan_verama(
    email: str,
    password: str,
    *,
    seen_ids: set[str] | None = None,
    scan_date: date | None = None,
    page_size: int = 100,
    headless: bool = True,
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

    def run_scan() -> list[AssignmentRecord]:
        by_source_id: dict[str, AssignmentRecord] = {}

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

            def api_get(path: str, *, params: dict[str, str] | None = None):
                response = api.get(
                    f"{VERAMA_BASE}{path}",
                    params=params,
                    headers={
                        **auth_headers,
                        "accept": "application/json, text/plain, */*",
                        "referer": f"{VERAMA_BASE}/app/job-requests",
                        "user-agent": SCAN_USER_AGENT,
                    },
                    timeout=60000,
                )
                if response.status in {401, 403}:
                    raise VeramaAuthExpired(
                        f"Verama API returned {response.status} for {path}"
                    )
                return response

            def fetch_detail(source_id: str) -> dict[str, Any]:
                for path in (
                    f"/api/job-requests/v2/{source_id}",
                    f"/api/job-requests/{source_id}",
                ):
                    response = api_get(path)
                    if response.status == 200:
                        return response.json()
                return {}

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
                    record = _verama_record_from_row(row)
                    if _verama_should_fetch_detail(
                        record,
                        seen_ids=seen_ids,
                        scan_date=scan_date,
                    ):
                        detail = fetch_detail(record.source_id)
                        if detail:
                            record = _merge_verama_detail(
                                record,
                                detail,
                                remoteness=row.get("remoteness"),
                            )
                    by_source_id[record.source_id] = record

                if payload.get("last") or not rows:
                    break
                page_num += 1

            browser.close()
            return list(by_source_id.values())

    try:
        try:
            records = run_scan()
        except VeramaAuthExpired:
            records = run_scan()

        return records, PlatformScanResult(source_key=source_key, status="ok", count=len(records))
    except PlaywrightTimeoutError as exc:
        return [], PlatformScanResult(
            source_key=source_key,
            status="error",
            count=0,
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return [], PlatformScanResult(
            source_key=source_key,
            status="error",
            count=0,
            message=str(exc),
        )


PlatformScanner = Callable[..., tuple[list[AssignmentRecord], PlatformScanResult]]

PLATFORM_SCANNERS: dict[str, PlatformScanner] = {
    "allakonsultuppdrag.se": scan_allakonsultuppdrag,
    "verama.com": scan_verama,
}

DEFAULT_SOURCES = list(PLATFORM_SCANNERS.keys())
DEFAULT_PLATFORMS = DEFAULT_SOURCES


def scan_platforms(
    platform_ids: list[str],
    *,
    seen_ids_by_source: dict[str, set[str]] | None = None,
    scan_date: date | None = None,
    max_pages: int | None = None,
    headless: bool = True,
) -> tuple[list[AssignmentRecord], list[PlatformScanResult]]:
    assignments: list[AssignmentRecord] = []
    results: list[PlatformScanResult] = []
    seen_ids_by_source = seen_ids_by_source or {}
    scan_date = scan_date or date.today()
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
                    message=f"Unknown platform: {platform_id}",
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
                seen_ids=seen_ids_by_source.get(platform_id, set()),
                scan_date=scan_date,
                headless=headless,
            )
        else:
            rows, result = scanner(max_pages=max_pages)

        assignments.extend(rows)
        results.append(result)

    return assignments, results
