"""Canonical assignment records and source scanner registry."""

from __future__ import annotations

import html
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Callable
from urllib.parse import urljoin

import requests

ALLAKONSULT_BASE = "https://allakonsultuppdrag.se"
VERAMA_BASE = "https://app.verama.com"
CHAS_BASE = "https://chaspartnernetwork.se"
ALLAKONSULT_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"
SCAN_USER_AGENT = "Mozilla/5.0 (compatible; AxessLabAssignmentScanner/1.0)"


@dataclass(frozen=True)
class SourceConfig:
    source_key: str
    prefix: str
    active: bool = True


SOURCE_REGISTRY: tuple[SourceConfig, ...] = (
    SourceConfig("allakonsultuppdrag.se", "a"),
    SourceConfig("verama.com", "v"),
    SourceConfig("chaspartnernetwork.se", "c"),
)

SOURCE_PREFIXES = {source.source_key: source.prefix for source in SOURCE_REGISTRY}
SOURCE_ORDER = {source.source_key: index for index, source in enumerate(SOURCE_REGISTRY)}
CROSS_SOURCE_PREFERENCE = {
    "verama.com": 0,
    "allakonsultuppdrag.se": 1,
    "chaspartnernetwork.se": 2,
}


@dataclass
class AssignmentRecord:
    source_key: str
    source_id: str
    listing_id: str
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
    def platform(self) -> str:
        """Backward-compatible alias used by older scripts/prompts."""
        return self.source_key

    @property
    def dedupe_key(self) -> str:
        return f"{self.source_key}:{self.source_id}"

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

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "AssignmentRecord":
        data = dict(row)
        if "source_key" not in data and "platform" in data:
            data["source_key"] = data.pop("platform")
        aliases = {
            "description_summary": "descriptionSummary",
            "published_date": "publishedDate",
            "last_application_date": "lastApplicationDate",
            "start_date": "startDate",
            "end_date": "endDate",
            "work_mode": "workMode",
            "source_url": "sourceUrl",
        }
        for old, new in aliases.items():
            if old in data and new not in data:
                data[new] = data.pop(old)
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in data.items() if key in allowed})


@dataclass
class PlatformScanResult:
    source_key: str
    status: str
    count: int
    message: str | None = None

    @property
    def platform(self) -> str:
        return self.source_key


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
    **_: Any,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    source_key = "allakonsultuppdrag.se"
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
                    listing_id=f"{SOURCE_PREFIXES[source_key]}{source_id}",
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


def _normalize_text(value: str) -> str:
    return " ".join(html.unescape(value or "").lower().split())


def _parse_api_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _verama_work_mode(row: dict[str, Any]) -> str:
    remoteness = row.get("remoteness")
    if remoteness is None:
        return ""
    try:
        numeric = int(remoteness)
    except (TypeError, ValueError):
        return f"{remoteness}% remote"
    if numeric == 100:
        return "remote"
    if numeric > 0:
        return f"{numeric}% remote"
    return "on-site"


def _verama_title_is_clearly_outside(title: str) -> bool:
    text = _normalize_text(title)
    outside = re.compile(
        r"\b(sap|network|nätverk|natverk|security operations|soc|hr|payroll|lön|lon|"
        r"automation engineer|factory|produktion|embedded|fpga|test engineer|"
        r"data engineer|dataingenjor|dataingenjör|devops|cloud architect|"
        r"solution architect|business analyst)\b"
    )
    target = re.compile(
        r"\b(accessibility|tillgänglighet|tillganglighet|wcag|react|next|frontend|"
        r"front-end|angular|wordpress|java|spring|fullstack|ux|ui|designer|"
        r"projektledare|project manager|scrum master|agile coach|koordinator)\b"
    )
    return bool(outside.search(text)) and not bool(target.search(text))


def _verama_location_precheck_passes(record: AssignmentRecord) -> bool:
    fields = _normalize_text(f"{record.workMode} {record.location}")
    percent_remote = re.search(r"\b(\d{1,3})\s*%\s*remote\b", fields)
    if percent_remote and int(percent_remote.group(1)) >= 100:
        return True
    if not percent_remote and any(
        term in fields for term in ("remote", "distans", "fjarrarbete", "fjärrarbete")
    ):
        return True
    near_stockholm = (
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
    if any(place in fields for place in near_stockholm):
        return True
    title = _normalize_text(record.title)
    return bool(re.search(r"\b(accessibility|tillgänglighet|tillganglighet|wcag)\b", title))


def _first_value(payload: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = payload.get(name)
        if value not in (None, "", []):
            return value
    return None


def _verama_summary(description: str) -> str:
    compact = " ".join(html.unescape(description or "").split())
    return compact[:300]


def _merge_verama_detail(record: AssignmentRecord, detail: dict[str, Any]) -> AssignmentRecord:
    description = _first_value(
        detail,
        (
            "description",
            "jobDescription",
            "assignmentDescription",
            "requestDescription",
            "roleDescription",
        ),
    )
    skills = _first_value(detail, ("skills", "competences", "requiredSkills", "requiredCompetences"))
    start_date = _first_value(detail, ("firstDayOfAssignment", "startDate", "assignmentStartDate"))
    end_date = _first_value(detail, ("lastDayOfAssignment", "endDate", "assignmentEndDate"))
    deadline = _first_value(
        detail,
        (
            "lastDayOfApplications",
            "lastApplicationDate",
            "applicationDeadline",
            "deadline",
        ),
    )
    duration = _first_value(detail, ("duration", "period", "assignmentPeriod", "extent"))
    explicit_remote = _first_value(detail, ("workMode", "locationType", "remoteDescription"))
    work_mode = record.workMode
    if explicit_remote:
        explicit_text = _normalize_text(str(explicit_remote))
        if any(term in explicit_text for term in ("distans", "remote", "fjärr", "fjarr")):
            work_mode = f"{work_mode} {explicit_remote}".strip()

    return AssignmentRecord(
        source_key=record.source_key,
        source_id=record.source_id,
        listing_id=record.listing_id,
        title=record.title,
        description=str(description or record.description or ""),
        descriptionSummary=record.descriptionSummary or _verama_summary(str(description or "")),
        publishedDate=record.publishedDate,
        lastApplicationDate=str(deadline or record.lastApplicationDate or ""),
        startDate=str(start_date or record.startDate or ""),
        endDate=str(end_date or record.endDate or ""),
        duration=str(duration or record.duration or ""),
        workMode=work_mode,
        location=record.location,
        sourceUrl=record.sourceUrl,
        broker=record.broker,
        skills=skills or record.skills or [],
    )


def _verama_should_fetch_detail(
    record: AssignmentRecord,
    *,
    seen_ids: set[str],
    scan_date: date,
) -> bool:
    if record.source_id in seen_ids:
        return False

    last_app = _parse_api_date(record.lastApplicationDate)
    if last_app is not None and last_app < scan_date:
        return False

    if _verama_title_is_clearly_outside(record.title):
        return False

    if not _verama_location_precheck_passes(record):
        return False

    if not record.lastApplicationDate:
        return True

    title = _normalize_text(record.title)
    targetish = re.compile(
        r"\b(accessibility|tillgänglighet|tillganglighet|wcag|react|next|frontend|"
        r"front-end|angular|wordpress|java|spring|fullstack|ux|ui|designer|"
        r"projektledare|project manager|scrum master|agile coach|koordinator|"
        r"consultant|konsult|developer|utvecklare|project lead)\b"
    )
    return bool(targetish.search(title))


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

    by_key: dict[str, AssignmentRecord] = {}

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
                    record = AssignmentRecord(
                        source_key=source_key,
                        source_id=source_id,
                        listing_id=f"{SOURCE_PREFIXES[source_key]}{source_id}",
                        title=row.get("title") or "",
                        description="",
                        descriptionSummary="",
                        publishedDate=row.get("firstDayOfApplications"),
                        lastApplicationDate=row.get("lastDayOfApplications"),
                        workMode=_verama_work_mode(row),
                        location=_verama_location(row.get("city"), row.get("countryCode")),
                        sourceUrl=f"{VERAMA_BASE}/app/job-requests/{source_id}",
                        broker=row.get("originServiceName") or "",
                    )
                    by_key[record.dedupe_key] = record

                if payload.get("last") or not rows:
                    break
                page_num += 1

            for dedupe_key, record in list(by_key.items()):
                if not _verama_should_fetch_detail(
                    record,
                    seen_ids=seen_ids,
                    scan_date=scan_date,
                ):
                    continue
                detail_payload: dict[str, Any] | None = None
                for path in (
                    f"{VERAMA_BASE}/api/job-requests/v2/{record.source_id}",
                    f"{VERAMA_BASE}/api/job-requests/{record.source_id}",
                ):
                    response = api.get(
                        path,
                        headers={
                            **auth_headers,
                            "accept": "application/json, text/plain, */*",
                            "referer": f"{VERAMA_BASE}/app/job-requests",
                        },
                        timeout=60000,
                    )
                    if response.status == 200:
                        detail_payload = response.json()
                        break
                    if response.status not in (404, 405):
                        raise RuntimeError(
                            f"Verama detail API returned {response.status} for {record.source_id}: "
                            f"{response.text()[:200]}"
                        )
                if detail_payload:
                    by_key[dedupe_key] = _merge_verama_detail(record, detail_payload)

            browser.close()

        records = list(by_key.values())
        return records, PlatformScanResult(source_key=source_key, status="ok", count=len(records))
    except PlaywrightTimeoutError as exc:
        return list(by_key.values()), PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(by_key),
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return list(by_key.values()), PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(by_key),
            message=str(exc),
        )


def _chas_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": SCAN_USER_AGENT,
            "Accept": "application/json",
        }
    )
    return session


def _strip_html(value: str) -> str:
    text = re.sub(r"<(br|/p|/div|/li|/h[1-6])\b[^>]*>", "\n", value, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _extract_chas_konsult_ids(markup: str) -> set[str]:
    ids: set[str] = set()
    for pattern in (
        r"call-off-listitem[^>]+(?:data-id|data-call-off-id|id)=['\"]?(?:call-off-)?(\d+)",
        r"(?:data-id|data-call-off-id|id)=['\"]?(?:call-off-)?(\d+)[^>]+call-off-listitem",
        r"/avrop/[^'\"]+['\"][^>]+data-id=['\"]?(\d+)",
    ):
        ids.update(re.findall(pattern, markup, flags=re.I | re.S))
    return ids


def _label_value(text: str, labels: tuple[str, ...]) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:^|\n)\s*(?:{label_pattern})\s*:?\s*([^\n|]+)",
        text,
        flags=re.I,
    )
    return match.group(1).strip(" :") if match else ""


def _chas_class_attr(class_name: str) -> str:
    return rf"class=['\"](?:[^'\"]*\s)?{re.escape(class_name)}(?:\s[^'\"]*)?['\"]"


def _extract_chas_class_block(markup: str, class_name: str) -> str:
    match = re.search(
        rf"<div\b[^>]*{_chas_class_attr(class_name)}[^>]*>(.*?)</div>",
        markup,
        flags=re.I | re.S,
    )
    return match.group(1) if match else ""


def _clean_chas_field(value: str) -> str:
    text = " ".join(_strip_html(value).split())
    return "" if text == "-" else text


def _extract_chas_card(markup: str) -> str:
    match = re.search(
        rf"<div\b[^>]*{_chas_class_attr('call-off-listitem')}[^>]*>.*?"
        rf"(?=<div\b[^>]*{_chas_class_attr('call-off-content-container')})",
        markup,
        flags=re.I | re.S,
    )
    return match.group(0) if match else ""


def _extract_chas_content(markup: str) -> str:
    match = re.search(
        rf"<div\b[^>]*{_chas_class_attr('call-off-content')}[^>]*>(.*?)"
        rf"(?:<div\b[^>]*{_chas_class_attr('backlink')}|</main>)",
        markup,
        flags=re.I | re.S,
    )
    return match.group(1) if match else ""


def _extract_chas_org(markup: str, text: str) -> str:
    match = re.search(
        r"call-off-organization.*?>(.*?)<",
        markup,
        flags=re.I | re.S,
    )
    if match:
        org = _strip_html(match.group(1)).strip()
        if org:
            return org
    return _label_value(text, ("Kund", "Organisation", "Beställare", "Bestallare"))


def _extract_chas_description(text: str, org: str) -> str:
    start_match = re.search(r"Uppdragsbeskrivning", text, flags=re.I)
    if start_match:
        description = text[start_match.start() :]
        stop_match = re.search(
            r"\n(?:Ansökan|Ansokan|Kontakt|Om Chas|Frågor|Fragor)\b",
            description,
            flags=re.I,
        )
        if stop_match:
            description = description[: stop_match.start()]
    else:
        description = text
    if org:
        return f"Client: {org}\n{description.strip()}"
    return description.strip()


def _parse_chas_detail(markup: str) -> dict[str, str]:
    text = _strip_html(markup)
    card_markup = _extract_chas_card(markup)
    content_markup = _extract_chas_content(markup)
    card_text = _strip_html(card_markup)
    content_text = _strip_html(content_markup) if content_markup else text
    scoped_text = "\n".join(part for part in (card_text, content_text) if part)
    org = _extract_chas_org(card_markup, card_text) or _extract_chas_org(markup, scoped_text)
    deadline_match = re.search(
        r"(?:Deadline|Sista(?:\s+anbudsdag|\s+ansökningsdag|\s+ansokningsdag)?)\s*:?\s*(\d{4}-\d{2}-\d{2})",
        scoped_text,
        flags=re.I,
    )
    interval_match = re.search(
        r"(\d{4}-\d{2}-\d{2})\s*(?:-|–|—|till)\s*(\d{4}-\d{2}-\d{2})",
        card_text or scoped_text,
        flags=re.I,
    )
    extent = _clean_chas_field(_extract_chas_class_block(card_markup, "extent"))
    if not extent:
        extent = _label_value(content_text, ("Omfattning", "Extent", "Beläggning", "Belaggning"))
    if not extent:
        percent = re.search(r"\b(\d{1,3}(?:,\d+)?)\s*%", scoped_text)
        extent = f"{percent.group(1)} %" if percent else ""
    work_type = _clean_chas_field(_extract_chas_class_block(card_markup, "worktype"))
    if not work_type:
        work_type = _label_value(content_text, ("Arbetssätt", "Arbetssatt", "Worktype"))
    location = _clean_chas_field(_extract_chas_class_block(card_markup, "location"))
    work_text = _normalize_text(scoped_text)
    if not work_type:
        if "ej distans" in work_text:
            work_type = "Ej distans"
        elif "hybrid" in work_text:
            work_type = "Hybrid"
        elif "distans" in work_text or "fjärrarbete" in work_text or "fjarrarbete" in work_text:
            work_type = "Distans"
    if not location:
        location = _label_value(content_text, ("Placeringsort", "Ort", "Location"))
    if not location:
        city_match = re.search(
            r"\b(Stockholm|Solna|Göteborg|Goteborg|Malmö|Malmo|Uppsala|Linköping|Linkoping)\b",
            scoped_text,
        )
        location = city_match.group(1) if city_match else ""

    detail = {
        "org": org,
        "description": _extract_chas_description(content_text, org),
        "lastApplicationDate": deadline_match.group(1) if deadline_match else "",
        "startDate": interval_match.group(1) if interval_match else "",
        "endDate": interval_match.group(2) if interval_match else "",
        "duration": extent or (
            f"{interval_match.group(1)} - {interval_match.group(2)}" if interval_match else ""
        ),
        "workMode": work_type,
        "location": location,
    }
    return detail


def scan_chaspartnernetwork(
    *,
    page_size: int = 100,
    max_pages: int | None = None,
    **_: Any,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    source_key = "chaspartnernetwork.se"
    session = _chas_session()
    by_key: dict[str, AssignmentRecord] = {}

    try:
        filter_response = session.get(
            f"{CHAS_BASE}/wp-admin/admin-ajax.php",
            params={
                "action": "cpn_filter_call_offs",
                "anbudstyp": "Konsult",
                "sort": "",
                "avtal_placeringsort": "",
                "fritext": "",
                "distance": "",
            },
            headers={"Accept": "text/html, */*"},
            timeout=60,
        )
        filter_response.raise_for_status()
        konsult_ids = _extract_chas_konsult_ids(filter_response.text)

        page = 1
        total_pages: int | None = None
        rows: list[dict[str, Any]] = []
        while True:
            if max_pages is not None and page > max_pages:
                break
            response = session.get(
                f"{CHAS_BASE}/wp-json/wp/v2/call_off",
                params={
                    "per_page": page_size,
                    "page": page,
                    "orderby": "date",
                    "order": "desc",
                },
                timeout=60,
            )
            response.raise_for_status()
            if total_pages is None:
                total_header = response.headers.get("X-WP-TotalPages")
                total_pages = int(total_header) if total_header and total_header.isdigit() else 1
            page_rows = response.json()
            rows.extend(page_rows)
            if page >= total_pages:
                break
            page += 1

        for row in rows:
            source_id = str(row.get("id"))
            if konsult_ids and source_id not in konsult_ids:
                continue
            link = row.get("link") or ""
            detail_response = session.get(link, headers={"Accept": "text/html, */*"}, timeout=60)
            detail_response.raise_for_status()
            detail = _parse_chas_detail(detail_response.text)
            title = _strip_html(row.get("title", {}).get("rendered") or "")
            org = detail.get("org") or ""
            record = AssignmentRecord(
                source_key=source_key,
                source_id=source_id,
                listing_id=f"{SOURCE_PREFIXES[source_key]}{source_id}",
                title=title,
                description=detail.get("description", ""),
                descriptionSummary=f"Client: {org}" if org else "",
                publishedDate=(row.get("date") or "")[:10],
                lastApplicationDate=detail.get("lastApplicationDate", ""),
                startDate=detail.get("startDate", ""),
                endDate=detail.get("endDate", ""),
                duration=detail.get("duration", ""),
                workMode=detail.get("workMode", ""),
                location=detail.get("location", ""),
                sourceUrl=urljoin(CHAS_BASE, link),
                broker="Chas Partner Network",
                skills=[],
            )
            by_key[record.dedupe_key] = record

        records = list(by_key.values())
        return records, PlatformScanResult(source_key=source_key, status="ok", count=len(records))
    except Exception as exc:  # noqa: BLE001
        return list(by_key.values()), PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(by_key),
            message=str(exc),
        )


PlatformScanner = Callable[..., tuple[list[AssignmentRecord], PlatformScanResult]]

PLATFORM_SCANNERS: dict[str, PlatformScanner] = {
    "allakonsultuppdrag.se": scan_allakonsultuppdrag,
    "verama.com": scan_verama,
    "chaspartnernetwork.se": scan_chaspartnernetwork,
}

DEFAULT_PLATFORMS = [source.source_key for source in SOURCE_REGISTRY if source.active]


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
    scan_date = scan_date or date.today()

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
                headless=headless,
                seen_ids=seen_ids_by_source.get(platform_id, set()),
                scan_date=scan_date,
            )
        else:
            rows, result = scanner(max_pages=max_pages)

        assignments.extend(rows)
        results.append(result)

    return assignments, results
