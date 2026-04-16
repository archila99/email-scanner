from __future__ import annotations

import re
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Optional

from app.config import settings
from app.classifiers.ollama_company_extractor import extract_company_with_ollama
from app.email.preprocess import NormalizedEmail
from app.models import Emails
from app.services.company_normalize import guess_company_from_domain, normalize_company_name


def _is_blank(s: Optional[str]) -> bool:
    return s is None or str(s).strip() == ""


def parse_sender_domain(sender: str) -> Optional[str]:
    _, addr = parseaddr(sender or "")
    if not addr or "@" not in addr:
        return None
    return addr.split("@", 1)[1].strip().lower() or None


_SUBJECT_RES: list[re.Pattern[str]] = [
    re.compile(r"(?i)\bapplication to\s+([^\n:|—\-]{2,80})"),
    re.compile(r"(?i)\bapplying to\s+([^\n:|—\-]{2,80})"),
    re.compile(r"(?i)\bthank you for (applying|your application) (to|at)\s+([^\n:|—\-]{2,80})"),
    re.compile(r"(?i)\b(interview|call|chat)\s+(with|at)\s+([^\n:|—\-]{2,80})"),
    re.compile(r"(?i)^\s*([A-Za-z0-9][A-Za-z0-9 &.'/-]{1,60})\s*[-—|:]\s*(application|interview|offer|update)\b"),
    # "Your application to COMPANY ..."
    re.compile(r"(?i)\byour application (to|at)\s+([^\n:|—\-]{2,80})\b"),
]


_BODY_RES: list[re.Pattern[str]] = [
    re.compile(r"(?i)\bthank you for (applying|your application) (to|at)\s+([^\n,.]{2,80})"),
    re.compile(r"(?i)\bwe (have )?received your application (to|at)\s+([^\n,.]{2,80})"),
    re.compile(r"(?i)\byour application (to|at)\s+([^\n,.]{2,80})\s+has been received\b"),
]


_ROLE_RES: list[re.Pattern[str]] = [
    re.compile(r"(?i)\b(position|role|job title)\s*[:\-]\s*([^\n]{2,120})"),
    re.compile(r"(?i)\b(intern|internship|engineer|developer|scientist|analyst)\b[^\n]{0,40}$"),
]

_ROLE_TITLE_RES: list[re.Pattern[str]] = [
    # Explicit “Position: X” / “Role: X”
    re.compile(r"(?i)\b(position|role|job title)\s*[:\-]\s*([^\n]{2,140})"),
    # Common titles inside subject/body
    re.compile(
        r"(?i)\b("
        r"software engineer|backend engineer|front[ -]?end engineer|full[ -]?stack engineer|"
        r"data scientist|data analyst|machine learning engineer|ml engineer|devops engineer|"
        r"security engineer|site reliability engineer|sre|product manager|pm|"
        r"intern|internship|research intern|engineering intern"
        r")\b"
    ),
]

_ROLE_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\b(frontend|front-end)\b"), "Frontend Engineer"),
    (re.compile(r"(?i)\b(back-end|backend)\b"), "Backend Engineer"),
    (re.compile(r"(?i)\b(full[- ]stack)\b"), "Full Stack Engineer"),
    (re.compile(r"(?i)\b(data scientist)\b"), "Data Scientist"),
    (re.compile(r"(?i)\b(data analyst)\b"), "Data Analyst"),
    (re.compile(r"(?i)\b(machine learning|ml)\b"), "Machine Learning Engineer"),
    (re.compile(r"(?i)\b(devops)\b"), "DevOps Engineer"),
    (re.compile(r"(?i)\b(sre|site reliability)\b"), "Site Reliability Engineer"),
    (re.compile(r"(?i)\b(product manager| pm )\b"), "Product Manager"),
    (re.compile(r"(?i)\b(intern|internship)\b"), "Intern"),
]


def _clean_fragment(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s{2,}", " ", s)
    s = s.strip(" \t\r\n-—|:;,.'\"()[]")
    return s


def _extract_from_subject(subject: str) -> Optional[str]:
    s = (subject or "").strip()
    if not s:
        return None
    for pat in _SUBJECT_RES:
        m = pat.search(s)
        if not m:
            continue
        # company is last capturing group in all patterns above
        frag = m.group(m.lastindex or 1)
        frag = _clean_fragment(frag)
        return frag or None
    return None


def _extract_from_body(body: str) -> Optional[str]:
    b = (body or "").strip()
    if not b:
        return None
    snippet = b[:2000]
    for pat in _BODY_RES:
        m = pat.search(snippet)
        if not m:
            continue
        frag = m.group(m.lastindex or 1)
        frag = _clean_fragment(frag)
        return frag or None
    return None


def _extract_role(subject: str, body: str) -> Optional[str]:
    s = f"{subject}\n{body}"
    for pat in _ROLE_RES:
        m = pat.search(s)
        if not m:
            continue
        if m.lastindex and m.lastindex >= 2:
            frag = _clean_fragment(m.group(2))
        else:
            frag = _clean_fragment(m.group(0))
        return frag or None
    return None


@dataclass(frozen=True)
class ExtractCompanyResult:
    company: Optional[str]
    method: str  # domain | subject | body | llm
    confidence: float


@dataclass(frozen=True)
class ExtractRoleResult:
    role: Optional[str]
    method: str  # regex | keyword | llm | none
    confidence: float


@dataclass(frozen=True)
class ExtractCompanyRoleResult:
    company: Optional[str]
    role: Optional[str]
    company_method: str  # domain | subject | body | llm | none
    role_method: str  # regex | keyword | llm | none
    confidence: float


def normalized_from_email_row(email: Emails) -> NormalizedEmail:
    sender = email.sender or ""
    _, addr = parseaddr(sender)
    from_domain = addr.split("@", 1)[-1].lower() if "@" in addr else None
    body = email.body or ""
    return NormalizedEmail(
        provider_message_id=email.raw_data or str(email.id or ""),
        from_address=addr or None,
        from_domain=from_domain,
        subject=email.subject,
        received_at=email.received_at,
        body_clean=body,
        body_excerpt=body[:600],
    )


def extract_company(email: Emails, allow_llm: bool = True) -> ExtractCompanyResult:
    """
    Priority:
    1) sender domain (ATS domains excluded in guess_company_from_domain)
    2) subject regex
    3) body regex
    4) LLM fallback (only if allow_llm=True)
    """
    domain = parse_sender_domain(email.sender)
    domain_guess = guess_company_from_domain(domain)
    if domain_guess:
        return ExtractCompanyResult(company=normalize_company_name(domain_guess), method="domain", confidence=0.62)

    subj_guess = _extract_from_subject(email.subject)
    if subj_guess:
        return ExtractCompanyResult(company=normalize_company_name(subj_guess), method="subject", confidence=0.78)

    body_guess = _extract_from_body(email.body or "")
    if body_guess:
        return ExtractCompanyResult(company=normalize_company_name(body_guess), method="body", confidence=0.72)

    if allow_llm and settings.use_llm:
        llm = extract_company_with_ollama(normalized_from_email_row(email))
        if llm.company and llm.confidence >= 0.55:
            return ExtractCompanyResult(
                company=normalize_company_name(llm.company),
                method="llm",
                confidence=float(llm.confidence),
            )

    return ExtractCompanyResult(company=None, method="none", confidence=0.0)


def extract_role(email: Emails, allow_llm: bool = True) -> ExtractRoleResult:
    """
    Role extraction is independent from company extraction.
    """
    subject = email.subject or ""
    body = email.body or ""
    text = f"{subject}\n{body}"

    # 1) regex patterns (explicit + common titles)
    for pat in _ROLE_TITLE_RES:
        m = pat.search(text)
        if not m:
            continue
        if m.lastindex and m.lastindex >= 2:
            role = _clean_fragment(m.group(2))
        else:
            role = _clean_fragment(m.group(0))
        if role:
            return ExtractRoleResult(role=role, method="regex", confidence=0.75)

    # 2) keyword fallback
    for pat, label in _ROLE_KEYWORDS:
        if pat.search(text):
            return ExtractRoleResult(role=label, method="keyword", confidence=0.55)

    # 3) LLM fallback (only if role still missing)
    if allow_llm and settings.use_llm:
        llm = extract_company_with_ollama(normalized_from_email_row(email))
        if llm.role and llm.confidence >= 0.55:
            return ExtractRoleResult(role=_clean_fragment(llm.role), method="llm", confidence=float(llm.confidence))

    return ExtractRoleResult(role=None, method="none", confidence=0.0)


def extract_company_role(
    email: Emails,
    *,
    allow_llm_company: bool = True,
    allow_llm_role: bool = True,
) -> ExtractCompanyRoleResult:
    c = extract_company(email, allow_llm=allow_llm_company)
    r = extract_role(email, allow_llm=allow_llm_role)
    # Conservative combined confidence: take max of the two signals.
    confidence = max(float(c.confidence or 0.0), float(r.confidence or 0.0))
    return ExtractCompanyRoleResult(
        company=c.company,
        role=r.role,
        company_method=c.method,
        role_method=r.method,
        confidence=confidence,
    )


# Backward-compatible wrapper (old callers)
@dataclass(frozen=True)
class ExtractOutcome:
    company: Optional[str]
    role: Optional[str]
    method: str  # domain | subject | body | llm | none
    confidence: float


def extract_company_role_for_email(email: Emails, *, allow_llm: bool = True) -> ExtractOutcome:
    """
    Backward-compatible wrapper for legacy callers.
    Uses the *new* split pipelines but preserves the old return shape.
    """
    res = extract_company_role(email, allow_llm_company=allow_llm, allow_llm_role=allow_llm)
    # Prefer company method as the legacy "method"; if company missing, expose role method.
    method = res.company_method if not _is_blank(res.company) else res.role_method
    return ExtractOutcome(company=res.company, role=res.role, method=method, confidence=res.confidence)


def needs_fill(company: Optional[str], role: Optional[str]) -> bool:
    return _is_blank(company) or _is_blank(role)
