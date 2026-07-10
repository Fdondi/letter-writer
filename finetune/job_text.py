"""Strip job-board chrome and keep substantive posting text for fine-tuning prompts."""
from __future__ import annotations

import re
from typing import Iterable, List

RANKER_JOB_EXCERPT_CHARS = 500
EDITOR_JOB_EXCERPT_CHARS = 900

_JOB_UI_LINE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^apply( now| to position| using linkedin)?$", re.I),
    re.compile(r"^save$", re.I),
    re.compile(r"^share$", re.I),
    re.compile(r"^message$", re.I),
    re.compile(r"^yes$", re.I),
    re.compile(r"^no$", re.I),
    re.compile(r"show more options", re.I),
    re.compile(r"clicked apply", re.I),
    re.compile(r"promoted by hirer", re.I),
    re.compile(r"responses managed off linkedin", re.I),
    re.compile(r"matches your job preferences", re.I),
    re.compile(r"workplace type is", re.I),
    re.compile(r"job type is", re.I),
    re.compile(r"your profile was shared", re.I),
    re.compile(r"did you apply", re.I),
    re.compile(r"undo shared profile", re.I),
    re.compile(r"tailor my resume", re.I),
    re.compile(r"create cover letter", re.I),
    re.compile(r"help me stand out", re.I),
    re.compile(r"meet the hiring team", re.I),
    re.compile(r"mutual connections", re.I),
    re.compile(r"^job poster", re.I),
    re.compile(r"show match details", re.I),
    re.compile(r"you(?:'d| would) be a top applicant", re.I),
    re.compile(r"your ai-powered job assessment", re.I),
    re.compile(r" is hiring$", re.I),
    re.compile(r"^\d+(st|nd|rd|th)$", re.I),
    re.compile(r" logo$", re.I),
    re.compile(r"^save .+ at .+$", re.I),
    re.compile(r"^hybrid$", re.I),
    re.compile(r"^full[- ]time$", re.I),
    re.compile(r"^remote$", re.I),
    re.compile(r"^on[- ]site$", re.I),
    re.compile(r"reposted \d+ (week|day|month)", re.I),
    re.compile(r"over \d+ people", re.I),
)

_SECTION_START = re.compile(
    r"(?i)^(about (the )?(job|company|role)|job description|what you(?:'ll| will)|"
    r"key responsibilities|responsibilities|requirements|what you bring|the role|"
    r"your mission|we are looking for|position overview|job overview|"
    r"our mission|the opportunity)"
)

_METADATA_LINE = re.compile(
    r"(?i)(?:·.{0,40}){2,}|"  # LinkedIn metadata rails (A · B · C)
    r"^\d+\s*(days?|weeks?|months?)\s+ago|"  # repost age only
    r"^pay rate|^start date|^experience \(years\)|^job location|^ob location"
)


def _normalize_job_text(job_text: str) -> str:
    return (job_text or "").replace("\u202f", " ").replace("\u00a0", " ")


def _is_job_ui_noise(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if len(stripped) <= 2:
        return True
    if any(pat.search(stripped) for pat in _JOB_UI_LINE_PATTERNS):
        return True
    if _METADATA_LINE.search(stripped):
        return True
    return False


def _section_start_index(lines: List[str]) -> int | None:
    for i, line in enumerate(lines):
        if _SECTION_START.search(line.strip()):
            return i
    return None


def _substantive_start_index(lines: List[str]) -> int:
    section = _section_start_index(lines)
    if section is not None:
        return section
    for i, line in enumerate(lines):
        if len(line) >= 40 and not _is_job_ui_noise(line):
            return i
    return 0


def _take_lines_up_to_char_limit(lines: Iterable[str], max_chars: int) -> str:
    parts: List[str] = []
    total = 0
    for line in lines:
        extra = len(line) + (1 if parts else 0)
        if total + extra > max_chars:
            break
        parts.append(line)
        total += extra
    return "\n".join(parts).strip()


def clean_job_excerpt(job_text: str, *, max_chars: int = RANKER_JOB_EXCERPT_CHARS) -> str:
    """Return a short excerpt of real job content, with scrape/UI chrome removed."""
    if not job_text or max_chars <= 0:
        return ""
    lines = [ln.strip() for ln in _normalize_job_text(job_text).splitlines()]
    lines = [ln for ln in lines if ln and not _is_job_ui_noise(ln)]
    if not lines:
        return ""
    start = _substantive_start_index(lines)
    body = lines[start:]
    if body and _SECTION_START.fullmatch(body[0].strip()):
        body = body[1:]
    return _take_lines_up_to_char_limit(body, max_chars)
