from __future__ import annotations

import re
from typing import Optional


_ATS_DOMAINS = {
    "greenhouse.io",
    "lever.co",
    "workday.com",
    "myworkday.com",
    "icims.com",
    "smartrecruiters.com",
    "successfactors.com",
    "taleo.net",
    "ashbyhq.com",
    "jobvite.com",
    "bamboohr.com",
}

# Very small curated map for common hiring domains / quirks.
_DOMAIN_BRAND_MAP: dict[str, str] = {
    "google.com": "Google",
    "amazon.com": "Amazon",
    "amazon.jobs": "Amazon",
    "amazon.eu": "Amazon",
    "microsoft.com": "Microsoft",
    "meta.com": "Meta",
    "fb.com": "Meta",
    "apple.com": "Apple",
    "netflix.com": "Netflix",
    "nvidia.com": "NVIDIA",
    "stripe.com": "Stripe",
}

_CANONICAL_BRANDS: dict[str, str] = {
    "google": "Google",
    "amazon": "Amazon",
    "microsoft": "Microsoft",
    "meta": "Meta",
    "apple": "Apple",
    "netflix": "Netflix",
    "nvidia": "NVIDIA",
    "stripe": "Stripe",
}

_LEGAL_SUFFIX_RE = re.compile(
    r"(?i)\b(inc|inc\.|llc|l\.l\.c\.|ltd|ltd\.|limited|corp|corp\.|corporation|gmbh|oy|oyj|ab|as|s\.a\.|s\.r\.l\.|bv|b\.v\.)\b\.?,?\s*$"
)


def _strip_www(domain: str) -> str:
    d = domain.lower().strip().strip(".")
    if d.startswith("www."):
        d = d[4:]
    return d


def _registrable_domain(domain: str) -> str:
    """
    Best-effort: map careers.google.com -> google.com
    This is heuristic, not a full PSL implementation.
    """
    d = _strip_www(domain)
    parts = [p for p in d.split(".") if p]
    if len(parts) < 2:
        return d

    # Handle common second-level ccTLD patterns like *.co.uk
    if len(parts) >= 3 and parts[-2] in {"co", "com", "net", "org", "gov", "ac"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])

    return ".".join(parts[-2:])


def guess_company_from_domain(domain: Optional[str]) -> Optional[str]:
    if not domain:
        return None
    d0 = _strip_www(domain)
    if d0 in _ATS_DOMAINS:
        return None

    if d0 in _DOMAIN_BRAND_MAP:
        return _DOMAIN_BRAND_MAP[d0]

    base = _registrable_domain(d0)
    if base in _DOMAIN_BRAND_MAP:
        return _DOMAIN_BRAND_MAP[base]

    if base in _ATS_DOMAINS:
        return None

    sld = base.split(".", 1)[0]
    if sld in {"gmail", "googlemail", "outlook", "hotmail", "yahoo", "icloud", "proton", "protonmail"}:
        return None

    # Title-case heuristic from registrable name
    brand = sld.replace("-", " ").replace("_", " ").strip()
    if not brand:
        return None
    return brand[:1].upper() + brand[1:]


def normalize_company_name(name: str) -> str:
    s = (name or "").strip()
    if not s:
        return ""

    raw = s
    s = s.lower()
    # normalize separators
    s = s.replace("careers.", "").replace("jobs.", "").replace("talent.", "")
    s = re.sub(r"\s+", " ", s).strip()

    # strip common legal suffix noise inside the string tail
    s = _LEGAL_SUFFIX_RE.sub("", s).strip()

    # map obvious host-ish strings
    if s.endswith(".com") and s.count(".") == 1:
        s = s[: -len(".com")]

    s = s.strip(" .")

    # Canonical brands (google.com / Google / GOOGLE)
    key = re.sub(r"[^a-z0-9]+", " ", s).strip()
    if key in _CANONICAL_BRANDS:
        return _CANONICAL_BRANDS[key]

    # Title case for display grouping
    parts = [p[:1].upper() + p[1:] if p else p for p in re.split(r"([\s/-])", raw) if p]
    out = "".join(parts).strip()
    # If raw had weird casing but is one token, still normalize via lower pipeline
    if not out:
        parts = [p[:1].upper() + p[1:] if p else p for p in re.split(r"([\s/-])", s) if p]
        out = "".join(parts).strip()
    return out
