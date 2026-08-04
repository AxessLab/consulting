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
CHAS_BASE = "https://chaspartnernetwork.se"
SOURCE_PREFIXES = {
    "allakonsultuppdrag.se": "a",
    "verama.com": "v",
    "chaspartnernetwork.se": "c",
}
ALLAKONSULT_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"
SCAN_USER_AGENT = "Mozilla/5.0 (compatible; AxessLabAssignmentScanner/1.0)"
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_DATE_RANGE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})\s*-\s*(\d{4}-\d{2}-\d{2})"
)
_DEADLINE_RE = re.compile(r"Deadline:\s*(\d{4}-\d{2}-\d{2})", re.I)
_ORG_COMMENT_RE = re.compile(
    r'call-off-organization[^>]*>(.*?)</div>',
    re.I | re.S,
)
_INFO_FIELD_RE = re.compile(
    r'<div class="(location|worktype|extent|consultants|interval)">\s*'
    r"(?:<[^>]+>\s*)*<span>(.*?)</span>",
    re.I | re.S,
)
_VERAMA_PLAUSIBLE_TITLE_RE = re.compile(
    r"\b(accessibility|tillgänglighet|tillganglighet|wcag|frontend|front-end|"
    r"react|next\.?js|angular|wordpress|java|spring|backend|fullstack|"
    r"full-stack|full stack|ux|ui|product designer|interaktionsdesign|"
    r"tjänstedesign|tjanstedesign|project manager|projektledare|scrum master|"
    r"agile coach|projektkoordinator|project coordinator|leveransansvarig|"
    r"developer|utvecklare|systemutvecklare|consultant|konsult)\b",
    re.I,
)
_VERAMA_CLEARLY_OUTSIDE_TITLE_RE = re.compile(
    r"\b(sap|network|nätverk|natverk|security operations|soc|hr|payroll|"
    r"automation engineer|factory|produktion|embedded|fpga|data engineer|"
    r"dataingenjör|dataingenjor|analyst|analytiker)\b",
    re.I,
)
_NEAR_STOCKHOLM_RE = re.compile(
    r"\b(stockholm|solna|sundbyberg|kista|bromma|sollentuna|danderyd|täby|taby|"
    r"järfälla|jarfalla|nacka|huddinge|lidingö|lidingo|älvsjö|alvsjo|"
    r"årsta|arsta|stockholms län|stockholms lan|botkyrka|upplands väsby|"
    r"upplands vasby|södertälje|sodertalje|haninge|tyresö|tyreso|"
    r"vällingby|vallingby|farsta|göteborg|goteborg|gothenburg)\b",
    re.I,
)


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


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _verama_work_mode(remoteness: Any) -> str:
    if remoteness is None:
        return ""
    try:
        percent = int(remoteness)
    except (TypeError, ValueError):
        return str(remoteness)
    if percent >= 100:
        return "remote"
    if percent > 0:
        return f"{percent}% remote"
    return "on-site"


def _verama_is_remote(work_mode: str, location: str) -> bool:
    fields = _WHITESPACE_RE.sub(" ", f"{work_mode} {location}".lower())
    fields = re.sub(r"\b(?:[1-9]|[1-9]\d)\s*%\s*remote\b", "", fields)
    return any(term in fields for term in ("remote", "distans", "fjärrarbete", "fjarrarbete"))


def _verama_location_precheck(record: AssignmentRecord) -> bool:
    if _verama_is_remote(record.work_mode, record.location):
        return True
    return bool(_NEAR_STOCKHOLM_RE.search(record.location or ""))


def _verama_strong_accessibility_title(title: str) -> bool:
    return bool(
        re.search(
            r"tillgänglighetsgransk|tillganglighetsgransk|"
            r"tillgänglighetsspecialist|tillganglighetsspecialist|"
            r"accessibility specialist|accessibility consultant|wcag specialist|"
            r"document accessibility|dokumenttillgänglighet|dokumenttillganglighet",
            title,
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

    last_application = _parse_date(record.last_application_date)
    if last_application is not None and last_application < scan_date:
        return False

    title = record.title or ""
    plausible_title = bool(_VERAMA_PLAUSIBLE_TITLE_RE.search(title))
    outside_title = bool(_VERAMA_CLEARLY_OUTSIDE_TITLE_RE.search(title)) and not plausible_title
    if outside_title:
        return False

    if not _verama_location_precheck(record) and not _verama_strong_accessibility_title(title):
        return False

    return plausible_title or not record.last_application_date


def _find_detail_value(data: Any, keys: set[str]) -> Any:
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in keys and value not in (None, "", []):
                return value
        for value in data.values():
            found = _find_detail_value(value, keys)
            if found not in (None, "", []):
                return found
    if isinstance(data, list):
        for item in data:
            found = _find_detail_value(item, keys)
            if found not in (None, "", []):
                return found
    return None


def _detail_text(data: Any, keys: set[str]) -> str:
    value = _find_detail_value(data, keys)
    if value is None:
        return ""
    if isinstance(value, str):
        return _chas_strip_html(value)
    return _chas_strip_html(jsonish(value))


def jsonish(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return " ".join(str(item) for item in _flatten_jsonish(value))
    return str(value)


def _flatten_jsonish(value: Any) -> list[Any]:
    if isinstance(value, dict):
        items: list[Any] = []
        for nested in value.values():
            items.extend(_flatten_jsonish(nested))
        return items
    if isinstance(value, list):
        items = []
        for nested in value:
            items.extend(_flatten_jsonish(nested))
        return items
    return [value]


def _detail_skills(data: Any) -> list[dict[str, Any]]:
    value = _find_detail_value(
        data,
        {
            "skills",
            "competences",
            "competencies",
            "requiredskills",
            "requiredcompetences",
        },
    )
    if not isinstance(value, list):
        return []
    skills: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            name = item.get("name") or item.get("label") or item.get("title")
            if name:
                skills.append({"name": str(name)})
        elif isinstance(item, str):
            skills.append({"name": item})
    return skills


def _verama_fetch_detail(api: Any, auth_headers: dict[str, str], source_id: str) -> dict[str, Any]:
    headers = {
        **auth_headers,
        "accept": "application/json, text/plain, */*",
        "referer": f"{VERAMA_BASE}/app/job-requests/{source_id}",
    }
    for path in (
        f"{VERAMA_BASE}/api/job-requests/v2/{source_id}",
        f"{VERAMA_BASE}/api/job-requests/{source_id}",
    ):
        response = api.get(path, headers=headers, timeout=60000)
        if response.status == 404:
            continue
        if response.status != 200:
            raise RuntimeError(
                f"Verama detail API returned {response.status} for {source_id}: "
                f"{response.text()[:200]}"
            )
        return response.json()
    return {}


def _merge_verama_detail(record: AssignmentRecord, detail: dict[str, Any]) -> None:
    description = _detail_text(
        detail,
        {
            "description",
            "jobdescription",
            "assignmentdescription",
            "descriptiontext",
            "requirements",
        },
    )
    if description:
        record.description = description
        record.description_summary = description[:300]

    last_application = _detail_text(
        detail,
        {"lastdayofapplications", "applicationdeadline", "deadline", "lastapplicationdate"},
    )
    if last_application and not record.last_application_date:
        record.last_application_date = last_application

    start_date = _detail_text(
        detail,
        {"firstdayofassignment", "startdate", "assignmentstartdate"},
    )
    if start_date:
        record.start_date = start_date

    end_date = _detail_text(
        detail,
        {"lastdayofassignment", "enddate", "assignmentenddate"},
    )
    if end_date:
        record.end_date = end_date

    duration = _detail_text(detail, {"duration", "extent", "scope"})
    if duration:
        record.duration = duration

    detail_work_mode = _detail_text(detail, {"workmode", "remotework", "locationtype"})
    if detail_work_mode and not record.work_mode:
        record.work_mode = detail_work_mode

    skills = _detail_skills(detail)
    if skills:
        record.skills = skills


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

    records: dict[str, AssignmentRecord] = {}

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
                        platform=platform,
                        source_id=source_id,
                        listing_id=f"{SOURCE_PREFIXES[platform]}{source_id}",
                        title=row.get("title") or "",
                        description="",
                        description_summary="",
                        published_date=row.get("firstDayOfApplications"),
                        last_application_date=row.get("lastDayOfApplications"),
                        work_mode=_verama_work_mode(row.get("remoteness")),
                        location=_verama_location(row.get("city"), row.get("countryCode")),
                        source_url=f"{VERAMA_BASE}/app/job-requests/{source_id}",
                        broker=row.get("originServiceName") or "",
                    )
                    if _verama_should_fetch_detail(
                        record,
                        seen_ids=seen_ids,
                        scan_date=scan_date,
                    ):
                        try:
                            detail = _verama_fetch_detail(api, auth_headers, source_id)
                            _merge_verama_detail(record, detail)
                        except Exception:
                            # Keep the normalized list row for memory; without detail it cannot match.
                            pass
                    records[source_id] = record

                if payload.get("last") or not rows:
                    break
                page_num += 1

            browser.close()

        return list(records.values()), PlatformScanResult(
            platform=platform, status="ok", count=len(records)
        )
    except PlaywrightTimeoutError as exc:
        return list(records.values()), PlatformScanResult(
            platform=platform,
            status="error",
            count=len(records),
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return list(records.values()), PlatformScanResult(
            platform=platform,
            status="error",
            count=len(records),
            message=str(exc),
        )


def _chas_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": SCAN_USER_AGENT,
            "Accept": "application/json, text/html, */*",
        }
    )
    return session


def _chas_strip_html(value: str) -> str:
    text = _TAG_RE.sub(" ", html.unescape(value or ""))
    return _WHITESPACE_RE.sub(" ", text).strip()


def _chas_fetch_call_off_index(
    session: requests.Session,
    *,
    page_size: int = 100,
    max_pages: int | None = None,
) -> dict[str, dict[str, str]]:
    """Map call_off id → title/link/date from the public WP REST API."""
    index: dict[str, dict[str, str]] = {}
    page = 1
    total_pages = 1

    while page <= total_pages:
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
        total_pages = int(response.headers.get("X-WP-TotalPages") or "1")
        for row in response.json() or []:
            source_id = str(row["id"])
            title = row.get("title") or {}
            index[source_id] = {
                "title": _chas_strip_html(
                    title.get("rendered") if isinstance(title, dict) else str(title)
                ),
                "link": row.get("link") or "",
                "date": (row.get("date") or "")[:10] or "",
            }
        page += 1

    return index


def _chas_konsult_ids(session: requests.Session) -> set[str]:
    response = session.get(
        f"{CHAS_BASE}/wp-admin/admin-ajax.php",
        params={
            "action": "cpn_filter_call_offs",
            "sort": "",
            "avtal_placeringsort": "",
            "anbudstyp": "Konsult",
            "fritext": "",
            "distance": "",
        },
        timeout=60,
    )
    response.raise_for_status()
    return set(re.findall(r'call-off-listitem" id="(\d+)"', response.text))


def _chas_parse_detail(html_text: str) -> dict[str, str]:
    """Extract location, dates, description, and client org from a detail page."""
    fields: dict[str, str] = {}
    for class_name, raw in _INFO_FIELD_RE.findall(html_text):
        value = _chas_strip_html(raw)
        if value and value != "-":
            fields[class_name] = value

    deadline_match = _DEADLINE_RE.search(html_text)
    if deadline_match:
        fields["deadline"] = deadline_match.group(1)

    interval = fields.get("interval", "")
    range_match = _DATE_RANGE_RE.search(interval)
    if range_match:
        fields["start_date"] = range_match.group(1)
        fields["end_date"] = range_match.group(2)

    org_match = _ORG_COMMENT_RE.search(html_text)
    if org_match:
        org = _chas_strip_html(org_match.group(1))
        if org:
            fields["organization"] = org

    desc_match = re.search(
        r"Uppdragsbeskrivning</h2>\s*(.*?)(?:<h2\b|#\s*Skicka in ansökan)",
        html_text,
        re.I | re.S,
    )
    if desc_match:
        fields["description"] = _chas_strip_html(desc_match.group(1))

    return fields


def scan_chaspartnernetwork(
    *,
    page_size: int = 100,
    max_pages: int | None = None,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    platform = "chaspartnernetwork.se"
    session = _chas_session()
    records: list[AssignmentRecord] = []

    try:
        index = _chas_fetch_call_off_index(
            session, page_size=page_size, max_pages=max_pages
        )
        konsult_ids = _chas_konsult_ids(session)
        selected_ids = [source_id for source_id in index if source_id in konsult_ids]
        # Preserve REST order (newest first); fall back to any konsult id missing from page window.
        if max_pages is None:
            for source_id in konsult_ids:
                if source_id not in index:
                    selected_ids.append(source_id)

        for source_id in selected_ids:
            meta = index.get(source_id) or {}
            source_url = meta.get("link") or f"{CHAS_BASE}/?post_type=call_off&p={source_id}"
            title = meta.get("title") or ""
            published_date = meta.get("date") or None
            description = ""
            description_summary = ""
            location = ""
            work_mode = ""
            duration = ""
            start_date = None
            end_date = None
            last_application_date = None

            try:
                detail = session.get(source_url, timeout=60)
                detail.raise_for_status()
                parsed = _chas_parse_detail(detail.text)
                location = parsed.get("location", "")
                work_mode = parsed.get("worktype", "")
                duration = parsed.get("extent", "") or parsed.get("interval", "")
                start_date = parsed.get("start_date")
                end_date = parsed.get("end_date")
                last_application_date = parsed.get("deadline")
                description = parsed.get("description", "")
                organization = parsed.get("organization", "")
                if organization:
                    description_summary = f"Client: {organization}"
                    if description:
                        description = f"Client: {organization}\n\n{description}"
                    else:
                        description = description_summary
                if not title:
                    title_match = re.search(
                        r'<h3 class="item-header"[^>]*>(.*?)</h3>',
                        detail.text,
                        re.I | re.S,
                    )
                    if title_match:
                        title = _chas_strip_html(title_match.group(1))
            except Exception:  # noqa: BLE001
                # Keep the REST stub so the listing still sees the assignment.
                pass

            records.append(
                AssignmentRecord(
                    platform=platform,
                    source_id=source_id,
                    listing_id=f"c{source_id}",
                    title=title,
                    description=description,
                    description_summary=description_summary,
                    published_date=published_date,
                    last_application_date=last_application_date,
                    start_date=start_date,
                    end_date=end_date,
                    duration=duration,
                    work_mode=work_mode,
                    location=location,
                    source_url=source_url,
                    broker="Chas Partner Network",
                )
            )

        return records, PlatformScanResult(
            platform=platform, status="ok", count=len(records)
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
    "chaspartnernetwork.se": scan_chaspartnernetwork,
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
    seen_ids_by_source = seen_ids_by_source or {}

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
                seen_ids=seen_ids_by_source.get(platform_id, set()),
                scan_date=scan_date,
            )
        else:
            rows, result = scanner(max_pages=max_pages)

        assignments.extend(rows)
        results.append(result)

    return assignments, results
