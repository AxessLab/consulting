"""Deterministic assignment filtering and consultant matching."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from assignment_platforms import AssignmentRecord
from consultant_utils import load_consultants

INHOUSE_A11Y_TEAM = "Inhouse accessibility team"

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

A11Y_STRONG_TERMS = [
    r"tillgänglighetsgranskare",
    r"tillganglighetsgranskare",
    r"tillgänglighetsspecialist",
    r"tillganglighetsspecialist",
    r"accessibility specialist",
    r"accessibility consultant",
    r"wcag specialist",
    r"document accessibility",
    r"dokumenttillgänglighet",
    r"dokumenttillganglighet",
    r"webbtillgänglighetsspecialist",
    r"webbtillganglighetsspecialist",
]

A11Y_WEAK_CONTEXT = re.compile(
    r"information kring tillgänglighet|information kring tillganglighet",
    re.I,
)

PM_TITLES = re.compile(
    r"\b(project manager|projektledare|scrum master|projektkoordinator|"
    r"project coordinator|agile coach|leveransansvarig)\b",
    re.I,
)

NON_IT_PM_CONTEXT = re.compile(
    r"\b(socialförvaltning|socialforvaltning|social services|rail|transport|"
    r"automotive|vehicle|marketing|value proposition|sales enablement|"
    r"organizational change|field support|mechatronic|seat belt)\b",
    re.I,
)

IT_PM_CONTEXT = re.compile(
    r"\b(it|digital|software|system|web|app|platform|erp|iam|payment|"
    r"digital workplace|intranät|intranet|e-service|e-tjänst|devops|cloud)\b",
    re.I,
)

EMPLOYMENT_AD = re.compile(
    r"\b(anställning|anstallning|permanent employment|rekrytering till fast)\b",
    re.I,
)

ROLE_CATEGORY_TAGS: dict[str, set[str]] = {
    "accessibility_specialist": {
        "accessibility",
        "accessibility-specialist",
        "accessibility-engineer",
        "accessibility-expert",
        "wcag",
        "audits",
        "physical-accessibility",
        "documents",
        "pdf",
    },
    "react_frontend": {
        "frontend",
        "react",
        "nextjs",
        "typescript",
        "design-system",
    },
    "angular": {"frontend", "angular"},
    "wordpress": {"frontend", "wordpress"},
    "java": {"java", "backend", "fullstack", "spring"},
    "fullstack_java": {"fullstack", "java", "react", "angular", "frontend"},
    "ux": {"ux", "ui", "product-design", "user-research", "design"},
    "pm": {"project-manager", "scrum-master", "agile-coach"},
}


@dataclass
class ConsultantProfile:
    name: str
    main_roles: set[str]
    role_tags: set[str]
    locations: set[str]
    active: bool


@dataclass
class MatchedAssignment:
    assignment: AssignmentRecord
    section: str
    consultants: list[str]
    hours_label: str
    client_label: str


def normalize_text(value: str) -> str:
    lowered = value.lower()
    normalized = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def phrase_match(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I) is not None


def load_consultant_profiles() -> list[ConsultantProfile]:
    profiles: list[ConsultantProfile] = []
    for consultant in load_consultants():
        if not consultant.get("active", True):
            continue
        main_roles = {normalize_text(role) for role in consultant.get("mainRoles", [])}
        role_tags = set(main_roles)
        for variant in consultant.get("cvs", []):
            if not variant.get("active", True):
                continue
            role_tags.update(normalize_text(role) for role in variant.get("roles", []))
        locations = {normalize_text(loc) for loc in consultant.get("locations", [])}
        profiles.append(
            ConsultantProfile(
                name=consultant["canonicalName"],
                main_roles=main_roles,
                role_tags=role_tags,
                locations=locations,
                active=True,
            )
        )
    return profiles


def skill_names(assignment: AssignmentRecord) -> list[str]:
    names: list[str] = []
    for skill in assignment.skills:
        if isinstance(skill, dict) and skill.get("name"):
            names.append(normalize_text(str(skill["name"])))
    return names


def combined_text(assignment: AssignmentRecord) -> str:
    parts = [
        assignment.title,
        assignment.description_summary,
        assignment.description,
        " ".join(skill_names(assignment)),
    ]
    return normalize_text(" ".join(parts))


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def is_active_assignment(assignment: AssignmentRecord, scan_date: date) -> bool:
    last_app = parse_iso_date(assignment.last_application_date)
    if last_app is None:
        return True
    return last_app >= scan_date


def is_remote(work_mode: str, location: str) -> bool:
    fields = normalize_text(f"{work_mode} {location}")
    return any(term in fields for term in ("remote", "distans", "fjarrarbete", "fjärrarbete"))


def is_hybrid(work_mode: str, location: str) -> bool:
    fields = normalize_text(f"{work_mode} {location}")
    return "hybrid" in fields


def location_tokens(location: str) -> set[str]:
    return {normalize_text(part.strip()) for part in re.split(r"[,/|]", location) if part.strip()}


def near_stockholm(location: str) -> bool:
    tokens = location_tokens(location)
    normalized_location = normalize_text(location)
    return bool(tokens & NEAR_STOCKHOLM) or any(
        place in normalized_location for place in NEAR_STOCKHOLM
    )


def in_gothenburg(location: str) -> bool:
    normalized = normalize_text(location)
    return any(alias in normalized for alias in GOTHENBURG_ALIASES)


def location_passes_for_categories(
    assignment: AssignmentRecord,
    categories: set[str],
) -> bool:
    if "accessibility_specialist" in categories:
        return True

    if is_remote(assignment.work_mode, assignment.location):
        return True

    if near_stockholm(assignment.location):
        return True

    frontend_role = bool(categories & {"react_frontend", "angular", "wordpress"})
    if frontend_role and in_gothenburg(assignment.location):
        return True

    if is_hybrid(assignment.work_mode, assignment.location) and near_stockholm(assignment.location):
        return True

    return False


def is_accessibility_specialist_role(assignment: AssignmentRecord) -> bool:
    title = normalize_text(assignment.title)
    if A11Y_WEAK_CONTEXT.search(title):
        return False
    if any(phrase_match(term, title) for term in A11Y_STRONG_TERMS):
        return True

    skills = " ".join(skill_names(assignment))
    has_a11y_skill = any(
        term in skills
        for term in ("tillganglighet", "accessibility", "wcag", "tillganglighetsgransk")
    )
    reviewer_title = phrase_match(
        r"tillgänglighetsgransk|tillganglighetsgransk|accessibility", title
    )
    return has_a11y_skill and reviewer_title


def mentions_accessibility(assignment: AssignmentRecord) -> bool:
    text = combined_text(assignment)
    return any(
        term in text
        for term in (
            "tillganglighet",
            "accessibility",
            "wcag",
            "tillganglighetsgransk",
        )
    )


def detect_role_categories(assignment: AssignmentRecord) -> set[str]:
    if is_accessibility_specialist_role(assignment):
        return {"accessibility_specialist"}

    text = combined_text(assignment)
    skills = skill_names(assignment)
    categories: set[str] = set()

    if re.search(
        r"\b(python|\.net|php|vue|c#|embedded|fpga|data engineer|mobile|ios|android|"
        r"solution architect|platform architect)\b",
        text,
    ):
        if re.search(r"\b(react|next\.js|nextjs|frontend|front-end)\b", text):
            categories.add("react_frontend")
    elif phrase_match(r"\b(react|next\.js|nextjs|frontend|front-end)\b", text) or (
        any(s in skills for s in ("react", "nextjs", "frontend"))
        and phrase_match(r"\b(frontend|front-end|react)\b", text)
    ):
        categories.add("react_frontend")

    if phrase_match(r"\b(angular|wordpress)\b", text) or any(
        s in skills for s in ("angular", "wordpress")
    ):
        if "angular" in text or "angular" in skills:
            categories.add("angular")
        if "wordpress" in text or "wordpress" in skills:
            categories.add("wordpress")

    if re.search(r"\b(\.net|php|vue)\b", text):
        pass
    elif phrase_match(r"\b(fullstack|full-stack|full stack)\b", text):
        if phrase_match(r"\bjava\b", text) or "java" in skills:
            if phrase_match(r"\b(react|angular)\b", text) or any(
                s in skills for s in ("react", "angular")
            ):
                categories.add("fullstack_java")
    elif phrase_match(r"\bjava\b", text) or "java" in skills:
        if not re.search(r"\b(python|\.net|php|vue|c#|embedded|fpga|data engineer)\b", text):
            categories.add("java")

    if re.search(r"\b(ui artist|game art|graphic artist)\b", text):
        pass
    elif re.search(r"\b(ios|android|mobile developer|software developer)\b", text):
        if re.search(r"\b(ux|ui designer|product designer|user experience)\b", text, re.I):
            categories.add("ux")
    elif re.search(
        r"\b(ux|ui|product designer|user experience|interaction design|"
        r"interaktionsdesign|tjanstedesign|tjänstedesign)\b",
        text,
        re.I,
    ):
        categories.add("ux")

    if matches_pm(text):
        categories.add("pm")

    if phrase_match(r"\b(arkitekt|architect)\b", text) and not PM_TITLES.search(text):
        categories.discard("pm")

    return categories


def matches_pm(text: str) -> bool:
    if not PM_TITLES.search(text):
        return False
    if NON_IT_PM_CONTEXT.search(text) and not IT_PM_CONTEXT.search(text):
        return False
    if phrase_match(r"\btechnical project manager\b", text) and not IT_PM_CONTEXT.search(text):
        return False
    return IT_PM_CONTEXT.search(text) is not None


def consultant_matches_category(profile: ConsultantProfile, category: str) -> bool:
    required = ROLE_CATEGORY_TAGS.get(category, set())
    if not required:
        return False
    if category == "accessibility_specialist":
        if "accessibility-specialist" in profile.role_tags:
            return True
        if "accessibility" in profile.role_tags and (
            "audits" in profile.role_tags
            or "wcag" in profile.role_tags
            or "accessibility-engineer" in profile.role_tags
            or "accessibility-expert" in profile.role_tags
            or "physical-accessibility" in profile.role_tags
            or "documents" in profile.role_tags
        ):
            return True
        return False

    overlap = profile.role_tags & required
    if category == "react_frontend":
        return bool(overlap) and ("react" in profile.role_tags or "frontend" in profile.role_tags)
    if category == "angular":
        return "angular" in profile.role_tags
    if category == "wordpress":
        return "wordpress" in profile.role_tags
    if category == "java":
        return "java" in profile.role_tags or (
            "backend" in profile.role_tags and "java" in profile.role_tags
        )
    if category == "fullstack_java":
        return "fullstack" in profile.role_tags and (
            "java" in profile.role_tags or "backend" in profile.role_tags
        )
    if category == "ux":
        return bool(profile.role_tags & {"ux", "ui", "product-design", "user-research"})
    if category == "pm":
        if "project-manager" in profile.main_roles or "agile-coach" in profile.main_roles:
            return True
        return "scrum-master" in profile.main_roles
    return bool(overlap)


def match_consultants_for_assignment(
    assignment: AssignmentRecord,
    profiles: list[ConsultantProfile],
) -> tuple[str, list[str]]:
    if EMPLOYMENT_AD.search(combined_text(assignment)):
        return "reject", []

    categories = detect_role_categories(assignment)
    if not categories:
        return "reject", []

    matched: list[str] = []
    title_text = normalize_text(assignment.title)
    for profile in profiles:
        for category in categories:
            if not consultant_matches_category(profile, category):
                continue
            if category == "pm" and "scrum-master" in profile.main_roles:
                if "project-manager" not in profile.main_roles and "agile-coach" not in profile.main_roles:
                    if not re.search(r"scrum master|scrum-master", title_text, re.I):
                        continue
            matched.append(profile.name)
            break

    matched = list(dict.fromkeys(matched))
    if not matched:
        return "reject", []

    if "accessibility_specialist" in categories:
        text = combined_text(assignment)
        if re.search(r"\b(team|teamleverans|2\s*x|flera|multiple)\b", text):
            matched.append(INHOUSE_A11Y_TEAM)
        return "accessibility_specialist", matched

    if not location_passes_for_categories(assignment, categories):
        return "reject_location", matched

    section = "other_a11y_mentions" if mentions_accessibility(assignment) else "other"
    return section, matched


def parse_hours_label(assignment: AssignmentRecord) -> str:
    text = f"{assignment.description} {assignment.duration}"
    scope_match = re.search(
        r"(omfattning|scope|utilization|beläggning|belaggning|engagemang|max)[^%\n]{0,40}(\d{1,3})\s*%",
        text,
        re.I,
    )
    if scope_match:
        return f"{scope_match.group(2)}%"

    if re.search(r"\b100\s*%", text):
        return "100%"
    if re.search(r"\b50\s*%", text):
        return "50%"
    return "not stated (probably full time)"


def parse_client_label(assignment: AssignmentRecord) -> str:
    description = assignment.description
    for pattern in (
        r"(?:Kund|End client|Slutkund)\s*:\s*([^\n|]+)",
        r"\btill\s+([A-ZÅÄÖ][A-Za-zÅÄÖåäö\s]+?)\b",
    ):
        match = re.search(pattern, description, re.I)
        if match:
            client = match.group(1).strip(" .")
            if len(client) > 3 and normalize_text(client) not in {
                "detta",
                "denna",
                "kunden",
                "client",
            }:
                return client
    return "not stated"


def posted_date_label(assignment: AssignmentRecord, scan_date: date) -> str:
    published = parse_iso_date(assignment.published_date)
    return published.isoformat() if published else scan_date.isoformat()


def validate_match(match: MatchedAssignment) -> str | None:
    text = combined_text(match.assignment)
    if match.section == "accessibility_specialist":
        if re.search(
            r"\b(security reviewer|devops|cloud engineer|backend developer|"
            r"frontend developer|fullstack developer|systemutvecklare)\b",
            text,
            re.I,
        ) and not is_accessibility_specialist_role(match.assignment):
            return "accessibility section but role is security/dev"
    return None


def format_slack_line(match: MatchedAssignment, scan_date: date) -> str:
    assignment = match.assignment
    location = f"{assignment.location} | {assignment.work_mode}".strip(" |")
    consultants = ", ".join(match.consultants)
    platform_note = f" [{assignment.platform}]" if assignment.platform else ""
    return (
        f"{assignment.listing_id}{platform_note} | {assignment.title} | {location} | "
        f"{match.hours_label} | Client: {match.client_label} | Broker: {assignment.broker} | "
        f"Link: {assignment.source_url} | Posted: {posted_date_label(assignment, scan_date)} | "
        f"Match: {consultants}"
    )


def cross_platform_dedupe(assignments: list[AssignmentRecord]) -> list[AssignmentRecord]:
    """Prefer verama.com when the same role appears on multiple platforms."""
    by_fingerprint: dict[str, AssignmentRecord] = {}
    platform_rank = {"verama.com": 0, "allakonsultuppdrag.se": 1}

    for assignment in assignments:
        fingerprint = normalize_text(
            f"{assignment.title}|{assignment.broker}|{assignment.location}"
        )
        existing = by_fingerprint.get(fingerprint)
        if existing is None:
            by_fingerprint[fingerprint] = assignment
            continue
        if platform_rank.get(assignment.platform, 99) < platform_rank.get(
            existing.platform, 99
        ):
            by_fingerprint[fingerprint] = assignment

    return list(by_fingerprint.values())


def export_consultant_summaries(
    profiles: list[ConsultantProfile] | None = None,
) -> list[dict[str, Any]]:
    profiles = profiles or load_consultant_profiles()
    return [
        {
            "name": profile.name,
            "mainRoles": sorted(profile.main_roles),
            "roleTags": sorted(profile.role_tags),
            "locations": sorted(profile.locations),
        }
        for profile in profiles
    ]


@dataclass
class AssignmentSuggestion:
    assignment: AssignmentRecord
    suggested_section: str | None
    suggested_consultants: list[str]
    reject_reason: str | None
    role_categories: list[str]
    mentions_accessibility: bool


def suggest_for_assignment(
    assignment: AssignmentRecord,
    profiles: list[ConsultantProfile],
) -> AssignmentSuggestion:
    section, consultants = match_consultants_for_assignment(assignment, profiles)
    categories = sorted(detect_role_categories(assignment))
    mentions_a11y = mentions_accessibility(assignment)

    if section.startswith("reject"):
        reason = "location" if section == "reject_location" else "role"
        return AssignmentSuggestion(
            assignment=assignment,
            suggested_section=None,
            suggested_consultants=consultants,
            reject_reason=reason,
            role_categories=categories,
            mentions_accessibility=mentions_a11y,
        )

    match = MatchedAssignment(
        assignment=assignment,
        section=section,
        consultants=consultants,
        hours_label=parse_hours_label(assignment),
        client_label=parse_client_label(assignment),
    )
    issue = validate_match(match)
    if issue:
        return AssignmentSuggestion(
            assignment=assignment,
            suggested_section=None,
            suggested_consultants=consultants,
            reject_reason=issue,
            role_categories=categories,
            mentions_accessibility=mentions_a11y,
        )

    return AssignmentSuggestion(
        assignment=assignment,
        suggested_section=section,
        suggested_consultants=consultants,
        reject_reason=None,
        role_categories=categories,
        mentions_accessibility=mentions_a11y,
    )


def suggestion_to_dict(suggestion: AssignmentSuggestion) -> dict[str, Any]:
    assignment = suggestion.assignment
    return {
        "dedupe_key": assignment.dedupe_key,
        "listing_id": assignment.listing_id,
        "platform": assignment.platform,
        "title": assignment.title,
        "location": assignment.location,
        "work_mode": assignment.work_mode,
        "suggested_section": suggestion.suggested_section,
        "suggested_consultants": suggestion.suggested_consultants,
        "reject_reason": suggestion.reject_reason,
        "role_categories": suggestion.role_categories,
        "mentions_accessibility": suggestion.mentions_accessibility,
    }


def suggest_assignments(
    assignments: list[AssignmentRecord],
    *,
    scan_date: date,
    profiles: list[ConsultantProfile] | None = None,
) -> tuple[list[AssignmentSuggestion], list[AssignmentSuggestion]]:
    """Return (active_new, expired) suggestions for assignments already filtered as new."""
    profiles = profiles or load_consultant_profiles()
    active: list[AssignmentSuggestion] = []
    expired: list[AssignmentSuggestion] = []

    for assignment in assignments:
        if not is_active_assignment(assignment, scan_date):
            expired.append(
                AssignmentSuggestion(
                    assignment=assignment,
                    suggested_section=None,
                    suggested_consultants=[],
                    reject_reason="expired application date",
                    role_categories=[],
                    mentions_accessibility=False,
                )
            )
            continue
        active.append(suggest_for_assignment(assignment, profiles))

    return active, expired


def process_assignments(
    assignments: list[AssignmentRecord],
    *,
    seen_keys: set[str],
    scan_date: date,
    profiles: list[ConsultantProfile] | None = None,
) -> tuple[list[MatchedAssignment], list[dict[str, Any]]]:
    profiles = profiles or load_consultant_profiles()
    reported: list[MatchedAssignment] = []
    debug_rejects: list[dict[str, Any]] = []

    for assignment in assignments:
        if assignment.dedupe_key in seen_keys:
            continue
        if not is_active_assignment(assignment, scan_date):
            debug_rejects.append(
                {
                    "id": assignment.listing_id,
                    "platform": assignment.platform,
                    "title": assignment.title,
                    "reason": "expired application date",
                }
            )
            continue

        section, consultants = match_consultants_for_assignment(assignment, profiles)
        if section.startswith("reject"):
            reason = "location" if section == "reject_location" else "role"
            debug_rejects.append(
                {
                    "id": assignment.listing_id,
                    "platform": assignment.platform,
                    "title": assignment.title,
                    "reason": reason,
                    "would_match": consultants,
                }
            )
            continue

        match = MatchedAssignment(
            assignment=assignment,
            section=section,
            consultants=consultants,
            hours_label=parse_hours_label(assignment),
            client_label=parse_client_label(assignment),
        )
        issue = validate_match(match)
        if issue:
            debug_rejects.append(
                {
                    "id": assignment.listing_id,
                    "platform": assignment.platform,
                    "title": assignment.title,
                    "reason": issue,
                }
            )
            continue
        reported.append(match)

    return reported, debug_rejects
